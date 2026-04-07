# PVS-Studio Tracker

> **Цель:** Создать автономный веб-сервис для приёма, инкрементального анализа и визуализации отчётов PVS-Studio (JSON). Замена SonarQube для PVS-пайплайнов.
> **Формат использования:** Оптимизирован для генерации кода через Qwen CLI / vibe-coding. Содержит чёткие контракты, ограничения и поэтапный план разработки.

---

## 📋 1. Обзор проекта
| Параметр | Значение |
|----------|----------|
| Язык | Python 3.10+ |
| Фреймворк | FastAPI + Uvicorn |
| БД | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLModel (Pydantic + SQLAlchemy) |
| UI | Jinja2 + HTMX + Bootstrap 5 + Chart.js |
| Auth | LDAP (Active Directory) |
| Отчёты | PVS-Studio JSON (`--outputFormat=json`) |
| Развёртывание | Нативная служба Windows/Linux (без Docker) |
| Очереди | FastAPI `BackgroundTasks` (Redis v1 не используется) |

---

## 📁 2. Структура проекта
```text
pvs-tracker/
├── main.py                 # Точка входа, роуты, middleware, запуск
├── config.py               # Настройки из .env, валидация
├── db.py                   # Инициализация движка, создание таблиц
├── models.py               # SQLModel схемы
├── parser.py               # Разбор PVS JSON, нормализация путей
├── incremental.py          # Алгоритм diff (new/existing/fixed)
├── auth.py                 # LDAP bind, сессии, защита роутов
├── webhooks.py             # Асинхронные уведомления
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   └── issues_table.html   # HTMX-фрагмент
├── static/                 # CSS/JS (если понадобится кастом)
├── reports/                # Хранилище загруженных файлов
├── .env.example
└── README.md
```

---

## 🗃 3. Модели данных (SQLModel)
```python
class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    language: str = "c++"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    webhook_url: str | None = None  # URL для уведомлений

class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    commit: str | None = None
    branch: str | None = None
    report_file: str
    status: str = "processing"  # processing | done | failed
    total_issues: int = 0

class Issue(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    fingerprint: str = Field(index=True, max_length=16)
    file_path: str
    line: int
    rule_code: str
    severity: str  # High | Medium | Low | Analysis
    message: str
    status: str = "existing"  # new | existing | fixed

class IgnoredIssue(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True)
    project_id: int = Field(foreign_key="project.id")
    reason: str
    author: str  # LDAP username
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

---

## 🔑 4. Ядровая логика

### 4.1 Фингерпринтинг предупреждений
```python
def compute_fingerprint(file: str, line: int, code: str, message: str) -> str:
    norm_file = file.replace("\\", "/").strip()
    norm_msg = " ".join(message.split())
    raw = f"{norm_file}:{line}:{code}:{norm_msg}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```
⚠️ **Важно:** Нормализация путей критична для кросс-платформенности (Windows CI → Linux сервер).

### 4.2 Инкрементальный diff
1. Загрузить `current_issues` из нового отчёта
2. Получить `prev_fps` из последнего `Run.status == "done"`
3. Классифицировать:
   - `fingerprint ∉ prev_fps` → `status = "new"`
   - `fingerprint ∈ prev_fps` → `status = "existing"`
   - `fingerprint ∈ prev_fps \ current_fps` → обновить `status = "fixed"` у записей предыдущего ранa
4. Вставка в БД: одна транзакция `session.commit()`

📌 **Производительность:** Для `< 50k` строк достаточно Python `set()`. При росте использовать SQL `LEFT JOIN` / `EXCEPT`.

---

## 🌐 5. API и UI маршруты

| Метод | Путь | Тип | Описание |
|-------|------|-----|----------|
| `POST` | `/api/v1/upload` | API | Multipart: `project_name`, `file` (JSON), `commit`, `branch`, `webhook_url` |
| `GET` | `/api/v1/projects/{id}/trends` | API | JSON с историей запусков (timestamps, new, fixed, total) |
| `GET` | `/ui/projects` | UI/HTMX | Список проектов |
| `GET` | `/ui/dashboard/{id}` | UI/HTMX | Главная страница проекта (график + форма фильтров) |
| `GET` | `/ui/issues` | UI/HTMX | Возвращает `issues_table.html` с пагинацией/фильтрами |
| `POST` | `/api/v1/issues/{fp}/ignore` | API | Добавление в `IgnoredIssue` |
| `GET`/`POST` | `/login`, `/logout` | UI | LDAP авторизация |

🔹 Все `/ui/*` маршруты возвращают `HTMLResponse` через Jinja2.  
🔹 Все `/api/*` маршруты возвращают JSON.  
🔹 Фильтры: `severity`, `status`, `q` (поиск по файлу/коду), `page`, `per_page`.

---

