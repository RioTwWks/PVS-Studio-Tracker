# PVS-Studio Tracker — Спецификация (Cursor)

> Автономный веб-сервис для приёма, инкрементального анализа и визуализации JSON-отчётов PVS-Studio.  
> Документ синхронизирован с кодом в `pvs_tracker/` (пакет, не flat `main.py` в корне).

---

## 1. Обзор

| Параметр | Значение |
|----------|----------|
| Язык | Python 3.10+ |
| Фреймворк | FastAPI + Uvicorn |
| БД | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLModel |
| UI | Jinja2 + HTMX + Bootstrap 5 + Chart.js |
| Auth UI (v1) | Session cookie + `User` в БД (`auth_service.py`) |
| Auth API (v2) | JWT + session + `User` (`auth_service.py`) |
| LDAP | `auth.py` (SIMPLE/NTLM), JIT Viewer, роли в UI |
| Отчёты | PVS JSON; сырой JSON в `RunReport`, не папка `reports/` |
| Очереди | `asyncio.create_task` для фоновых задач; без Redis/Celery |
| Деплой | Нативная служба (примеры systemd/NSSM в §8), файлов юнитов в репо нет |

Запуск: `uvicorn pvs_tracker.main:app --host 0.0.0.0 --port 8080`

---

## 2. Структура проекта

```text
PVS-Studio-Tracker/
├── pvs_tracker/
│   ├── main.py              # v1 UI/API, startup, dashboard
│   ├── api.py               # /api/v2/* REST
│   ├── models.py
│   ├── db.py
│   ├── parser.py
│   ├── incremental.py       # diff по target_platform
│   ├── platforms.py         # windows/linux/macos, cross_platform_fp
│   ├── dashboard_context.py # метрики дашборда по платформе
│   ├── dashboard_history.py # history / history_by_platform
│   ├── run_queries.py, issues_query.py
│   ├── classifier_parser.py
│   ├── code_viewer.py
│   ├── file_resolver.py
│   ├── auth.py              # LDAP SIMPLE/NTLM
│   ├── auth_service.py      # JWT, User, RBAC
│   ├── security.py          # bcrypt, technical debt
│   ├── issue_author.py      # author on new/existing/fixed issues
│   ├── upload_metadata.py   # CI .meta.json (commit author)
│   ├── warnings_catalog.py  # sync classifier from pvs-studio.com
│   ├── project_groups.py    # ProjectGroup for home UI
│   ├── quality_gate.py      # gate = набор rule_code (QualityGateRule)
│   ├── notifications.py     # SMTP после POST /api/v1/upload
│   ├── webhooks.py
│   ├── inbound_webhooks.py    # POST /webhook/inbound
│   ├── jenkins_service.py
│   ├── jira_service.py, jira_sync.py
│   ├── repository_service.py
│   ├── project_ci.py, project_manage.py, project_form_context.py
│   ├── project_groups.py, ci_config.py, admin_utils.py
│   ├── git_integration.py
│   ├── artifact_storage.py
│   └── templates/
│       ├── home.html
│       ├── projects/project_form.html, projects/_form_fields.html
│       ├── dashboard.html
│       ├── dashboard/_overview_tab.html
│       ├── dashboard/_issues_tab.html
│       ├── dashboard/_code_tab.html
│       ├── dashboard/_trends_tab.html
│       ├── dashboard/_trends_content.html   # fragment для OS switcher
│       ├── dashboard/_platform_switcher.html
│       ├── dashboard/_ci_tab.html, dashboard/_ci_panel.html, dashboard/_ci_actions.html
│       ├── dashboard/_upload_tab.html
│       ├── dashboard/_settings_tab.html, dashboard/_settings_params_panel.html
│       ├── dashboard/_scripts.html
│       ├── profile_settings.html
│       ├── quality_gates_settings.html
│       ├── global_settings.html
│       ├── issues_table.html
│       ├── partials/issues_rows.html, issue_row.html
│       ├── code_view.html          # HTMX partial, без base.html
│       └── code_viewer_page.html
├── static/                  # style.css, app.js, translations.json
├── tests/
├── Actual_warnings.csv
├── migrate.py
├── .env.example
└── .cursor/                 # правила и skills для Cursor
```

