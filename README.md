# PVS-Studio Tracker

Инкрементальный трекер отчётов [PVS-Studio](https://pvs-studio.com/) — веб-приложение для загрузки, классификации и визуализации предупреждений статического анализатора across коммитов и веток.

## Возможности

- **Загрузка отчётов** — REST API `POST /api/v1/upload` принимает JSON-отчёт PVS-Studio, имя проекта, коммит и ветку
- **Инкрементальная классификация** — каждое предупреждение получает стабильный fingerprint (SHA-256), что позволяет отслеживать статус: **new**, **existing**, **fixed**, **ignored**
- **Дашборд с трендами** — график изменения количества проблем по запускам (Chart.js)
- **Таблица предупреждений** — фильтрация по уровню серьёзности, статусу, поиск по файлу/правилу (HTMX)
- **Inline Code Viewer** — просмотр исходного кода с предупреждениями прямо в дашборде (как в SonarQube):
  - **Вкладка «Код»** — на дашборде проекта переключайтесь между вкладками «Предупреждения» и «Код»
  - **Просмотр кода** — кликните кнопку «🔍 Код» напротив любого предупреждения, чтобы увидеть файл с подсветкой проблемной строки
  - **Страница Code Viewer** — отдельная страница `/ui/projects/{id}/code-viewer` с файловым браузером для навигации по всем файлам с предупреждениями
  - **Аннотации на уровне строк** — каждая строка с предупреждением показывает цветные бейджи (серьёзность + правило)
  - **Безопасный доступ** — защита от path traversal, поддержка Windows/Linux путей
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
- **Inline Code Viewer** — SonarQube-style code inspection с файловым браузером
- **ldap3** (LDAP/AD)
- **pytest**, **ruff**, **mypy**
