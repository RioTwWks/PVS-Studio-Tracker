# PVS-Studio Tracker

Инкрементальный трекер отчётов [PVS-Studio](https://pvs-studio.com/) — веб-приложение для загрузки, классификации и визуализации предупреждений статического анализатора across коммитов и веток.

**Версия 0.2.0** — полнофункциональная платформа уровня SonarQube для работы с отчётами PVS-Studio.

## Возможности

### 📊 Анализ и отслеживание проблем
- **Загрузка отчётов** — REST API `POST /api/v1/upload` принимает JSON-отчёт PVS-Studio, имя проекта, коммит и ветку
- **Инкрементальная классификация** — каждое предупреждение получает стабильный fingerprint (SHA-256), что позволяет отслеживать статус: **new**, **existing**, **fixed**, **ignored**
- **Технический долг** — автоматический расчёт времени устранения на основе серьёзности и приоритета правила
- **CWE интеграция** — автоматическое извлечение и привязка CWE ID к предупреждениям
- **Column-level точность** — поддержка позиций column, endLine, endColumn из отчётов PVS-Studio

### 🔐 Управление пользователями и доступом
- **JWT аутентификация** — токены с истечением срока действия для API доступа
- **Role-based access control (RBAC)** — три роли: Admin, User, Viewer
- **Project-level permissions** — назначение прав доступа на уровне отдельных проектов
- **Session-based auth** — для веб-интерфейса

### 🎯 Quality Gates
- **Настраиваемые пороги качества** — создание пользовательских quality gates с условиями
- **Автоматическая оценка** — проверка качества после каждой загрузки отчёта
- **Default quality gate** — предустановленные условия (0 new issues)
- **Quality gate history** — отслеживание прохождения порогов по запускам

### 👥 Командная работа
- **Комментарии к проблемам** — обсуждение и документирование решений
- **Resolution workflow** — статусы: unresolved, fixed, wontfix, acknowledged, ignored
- **Audit trail** — полный журнал действий: кто загрузил, проигнорировал, изменил
- **Activity log** — история активности проекта с фильтрацией

### 📈 Дашборды и метрики
- **Дашборд с трендами** — график изменения количества проблем по запускам (Chart.js)
- **SonarQube-style рейтинги** — A-E ratings для Reliability, Security, Maintainability
- **Сравнение New Code vs Overall Code** — отдельные метрики для новых и всех проблем
- **Severity distribution** — визуальное распределение по уровням серьёзности
- **Branch filtering** — фильтрация данных по веткам

### 📁 Inline Code Viewer
- **Просмотр кода из дашборда** — переключение между вкладками «Предупреждения» и «Код»
- **Синтаксическая подсветка** — Prism.js для C, C++, C#, Java, Python, JavaScript
- **Аннотации на уровне строк** — цветные бейджи (серьёзность + правило)
- **Безопасный доступ** — защита от path traversal, поддержка Windows/Linux путей
- **Standalone страница** — `/ui/projects/{id}/code-viewer` с файловым браузером

### 🔌 Интеграции
- **Webhook для CI/CD** — автоматические уведомления при оценке quality gate
- **CSV экспорт** — выгрузка всех проблем с метаданными (CWE, technical debt, resolution)
- **RESTful API v2** — полный CRUD для проектов, пользователей, quality gates, проблем
- **LDAP support** — интеграция с Active Directory (через auth.py)

### 🌐 Интерфейс
- **i18n (RU/EN)** — клиентский перевод через `translations.json`
- **Dark/Light theme** — переключение тем с сохранением в localStorage
- **Responsive design** — адаптивная вёрстка для мобильных устройств
- **HTMX** — серверный рендеринг с динамическими обновлениями

## Быстрый старт

```bash
# 1. Создание виртуального окружения
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS

# 2. Установка зависимостей
pip install -e ".[dev]"

# 3. Миграция базы данных (обязательно для v0.2.0+)
python migrate.py

# 4. Запуск сервера
uvicorn pvs_tracker.main:app --reload --host 0.0.0.0 --port 8080
```

Откройте [http://localhost:8080](http://localhost:8080) — войдите с учётными данными:
- **Username**: admin
- **Password**: admin

**⚠️ Обязательно смените пароль после первого входа!**

## Миграция с v0.1.x

Если вы обновляетесь с предыдущей версии, выполните миграцию:

```bash
python migrate.py
```

Это создаст новые таблицы и добавит:
- Управление пользователями с JWT
- Quality gates с настраиваемыми условиями
- Комментарии к проблемам и workflow разрешений
- Audit trail и activity logging
- Расчёт технического долга
- Интеграцию CWE и column information

## API

### Аутентификация

**Linux/macOS (bash):**
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
curl.exe -X POST http://localhost:8080/api/v2/auth/login -H "Content-Type: application/json" -d '{\"username\": \"admin\", \"password\": \"admin\"}'
```

Ответ:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@localhost",
    "role": "admin"
  }
}
```

**Сохранение токена в переменную:**

Linux/macOS:
```bash
TOKEN=$(curl -s -X POST http://localhost:8080/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
```

Windows (cmd):
```cmd
for /f "tokens=*" %i in ('curl -s -X POST http://localhost:8080/api/v2/auth/login -H "Content-Type: application/json" -d "{\"username\": \"admin\", \"password\": \"admin\"}" ^| python -c "import sys, json; print(json.load(sys.stdin)['access_token'])"') do set TOKEN=%i
echo %TOKEN%
```

Windows (PowerShell):
```powershell
$response = Invoke-RestMethod -Uri http://localhost:8080/api/v2/auth/login -Method POST -ContentType "application/json" -Body '{"username": "admin", "password": "admin"}'
$TOKEN = $response.access_token
```

### Управление проектами

**Linux/macOS:**
```bash
# Список проектов
curl http://localhost:8080/api/v2/projects \
  -H "Authorization: Bearer %TOKEN%"

# Создание проекта
curl -X POST http://localhost:8080/api/v2/projects \
  -H "Authorization: Bearer %TOKEN%" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"my-project\", \"language\": \"c++\", \"description\": \"My C++ project\"}"
```

**Windows (cmd):**
```cmd
REM Список проектов
curl http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%"

REM Создание проекта
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"my-project\", \"language\": \"c++\", \"description\": \"My C++ project\"}"

REM Создание проекта с путями (обратите внимание на экранирование обратных слешей)
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"my-project\", \"language\": \"c++\", \"source_root_win\": \"C:\\\\Projects\\\\my-project\\\\src\", \"source_root_linux\": \"/home/user/projects/my-project/src\"}"

REM Удаление проекта (только admin)
curl -X DELETE http://localhost:8080/api/v2/projects/1 -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
# Список проектов
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Headers @{Authorization="Bearer $TOKEN"}

# Создание проекта
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "my-project", "language": "c++"}'

# Создание проекта с путями
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "my-project", "language": "c++", "source_root_win": "C:\\Projects\\my-project\\src", "source_root_linux": "/home/user/projects/my-project/src"}'

# Удаление проекта
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects/1 -Method DELETE -Headers @{Authorization="Bearer $TOKEN"}
```

### Загрузка отчёта

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
REM Загрузка отчёта (используйте двойные кавычки для путей с пробелами)
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "commit=abc1234" -F "branch=main" -H "Authorization: Bearer %TOKEN%"

REM Загрузка с архивом исходников
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "source_archive=@sources.zip" -F "commit=abc1234" -F "branch=main" -H "Authorization: Bearer %TOKEN%"

REM Загрузка отчёта с Git конфигурацией проекта (предварительно настройте Git URL)
curl -X POST http://localhost:8080/api/v1/upload -F "project_name=my-project" -F "file=@report.json" -F "commit=abc1234def5678" -F "branch=develop" -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
# Загрузка отчёта
$reportPath = "C:\path\to\report.json"
Invoke-RestMethod -Uri http://localhost:8080/api/v1/upload -Method POST -Headers @{Authorization="Bearer $TOKEN"} -Form @{
    project_name = "my-project"
    file = Get-Item $reportPath
    commit = "abc1234"
    branch = "main"
}

# Загрузка с архивом исходников
Invoke-RestMethod -Uri http://localhost:8080/api/v1/upload -Method POST -Headers @{Authorization="Bearer $TOKEN"} -Form @{
    project_name = "my-project"
    file = Get-Item "C:\path\to\report.json"
    source_archive = Get-Item "C:\path\to\sources.zip"
    commit = "abc1234"
    branch = "main"
}
```

Ответ:
```json
{
  "status": "success",
  "run_id": 1,
  "total_issues": 42,
  "quality_gate": {
    "status": "passed",
    "conditions": [...],
    "summary": {"passed": 2, "failed": 0, "total": 2}
  }
}
```

### Управление пользователями (только admin)

**Linux/macOS:**
```bash
curl http://localhost:8080/api/v2/users \
  -H "Authorization: Bearer $TOKEN"