**Нет в репозитории:** `config.py` (настройки через `os.getenv` в модулях), `reports/` как FS-хранилище.

---

## 3. Модели (основные)

См. `pvs_tracker/models.py`. Кратко:

- **Project** — `name`, `slug` (Sonar Project Key), `group_name`, CI-поля (`repo_path`, `cvs_system`, `analysis_branch`, `disable_jira`, `disabled`, Jenkins/Jira metadata, PVS/CMake поля), `source_root_*`, `quality_gate_id`, …
- **Run** — `project_id`, `commit`, `branch`, `commit_author_name`, `commit_author_email`, `target_platform` (`windows|linux|macos`), `report_type` (`incremental|full`), `status`, метрики …
- **Issue** — `fingerprint`, `cross_platform_fp`, `file_path`, `line`, `rule_code`, `status` (`new|existing|fixed|ignored`), `author_name`, `author_email`, `jira_issue_key`, …
- **ProjectGroup** — `name`, `display_order`; группы для главной и форм проекта (CRUD `/api/v2/admin/groups`)
- **QualityGate** + **QualityGateRule** — scope оценки: набор `rule_code`; fail при `new` в scope
- **ErrorClassifier** — из `Actual_warnings.csv` при старте
- **GlobalSettings** — дефолтные source roots
- **User** — `first_name`, `last_name`, `email`, `notify_api_uploads`, …
- **UserProjectNotification** — подписка user→project на email при `POST /api/v1/upload`
- **ProjectMember**, **QualityGate**, **RunReport**, **IssueComment**, **ActivityLog**, …

**Ignore:** нет таблицы `IgnoredIssue`. `POST /api/v1/issues/{fingerprint}/ignore` выставляет `Issue.status = "ignored"` по fingerprint.

---

## 4. Парсинг и фингерпринт

### Форматы JSON

- **Modern:** `warnings[]`, `positions[]`, numeric `level` (0–3)
- **Legacy:** `fileName`, `lineNumber`, `warningCode`, string level

### Пустой file

Не пропускать: `file_path = __analysis__/{code}`, `line = 0`.

### Fingerprint (`parser.compute_fingerprint`)

