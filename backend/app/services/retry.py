"""Retry helper: exponential backoff for transient external failures."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class RetryExhausted(Exception):
    """Raised when an operation cannot be completed by retrying.

    Covers two distinct outcomes, distinguished by :attr:`permanent`:

    * the attempt budget was consumed (``permanent`` is ``False``);
    * the failure was classified as permanent and retrying was abandoned after
      the first attempt (``permanent`` is ``True``).
    """

    def __init__(
        self,
        attempts: int,
        last_error: Exception,
        *,
        attempts_made: int | None = None,
        permanent: bool = False,
    ) -> None:
        """Record how the operation ended.

        Args:
            attempts: The configured attempt budget.
            last_error: The final exception raised by the operation.
            attempts_made: How many attempts actually ran (defaults to the budget).
            permanent: Whether retrying was abandoned as futile.
        """
        self.attempts = attempts
        self.attempts_made = attempts if attempts_made is None else attempts_made
        self.last_error = last_error
        self.permanent = permanent
        outcome = (
            "permanently rejected"
            if permanent
            else f"failed after {self.attempts_made} attempts"
        )
        super().__init__(f"Operation {outcome}: {last_error}")


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    should_retry: Callable[[BaseException], bool] | None = None,
    operation_name: str = "operation",
    correlation_id: str | None = None,
) -> T:
    """Run ``operation`` with exponential backoff.

    Delay between attempt ``n`` and ``n+1`` is
    ``min(base_delay * backoff_factor ** n, max_delay)`` seconds
    (2s, 4s, 8s by default).

    Args:
        operation: A zero-argument coroutine factory to invoke.
        attempts: Total number of attempts (including the first).
        base_delay: Delay before the first retry, in seconds.
        backoff_factor: Multiplier applied to the delay after each failure.
        max_delay: Upper bound on the delay, in seconds.
        retry_on: Exception classes that trigger a retry.
        should_retry: Optional predicate applied to the caught exception. When it
            returns ``False`` the failure is treated as permanent, logged and
            re-raised immediately instead of consuming the remaining attempts.
            Useful for 4xx responses from external APIs, which never succeed on
            a retry and would otherwise waste the backoff budget.
        operation_name: Label used in structured logs.
        correlation_id: Optional correlation id propagated to the logs.

    Returns:
        The value returned by ``operation`` on a successful attempt.

    Raises:
        RetryExhausted: If every attempt fails.
    """
    last_error: Exception = RuntimeError("no attempts made")
    attempts_made = 0
    permanent = False
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except retry_on as exc:  # noqa: PERF203 - retry loop is intentional
            last_error = exc
            attempts_made = attempt
            if should_retry is not None and not should_retry(exc):
                permanent = True
                logger.warning(
                    "retry_abandoned_permanent",
                    operation=operation_name,
                    attempt=attempt,
                    attempts=attempts,
                    error=str(exc),
                    correlation_id=correlation_id,
                )
                break
            if attempt >= attempts:
                logger.error(
                    "retry_exhausted",
                    operation=operation_name,
                    attempt=attempt,
                    attempts=attempts,
                    error=str(exc),
                    correlation_id=correlation_id,
                )
                break
            delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
            logger.warning(
                "retry_scheduled",
                operation=operation_name,
                attempt=attempt,
                attempts=attempts,
                delay_seconds=delay,
                error=str(exc),
                correlation_id=correlation_id,
            )
            await asyncio.sleep(delay)
    raise RetryExhausted(
        attempts, last_error, attempts_made=attempts_made, permanent=permanent
    )