```

**Windows (cmd):**
```cmd
REM Список пользователей
curl http://localhost:8080/api/v2/users -H "Authorization: Bearer %TOKEN%"

REM Создание пользователя
curl -X POST http://localhost:8080/api/v2/users -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"username\": \"developer1\", \"email\": \"dev@example.com\", \"password\": \"secure123\", \"role\": \"user\"}"
```

**Windows (PowerShell):**
```powershell
# Список пользователей
Invoke-RestMethod -Uri http://localhost:8080/api/v2/users -Headers @{Authorization="Bearer $TOKEN"}

# Создание пользователя
Invoke-RestMethod -Uri http://localhost:8080/api/v2/users -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"username": "developer1", "email": "dev@example.com", "password": "secure123", "role": "user"}'
```

### Quality Gates

**Linux/macOS:**
```bash
curl http://localhost:8080/api/v2/quality-gates \
  -H "Authorization: Bearer $TOKEN"
```

**Windows (cmd):**
```cmd
REM Список quality gates
curl http://localhost:8080/api/v2/quality-gates -H "Authorization: Bearer %TOKEN%"

REM Создание quality gate
curl -X POST http://localhost:8080/api/v2/quality-gates -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"Strict Gate\", \"is_default\": false}"

REM Добавление условия
curl -X POST http://localhost:8080/api/v2/quality-gates/1/conditions -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"metric\": \"new_issues\", \"operator\": \"gt\", \"threshold\": 0, \"error_policy\": \"error\"}"
```

**Windows (PowerShell):**
```powershell
# Создание quality gate
Invoke-RestMethod -Uri http://localhost:8080/api/v2/quality-gates -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "Strict Gate", "is_default": false}'

