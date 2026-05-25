"""
Конфигурация rate limiting для приложения FastAPI.

Использует SlowAPI для rate limiting с in-memory хранилищем.
Для production рассмотрите использование Redis бэкенда.
"""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import Request
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

# Инициализация limiter с in-memory хранилищем
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],  # Лимит по умолчанию для всех endpoint'ов
    storage_uri="memory://"  # In-memory хранилище (используйте "redis://localhost:6379" для production)
)


# Пользовательский обработчик для ошибок превышения rate limit
def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # Возвращает JSON ответ с информацией о повторной попытке
    logger.warning(
        f"Превышен rate limit для {request.client.host} на {request.url.path}"
    )

    # Расчёт retry after
    try:
        retry_after = str(exc.detail.reset_at - exc.detail.now) if hasattr(exc.detail, 'reset_at') else "60"
        limit = str(exc.detail.limit.limit) if hasattr(exc.detail, 'limit') else "unknown"
    except (AttributeError, TypeError):
        retry_after = "60"
        limit = "unknown"

    return JSONResponse(
        status_code=429,
        content={
            "detail": "Превышен rate limit",
            "limit": limit,
            "retry_after": retry_after,
        },
        headers={
            "Retry-After": retry_after,
            "X-RateLimit-Limit": limit,
            "X-RateLimit-Remaining": "0",
        }
    )


# Пресеты для распространённых сценариев rate limiting
class RateLimits:

    # Webhook endpoint'ы (разрешают всплески во время push)
    WEBHOOK = "30/minute"

    # SonarQube webhook (анализ завершается реже)
    SONARQUBE_WEBHOOK = "10/minute"

    # Административные операции (предотвращают случайное массовое удаление)
    ADMIN_DELETE = "5/minute"
    ADMIN_ANALYZE = "10/minute"

    # Public endpoint'ы
    PUBLIC_LIST = "60/minute"
    PUBLIC_FORM = "30/minute"

    # Health checks (более разрешающие)
    HEALTH_CHECK = "120/minute"

    # Строгие лимиты для чувствительных операций
    STRICT = "3/minute"
