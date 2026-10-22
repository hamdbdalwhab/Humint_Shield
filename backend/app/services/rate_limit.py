"""Redis-backed sliding-window rate limiter with in-memory fallback.

Uses a Redis sorted set per key: each request is stored as a member scored by
the current epoch-millisecond timestamp; members older than the window are
evicted, and the cardinality of the set is the request count.  When Redis is
unavailable (for example in unit tests) a process-local deque is used so the
application keeps functioning.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(Exception):
    """Raised when a client exceeds the configured request budget."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Rate limit exceeded; retry after {retry_after}s")
        self.retry_after = retry_after


class RateLimiter:
    """Sliding-window limiter supporting Redis and in-memory backends."""

    def __init__(self, redis_client=None) -> None:
        """Initialise the limiter.

        Args:
            redis_client: Optional ``redis.asyncio.Redis`` instance.  When
                ``None``, :meth:`_get_redis` attempts to create one lazily.
        """
        self._redis = redis_client
        self._redis_failed = False
        self._memory: dict[str, deque[float]] = defaultdict(deque)

    async def _get_redis(self):
        """Return a Redis client or ``None`` when unavailable."""
        if self._redis is not None or self._redis_failed:
            return self._redis
        settings = get_settings()
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            await client.ping()
            self._redis = client
        except Exception as exc:  # pragma: no cover - depends on environment
            logger.warning("rate_limit_redis_unavailable", error=str(exc))
            self._redis_failed = True
            self._redis = None
        return self._redis

    async def check(self, key: str, limit: int | None = None, window: int | None = None) -> None:
        """Record a request and raise if the budget is exhausted.

        Args:
            key: Identity of the caller (IP + route, username, ...).
            limit: Maximum requests per window (defaults to settings).
            window: Window length in seconds (defaults to settings).

        Raises:
            RateLimitExceeded: When the number of requests in the window
                exceeds ``limit``.
        """
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit = limit or settings.rate_limit_requests
        window = window or settings.rate_limit_window_seconds
        now = time.time()
        client = await self._get_redis()
        if client is not None:
            try:
                await self._check_redis(client, key, limit, window, now)
                return
            except RateLimitExceeded:
                raise
            except Exception as exc:  # pragma: no cover - redis outage
                logger.warning("rate_limit_redis_error", error=str(exc))
                self._redis_failed = True
                self._redis = None
        self._check_memory(key, limit, window, now)

    async def _check_redis(self, client, key: str, limit: int, window: int, now: float) -> None:
        """Sliding-window check backed by a Redis sorted set."""
        redis_key = f"ratelimit:{key}"
        cutoff = now - window
        pipe = client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        pipe.zadd(redis_key, {f"{now}": now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window + 1)
        _, _, count, _ = await pipe.execute()
        if int(count) > limit:
            raise RateLimitExceeded(retry_after=window)

    def _check_memory(self, key: str, limit: int, window: int, now: float) -> None:
        """Sliding-window check backed by a process-local deque."""
        bucket = self._memory[key]
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window - (now - bucket[0])) + 1)
            raise RateLimitExceeded(retry_after=retry_after)
        bucket.append(now)

    async def reset(self, key: str) -> None:
        """Clear the counters for ``key`` (used by tests and admin tooling)."""
        self._memory.pop(key, None)
        client = await self._get_redis()
        if client is not None:
            try:
                await client.delete(f"ratelimit:{key}")
            except Exception:  # pragma: no cover - best effort
                pass


#: Shared limiter instance used by the FastAPI dependency.
_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Return the shared :class:`RateLimiter` instance."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