# Добавление условия
Invoke-RestMethod -Uri http://localhost:8080/api/v2/quality-gates/1/conditions -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"metric": "new_issues", "operator": "gt", "threshold": 0, "error_policy": "error"}'
```

### Проблемы и комментарии

**Windows (cmd):**
```cmd
REM Список проблем проекта
curl http://localhost:8080/api/v2/projects/1/issues -H "Authorization: Bearer %TOKEN%"

REM Фильтрация по серьёзности
curl http://localhost:8080/api/v2/projects/1/issues?severity=High -H "Authorization: Bearer %TOKEN%"

REM Обновление resolution проблемы
curl -X POST http://localhost:8080/api/v2/issues/123/resolution -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"resolution\": \"wontfix\", \"comment\": \"Not applicable for our use case\"}"

REM Добавление комментария
curl -X POST http://localhost:8080/api/v2/issues/123/comments -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"comment\": \"This is a false positive\"}"

REM Экспорт в CSV
curl http://localhost:8080/api/v2/projects/1/export/csv -H "Authorization: Bearer %TOKEN%" -o issues_project1.csv
```

**Windows (PowerShell):**
```powershell
# Список проблем
Invoke-RestMethod -Uri "http://localhost:8080/api/v2/projects/1/issues" -Headers @{Authorization="Bearer $TOKEN"}

# Фильтрация
Invoke-RestMethod -Uri "http://localhost:8080/api/v2/projects/1/issues?severity=High" -Headers @{Authorization="Bearer $TOKEN"}

# Обновление resolution
Invoke-RestMethod -Uri http://localhost:8080/api/v2/issues/123/resolution -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"resolution": "wontfix", "comment": "Not applicable"}'

# Добавление комментария
Invoke-RestMethod -Uri http://localhost:8080/api/v2/issues/123/comments -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"comment": "This is a false positive"}'

# Экспорт в CSV
Invoke-WebRequest -Uri http://localhost:8080/api/v2/projects/1/export/csv -Headers @{Authorization="Bearer $TOKEN"} -OutFile issues_project1.csv
```

### Activity Log

**Windows (cmd):**
```cmd
REM История активности проекта
curl "http://localhost:8080/api/v2/projects/1/activity?limit=100" -H "Authorization: Bearer %TOKEN%"
```

**Windows (PowerShell):**
```powershell
# История активности
Invoke-RestMethod -Uri "http://localhost:8080/api/v2/projects/1/activity?limit=100" -Headers @{Authorization="Bearer $TOKEN"}
```

### Настройка Git Integration (SonarQube-style)

**Windows (cmd):**
```cmd
REM Создание проекта с Git URL
curl -X POST http://localhost:8080/api/v2/projects -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\": \"my-project\", \"git_url\": \"https://github.com/org/repo.git\", \"git_branch\": \"main\"}"