## 🔐 6. LDAP Аутентификация
- Библиотека: `ldap3`
- Стратегия: прямое биндинг `username@domain` → проверка результата
- Сессии: `starlette.middleware.sessions.SessionMiddleware` + подписанные cookies
- Защита: декоратор/зависимость `require_auth(request: Request)` для всех `/ui/*` и мутаций `/api/*`
- Хранение пользователя: `request.session["user"] = {"username": "...", "display_name": "..."}`

---

## 📡 7. Webhooks
- Триггер: успешный/неудачный парсинг отчёта
- Реализация: `FastAPI.BackgroundTasks` + `httpx.AsyncClient`
- Payload:
```json
{
  "event": "pvs_report_processed",
  "project": "my-app",
  "run_id": 42,
  "commit": "abc123",
  "status": "success",
  "total_issues": 142,
  "new_issues": 3,
  "fixed_issues": 7,
  "timestamp": "2026-04-07T10:00:00Z"
}
```
- Retry: простой `try/except` + лог. Без очередей в v1.

---

## 🖥 8. Развёртывание (Служба)

### Linux (systemd)
```ini
[Unit]
Description=PVS Tracker Service
After=network.target

[Service]
Type=simple
User=pvsuser
WorkingDirectory=/opt/pvs-tracker
ExecStart=/opt/pvs-tracker/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080 --workers 2
Restart=on-failure
EnvironmentFile=/opt/pvs-tracker/.env

[Install]
WantedBy=multi-user.target
```

### Windows (WinSW / NSSM)
- Скачать `winsw.xml` → `nssm install PVSTracker "C:\path\to\python.exe" "-m" "uvicorn" "main:app" "--host" "0.0.0.0" "--port" "8080"`
- Настроить `WorkingDirectory`, `Environment` (`.env` путь), `StartMode=Automatic`

---

## ✅ 9. Acceptance Criteria
| Требование | Проверка |
|------------|----------|
| Загрузка JSON-отчёта PVS | `curl -F file=@report.json ...` → статус `200`, запись в БД |
| Инкрементальный diff | Второй запуск с 1 новым и 1 удалённым предупреждением → корректные статусы |
| LDAP вход | Успешный бинд → доступ к `/ui/dashboard`, невалидный пароль → `401` |
| Фильтрация таблицы | HTMX подгружает отфильтрованную страницу без перезагрузки |
| Webhook | На указанный URL приходит JSON с `event: pvs_report_processed` |
| Служба | `systemctl status pvs-tracker` / `services.msc` → запущена, автозапуск |

---

## 🤖 10. Инструкция для Qwen CLI (Vibe-Coding)

Используй следующий порядок генерации. После каждого шага запускай `python -m uvicorn main:app --reload` и проверяй работу.

```text
🟢 PHASE 1: Базовая структура
- Создай config.py (pydantic Settings, загрузка .env)
- Создай db.py, models.py (SQLModel таблицы)
- Инициализируй main.py с FastAPI, SessionMiddleware, Jinja2, статикой

🟡 PHASE 2: Парсер + Инкремент
- parser.py: устойчивый разбор PVS JSON (обработка разных имён полей)
- incremental.py: diff-логика, транзакция, статусы new/existing/fixed

🟠 PHASE 3: API + Загрузка
- POST /api/v1/upload (сохранение файла, запуск парсера, background webhook)
- GET /api/v1/projects/{id}/trends

🔵 PHASE 4: UI + HTMX
- templates/base.html, dashboard.html, issues_table.html
- GET /ui/* маршруты, пагинация, фильтры, Chart.js

🟣 PHASE 5: Auth + Webhooks
- auth.py: LDAP bind, require_auth, login/logout
- webhooks.py: async httpx, обработка ошибок

🟤 PHASE 6: Деплой + Тесты
- systemd/winsw конфиги
- Проверка всех Acceptance Criteria
```

### 💡 Подсказки для AI-генерации
1. **Не генерируй всё сразу.** Делай по фазам, проверяй импорт и синтаксис.
2. **Используй явные аннотации типов.** Qwen лучше пишет код с `def foo(...) -> Response:`.
3. **Обрабатывай ошибки парсинга.** PVS JSON может менять структуру между версиями. Используй `.get()` с дефолтами и `try/except ValueError`.
4. **HTMX требует корректных статусов.** Возвращай `HTMLResponse` с `status_code=200` для фрагментов.
5. **Сессии:** укажи `SECRET_KEY` в `.env`. Без него `SessionMiddleware` упадёт.

---

## 📎 11. Переменные окружения (`.env`)
```env
DATABASE_URL=sqlite:///./pvs_tracker.db
SECRET_KEY=change-me-to-secure-random-string
LDAP_SERVER=ldap://dc.company.local:389
LDAP_DOMAIN=company.local
APP_HOST=0.0.0.0
APP_PORT=8080
WORKERS=2
```