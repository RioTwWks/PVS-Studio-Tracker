# Правила генерации кода — PVS-Tracker (Cursor)

> Строгие директивы для агентов Cursor. Нарушение контрактов из `spec.md` — повод переписать решение.

---

## 1. Контекст

- Трекер предупреждений PVS-Studio с инкрементальной аналитикой.
- Приоритет: **стабильность > скорость > фичи**.
- Перед правками: `.cursor/spec.md`, `.cursor/context.md`, существующий модуль.

---

## 2. Архитектура

| Правило | Детали |
|---------|--------|
| Без Docker | systemd / WinSW / NSSM; пути из `.env` |
| БД | `db.py`; `create_all` + `migrate.py` при апгрейде |
| Очереди | `asyncio.create_task` или `BackgroundTasks`; **без** Celery/Redis/Kafka |
| Async | `async def` в роутах; sync `Session` через `Depends(get_session)` |
| Модули | Один файл — одна зона: не сливать parser/models/auth |
| Classifier | CSV → `ErrorClassifier`; линк в `incremental.py` по `rule_code` |

---

## 3. Python / Backend

- Type hints обязательны.
- Pydantic v2 для API-схем в `api.py` и форм.
- SQLModel: `SQLModel, table=True`, FK через `Field(foreign_key=...)`.
- Логирование: `logger = logging.getLogger(__name__)`; **без** `print()` в новом/правимом коде.
- API: `HTTPException`; UI upload errors — redirect или HTML error page.
- `Depends(get_session)`, `Depends(require_auth)` / `auth_service` для v2.

**Конфиг:** нет `config.py` — `os.getenv` в `db.py`, `main.py`, `auth_service.py`, `webhooks.py`, `git_integration.py`.

---

## 4. Frontend (Jinja2 + HTMX)

- Страницы наследуют `base.html`.
- **Исключения:** `code_view.html`, `partials/*` — только фрагмент для HTMX.
- UI upload → `/ui/upload` → **303** на дашборд; API → JSON.
- Фильтры и пагинация — query params; все `hx-get` сохраняют активные фильтры.
- Chart.js: инициализация в trends/scripts partial; **не** перезагружать при смене фильтра issues.
- `hx-target` — конкретный `id` (например `#issues-table-full`).
- **CI toast:** только `sq-toast` в `app.js` — не класс bootstrap `toast` (скрыт без `.show`).
- **Inline Code (Issues):** `toggleInlineCode` / `closeInlineCodeRow` в `app.js`; не трогать `max-height` на строке после анимации.
- **CI panel:** HTMX → `#project-ci-panel`; уведомление из `#ci-toast-payload` в ответе или `HX-Trigger`.
- **Шаблоны manage:** `project_manage._template_ctx()` передаёт `current_user`.

---

## 5. Безопасность и сессии

- Секреты только из `.env`; не коммитить credentials.
- UI session: `request.session["user"]` = **username string** (как в `main.py` сейчас).
- API v2: JWT (`auth_service.py`), пароли bcrypt в `User`.
- LDAP: реализация в `auth.py` — подключать к `POST /login` явно, не дублировать stub.
- CSRF: для мутаций учитывать `Origin`/`Referer` в production.

---

## 6. Инкремент и парсинг

### Fingerprint

Следовать `parser.compute_fingerprint` (см. код; `.strip()` на file в rules — опционально, не расходиться с тестами).

### Diff

1. `current_fps` из отчёта.
2. `prev_fps` из последнего `Run.status == "done"`, без `ignored`/`fixed`.
3. В **текущем** run: `new` / `existing`.
4. `prev_fps - current_fps` → новые `Issue` в **текущем** run, `status="fixed"`.
5. **Не** менять строки предыдущего run.
6. Один `commit()` после всех вставок.

### Парсер

`.get()` + defaults; пустой file → `__analysis__/{code}`; warn на неизвестные ключи.

---

## 7. Cursor Agent

| Требование | Действие |
|------------|----------|
| Scope | Минимальный diff; не трогать несвязанные файлы |
| Skills | `@pvs-tracker-dev`, `@fix-parser`, `@add-htmx-filter` по задаче |
| Проверка | `uvicorn pvs_tracker.main:app --reload` + целевой `pytest` |
| v2 API | Новые REST — в `api.py`, схемы Pydantic, JWT deps |

---

## 8. Запреты

- `print()` в production-коде
- Redis, Celery, Docker, Alembic (без согласования)
- HTML из `/api/*`
- Sync `requests` в async handlers
- Обновление `status=fixed` у issues **предыдущего** run
- Таблица `IgnoredIssue` (используй `Issue.status=ignored`)
- `eval` / небезопасный `subprocess`

---

## 9. Чек-лист

- [ ] `uvicorn pvs_tracker.main:app` стартует
- [ ] `/api/*` → JSON, `/ui/*` → HTML (кроме оговорённых JSON в v2)
- [ ] Diff: fixed/new/existing в текущем run
- [ ] Classifier из CSV при старте
- [ ] HTMX фильтры без перезагрузки chart
- [ ] Type hints, без хардкода секретов