REM Обновление Git настроек проекта
curl -X PATCH http://localhost:8080/api/v2/projects/1 -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"git_url\": \"https://github.com/org/repo.git\", \"git_branch\": \"develop\"}"
```

**Windows (PowerShell):**
```powershell
# Создание проекта с Git URL
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects -Method POST -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"name": "my-project", "git_url": "https://github.com/org/repo.git", "git_branch": "main"}'

# Обновление Git настроек
Invoke-RestMethod -Uri http://localhost:8080/api/v2/projects/1 -Method PATCH -Headers @{Authorization="Bearer $TOKEN"} -ContentType "application/json" -Body '{"git_url": "https://github.com/org/repo.git", "git_branch": "develop"}'
```

## Inline Code Viewer

### Просмотр кода из дашборда

1. **Откройте дашборд проекта** — вы увидите две вкладки: «Предупреждения» и «Код»
2. **Переключитесь на вкладку «Код»** — покажется подсказка выбрать предупреждение
3. **Вернитесь на вкладку «Предупреждения»** — найдите нужное предупреждение в таблице
4. **Кликните кнопку «🔍 Код»** — автоматически переключит на вкладку «Код» и загрузит файл
5. **Просмотрите код** — проблемная строка будет подсвечена и автоматически прокручена в видимую область

### Полнофункциональный Code Viewer

Для детального анализа всех файлов с предупреждениями:

1. **Откройте дашборд проекта**
2. **Перейдите на вкладку «Код»** — это встроенный файловый браузер с навигацией
3. **Выберите файл** — кликните на файл из таблицы предупреждений
4. **Просмотрите код** — увидите исходный код с аннотациями
5. **Навигация** — переключайтесь между файлами без перезагрузки страницы

**Альтернатива:** Отдельная страница `/ui/projects/{id}/code-viewer` с файловым браузером (показывает все файлы с предупреждениями).

### Настройка Source Root

Для работы Code Viewer необходимо указать корневую директорию исходников для каждой ОС:

**Через веб-интерфейс (рекомендуется):**

1. Откройте дашборд проекта
2. Перейдите на вкладку **"⚙️ Настройки проекта"** (третья вкладка)
3. В секции "Корневая директория исходников" укажите пути:
   - **Windows**: `C:\Projects\my-project\src`
   - **Linux**: `/home/user/projects/my-project/src`
4. Нажмите кнопку **"Сохранить оба пути"** ✓

Можно заполнить только один путь (например, только Linux, если сервер на Linux).

**Через API:**

```bash
curl -X PUT http://localhost:8080/api/v1/projects/1/source-roots \
  -H "Content-Type: application/json" \
  -d '{
    "source_root_win": "C:/Projects/my-project/src",
    "source_root_linux": "/home/user/projects/my-project/src"
  }'
```

**Важно:**
- Путь должен существовать на сервере и содержать исходные файлы
- Поддерживаются как абсолютные, так и относительные пути
- Пути из отчётов PVS-Studio автоматически нормализуются и сопоставляются с `source_root` для текущей ОС
- Code Viewer автоматически определяет ОС сервера и использует соответствующий путь
- Защита от path traversal: файлы вне `source_root` недоступны

## API

### Загрузка отчёта

```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -F "project_name=my-project" \
  -F "file=@report.json" \
  -F "commit=abc1234" \
  -F "branch=main"
```

Ответ:
```json
{"status": "success", "run_id": 1, "total_issues": 42}
```

### Дашборд (JSON)

```bash
curl http://localhost:8080/api/v1/projects/1/dashboard
```

### Пометить как ложное срабатывание

```bash
curl -X POST http://localhost:8080/api/v1/issues/<fingerprint>/ignore
```

## Формат отчёта

Приложение ожидает JSON в формате PVS-Studio:

```json
{
  "version": "8.10",
  "warnings": [
    {
      "fileName": "src/main.cpp",
      "lineNumber": 42,
      "warningCode": "V501",
      "level": "High",
      "message": "Identical expressions in 'if' condition."
    }
  ]
}
```

## Структура проекта

```
pvs_tracker/
├── __init__.py
├── main.py           # FastAPI-приложение, маршруты, инициализация БД
├── models.py         # SQLModel-модели: Project, Run, Issue, ErrorClassifier
├── parser.py         # Парсер JSON-отчётов PVS-Studio + fingerprinting
├── incremental.py    # Классификация предупреждений (new/existing/fixed)
├── code_viewer.py    # Inline Code Viewer: routes для просмотра кода
├── file_resolver.py  # Безопасное разрешение путей (защита от path traversal)
├── db.py             # Движок БД и управление сессиями
├── classifier_parser.py  # Парсер CSV классификатора ошибок
├── auth.py           # LDAP-аутентификация (заготовка)
└── templates/
    ├── base.html         # Базовый шаблон (Bootstrap + HTMX + Chart.js)
    ├── home.html         # Главная: список проектов + форма загрузки
    ├── login.html        # Страница входа
    ├── dashboard.html    # Дашборд с графиком трендов + вкладки (Issues/Code)
    ├── issues_table.html # Таблица предупреждений с пагинацией
    ├── code_view.html    # Inline просмотр кода (HTMX partial, без base.html)
    └── code_viewer_page.html # Полнофункциональная страница Code Viewer
