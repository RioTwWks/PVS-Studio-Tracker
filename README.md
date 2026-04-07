# PVS-Studio Tracker

Инкрементальный трекер отчётов [PVS-Studio](https://pvs-studio.com/) — веб-приложение для загрузки, классификации и визуализации предупреждений статического анализатора across коммитов и веток.

## Возможности

- **Загрузка отчётов** — REST API `POST /api/v1/upload` принимает JSON-отчёт PVS-Studio, имя проекта, коммит и ветку
- **Инкрементальная классификация** — каждое предупреждение получает стабильный fingerprint (SHA-256), что позволяет отслеживать статус: **new**, **existing**, **fixed**, **ignored**
- **Дашборд с трендами** — график изменения количества проблем по запускам (Chart.js)
- **Таблица предупреждений** — фильтрация по уровню серьёзности, статусу, поиск по файлу/правилу (HTMX)
- **Ложные срабатывания** — кнопка «Игнор» помечает предупреждение как false positive
- **LDAP-аутентификация** — заготовка для интеграции с Active Directory (`auth.py`)

## Быстрый старт

```bash
# 1. Создание виртуального окружения
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS

# 2. Установка зависимостей
pip install -e ".[dev]"

# 3. Запуск сервера
uvicorn pvs_tracker.main:app --reload --host 0.0.0.0 --port 8080
```

Откройте [http://localhost:8080](http://localhost:8080) — войдите с любыми учётными данными (MVP-режим).

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
├── models.py         # SQLModel-модели: Project, Run, Issue
├── parser.py         # Парсер JSON-отчётов PVS-Studio + fingerprinting
├── incremental.py    # Классификация предупреждений (new/existing/fixed)
├── auth.py           # LDAP-аутентификация (заготовка)
└── templates/
    ├── base.html         # Базовый шаблон (Bootstrap + HTMX + Chart.js)
    ├── home.html         # Главная: список проектов + форма загрузки
    ├── login.html        # Страница входа
    ├── dashboard.html    # Дашборд с графиком трендов
    └── issues_table.html # Таблица предупреждений с пагинацией
```

## Конфигурация

| Переменная окружения | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pvs_tracker.db` | Строка подключения к БД |
| `SECRET_KEY` | `dev-change-me` | Ключ для сессионных cookie |

Для продакшена замените:
- `SECRET_KEY` — на случайную строку
- БД — на PostgreSQL (`postgresql://user:pass@host/dbname`)
- Auth — подключите реальный LDAP в `auth.py`

## Разработка

```bash
# Линтер
ruff check .

# Типизация
mypy .

# Тесты
pytest
```

## Технологии

- **Python 3.10+**, **FastAPI**, **Uvicorn**
- **SQLModel** (SQLite по умолчанию)
- **Jinja2**, **HTMX**, **Bootstrap 5**, **Chart.js**
- **ldap3** (LDAP/AD)
- **pytest**, **ruff**, **mypy**
