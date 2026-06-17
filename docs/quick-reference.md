# Быстрая справка (API и CLI)

[← Документация](README.md) · Агенты: [CURSOR.md](../CURSOR.md) · [.cursor/spec.md](../.cursor/spec.md)

Локальный вход (`User` + bcrypt) или LDAP (`LDAP_ENABLED` в `.env`). После `migrate.py` по умолчанию: `admin` / `admin`.

## Содержание

- [Быстрый старт](#-быстрый-старт)
- [Аутентификация](#-аутентификация)
- [Проекты](#-управление-проектами)
- [Загрузка отчётов](#-загрузка-отчётов)
- [Тип отчёта (report_type)](#-тип-отчёта-report_type)
- [Quality Gates](#-quality-gates-rule-codes)
- [Профиль и email](#-профиль-и-уведомления)
- [Проблемы](#-проблемы)
- [Пользователи](#-пользователи-admin)
- [Экспорт и activity](#-экспорт)
- [Git, webhooks, SMTP](#-настройка-git-integration)
- [Сводка endpoints](#-сводка-api-endpoints)
- [Workflow](#-типичные-workflow)

## 🚀 Быстрый старт

```bash
# Установка
pip install -e ".[dev]"

# Миграция базы данных (ОБЯЗАТЕЛЬНО)
python migrate.py

# Запуск сервера
uvicorn pvs_tracker.main:app --reload --host 0.0.0.0 --port 8080

# Вход
# Username: admin
# Password: admin
# ⚠️ Смените немедленно после первого входа!
```

---

## 🔑 Аутентификация

Локальный вход: пользователь в таблице `User` (`auth_provider=local`, bcrypt).  
LDAP: `LDAP_ENABLED=true` и переменные `LDAP_*` в `.env` — тот же `POST /login` / `/api/v2/auth/login`; новые учётки получают роль **viewer**.

### Получение JWT токена

**Linux/macOS:**
```bash
curl -X POST http://localhost:8080/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'
```

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/auth/login -H "Content-Type: application/json" -d "{\"username\": \"admin\", \"password\": \"admin\"}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/auth/login -Method POST -ContentType "application/json" -Body '{"username": "admin", "password": "admin"}'
```

**Ответ:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {"id": 1, "username": "admin", "role": "admin"}
}
```

### Сохранение токена

**Linux/macOS:**
```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
```

**Windows (cmd):**
```cmd
for /f "tokens=*" %i in ('curl -s -X POST http://localhost:8080/api/v2/auth/login -H "Content-Type: application/json" -d "{\"username\": \"admin\", \"password\": \"admin\"}" ^| python -c "import sys, json; print(json.load(sys.stdin)['access_token'])"') do set TOKEN=%i
```

**Windows (PowerShell):**
```powershell
$response = Invoke-RestMethod -Uri http://localhost:8080/api/v2/auth/login -Method POST -ContentType "application/json" -Body '{"username": "admin", "password": "admin"}'
$TOKEN = $response.access_token
```

### Использование токена

**Linux/macOS:**
```bash
curl http://localhost:8080/api/v2/projects -H "Authorization: Bearer $TOKEN"
```

**Windows (cmd):**
```cmd
curl http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Headers @{Authorization="Bearer $TOKEN"}
```

---

## 📁 Управление проектами

### Список проектов

**Windows (cmd):**
```cmd
curl http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%"
```

### Создание проекта

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"my-project\", \"language\": \"c++\"}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "my-project", "language": "c++"}'
```

### Удаление проекта (Admin)

**Windows (cmd):**
```cmd
curl -X DELETE http://localhost:8080/api/v2/projects/1 -H "Authorization: Bearer %TOKEN%"
```

---

## 📊 Загрузка отчётов

### Тип отчёта (`report_type`)

Трекер различает **частичный** отчёт PVS (инкрементальный анализ) и **полный** снимок. Параметр обязателен для корректного diff.

| `report_type` | Поведение diff |
|---------------|----------------|
| `incremental` (**по умолчанию**) | Только `new` / `existing` из JSON; warning'и, отсутствующие в отчёте, **не** помечаются `fixed` |
| `full` | Полный снимок: исчезнувшие fingerprint'ы → `status=fixed` в текущем run |

Передаётся полем формы, в `commit_metadata` JSON (`"report_type": "full"`) или селектором на вкладке Upload в UI. Сохраняется в `Run.report_type`.

**Повторная загрузка на тот же commit+branch+platform:**

- `incremental` — добавляет только новые fingerprint'ы (без пересчёта `fixed`)
- `full` — заменяет issues run'а и пересчитывает diff

### Загрузка через API

**Linux/macOS (инкрементальный, типичный CI):**
```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -F "project_name=my-project" \
  -F "file=@report.json" \
  -F "commit=abc1234" \
  -F "branch=main" \
  -F "report_type=incremental" \
  -H "Authorization: Bearer $TOKEN"
```

**Linux/macOS (полный снимок):**
```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -F "project_name=my-project" \
  -F "file=@report.json" \
  -F "commit=abc1234" \
  -F "branch=main" \
  -F "report_type=full" \
  -H "Authorization: Bearer $TOKEN"
```

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "commit=abc1234" -F "branch=main" -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v1/upload -Method POST -Headers @{Authorization="Bearer $TOKEN"} -Form @{
    project_name = "my-project"
    file = Get-Item "C:\path\to\report.json"
    commit = "abc1234"
    branch = "main"
}
```

### Загрузка с архивом исходников

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "source_archive=@sources.zip" -F "commit=abc1234" -F "branch=main" -H "Authorization: Bearer %TOKEN%"
```

### Метаданные коммита (CI / Jira assignee)

Файл от `pvs_snapshot.py` (`commit`, `commit_author_name`, `commit_author_email`, `release_version`, `report_type`):

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "commit_metadata=@snapshot.meta.json" -F "target_platform=windows" -H "Authorization: Bearer %TOKEN%"
```

Подробнее: [jenkins-ci.md — метаданные](jenkins-ci.md#метаданные-коммита-metajson).

**Ответ:**
```json
{
  "status": "success",
  "run_id": 1,
  "target_platform": "windows",
  "report_type": "incremental",
  "total_issues": 42,
  "quality_gate": {
    "status": "passed",
    "summary": {"passed": 2, "failed": 0, "total": 2}
  }
}
```

---

## 🎯 Quality Gates (rule codes)

Gate = набор PVS `rule_code`. **Failed**, если в текущем run есть **new** issues с кодом из scope.

### Список Quality Gates

**Windows (cmd):**
```cmd
curl http://localhost:8080/api/v2/quality-gates -H "Authorization: Bearer %TOKEN%"
```

### Создание gate с правилами (Admin)

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/quality-gates -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "Core C++", "is_default": false, "rule_codes": ["V501", "V522"]}'
```

### Обновление rule codes (Admin)

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/quality-gates/1 -Method PUT -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"rule_codes": ["V501", "V522", "V773"]}'
```

UI: `/ui/settings/quality-gates` (admin).

---

## 👤 Профиль и уведомления

### Текущий профиль

```cmd
curl http://localhost:8080/api/v2/users/me -H "Authorization: Bearer %TOKEN%"
```

### Обновление профиля

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/users/me -Method PATCH -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"first_name":"Ivan","last_name":"Petrov","email":"ivan@example.com","notify_api_uploads":true}'
```

### Подписки на проекты (email после API upload)

```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/users/me/notifications -Method PUT -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"project_ids":[1,2]}'
```

UI: `/ui/settings/profile`. Письма только после `POST /api/v1/upload` (нужен `SMTP_HOST` в `.env`).

---

## 🐛 Проблемы

### Список проблем

**Windows (cmd):**
```cmd
curl http://localhost:8080/api/v2/projects/1/issues -H "Authorization: Bearer %TOKEN%"
```

### Фильтрация проблем

**Windows (cmd):**
```cmd
REM По серьёзности
curl "http://localhost:8080/api/v2/projects/1/issues?severity=High" -H "Authorization: Bearer %TOKEN%"

REM По статусу
curl "http://localhost:8080/api/v2/projects/1/issues?status=new" -H "Authorization: Bearer %TOKEN%"

REM По resolution
curl "http://localhost:8080/api/v2/projects/1/issues?resolution=wontfix" -H "Authorization: Bearer %TOKEN%"

REM Поиск
curl "http://localhost:8080/api/v2/projects/1/issues?q=V501" -H "Authorization: Bearer %TOKEN%"

REM Пагинация
curl "http://localhost:8080/api/v2/projects/1/issues?page=2&per_page=20" -H "Authorization: Bearer %TOKEN%"
```

### Обновление Resolution

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/issues/<fingerprint>/resolution -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"resolution\": \"wontfix\", \"comment\": \"Not applicable\"}"
```

**Значения Resolution:**
- `unresolved` — не решено
- `fixed` — исправлено
- `wontfix` — не будет исправлено
- `acknowledged` — признано
- `ignored` — проигнорировано (false positive)

### Добавление комментария

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/issues/<issue_id>/comments -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"comment\": \"This is a false positive\"}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/issues/123/comments -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"comment": "This is a false positive"}'
```

---

## 👥 Пользователи (Admin)

### Список пользователей

**Windows (cmd):**
```cmd
curl http://localhost:8080/api/v2/users -H "Authorization: Bearer %TOKEN%"
```

### Создание пользователя

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/users -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"username\": \"developer1\", \"email\": \"dev@example.com\", \"password\": \"secure123\", \"role\": \"user\"}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/users -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"username": "developer1", "email": "dev@example.com", "password": "secure123", "role": "user"}'
```

**Роли:**
- `admin` — полный доступ
- `user` — может загружать отчёты и комментировать
- `viewer` — только чтение

---

## 📥 Экспорт

### Экспорт проблем в CSV

**Windows (cmd):**
```cmd
curl http://localhost:8080/api/v2/projects/1/export/csv -H "Authorization: Bearer %TOKEN%" -o issues_project1.csv
```

**Windows (PowerShell):**
```powershell
Invoke-WebRequest -Uri http://localhost:8080/api/v2/projects/1/export/csv -Headers @{Authorization="Bearer $TOKEN"} -OutFile issues_project1.csv
```

---

## 📜 Activity Log

### Получение Activity Log проекта

**Windows (cmd):**
```cmd
curl "http://localhost:8080/api/v2/projects/1/activity?limit=100" -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri "http://localhost:8080/api/v2/projects/1/activity?limit=100" -Headers @{Authorization="Bearer $TOKEN"}
```

---

## 🔧 Настройка Git Integration

### Создание проекта с Git URL

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"my-project\", \"git_url\": \"https://github.com/org/repo.git\", \"git_branch\": \"main\"}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "my-project", "git_url": "https://github.com/org/repo.git", "git_branch": "main"}'
```

---

## 🌐 Webhooks

### Настройка

**Windows (cmd):**
```cmd
set WEBHOOK_URL=https://your-ci.example.com/webhook/pvs
set WEBHOOK_SECRET=your-hmac-secret
```

**Windows (PowerShell):**
```powershell
$env:WEBHOOK_URL="https://your-ci.example.com/webhook/pvs"
$env:WEBHOOK_SECRET="your-hmac-secret"
```

События: `quality_gate_evaluated`, `report_uploaded`.

---

## 📧 Email (SMTP)

Подписчики с `notify_api_uploads` и выбранными проектами получают письмо после успешного `POST /api/v1/upload`.

**Windows (PowerShell):**
```powershell
$env:SMTP_HOST="smtp.example.com"
$env:SMTP_PORT="587"
$env:SMTP_USER="user"
$env:SMTP_PASSWORD="secret"
$env:SMTP_FROM="pvs-tracker@example.com"
$env:APP_BASE_URL="http://localhost:8080"
```

См. `.env.example`.

---

## 📊 Система рейтинлей

### Reliability / Maintainability
| Рейтинг | Проблемы |
|---------|----------|
| A | 0 |
| B | 1-10 |
| C | 11-30 |
| D | 31-100 |
| E | 100+ |

### Security
| Рейтинг | Проблемы |
|---------|----------|
| A | 0 |
| B | 1-5 |
| C | 6-20 |
| D | 21-50 |
| E | 50+ |

---

## 🔍 Сводка API Endpoints

### Аутентификация
- `POST /api/v2/auth/login` — Вход

### Пользователи
- `GET /api/v2/users/me` — Профиль (+ `notification_project_ids`)
- `PATCH /api/v2/users/me` — Обновить имя, email, флаг уведомлений
- `GET /api/v2/users/me/notifications` — Подписки на проекты
- `PUT /api/v2/users/me/notifications` — Заменить список `project_ids`
- `GET /api/v2/users` — Список (admin)
- `POST /api/v2/users` — Создать (admin)
- `PATCH /api/v2/users/{id}` — Обновить (admin)

### Проекты
- `GET /api/v2/projects` — Список
- `POST /api/v2/projects` — Создать
- `GET /api/v2/projects/{id}` — Получить
- `PATCH /api/v2/projects/{id}` — Обновить
- `DELETE /api/v2/projects/{id}` — Удалить (admin)
- `POST /api/v2/projects/{id}/members` — Добавить участника
- `GET /api/v2/projects/{id}/members` — Список участников
- `GET /api/v2/projects/{id}/activity` — Activity log

### Quality Gates
- `GET /api/v2/quality-gates` — Список
- `POST /api/v2/quality-gates` — Создать + `rule_codes` (admin)
- `GET /api/v2/quality-gates/{id}` — Получить + `rule_codes`
- `PUT /api/v2/quality-gates/{id}` — Обновить имя / default / `rule_codes` (admin)
- `DELETE /api/v2/quality-gates/{id}` — Удалить (admin)

### Warnings catalog
- `GET /api/v2/warnings` — Каталог правил
- `POST /api/v2/warnings/sync` — Синхронизация с pvs-studio.com (admin)

### Проблемы
- `GET /api/v2/projects/{id}/issues` — Список
- `POST /api/v2/issues/{fingerprint}/resolution` — Обновить resolution
- `GET /api/v2/issues/{id}/comments` — Список комментариев
- `POST /api/v2/issues/{id}/comments` — Добавить комментарий
- `GET /api/v2/projects/{id}/export/csv` — Экспорт CSV

### Legacy (v1)
- `POST /api/v1/upload` — Загрузка отчёта (`target_platform`: windows|linux|macos; `report_type`: incremental|full, default incremental)
- `GET /api/v1/projects/{id}/dashboard` — Дашборд JSON
- `GET /api/v1/projects/{id}/platform-metrics` — KPI/тренд для OS switcher

### UI (фрагменты)
- `GET /ui/settings/profile` — Настройки профиля
- `GET /ui/settings/quality-gates` — Quality gates (admin)
- `GET /ui/projects/{id}/trends-fragment` — HTML KPI + chart по платформе
- `GET /` — Главная: проекты по группам (цвет карточки = статус CI/Jira)
- `GET /ui/projects/new` — Форма нового проекта (Sonar-поля)
- `POST /ui/projects/create` — Создать проект → dashboard `?tab=ci`
- `GET /ui/projects/{id}/dashboard?tab=ci` — Вкладка Analysis / CI
- `GET /ui/projects/{id}/dashboard?tab=settings&settings_tab=params` — Параметры CI
- `POST /ui/projects/{id}/toggle-disabled` — HTMX; toast «Проект вкл/выкл»
- `POST /ui/projects/{id}/toggle-jira` — HTMX; toast Jira
- `POST /webhook/inbound` — TFS/Git → Jenkins (Basic auth)
- Issues → кнопка **Code** — inline-фрагмент (`GET /ui/file`); закрытие с анимацией в `app.js`

**Отладка toast:** в консоли браузера `showToast('test', 'success')`; после правок `app.js` — Ctrl+F5.

---

## 🎯 Типичные Workflow

### 1. Первичная настройка

**Windows (cmd):**
```cmd
REM Установка и миграция
pip install -e ".[dev]"
python migrate.py

REM Запуск сервера
uvicorn pvs_tracker.main:app --reload

REM Вход как admin
REM Username: admin, Password: admin
```

### 2. Создание проекта и загрузка

**Windows (cmd):**
```cmd
REM Получение токена
for /f "tokens=*" %i in ('curl -s -X POST http://localhost:8080/api/v2/auth/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"admin\"}" ^| python -c "import sys, json; print(json.load(sys.stdin)['access_token'])"') do set TOKEN=%i

REM Создание проекта
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\":\"my-project\"}"

REM Загрузка отчёта
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -H "Authorization: Bearer %TOKEN%"
```

### 3. Добавление участника

**Windows (cmd):**
```cmd
REM Создание пользователя
curl -X POST http://localhost:8080/api/v2/users -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"username\":\"developer\",\"password\":\"pass123\",\"role\":\"user\"}"

REM Добавление в проект
curl -X POST http://localhost:8080/api/v2/projects/1/members -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"user_id\":2,\"role\":\"user\"}"
```

---

## 📚 Другие документы

| Документ | Описание |
|----------|----------|
| [README.md](../README.md) | Обзор продукта и установка |
| [docs/README.md](README.md) | Указатель всей документации |
| [inline-code-viewer.md](inline-code-viewer.md) | Просмотр кода (Git / archive / FS) |
| [jenkins-ci.md](jenkins-ci.md) | Jenkins, webhook, `.meta.json` |
| [v0.2-transformation.md](v0.2-transformation.md) | История v0.2 (часть QG устарела) |
| [CURSOR.md](../CURSOR.md) | Гид для Cursor |

---

**Версия**: 0.2.0
