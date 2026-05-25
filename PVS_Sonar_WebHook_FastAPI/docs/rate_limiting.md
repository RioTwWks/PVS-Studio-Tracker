# Rate Limiting для API

## Обзор

Добавьте rate limiting для защиты webhook endpoints от перегрузки и обеспечения справедливого использования.

## Варианты реализации

### Вариант 1: SlowAPI (Рекомендуется)

**Преимущества:**
- Создан для FastAPI/Starlette
- Использует redis или in-memory хранилище
- Гибкие правила rate limit

**Установка:**
```bash
pip install slowapi
```

**Использование:**
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Request

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/webhook")
@limiter.limit("10/minute")  # 10 запросов в минуту
async def webhook(request: Request):
    ...
```

### Вариант 2: FastAPI-Limiter

**Преимущества:**
- На основе Redis
- Поддержка WebSocket

**Установка:**
```bash
pip install fastapi-limiter redis
```

### Вариант 3: Custom Middleware
Для простого in-memory rate limiting без зависимостей.

## Рекомендуемая конфигурация

### Webhook Endpoints
- `/webhook`: 30 запросов/минуту (разрешает всплески во время push)
- `/sonarqube-webhook`: 10 запросов/минуту (анализ завершается реже)

### Admin Endpoints
- `/project/delete/*`: 5 запросов/минуту (предотвращает случайное массовое удаление)
- `/project/analyze/*`: 10 запросов/минуту

### Public Endpoints
- `/list`: 60 запросов/минуту
- `/`: 30 запросов/минуту

## План реализации

1. Добавить `slowapi` в `requirements.txt`
2. Создать `app/rate_limiter.py` с конфигурацией
3. Применить декораторы к webhook routes
4. Добавить заголовки rate limit к ответам
5. Добавить тесты для rate limiting

## Заголовки ответов

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 5
X-RateLimit-Reset: 1609459200
Retry-After: 60  (при ответе 429)
```

## Ответ об ошибке (429)

```json
{
    "detail": "Rate limit exceeded. Maximum 10 requests per minute.",
    "limit": "10/minute",
    "retry_after": "60"
}
```

## Реализация в проекте

### app/rate_limiter.py

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import Request
from fastapi.responses import JSONResponse

# Инициализация limiter с in-memory хранилищем
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],  # Лимит по умолчанию
    storage_uri="memory://"  # In-memory (use "redis://localhost:6379" для production)
)

# Обработчик превышения rate limit
def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "limit": str(exc.detail.limit.limit),
            "retry_after": str(exc.detail.reset_at - exc.detail.now),
        },
        headers={
            "Retry-After": str(exc.detail.reset_at - exc.detail.now),
            "X-RateLimit-Limit": str(exc.detail.limit.limit),
            "X-RateLimit-Remaining": "0",
        }
    )

# Пресеты rate limit для разных сценариев
class RateLimits:
    # Пресеты для распространённых сценариев

    # Webhook endpoints
    WEBHOOK = "30/minute"
    SONARQUBE_WEBHOOK = "10/minute"

    # Admin operations
    ADMIN_DELETE = "5/minute"
    ADMIN_ANALYZE = "10/minute"

    # Public endpoints
    PUBLIC_LIST = "60/minute"
    PUBLIC_FORM = "30/minute"

    # Health checks
    HEALTH_CHECK = "120/minute"
```

### Интеграция с main.py

```python
from .rate_limiter import limiter, rate_limit_exceeded_handler, RateLimits

app = FastAPI()

# Инициализация rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Применение к endpoints
@app.post("/webhook")
@limiter.limit(RateLimits.WEBHOOK)
async def handle_webhook(request: Request, ...):
    ...
```

## Тестирование

### Unit тесты

```python
# Test rate limiting on webhook endpoint
def test_rate_limit_webhook_endpoint(client):
    payload = get_git_push_payload()
    headers = get_auth_headers()

    # Сделать 35 запросов (превысить лимит 30/минуту)
    responses = []
    for _ in range(35):
        response = client.post("/webhook", json=payload, headers=headers)
        responses.append(response)

    # Хотя бы один запрос должен получить 429
    rate_limited = [r for r in responses if r.status_code == 429]
    assert len(rate_limited) > 0
```

### Integration тесты

```python
# Test that 429 response has correct format
def test_rate_limit_429_response_format(client):
    # Делать запросы пока не получим 429
    for i in range(150):
        response = client.get("/webhook/health")
        if response.status_code == 429:
            break

    # Проверить формат ответа
    data = response.json()
    assert "detail" in data
    assert "limit" in data
    assert "retry_after" in response.headers
```

## Production рекомендации

### Redis для Rate Limiting

Для production используйте Redis для распределённого rate limiting:

```python
# В app/main.py или startup
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="redis://redis-server:6379"
)
```

### Мониторинг

Отслеживайте следующие метрики:

- **Частота 429 ответов** — Указывает на необходимость увеличения лимитов
- **Пиковые нагрузки** — Помогает настроить лимиты для всплесков
- **По пользователям/IP** — Выявление злоупотреблений
