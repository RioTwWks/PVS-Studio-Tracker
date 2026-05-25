"""
Кэширование для запросов к SonarQube API.

Предоставляет слой кэширования для уменьшения вызовов API и улучшения времени отклика.

Возможности:
- Истечение по TTL
- Инвалидация кэша при событиях webhook
- Настраиваемые настройки кэша для разных endpoint'ов
- Fallback на прямой API при промахе кэша/ошибке
"""

import json
import hashlib
from datetime import datetime
from typing import Optional, Any, Dict
from functools import wraps
import logging

logger = logging.getLogger(__name__)


# Базовый интерфейс бэкенда кэша
class CacheBackend:

    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: int) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def clear_pattern(self, pattern: str) -> None:
        raise NotImplementedError


# In-memory бэкенд кэша для development/testing
class InMemoryCache(CacheBackend):
    # Использует простой dict с отслеживанием TTL. Не подходит для production (нет персистентности, нет распределённого кэширования)

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cleanup_interval = 300  # секунды
        self._last_cleanup = datetime.now()

    # Удаление просроченных записей
    def _cleanup_expired(self):
        now = datetime.now()
        if (now - self._last_cleanup).total_seconds() < self._cleanup_interval:
            return

        expired_keys = [
            key for key, data in self._cache.items()
            if data.get("expires_at", 0) < now.timestamp()
        ]
        for key in expired_keys:
            del self._cache[key]

        self._last_cleanup = now

    def get(self, key: str) -> Optional[Any]:
        self._cleanup_expired()

        data = self._cache.get(key)
        if not data:
            return None

        if data.get("expires_at", 0) < datetime.now().timestamp():
            del self._cache[key]
            return None

        return data.get("value")

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._cache[key] = {
            "value": value,
            "expires_at": datetime.now().timestamp() + ttl,
            "created_at": datetime.now().timestamp()
        }

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    # Удаление всех ключей, соответствующих шаблону (простое совпадение префикса)
    def clear_pattern(self, pattern: str) -> None:
        keys_to_delete = [key for key in self._cache if key.startswith(pattern)]
        for key in keys_to_delete:
            del self._cache[key]


# Redis бэкенд кэша для production
class RedisCache(CacheBackend):
    # Обеспечивает персистентное, распределённое кэширование с правильной поддержкой TTL

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        try:
            import redis
            self._redis = redis.from_url(redis_url, decode_responses=True)
            self._available = True
            logger.info(f"Подключено к Redis: {redis_url}")
        except ImportError:
            logger.warning("Пакет Redis не установлен. Переключение на in-memory кэш.")
            self._available = False
            self._fallback = InMemoryCache()
        except Exception as e:
            logger.warning(f"Не удалось подключиться к Redis: {e}. Переключение на in-memory кэш.")
            self._available = False
            self._fallback = InMemoryCache()

    # Проверка доступности Redis
    def _check_available(self) -> bool:
        if not self._available:
            return False
        try:
            self._redis.ping()
            return True
        except Exception:
            return False

    def get(self, key: str) -> Optional[Any]:
        if not self._check_available():
            return self._fallback.get(key)

        try:
            data = self._redis.get(key)
            if not data:
                return None
            return json.loads(data)
        except Exception as e:
            logger.error(f"Ошибка Redis get: {e}")
            return self._fallback.get(key)

    def set(self, key: str, value: Any, ttl: int) -> None:
        if not self._check_available():
            return self._fallback.set(key, value, ttl)

        try:
            serialized = json.dumps(value, default=str)
            self._redis.setex(key, ttl, serialized)
        except Exception as e:
            logger.error(f"Ошибка Redis set: {e}")
            self._fallback.set(key, value, ttl)

    def delete(self, key: str) -> None:
        if not self._check_available():
            return self._fallback.delete(key)

        try:
            self._redis.delete(key)
        except Exception as e:
            logger.error(f"Ошибка Redis delete: {e}")
            self._fallback.delete(key)

    # Удаление всех ключей, соответствующих шаблону, с использованием Redis SCAN
    def clear_pattern(self, pattern: str) -> None:
        if not self._check_available():
            return self._fallback.clear_pattern(pattern)

        try:
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=f"{pattern}*", count=100)
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.error(f"Ошибка Redis clear_pattern: {e}")
            self._fallback.clear_pattern(pattern)


# Пресеты TTL кэша (в секундах)
class CacheTTL:
    # Пресеты TTL кэша для разных endpoint'ов SonarQube API

    # Кэш issues — короткий TTL (часто обновляется)
    ISSUES = 300  # 5 минут

    # Фрагменты кода — средний TTL (редко меняется)
    CODE_SNIPPET = 3600  # 1 час

    # Метрики проекта — средний TTL
    MEASURES = 600  # 10 минут

    # Статус quality gate — короткий TTL
    QUALITY_GATE = 300  # 5 минут

    # Информация о проекте — длинный TTL (редко меняется)
    PROJECT_INFO = 7200  # 2 часа

    # TTL по умолчанию
    DEFAULT = 600  # 10 минут


