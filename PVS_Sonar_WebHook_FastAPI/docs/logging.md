# Конфигурация логирования

Централизованная система логирования с ежедневной ротацией и автоматической очисткой.

## Возможности

- **Единая настройка** — Централизованная конфигурация в `app/logging_config.py`
- **Ежедневная ротация** — Автоматическая ротация логов каждый день
- **Автоматическая очистка** — Удаление логов старше периода хранения (по умолчанию 30 дней)
- **Структурированное логирование** — Согласованный формат с контекстом (repo_type, repo_name)
- **Раздельные логи** — Отдельные файлы логов для разных компонентов
- **Context manager** — Временный контекст для связанных сообщений
- **Вспомогательные функции** — Удобные функции для типовых сценариев

## Использование

### Базовое использование

```python
from app.logging_config import get_logger

logger = get_logger(__name__)
logger.info("Сообщение")
logger.error("Ошибка", exc_info=True)
```

### Логирование с контекстом

```python
from app.logging_config import get_logger

logger = get_logger("tfs_webhook")

logger.info(
    "Обработка веб-хука",
    extra={
        "repo_type": "Git",
        "repo_name": "MyRepo"
    }
)

# Вывод:
# 2025-01-15 10:30:00 [INFO] [tfs_webhook] [Git/MyRepo] Обработка веб-хука
```

### Component-specific логгер

```python
from app.logging_config import get_component_logger

# Логгер с предустановленным контекстом
logger = get_component_logger("webhook", repo_type="Git", repo_name="MyRepo")

# Все сообщения автоматически включают контекст
logger.info("Веб-хук получен")
# Вывод: [Git/MyRepo] Веб-хук получен
```

### Context Manager

```python
from app.logging_config import LogContext, get_logger

logger = get_logger(__name__)

# Временный контекст для связанных сообщений
with LogContext(repo_type="Git", repo_name="MyRepo"):
    logger.info("Начало обработки")
    logger.info("Шаг 1")
    logger.info("Шаг 2")
    # Все сообщения имеют одинаковый контекст
```

### Вспомогательные функции

```python
from app.logging_config import (
    get_logger,
    log_startup,
    log_shutdown,
    log_error_with_traceback
)

logger = get_logger(__name__)

# Логирование запуска
log_startup(logger, "ServiceName")

# Логирование остановки
log_shutdown(logger, "ServiceName")

# Логирование ошибки с traceback
try:
    # Какая-то операция
    pass
except Exception as e:
    log_error_with_traceback(
        logger,
        "Операция не удалась",
        e,
        repo_type="Git",
        repo_name="MyRepo"
    )
```

## Настройка

### Параметры setup_logging()

```python
from app.logging_config import setup_logging

setup_logging(
    log_level='INFO',           # Глобальный уровень логирования
    log_dir='logs',             # Базовая директория для логов
    retention_days=30,          # Количество дней хранения логов
    console_output=True,        # Включить вывод в консоль
    context_filter=True         # Добавить фильтр контекста
)
```

### Уровни логирования

| Уровень | Значение | Когда использовать |
|---------|----------|-------------------|
| DEBUG | 10 | Детальная отладочная информация |
| INFO | 20 | Общие рабочие сообщения |
| WARNING | 30 | Предупреждения (некритичные) |
| ERROR | 40 | Ошибки |
| CRITICAL | 50 | Критические ошибки, требующие немедленного внимания |

## Формат логов

### Подробный формат (файл)

```
%(asctime)s [%(levelname)s] [%(name)s] [%(repo_type)s/%(repo_name)s] %(message)s
```

Пример:
```
2025-01-15 10:30:00 [INFO] [tfs_webhook] [Git/MyRepo] Обработка веб-хука
```

### Формат консоли

```
%(asctime)s [%(levelname)s] %(name)s: %(message)s
```

Пример:
```
2025-01-15 10:30:00 [INFO] tfs_webhook: Обработка веб-хука
```

## Структура файлов логов

```
logs/
├── app.log                    # Главный лог приложения (ежедневная ротация)
├── app.log.2025-01-14         # Ротированный лог предыдущего дня
├── app.log.2025-01-13         # Старые ротированные логи
├── webhooks/
│   └── tfs_webhook.log        # Логи TFS веб-хуков
└── sonarqube/
    └── sonarqube_webhook.log  # Логи SonarQube веб-хуков
```

## Ротация логов

### Ежедневная ротация

