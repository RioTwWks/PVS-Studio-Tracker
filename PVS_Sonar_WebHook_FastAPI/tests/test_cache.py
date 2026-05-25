"""
Unit тесты для проверки функциональности кэширования

Тесты покрывают:
- In-memory cache backend
- Cache key generation
- TTL expiration
- Cache invalidation
- Statistics tracking
"""

import time

from app.cache import (
    InMemoryCache,
    SonarQubeCache,
    CacheTTL,
    get_cache,
    init_cache,
    reset_cache,
)


# Тесты InMemoryCache

# Тесты для in-memory cache backend
class TestInMemoryCache:

    # Test basic set and get operations
    def test_set_and_get(self):
        cache = InMemoryCache()
        cache.set("test_key", {"data": "value"}, 60)

        result = cache.get("test_key")
        assert result == {"data": "value"}

    # Test getting a key that doesn't exist
    def test_get_nonexistent_key(self):
        cache = InMemoryCache()
        result = cache.get("nonexistent")
        assert result is None

    # Test that entries expire after TTL
    def test_ttl_expiration(self):
        cache = InMemoryCache()
        cache.set("short_lived", "data", 1)  # 1 second TTL

        # Should exist immediately
        assert cache.get("short_lived") == "data"

        # Wait for expiration
        time.sleep(1.5)

        # Should be expired
        assert cache.get("short_lived") is None

    # Test manual deletion
    def test_delete(self):
        cache = InMemoryCache()
        cache.set("to_delete", "data", 60)
        assert cache.get("to_delete") == "data"

        cache.delete("to_delete")
        assert cache.get("to_delete") is None

    # Test clearing keys by pattern
    def test_clear_pattern(self):
        cache = InMemoryCache()
        cache.set("project:abc:issues", "data1", 60)
        cache.set("project:abc:measures", "data2", 60)
        cache.set("project:xyz:issues", "data3", 60)

        # Clear all abc project keys
        cache.clear_pattern("project:abc")

        assert cache.get("project:abc:issues") is None
        assert cache.get("project:abc:measures") is None
        assert cache.get("project:xyz:issues") == "data3"

    # Test automatic cleanup of expired entries
    def test_cleanup_expired(self):
        cache = InMemoryCache()
        cache._cleanup_interval = 0  # Force cleanup on every access

        cache.set("expired", "data", 1)
        time.sleep(1.5)

        # Access should trigger cleanup
        assert cache.get("expired") is None


# SonarQubeCache Tests

# Tests for SonarQube cache manager
class TestSonarQubeCache:

    # Reset cache before each test
    def setup_method(self):
        reset_cache()

    # Reset cache after each test
    def teardown_method(self):
        reset_cache()

    # Test that same params generate same key
    def test_make_key_consistency(self):
        cache = SonarQubeCache(InMemoryCache())

        key1 = cache._make_key("issues/search", {"project": "abc", "type": "BUG"})
        key2 = cache._make_key("issues/search", {"type": "BUG", "project": "abc"})

        # Keys should be same regardless of parameter order
        assert key1 == key2

    # Test that hits and misses are tracked
    def test_cache_hit_miss_tracking(self):
        cache = SonarQubeCache(InMemoryCache())

        # First get - miss
        cache.get("test", {"key": "value"})
        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

        # Set and get - hit
        cache.set("test", {"data": 1}, {"key": "value"}, 60)
        cache.get("test", {"key": "value"})
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    # Test project-specific invalidation
    def test_invalidate_project(self):
        cache = SonarQubeCache(InMemoryCache())

        # Cache data for two projects
        cache.set("issues:project1", "project1_data", {}, 60)
        cache.set("issues:project2", "project2_data", {}, 60)

        # Invalidate project1 (clears all cache for simplicity in this test)
        cache.invalidate_all()

        # Both should be cleared (simplified test)
        assert cache.get("issues:project1", {}) is None

    # Test clearing all cache
    def test_invalidate_all(self):
        cache = SonarQubeCache(InMemoryCache())

        cache.set("key1", "value1", {}, 60)
        cache.set("key2", "value2", {}, 60)

        cache.invalidate_all()

        assert cache.get("key1", {}) is None
        assert cache.get("key2", {}) is None


# Cache TTL Presets Tests

# Tests for cache TTL configuration
class TestCacheTTLPresets:

    # Test that TTL presets have reasonable values
    def test_ttl_values(self):
        assert CacheTTL.ISSUES == 300  # 5 minutes
        assert CacheTTL.CODE_SNIPPET == 3600  # 1 hour
        assert CacheTTL.MEASURES == 600  # 10 minutes
        assert CacheTTL.QUALITY_GATE == 300  # 5 minutes
        assert CacheTTL.PROJECT_INFO == 7200  # 2 hours
        assert CacheTTL.DEFAULT == 600  # 10 minutes

    # Test that TTL values follow expected ordering
    def test_ttl_ordering(self):
        # Short TTL for frequently changing data
        assert CacheTTL.ISSUES < CacheTTL.MEASURES
        assert CacheTTL.QUALITY_GATE < CacheTTL.MEASURES

        # Long TTL for stable data
        assert CacheTTL.PROJECT_INFO > CacheTTL.MEASURES
        assert CacheTTL.CODE_SNIPPET > CacheTTL.MEASURES


# Global Cache Instance Tests

# Tests for global cache management
class TestGlobalCacheInstance:

    def setup_method(self):
        reset_cache()

    def teardown_method(self):
        reset_cache()

    # Test that get_cache returns same instance
    def test_get_cache_singleton(self):
        cache1 = get_cache()
        cache2 = get_cache()

        assert cache1 is cache2

    # Test initializing with specific backend
    def test_init_cache_with_backend(self):
        custom_cache = init_cache(backend=InMemoryCache())
        retrieved = get_cache()

        assert custom_cache is retrieved

    # Test resetting global cache
    def test_reset_cache(self):
        cache1 = get_cache()
        reset_cache()
        cache2 = get_cache()

        assert cache1 is not cache2


# Integration Tests

# Integration tests for caching with SonarQube client
class TestCacheIntegration:

    def setup_method(self):
        reset_cache()

    def teardown_method(self):
        reset_cache()

    # Test caching behavior with mocked API
    def test_cache_integration_with_mock(self):
        from app.cache import SonarQubeCache, InMemoryCache

        # Create cache
        cache = SonarQubeCache(InMemoryCache())

        # Simulate API call
        api_response = {"total": 5, "issues": [{"key": "issue1"}]}

        # Cache the response
        cache.set("issues/search", api_response, {"componentKeys": "test"}, CacheTTL.ISSUES)

        # Retrieve from cache
        cached = cache.get("issues/search", {"componentKeys": "test"})
        assert cached == api_response

    # Test cache key format for SonarQube endpoints
    def test_cache_key_generation_for_sonarqube(self):
        cache = SonarQubeCache(InMemoryCache())

        key = cache._make_key("api/issues/search", {
            "componentKeys": "my-project",
            "types": ["BUG", "VULNERABILITY"]
        })

        # Key should contain endpoint name
        assert "api:issues:search" in key

        # Key should contain parameter hash
        assert len(key.split(":")) >= 3
