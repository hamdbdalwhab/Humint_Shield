"""Tests for the retry helper."""
from __future__ import annotations

import pytest

from app.services.retry import RetryExhausted, retry_async


async def test_retry_succeeds_first_attempt() -> None:
    """A successful operation is not retried."""
    calls = {"n": 0}

    async def operation() -> str:
        calls["n"] += 1
        return "ok"

    assert await retry_async(operation, attempts=3) == "ok"
    assert calls["n"] == 1


async def test_retry_eventually_succeeds() -> None:
    """Transient failures are retried until success."""
    calls = {"n": 0}

    async def operation() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    result = await retry_async(operation, attempts=3, base_delay=0.001, backoff_factor=1.0)
    assert result == "recovered"
    assert calls["n"] == 3


async def test_retry_exhausted_raises() -> None:
    """Exhausting every attempt raises ``RetryExhausted``."""
    calls = {"n": 0}

    async def operation() -> None:
        calls["n"] += 1
        raise RuntimeError("always fails")

    with pytest.raises(RetryExhausted) as excinfo:
        await retry_async(operation, attempts=2, base_delay=0.001, backoff_factor=1.0)
    assert calls["n"] == 2
    assert excinfo.value.attempts == 2
    assert "always fails" in str(excinfo.value.last_error)


async def test_should_retry_false_stops_immediately() -> None:
    """A permanent failure is not retried, however many attempts are allowed."""
    calls = {"n": 0}

    async def operation() -> None:
        calls["n"] += 1
        raise RuntimeError("permanent rejection")

    with pytest.raises(RetryExhausted) as excinfo:
        await retry_async(
            operation,
            attempts=5,
            base_delay=0.001,
            backoff_factor=1.0,
            should_retry=lambda exc: False,
        )
    assert calls["n"] == 1
    assert excinfo.value.attempts == 5
    assert excinfo.value.attempts_made == 1
    assert excinfo.value.permanent is True
    assert "permanently rejected" in str(excinfo.value)
    assert "permanent rejection" in str(excinfo.value.last_error)


async def test_should_retry_true_keeps_retrying() -> None:
    """An exception the predicate accepts still consumes the full budget."""
    calls = {"n": 0}

    async def operation() -> None:
        calls["n"] += 1
        raise RuntimeError("transient")

    with pytest.raises(RetryExhausted):
        await retry_async(
            operation,
            attempts=3,
            base_delay=0.001,
            backoff_factor=1.0,
            should_retry=lambda exc: True,
        )
    assert calls["n"] == 3
