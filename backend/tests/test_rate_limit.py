"""Tests for the in-memory sliding-window rate limiter."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.rate_limit import RateLimitExceeded, RateLimiter


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    """Enable rate limiting for this module (it is off in the global test env)."""
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)


async def test_allows_requests_within_budget() -> None:
    """Requests under the limit are permitted."""
    limiter = RateLimiter()
    limiter._redis_failed = True  # force the in-memory path
    for _ in range(5):
        await limiter.check("client-a", limit=5, window=60)


async def test_blocks_requests_over_budget() -> None:
    """The next request over the limit is rejected with a retry hint."""
    limiter = RateLimiter()
    limiter._redis_failed = True
    for _ in range(3):
        await limiter.check("client-b", limit=3, window=60)
    with pytest.raises(RateLimitExceeded) as excinfo:
        await limiter.check("client-b", limit=3, window=60)
    assert excinfo.value.retry_after >= 1


async def test_keys_are_isolated() -> None:
    """Separate keys have independent budgets."""
    limiter = RateLimiter()
    limiter._redis_failed = True
    await limiter.check("client-c", limit=1, window=60)
    await limiter.check("client-d", limit=1, window=60)


async def test_reset_clears_budget() -> None:
    """Resetting a key restores its budget."""
    limiter = RateLimiter()
    limiter._redis_failed = True
    await limiter.check("client-e", limit=1, window=60)
    await limiter.reset("client-e")
    await limiter.check("client-e", limit=1, window=60)


async def test_window_expiry_restores_budget() -> None:
    """Once entries fall outside the window the budget is restored."""
    limiter = RateLimiter()
    limiter._redis_failed = True
    await limiter.check("client-f", limit=1, window=0.01)
    import asyncio

    await asyncio.sleep(0.05)
    await limiter.check("client-f", limit=1, window=0.01)


async def test_disabled_limiter_is_noop(monkeypatch) -> None:
    """When rate limiting is disabled no request is ever blocked."""
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    limiter = RateLimiter()
    limiter._redis_failed = True
    for _ in range(50):
        await limiter.check("client-g", limit=1, window=60)
