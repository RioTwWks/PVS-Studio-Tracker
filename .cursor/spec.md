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
| Auth UI (v1) | Session cookie; MVP — любые непустые логин/пароль |
| Auth API (v2) | JWT + `User` в БД (`auth_service.py`) |
| LDAP | Заготовка в `auth.py`, **не подключена** к `main.py` |
| Отчёты | PVS JSON; сырой JSON в `RunReport`, не папка `reports/` |
| Очереди | `asyncio.create_task` для фоновых задач; без Redis/Celery |
| Деплой | Нативная служба (примеры systemd/NSSM в §8), файлов юнитов в репо нет |

Запуск: `uvicorn pvs_tracker.main:app --host 0.0.0.0 --port 8080`

---

## 2. Структура проекта

```text
PVS-Studio-Tracker/
├── pvs_tracker/
│   ├── main.py              # v1 UI/API, startup, dashboard history
│   ├── api.py               # /api/v2/* REST
│   ├── models.py
│   ├── db.py
│   ├── parser.py
│   ├── incremental.py
│   ├── classifier_parser.py
│   ├── code_viewer.py
│   ├── file_resolver.py
│   ├── auth.py              # LDAP stub (не используется main)
│   ├── auth_service.py      # JWT, User, RBAC
│   ├── security.py          # technical debt
│   ├── quality_gate.py
│   ├── webhooks.py
│   ├── git_integration.py
│   ├── artifact_storage.py
│   └── templates/
│       ├── dashboard.html
│       ├── dashboard/_overview_tab.html
│       ├── dashboard/_issues_tab.html
│       ├── dashboard/_code_tab.html
│       ├── dashboard/_trends_tab.html
│       ├── dashboard/_upload_tab.html
│       ├── dashboard/_settings_tab.html
│       ├── dashboard/_scripts.html
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

- **Project** — `name`, `language`, `source_root_*`, `git_*`, `quality_gate_id`, …
- **Run** — `project_id`, `commit`, `branch`, `status`, `total_issues`, `new_issues`, `fixed_issues`, …
- **Issue** — `fingerprint`, `file_path`, `line`, `rule_code`, `severity`, `message`, `status` (`new|existing|fixed|ignored`), `resolution`, `classifier_id`, `cwe_id`, `technical_debt_minutes`, …
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

1. **prev_run** — последний `Run` с `status == "done"` для `project_id` (**без фильтра по branch**).
2. **prev_fps** — fingerprints из prev run, где `status not in ("ignored", "fixed")`.
3. Для каждого warning в новом отчёте — новая строка `Issue` в **текущем** `run_id`:
   - нет в `prev_fps` → `new`
   - есть в `prev_fps` → `existing`
4. **fixed:** `prev_fps - current_fps` → **новые** строки `Issue` в **текущем** run со `status="fixed"` (копия метаданных из prev). Старые строки prev run **не обновляются**.
5. Один `session.commit()` в конце.

### Тренд на дашборде (`main.py`)

Для графика по ветке: **кумулятивный** активный набор fingerprints; `total` в history — не просто `new+existing` одного run. Per-run поля `new`/`fixed` — счётчики issues **внутри** этого run.

---

## 6. Маршруты

### UI / v1 (`main.py`, `code_viewer.py`)

| Метод | Путь | Ответ | Auth |
|-------|------|-------|------|
| GET | `/`, `/login` | HTML | — |
| POST | `/login` | 303 session | MVP любой login |
| GET | `/logout` | 303 | — |
| GET | `/ui/projects/{id}/dashboard` | HTML | — |
| GET | `/ui/issues` | HTML / partial | — |
| POST | `/ui/upload` | 303 | session `require_auth` |
| POST | `/ui/projects` | redirect | session |
| GET | `/ui/settings/profile` | HTML | session |
| GET | `/ui/settings/global` | HTML | session admin |
| GET | `/ui/file` | HTML partial | — |
| GET | `/ui/projects/{id}/code-viewer` | HTML | — |
| POST | `/api/v1/upload` | JSON | session |
| GET | `/api/v1/projects/{id}/dashboard` | JSON | — |
| POST | `/api/v1/issues/{fp}/ignore` | JSON | session |
| PUT | `/api/v1/projects/{id}/source-roots` | JSON | session |

Фильтры `/ui/issues`: `project_id`, `branch`, `severity`, `status_filter`, `q`, `page`, `sort_by`, `order`, `fragment`.

### API v2 (`api.py`, prefix `/api/v2`)

JWT Bearer и/или session → `User` из БД. Примеры: `auth/login`, `users/me` (GET/PATCH), `users/me/notifications` (GET/PUT), `projects`, `issues`, `quality-gates`, `export/csv`, `settings/global`, `activity`.

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
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`, `APP_BASE_URL` | `notifications.py` |
| `GIT_CACHE_DIR`, `SNAPSHOTS_DIR`, … | `git_integration.py` |

`python-dotenv` загружается в `auth_service.py` при импорте.

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
| Diff | Второй upload: `new`/`fixed`/`existing` в **текущем** run |
| HTMX filters | Таблица обновляется без перезагрузки графика |
| API v2 auth | `POST /api/v2/auth/login` → JWT |
| Webhook | При `WEBHOOK_URL` — POST с `event` из §7 |
| Tests | `pytest` зелёный |

---

## 10. Cursor Agent

1. Читать `.cursor/rules.md` + этот файл.
2. Минимальный diff; type hints; без `print()` в production (в `webhooks.py` есть legacy `print` — при правке заменить на `logger`).
3. Под-скиллы: `fix-parser`, `add-htmx-filter`, `add-api-route`.
4. После изменений: `uvicorn pvs_tracker.main:app --reload` и целевой `pytest`.

Фазы 1–6 из старого плана — **исторический** roadmap; проект уже реализован. Новые фичи — по `rules.md` и без banned stack (§1).
