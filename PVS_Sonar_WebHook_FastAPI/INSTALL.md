# Руководство по установке

## Быстрый старт

### 1. Активация виртуального окружения
```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows CMD
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate
```

### 2. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 3. Установка pywin32 (только Windows)
```bash
python Scripts/pywin32_postinstall.py -install
```

### 4. Запуск приложения
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## Необходимые зависимости

Следующие пакеты требуются, но могут быть не установлены:

- **slowapi==0.1.9** — Rate limiting
- **redis==5.2.1** — Бэкенд кэширования (опционально для production)
- **pytest==8.3.5** — Фреймворк тестирования
- **pytest-asyncio==0.24.0** — Поддержка async тестов
- **pytest-cov==6.0.0** — Отчёты о покрытии
- **httpx==0.28.1** — HTTP клиент для тестов
- **respx==0.22.0** — Mock HTTP для тестов

## Настройка

### Переменные окружения

Создайте файл `.env` в корне проекта:

```env
# Веб-сервер
WEBHOOK_USERNAME=builder
WEBHOOK_PASSWORD=password

# SonarQube
SONARQUBE_URL=http://qube
SONARQUBE_TOKEN=sqp_...
SONARQUBE_WEBHOOK_SECRET=default_secret_here

# Jenkins
JENKINS_URL=https://newbuilder
JENKINS_TOKEN=...
JENKINS_JOB_NAME=Test_FastAPI

# Jira
JIRA_USERNAME=...
JIRA_PASSWORD=...
JIRA_URL=https://salta:8443

# Администраторы
ADMIN_IPS=192.168.32.139,192.168.32.133
ADMIN_HOSTNAMES=pc-ieme,pc-vvor
```

### База данных

База данных SQLite создаётся автоматически при первом запуске.

Для ручной инициализации:
```bash
python init_db.py
```

## Установка без доступа к интернету

Если у сервера нет доступа к интернету:

### 1. На машине с интернетом:
```bash
pip download -r requirements.txt -d ./offline_packages
```

Скопируйте папку `offline_packages/` на целевой сервер.

### 2. На целевом сервере:
```bash
pip install --no-index --find-links=./offline_packages -r requirements.txt
```

**Параметры:**
- `--no-index` — запрещает обращение к PyPI
- `--find-links=./offline_packages` — искать пакеты в локальной папке

## Проверка установки

### Проверка импортов
```bash
python test_import.py
```

Ожидаемый вывод:
```
✓ slowapi installed
✓ app.main imports successfully
```

### Запуск тестов
```bash
pytest -v --no-cov
```

## Устранение неполадок

### ModuleNotFoundError: No module named 'slowapi'
```bash
pip install slowapi
```

### ModuleNotFoundError: No module named 'redis'
```bash
pip install redis
```

### Установка всех недостающих зависимостей
```bash
pip install -r requirements.txt
```

## Настройка Redis (для production)

### 1. Установка Redis
```bash
# Docker
docker run -d -p 6379:6379 redis:alpine

# Или установите системный пакет
```

### 2. Настройка в коде
```python
# В app/main.py или startup
from app.cache import init_cache
init_cache(redis_url="redis://localhost:6379")
```

### 3. Проверка подключения
```bash
redis-cli ping
# Ответ: PONG
```

## Логи

Логи записываются в директорию `logs/`:
- `app.log` — основные логи приложения
- `webhooks/tfs_webhook.log` — логи TFS веб-хуков
- `sonarqube/sonarqube_webhook.log` — логи SonarQube веб-хуков
- `pytest/pytest.log` — логи тестов

## Мониторинг

### Метрики для отслеживания:
- **Hit rate кэша** — отношение попаданий к запросам (целевое: >70%)
- **Rate limit срабатывания** — количество 429 ответов
- **Время ответа API** — среднее время обработки запросов
- **Объём логов** — MB логов в день
