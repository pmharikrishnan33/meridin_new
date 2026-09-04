"""
Redis caching layer.

Provides a thin async wrapper around ``redis.asyncio`` for caching
frequently-accessed data such as product lookups, intent predictions,
and session state.  When Redis is unavailable the cache degrades
gracefully to a no-op, so the application continues to function.
"""

import json
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings
from app.utils.logger import logger


class RedisCache:
    """
    Async Redis cache with JSON serialization.

    Usage::

        await cache.set("product:123", product_data, ttl=300)
        data = await cache.get("product:123")
    """

    def __init__(self, url: Optional[str] = None, default_ttl: int = 300):
        # URL is resolved at connect() time to ensure settings are fully loaded
        self._url_override = url
        self._default_ttl = default_ttl
        self._client: Optional[redis.Redis] = None
        self._connected = False

    def _get_url(self) -> str:
        """Resolve Redis URL at connection time to ensure settings are loaded."""
        if self._url_override:
            return self._url_override
        # Import here to get the latest settings (avoids lru_cache timing issues)
        from app.core.config import settings
        return settings.REDIS_URL

    async def connect(self, url: Optional[str] = None) -> None:
        """Connect to Redis."""
        connect_url = url or self._get_url()
        try:
            logger.info("Redis URL being used: %s", connect_url)

            self._client = redis.from_url(
                connect_url,
                decode_responses=True,
            )

            await self._client.ping()

            self._connected = True

            logger.info("Redis connected successfully.")

        except Exception as e:
            logger.warning(
                "Redis connection failed: %s. Running without cache.",
                e,
            )

            self._client = None
            self._connected = False

    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            self._connected = False
            logger.info("Redis connection closed.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from the cache. Returns None if missing or Redis is down."""
        if not self._connected or self._client is None:
            return None
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.debug(f"Redis GET failed for key '{key}': {e}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Store a value in the cache. Returns True on success."""
        if not self._connected or self._client is None:
            return False
        try:
            raw = json.dumps(value, default=str)
            await self._client.setex(key, ttl or self._default_ttl, raw)
            return True
        except Exception as e:
            logger.debug(f"Redis SET failed for key '{key}': {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from the cache. Returns True if a key was removed."""
        if not self._connected or self._client is None:
            return False
        try:
            result = await self._client.delete(key)
            return result > 0
        except Exception as e:
            logger.debug(f"Redis DELETE failed for key '{key}': {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        if not self._connected or self._client is None:
            return False
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.debug(f"Redis EXISTS failed for key '{key}': {e}")
            return False

    async def increment(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> Optional[int]:
        """Atomically increment a counter. Returns the new value or None on failure."""
        if not self._connected or self._client is None:
            return None
        try:
            result = await self._client.incrby(key, amount)
            if ttl is not None and result == amount:
                await self._client.expire(key, ttl)
            return result
        except Exception as e:
            logger.debug(f"Redis INCR failed for key '{key}': {e}")
            return None


    async def get_int(self, key: str) -> Optional[int]:
        """Return an integer counter value, or None when Redis is unavailable."""
        if not self._connected or self._client is None:
            return None
        try:
            value = await self._client.get(key)
            return int(value) if value is not None else 0
        except Exception as e:
            logger.debug(f"Redis integer GET failed for key '{key}': {e}")
            return None

    async def reserve_counter(
        self,
        key: str,
        amount: int,
        limit: int,
        ttl: Optional[int] = None,
    ) -> Optional[int]:
        """Atomically reserve counter capacity without crossing a hard limit.

        Returns the new counter value, -1 when the reservation is rejected,
        or None when Redis is unavailable.
        """
        if not self._connected or self._client is None:
            return None
        if amount <= 0 or limit <= 0:
            return None

        script = """
        local current = tonumber(redis.call('GET', KEYS[1]) or '0')
        local amount = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        if current + amount > limit then
            return -1
        end
        local value = redis.call('INCRBY', KEYS[1], amount)
        local ttl = tonumber(ARGV[3])
        if ttl and ttl > 0 and value == amount then
            redis.call('EXPIRE', KEYS[1], ttl)
        end
        return value
        """
        try:
            return int(await self._client.eval(
                script,
                1,
                key,
                amount,
                limit,
                ttl or 0,
            ))
        except Exception as e:
            logger.error(f"Redis counter reservation failed for key '{key}': {e}")
            return None

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Retrieve multiple values at once."""
        if not self._connected or self._client is None:
            return {}
        try:
            raw = await self._client.mget(keys)
            return {
                key: json.loads(val) if val is not None else None
                for key, val in zip(keys, raw)
            }
        except Exception as e:
            logger.debug(f"Redis MGET failed: {e}")
            return {}


# Module-level singleton
redis_cache = RedisCache()