# Менеджер кэша SonarQube API
class SonarQubeCache:
    # Предоставляет кэширование для распространённых вызовов SonarQube API с автоматической генерацией ключей и инвалидацией кэша.

    def __init__(self, backend: Optional[CacheBackend] = None):
        self.backend = backend or InMemoryCache()
        self.key_prefix = "sonarqube:cache"
        self._hits = 0
        self._misses = 0

    # Генерация ключа кэша из endpoint и параметров
    def _make_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        # Использует MD5 хэш отсортированных параметров для согласованных ключей

        # Сортировка параметров для согласованной генерации ключей
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        param_hash = hashlib.md5(sorted_params.encode()).hexdigest()[:12]

        # Создание читаемого ключа
        endpoint_name = endpoint.strip("/").replace("/", ":")
        return f"{self.key_prefix}:{endpoint_name}:{param_hash}"

    # Получение кэшированного ответа для endpoint
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        params = params or {}
        key = self._make_key(endpoint, params)

        data = self.backend.get(key)
        if data is not None:
            self._hits += 1
            logger.debug(f"Попадание кэша: {key}")
            return data

        self._misses += 1
        logger.debug(f"Промах кэша: {key}")
        return None

    # Кэширование ответа для endpoint
    def set(self, endpoint: str, value: Any, params: Optional[Dict] = None,
            ttl: Optional[int] = None) -> None:
        params = params or {}
        key = self._make_key(endpoint, params)
        ttl = ttl or CacheTTL.DEFAULT

        self.backend.set(key, value, ttl)
        logger.debug(f"Закэшировано: {key} (TTL: {ttl}s)")

    # Инвалидация кэша для конкретного endpoint
    def invalidate(self, endpoint: str, params: Optional[Dict] = None) -> None:
        params = params or {}
        key = self._make_key(endpoint, params)
        self.backend.delete(key)
        logger.info(f"Кэш инвалидирован: {key}")

    # Инвалидация всех записей кэша для проекта
    def invalidate_project(self, project_key: str) -> None:
        # Вызывается при получении webhook о завершении анализа проекта
        pattern = f"{self.key_prefix}:*:{project_key}"
        self.backend.clear_pattern(pattern)
        logger.info(f"Кэш инвалидирован для проекта: {project_key}")

    # Очистка всех записей кэша
    def invalidate_all(self) -> None:
        self.backend.clear_pattern(f"{self.key_prefix}:")
        logger.info("Весь кэш очищен")

    # Получение статистики кэша
    def get_stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "backend": self.backend.__class__.__name__
        }


# Декоратор для кэширования вызовов функций
def cached(ttl: Optional[int] = None, key_prefix: str = ""):
    # Декоратор для кэширования результатов функций
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Получение экземпляра кэша из модуля функции или глобального
            cache = getattr(wrapper, '_cache', None)
            if not cache:
                return func(*args, **kwargs)

            # Генерация ключа кэша из имени функции и аргументов
            key_data = {
                "func": func.__name__,
                "args": args,
                "kwargs": kwargs
            }
            key = f"{key_prefix}:{func.__name__}:{hashlib.md5(json.dumps(key_data, sort_keys=True, default=str).encode()).hexdigest()[:12]}"

            # Попытка кэша
            cached_result = cache.backend.get(key)
            if cached_result is not None:
                return cached_result

            # Вызов функции
            result = func(*args, **kwargs)

            # Кэширование результата
            if result is not None:
                cache.backend.set(key, result, ttl or CacheTTL.DEFAULT)

            return result

        return wrapper
    return decorator


# Глобальный экземпляр кэша
_cache_instance: Optional[SonarQubeCache] = None


# Получение или создание глобального экземпляра кэша
def get_cache(backend: Optional[CacheBackend] = None) -> SonarQubeCache:
    # Опциональный бэкенд кэша. Если None, используется Redis или in-memory
    global _cache_instance

    if _cache_instance is None:
        _cache_instance = SonarQubeCache(backend)

    return _cache_instance  # Экземпляр SonarQubeCache


# Инициализация кэша с указанным бэкендом
def init_cache(
    redis_url: Optional[str] = None,            # Redis URL для production. Если None, используется in-memory.
    backend: Optional[CacheBackend] = None      # Опциональный бэкенд кэша для прямого использования
) -> SonarQubeCache:
    global _cache_instance

    if backend:
        _cache_instance = SonarQubeCache(backend)
        logger.info("Кэш инициализирован с предоставленным бэкендом")
    elif redis_url:
        _cache_instance = SonarQubeCache(RedisCache(redis_url))
        logger.info(f"Кэш инициализирован с Redis: {redis_url}")
    else:
        _cache_instance = SonarQubeCache(InMemoryCache())
        logger.info("Кэш инициализирован с in-memory бэкендом")

    return _cache_instance      # Инициализированный экземпляр SonarQubeCache


# Сброс глобального экземпляра кэша (полезно для тестирования)
def reset_cache() -> None:
    global _cache_instance
    _cache_instance = None