```python
norm_msg = " ".join(message.split())
raw = f"{file.replace(chr(92), '/')}:{line}:{code}:{norm_msg}"
return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

---

## 5. Инкрементальный diff (`incremental.classify_and_store`)

Параметр upload **`report_type`** (`incremental` | `full`, default `incremental`) задаёт, считать ли JSON полным снимком warning'ов.

| `report_type` | `fixed` при diff |
|---------------|------------------|
| `incremental` | **Нет** — только `new` / `existing` из JSON |
| `full` | **Да** — `prev_fps - current_fps` → новые `Issue` со `status=fixed` |

1. **prev_run** — последний `Run` с `status == "done"` для `project_id` и **того же** `target_platform`, кроме текущего run.
2. **Сопоставление:** `cross_platform_fp` (нормализация путей через `platforms.compute_cross_platform_fp` + source roots); `fingerprint` — per-report SHA-256[:16] из `parser.compute_fingerprint`.
3. **prev_fps** — fingerprints из prev run, где `status not in ("ignored", "fixed")`.
4. Для каждого warning — новая строка `Issue` в **текущем** `run_id`: нет в `prev_fps` → `new`, есть → `existing` (при первом run платформы всё → `existing`).
5. **fixed** (только при `report_type=full`): исчезнувшие FP → новые `Issue` в **текущем** run со `status="fixed"`. Старые строки prev run **не обновляются**.
6. Один `session.commit()` в конце.

**Повторный upload** на тот же `commit+branch+platform`: `add_issues_to_existing_run` — при `incremental` добавляет новые FP; при `full` заменяет issues run'а и вызывает полный diff.

**Ветка UI:** фильтр `?branch=` для графика и таблицы; diff **не** сравнивает по branch (только platform).

### Upload metadata и автор issues

- Опциональный файл `commit_metadata` (UTF-8 JSON) на `POST /ui/upload` и `POST /api/v1/upload`: ключи `commit`, `commit_author_name`, `commit_author_email`, `release_version`, `report_type` (`upload_metadata.py`).
- Поля формы/upload сливаются с metadata; при конфликте приоритет у формы (см. `merge_commit_upload_fields`).
- `issue_author.resolve_issue_author`: **new** → `Run.commit_author_*`; **existing** / **fixed** → из prev `Issue` (при первом run платформы — автор текущего коммита).

### Дашборд и платформы

- Переключатель ОС: `windows` / `linux` / `macos` (`dashboard/_platform_switcher.html`).
- Без полной перезагрузки: `GET /api/v1/projects/{id}/platform-metrics`, `GET /ui/projects/{id}/trends-fragment?platform_filter=`.
- Логика метрик: `dashboard_context.build_platform_metrics` + `dashboard_history.build_dashboard_histories`.
- Тренд: **кумулятивный** активный набор; `total` в history — не `new+existing` одного run.

---

## 6. Маршруты

### UI / v1 (`main.py`, `code_viewer.py`)

| Метод | Путь | Ответ | Auth |
|-------|------|-------|------|
| GET | `/`, `/login` | HTML | — |
| POST | `/login` | 303 session | `authenticate_credentials` (local/LDAP) |
| GET | `/logout` | 303 | — |
| GET | `/ui/projects/{id}/dashboard` | HTML | — |
| GET | `/ui/projects/{id}/overview-fragment` | HTML partial (Overview KPI) | — |
| GET | `/ui/projects/{id}/trends-fragment` | HTML partial (KPI + chart) | — |
| GET | `/ui/projects/{id}/edit` | HTML форма проекта | session |
| GET | `/ui/issues` | HTML / partial | — |
| POST | `/ui/upload` | 303 | session `require_auth` |
| POST | `/ui/projects` | redirect | session |
| GET | `/ui/projects/new` | HTML форма CI | session |
| POST | `/ui/projects/create` | 303 → dashboard `?tab=ci` | session |
| GET | `/ui/projects/{id}/clone` | HTML форма клона | session |
| POST | `/ui/projects/{id}/ci` | 303 → `?tab=settings&settings_tab=params` | session |
| POST | `/ui/projects/{id}/toggle-disabled` | HTML fragment `#project-ci-panel` + toast | session |
| POST | `/ui/projects/{id}/toggle-jira` | HTML fragment + toast | session |
| POST | `/ui/projects/{id}/trigger-analysis` | HTML fragment + toast | admin |
| POST | `/ui/projects/{id}/delete` | 303 → `/` | admin |
| GET | `/ui/projects/manage` | 303 → `/` | — |
| POST | `/webhook/inbound` | JSON | Basic auth |
| GET | `/webhook/inbound/health` | JSON | — |
| POST | `/api/v1/projects/{slug}/analysis-callback` | JSON | — |
| GET | `/ui/settings/profile` | HTML | session |
| GET | `/ui/settings/quality-gates` | HTML | session admin |
| GET | `/ui/settings/global` | HTML | session admin |
| GET | `/ui/file` | HTML partial | — |
| GET | `/ui/projects/{id}/code-viewer` | HTML | — |
| POST | `/api/v1/upload` | JSON | session (+ email подписчикам) |
| GET | `/api/v1/projects/{id}/dashboard` | JSON | — |
| GET | `/api/v1/projects/{id}/platform-metrics` | JSON | — |
| POST | `/api/v1/issues/{fp}/ignore` | JSON | session |
| GET | `/api/v1/issues/{issue_id}/snippet` | JSON | — |
| PUT | `/api/v1/projects/{id}/source-roots` | JSON | session |

