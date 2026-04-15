# PVS-Studio Tracker v0.2.0 — Быстрая справка

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

### Загрузка через API

**Linux/macOS:**
```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -F "project_name=my-project" \
  -F "file=@report.json" \
  -F "commit=abc1234" \
  -F "branch=main" \
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

**Ответ:**
```json
{
  "status": "success",
  "run_id": 1,
  "total_issues": 42,
  "quality_gate": {
    "status": "passed",
    "summary": {"passed": 2, "failed": 0, "total": 2}
  }
}
```

---

## 🎯 Quality Gates

### Список Quality Gates

**Windows (cmd):**
```cmd
curl http://localhost:8080/api/v2/quality-gates -H "Authorization: Bearer %TOKEN%"
```

### Создание Quality Gate (Admin)

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/quality-gates -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"Strict Gate\", \"is_default\": false}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/quality-gates -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "Strict Gate", "is_default": false}'
```

### Добавление условия (Admin)

**Windows (cmd):**
```cmd
curl -X POST http://localhost:8080/api/v2/quality-gates/1/conditions -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"metric\": \"new_issues\", \"operator\": \"gt\", \"threshold\": 0, \"error_policy\": \"error\"}"
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8080/api/v2/quality-gates/1/conditions -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"metric": "new_issues", "operator": "gt", "threshold": 0, "error_policy": "error"}'
```

**Доступные метрики:**
- `new_issues`, `fixed_issues`, `active_issues`, `total_issues`
- `reliability_rating`, `security_rating`, `maintainability_rating`
- `technical_debt_minutes`, `security_issues`

**Операторы:** `gt`, `gte`, `lt`, `lte`, `eq`, `ne`

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
- `GET /api/v2/users/me` — Текущий пользователь
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
- `POST /api/v2/quality-gates` — Создать (admin)
- `GET /api/v2/quality-gates/{id}` — Получить
- `POST /api/v2/quality-gates/{id}/conditions` — Добавить условие (admin)

### Проблемы
- `GET /api/v2/projects/{id}/issues` — Список
- `POST /api/v2/issues/{fingerprint}/resolution` — Обновить resolution
- `GET /api/v2/issues/{id}/comments` — Список комментариев
- `POST /api/v2/issues/{id}/comments` — Добавить комментарий
- `GET /api/v2/projects/{id}/export/csv` — Экспорт CSV

### Legacy (v1)
- `POST /api/v1/upload` — Загрузка отчёта
- `GET /api/v1/projects/{id}/dashboard` — Дашборд

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

## 📚 Документация

- **Полное руководство**: README.md
- **Детали трансформации**: SONARQUBE_TRANSFORMATION.md
- **Inline Code Viewer**: INLINE_CODE_GUIDE.md

---

**Версия**: 0.2.0 | **Дата**: 15 апреля 2026