- Логи ротируются в полночь автоматически
- Ротированные файлы именуются: `app.log.YYYY-MM-DD`
- Настроено через `TimedRotatingFileHandler`

### Политика хранения

- По умолчанию: 30 дней
- Настраивается через параметр `retention_days`
- Старые логи автоматически удаляются при ротации

### Ручная очистка

```python
from app.logging_config import DailyRotatingFileHandler

handler = DailyRotatingFileHandler(
    filename='logs/app.log',
    retention_days=7  # Хранить только 7 дней
)
```

## Best Practices

### 1. Используйте соответствующие уровни

```python
# Хорошо
logger.debug("Вход в функцию с параметрами: %s", params)
logger.info("Обработка запроса для пользователя: %s", user_id)
logger.warning("Попытка повторной отправки %d из %d", attempt, max_attempts)
logger.error("Не удалось подключиться к базе данных: %s", error)
```

### 2. Включайте контекст

```python
# Плохо
logger.error("Не удалось обработать веб-хук")

# Хорошо
logger.error(
    "Не удалось обработать веб-хук",
    extra={
        "repo_type": "Git",
        "repo_name": "MyRepo",
        "webhook_id": webhook_id
    }
)
```

### 3. Используйте структурированное логирование

```python
# Вместо конкатенации строк
logger.info(f"Пользователь {user_id} вошёл с {ip_address}")

# Используйте структурированное логирование
logger.info(
    "Пользователь вошёл",
    extra={
        "user_id": user_id,
        "ip_address": ip_address
    }
)
```

### 4. Избегайте чувствительных данных

```python
# Плохо — логирует чувствительные данные
logger.info(f"Пароль пользователя: {password}")

# Хорошо — логирует только необходимую информацию
logger.info("Попытка аутентификации пользователя", extra={"user_id": user_id})
```

### 5. Используйте Context Manager для связанных операций

```python
with LogContext(repo_type="Git", repo_name="MyRepo"):
    logger.info("Начало анализа")
    # ... обработка ...
    logger.info("Анализ завершён")
```

## Мониторинг

### Агрегация логов

Для production окружений рассмотрите:

1. **ELK Stack** (Elasticsearch, Logstash, Kibana)
2. **Splunk** — Корпоративное управление логами
3. **Graylog** — Open source альтернатива
4. **Fluentd** — Сборщик и передатчик логов

### Парсинг логов

Пример regex для парсинга:
```regex
^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(?P<level>\w+)\] \[(?P<logger>\w+)\] \[(?P<repo_type>\w+)/(?P<repo_name>[\w-]+)\] (?P<message>.*)$
```

### Метрики для отслеживания

- **Частота ошибок** — Ошибок в минуту/час
- **Объём логов** — MB в день
- **Частота предупреждений** — Предупреждения, указывающие на потенциальные проблемы
- **Время отклика** — Если логируется

## Устранение неполадок

### Логи не появляются

1. Проверьте настройку уровня логирования
2. Проверьте права доступа к директории
3. Проверьте свободное место на диске
4. Проверьте настройку обработчика

### Слишком много логов

1. Увеличьте уровень логирования (например, INFO → WARNING)
2. Уменьшите debug логирование в production
3. Реализуйте выборку логов для событий с высокой частотой
4. Уменьшите период хранения

### Файлы логов слишком большие

1. Уменьшите количество дней хранения
2. Включите сжатие логов (будущее улучшение)
3. Реализуйте ротацию с меньшими интервалами
4. Архивируйте старые логи во внешнее хранилище

## Производительность

### Асинхронное логирование (будущее)

Для высоконагруженных сценариев:
```python
import logging.handlers
import queue

# Асинхронный обработчик
log_queue = queue.Queue(-1)  # неограниченный размер буфера
async_handler = logging.handlers.QueueHandler(log_queue)
queue_listener = logging.handlers.QueueListener(log_queue, file_handler)
```

### Буферизация логов

Логи буферизируются по умолчанию. Для принудительной сброски:
```python
for handler in logger.handlers:
    handler.flush()
```

## Руководство по миграции

### Из старой системы логирования

**До:**
```python
# Старый стиль
logger = logging.getLogger("tfs_webhook")
logger.info("Сообщение")
```

**После:**
```python
# Новый стиль
from app.logging_config import get_logger
logger = get_logger("tfs_webhook", log_dir="logs/webhooks", add_file_handler=True)
logger.info("Сообщение", extra={"repo_type": "Git", "repo_name": "MyRepo"})
```