Фильтры `/ui/issues`: `project_id`, `branch`, `severity`, `status_filter`, `q`, `page`, `sort_by`, `order`, `fragment`.

### API v2 (`api.py`, prefix `/api/v2`)

JWT Bearer и/или session → `User` из БД. Примеры: `auth/login`, `users/me` (GET/PATCH), `users/me/notifications` (GET/PUT), `users` (admin CRUD), `admin/groups` (CRUD `ProjectGroup`), `projects`, `issues`, `quality-gates` (CRUD + rules), `warnings` (`GET`, `POST /sync`, `POST /backfill-languages`), `export/csv`, `settings/global`, `activity`.

Полный список — grep `@router` в `api.py`.

---

## 7. Webhooks (`webhooks.py`) и email (`notifications.py`)

- URL: `WEBHOOK_URL`, подпись: `WEBHOOK_SECRET`
- События: `report_uploaded`, `quality_gate_evaluated` (не `pvs_report_processed`)
- Отправка: `httpx` async (`send_webhook`)
- Email: при успешном `POST /api/v1/upload` — `schedule_api_upload_notifications` → SMTP (`SMTP_*`, `APP_BASE_URL`) подписчикам с `notify_api_uploads` и `UserProjectNotification`

---

## 8. Переменные окружения

См. `.env.example`. Основные:

| Variable | Модуль |
|----------|--------|
| `DATABASE_URL` | `db.py` |
| `SECRET_KEY` | `main.py` (sessions) |
| `JWT_SECRET_KEY` | `auth_service.py` |
| `WEBHOOK_URL`, `WEBHOOK_SECRET` | `webhooks.py` |
| `WEBHOOK_USERNAME`, `WEBHOOK_PASSWORD` | `inbound_webhooks.py` |
| `JENKINS_*`, `JIRA_*` | `jenkins_service.py`, `jira_service.py` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`, `APP_BASE_URL` | `notifications.py` |
| `GIT_CACHE_DIR`, `SNAPSHOTS_DIR`, … | `git_integration.py` |
| `LDAP_ENABLED`, `LDAP_URL`, `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD`, `LDAP_USER_*`, … | `auth.py` |

`python-dotenv` загружается в `auth_service.py` и `auth.py` при импорте.

### Деплой (пример Linux)

```ini
ExecStart=/opt/pvs-tracker/.venv/bin/uvicorn pvs_tracker.main:app --host 0.0.0.0 --port 8080
EnvironmentFile=/opt/pvs-tracker/.env
```

---

## 9. Acceptance criteria (актуальные)

| Требование | Проверка |
|------------|----------|
| Upload JSON | `POST /api/v1/upload` или `/ui/upload` → run `done` |
| Diff incremental | `report_type=incremental` → второй upload: `new`/`existing`, без ложных `fixed` |
| Diff full | `report_type=full` → второй upload: `new`/`fixed`/`existing` в **текущем** run |
| HTMX filters | Таблица обновляется без перезагрузки графика |
| API v2 auth | `POST /api/v2/auth/login` → JWT |
| Webhook | При `WEBHOOK_URL` — POST с `event` из §7 |
| Email | `notify_api_uploads` + подписка + `SMTP_HOST` → письмо после `/api/v1/upload` |
| Platform dashboard | Переключатель ОС обновляет trends без reload |
| Tests | `pytest` зелёный |

---

## 10. Cursor Agent

1. Читать `.cursor/rules.md` + этот файл.
2. Минимальный diff; type hints; без `print()` в production (`logging`).
3. Под-скиллы: `fix-parser`, `add-htmx-filter`, `add-api-route`.
4. После изменений: `uvicorn pvs_tracker.main:app --reload` и целевой `pytest` (в т.ч. `test_report_type`, `test_profile_notifications`, `test_platforms`, `test_auth_local`, `test_auth_ldap`, `test_upload_metadata`, `test_issue_author`, `test_warnings_catalog`).

Фазы 1–6 из старого плана — **исторический** roadmap; проект уже реализован. Новые фичи — по `rules.md` и без banned stack (§1).