```

## Конфигурация

| Переменная окружения | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pvs_tracker.db` | Строка подключения к БД |
| `SECRET_KEY` | `dev-change-me` | Ключ для сессионных cookie |
| `JWT_SECRET_KEY` | значение SECRET_KEY | Ключ для подписи JWT токенов |
| `WEBHOOK_URL` | `` | URL для webhook уведомлений (CI/CD) |
| `WEBHOOK_SECRET` | `` | Секрет для подписи webhook запросов |

Для продакшена замените:
- `SECRET_KEY` и `JWT_SECRET_KEY` — на случайные криптографические строки
- БД — на PostgreSQL (`postgresql://user:pass@host/dbname`)
- Auth — подключите реальный LDAP в `auth.py`
- Настройте `WEBHOOK_URL` для интеграции с CI/CD (GitLab, Jenkins, etc.)

## Структура проекта

```
pvs_tracker/
├── __init__.py
├── main.py           # FastAPI-приложение, маршруты, инициализация БД
├── models.py         # SQLModel-модели: Project, Run, Issue, User, QualityGate, etc.
├── parser.py         # Парсер JSON-отчётов PVS-Studio + fingerprinting + CWE
├── incremental.py    # Классификация предупреждений (new/existing/fixed) + тех. долг
├── api.py            # RESTful API v2: projects, users, quality gates, issues
├── auth_service.py   # JWT аутентификация и RBAC
├── quality_gate.py   # Оценка quality gates с настраиваемыми условиями
├── webhooks.py       # Webhook интеграция для CI/CD
├── security.py       # Hashing паролей и расчёт технического долга
├── code_viewer.py    # Inline Code Viewer: routes для просмотра кода
├── file_resolver.py  # Безопасное разрешение путей (защита от path traversal)
├── db.py             # Движок БД и управление сессиями
├── classifier_parser.py  # Парсер CSV классификатора ошибок
├── auth.py           # LDAP-аутентификация (заготовка)
└── templates/
    ├── base.html         # Базовый шаблон (Bootstrap + HTMX + Chart.js + Prism.js)
    ├── home.html         # Главная: список проектов + форма загрузки
    ├── login.html        # Страница входа
    ├── dashboard.html    # Дашборд с графиком трендов + вкладки (Overview/Issues/Code/Settings)
    ├── issues_table.html # Таблица предупреждений с пагинацией
    ├── code_view.html    # Inline просмотр кода (HTMX partial, без base.html)
    └── code_viewer_page.html # Полнофункциональная страница Code Viewer
```

## Разработка

```bash
# Линтер
ruff check .

# Типизация
mypy .

# Тесты
pytest
pytest -v  # подробный вывод
pytest tests/test_smoke.py -v  # smoke тесты
```

## Технологии

- **Python 3.10+**, **FastAPI**, **Uvicorn**
- **SQLModel** (SQLite по умолчанию, PostgreSQL поддерживается)
- **PyJWT** — JWT токены для API аутентификации
- **bcrypt** — безопасное хеширование паролей
- **Jinja2**, **HTMX**, **Bootstrap 5**, **Chart.js**, **Prism.js**
- **Inline Code Viewer** — SonarQube-style code inspection с файловым браузером и синтаксической подсветкой
- **ldap3** (LDAP/AD)
- **httpx** — асинхронные HTTP запросы для webhooks
- **pytest**, **ruff**, **mypy**

## Что нового в v0.2.0

### Ключевые улучшения:
- ✅ User management с JWT authentication
- ✅ Role-based access control (Admin/User/Viewer)
- ✅ Configurable quality gates с custom thresholds
- ✅ Issue comments и resolution workflow
- ✅ Activity logging и audit trail
- ✅ Technical debt calculation
- ✅ CWE и column information tracking
- ✅ CSV export для issues
- ✅ Webhook интеграция для CI/CD
- ✅ Prism.js syntax highlighting для кода
- ✅ Полный RESTful API v2 для всех ресурсов
