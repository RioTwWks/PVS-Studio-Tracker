# Кэширование запросов к SonarQube

## Обзор

Слой кэширования для запросов к SonarQube API для уменьшения количества вызовов API и ускорения времени отклика.

## Возможности

- **Истечение по TTL** — Разная длительность кэширования для разных типов эндпоинтов
- **Автоматическая инвалидация** — Очистка кэша при завершении анализа
- **Два бэкенда** — Redis (production) или in-memory (development)
- **Graceful fallback** — Автоматический переход на in-memory при недоступности Redis
- **Статистика кэша** — Подсчёт попаданий/промахов для мониторинга

## Архитектура

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  SonarQube      │————>│  Слой кэша       │————>│  API клиент     │
│  Webhook        │     │  (инвалидация)   │     │  (кэширование)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │  Бэкенд кэша    │
                        │  ┌───────────┐  │
                        │  │   Redis   │  │ (production)
                        │  └───────────┘  │
                        │  ┌───────────┐  │
                        │  │ In-Memory │  │ (development)
                        │  └───────────┘  │
                        └─────────────────┘
```

## Настройка

### Development (In-Memory)

Не требуется настройка. In-memory кэш используется по умолчанию.

```python
from app.cache import get_cache

cache = get_cache()  # Использует InMemoryCache
```

### Production (Redis)

Инициализируйте кэш с Redis URL:

```python
# В app/main.py или startup
from app.cache import init_cache

init_cache(redis_url="redis://localhost:6379")
```

Или через переменную окружения:

```env
REDIS_URL=redis://redis-server:6379
```

## Использование

### Ручное кэширование

```python
from app.cache import get_cache, CacheTTL

cache = get_cache()

# Получить из кэша
cached = cache.get("issues/search", {"componentKeys": project_key})
if cached:
    return cached

# Получить из API и сохранить в кэш
data = fetch_from_api()
cache.set("issues/search", data, {"componentKeys": project_key}, CacheTTL.ISSUES)
```

### Автоматическая инвалидация

Кэш автоматически инвалидируется при получении webhook:

```python
# В sonarqube_webhook.py
async def process_sonarqube_webhook(payload, db):
    project_key = payload.project.key

    # Инвалидировать весь кэш для этого проекта
    cache.invalidate_project(project_key)

    # Продолжить обработку...
```

### Ручная инвалидация

```python
# Инвалидировать конкретный эндпоинт
cache.invalidate("issues/search", {"componentKeys": project_key})

# Инвалидировать весь кэш для проекта
cache.invalidate_project(project_key)

# Очистить весь кэш
cache.invalidate_all()
```

### Получение статистики

```python
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']}")
print(f"Backend: {stats['backend']}")
```

Пример вывода:
```json
{
    "hits": 150,
    "misses": 50,
    "hit_rate": "75.0%",
    "backend": "RedisCache"
}
```

## Интеграции

### SonarQube API клиент

Все вызовы API в `sonarqube_api_client.py` кэшируются:

- `get_project_measures()` — Кэш (10 мин)
- `get_project_issues()` — Кэш (5 мин)
- `get_fixed_issues()` — Кэш (5 мин)
- `get_project_branches()` — Кэш (2 часа)
- `get_project_qualitygates_status()` — Кэш (5 мин)

## TTL пресеты кэша

| Тип эндпоинта | TTL | Обоснование |
|--------------|-----|-----------|
| Issues | 5 минут | Часто обновляются |
| Quality Gate | 5 минут | Меняется с каждым анализом |
| Measures | 10 минут | Относительно стабильны |
| Code Snippets | 1 час | Исходный код редко меняется |
| Project Info | 2 часа | Метаданные проекта редко меняются |

## Мониторинг

### Метрики для отслеживания

- **Hit rate** — Должен быть >70% для часто запрашиваемых данных
- **Miss rate** — Высокий miss rate может указывать на слишком короткий TTL
- **Использование памяти** — Мониторьте потребление памяти Redis
- **Частота вытеснения** — Высокая частота может требовать больше памяти Redis

### Логирование

Операции кэша логируются на уровне DEBUG:

```
2025-01-15 10:30:00 - DEBUG - Cache HIT: sonarqube:cache:issues/search:abc123
2025-01-15 10:30:01 - DEBUG - Cache MISS: sonarqube:cache:issues/search:def456
2025-01-15 10:30:05 - INFO - Cache invalidated for project: my-project
```

## Production рекомендации

### Настройка Redis

Рекомендуемые настройки Redis:

```conf
# Управление памятью
maxmemory 256mb
maxmemory-policy allkeys-lru

# Персистентность (опционально)
save 900 1
save 300 10

# Сеть
bind 127.0.0.1
port 6379
```

### Высокая доступность

Для production окружений:

1. **Redis Sentinel** — Автоматический failover
2. **Redis Cluster** — Горизонтальное масштабирование
3. **Connection pooling** — Повторное использование соединений

Пример с Sentinel:
```python
init_cache(redis_url="redis://sentinel1:26379,redis://sentinel2:26379/mymaster")
```

### Предварительное заполнение кэша

Предварительно заполните кэш для часто запрашиваемых проектов:

```python
def warm_cache(project_keys: List[str]):
    cache = get_cache()
    for key in project_keys:
        # Получить и сохранить данные заранее
        data = sonarqube_client.get_project_issues(key)
        cache.set("issues/search", data, {"componentKeys": key}, CacheTTL.ISSUES)
```

## Устранение неполадок

### Высокий Miss Rate

1. Проверьте настройки TTL — могут быть слишком короткими
2. Проверьте согласованность ключей кэша — параметры должны совпадать
3. Проверьте частоту инвалидации

### Проблемы с памятью

1. Мониторьте память Redis: `redis-cli INFO memory`
2. Настройте TTL для менее критичных данных
3. Рассмотрите политики вытеснения Redis

### Ошибки подключения

1. Проверьте доступность Redis
2. Проверьте строку подключения
3. Проверьте правила фаервола
4. Просмотрите логи Redis

## Влияние на производительность

### До кэширования

- Средний вызов API: 200-500ms
- 10 запросов issues/минуту = 2-5 секунд всего

### После кэширования

- Попадание в кэш: <1ms
- Промах кэша: 200-500ms (только первый запрос)
- При hit rate 80%: ~40ms в среднем (сокращение на 80%)
