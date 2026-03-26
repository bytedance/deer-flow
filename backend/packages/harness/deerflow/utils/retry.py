"""Retry utilities for handling transient errors.

This module provides decorators and utilities for automatic retry of operations
that may fail due to transient errors (network issues, rate limiting, etc.).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds
DEFAULT_EXPONENTIAL_BASE = 2.0
DEFAULT_JITTER = True


class RetryError(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, message: str, last_exception: Exception | None = None, attempts: int = 0):
        super().__init__(message)
        self.last_exception = last_exception
        self.attempts = attempts

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.attempts > 0:
            parts.append(f"(failed after {self.attempts} attempts)")
        if self.last_exception:
            parts.append(f"Last error: {self.last_exception}")
        return " | ".join(parts)


def calculate_delay(
    attempt: int,
    *,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exponential_base: float = DEFAULT_EXPONENTIAL_BASE,
    jitter: bool = DEFAULT_JITTER,
) -> float:
    """Calculate the delay before the next retry attempt.

    Uses exponential backoff with optional jitter to avoid thundering herd.

    Args:
        attempt: The current attempt number (0-indexed).
        initial_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        exponential_base: Base for exponential backoff.
        jitter: Whether to add random jitter to the delay.

    Returns:
        The delay in seconds before the next retry.
    """
    delay = initial_delay * (exponential_base**attempt)
    delay = min(delay, max_delay)
    if jitter:
        # Add random jitter (0.5x to 1.5x the delay)
        delay = delay * (0.5 + random.random())
    return delay


def should_retry(
    exception: Exception,
    *,
    retry_on: tuple[type[Exception], ...] | None = None,
    retry_on_status_codes: set[int] | None = None,
) -> bool:
    """Determine if an exception should trigger a retry.

    Args:
        exception: The exception that was raised.
        retry_on: Tuple of exception types that should trigger retry.
        retry_on_status_codes: Set of HTTP status codes that should trigger retry.

    Returns:
        True if the operation should be retried, False otherwise.
    """
    if retry_on is None:
        # Default retry on common transient errors
        retry_on = (
            ConnectionError,
            TimeoutError,
            OSError,  # Includes network errors
        )

    # Check if exception is of a retryable type
    if isinstance(exception, retry_on):
        return True

    # Check for specific DeerFlow exceptions with recoverable flag
    from deerflow.exceptions import DeerFlowError, ModelAPICallError

    if isinstance(exception, DeerFlowError):
        if exception.recoverable:
            return True
        if isinstance(exception, ModelAPICallError):
            # Retry on rate limits and server errors
            if exception.status_code in (retry_on_status_codes or {429, 500, 502, 503, 504}):
                return True

    return False


def retry(
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exponential_base: float = DEFAULT_EXPONENTIAL_BASE,
    jitter: bool = DEFAULT_JITTER,
    retry_on: tuple[type[Exception], ...] | None = None,
    retry_on_status_codes: set[int] | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for automatic retry of functions on transient errors.

    Args:
        max_retries: Maximum number of retry attempts.
        initial_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay between retries in seconds.
        exponential_base: Base for exponential backoff.
        jitter: Whether to add random jitter to delays.
        retry_on: Tuple of exception types that should trigger retry.
        retry_on_status_codes: Set of HTTP status codes that should trigger retry.
        on_retry: Optional callback called before each retry with (exception, attempt, delay).

    Returns:
        Decorated function with retry logic.

    Example:
        >>> @retry(max_retries=3, initial_delay=1.0)
        ... def fetch_data():
        ...     return requests.get("https://api.example.com/data")

        >>> @retry(retry_on=(ConnectionError, TimeoutError))
        ... async def fetch_async():
        ...     return await aiohttp.get("https://api.example.com/data")
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs) -> T:
                last_exception: Exception | None = None
                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        if attempt == max_retries or not should_retry(
                            e,
                            retry_on=retry_on,
                            retry_on_status_codes=retry_on_status_codes,
                        ):
                            raise
                        delay = calculate_delay(
                            attempt,
                            initial_delay=initial_delay,
                            max_delay=max_delay,
                            exponential_base=exponential_base,
                            jitter=jitter,
                        )
                        logger.warning(
                            "Retry %d/%d for %s after %s: waiting %.2fs",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            type(e).__name__,
                            delay,
                        )
                        if on_retry:
                            on_retry(e, attempt, delay)
                        await asyncio.sleep(delay)
                raise RetryError(
                    f"Unexpected state in retry logic for {func.__name__}",
                    last_exception=last_exception,
                    attempts=max_retries + 1,
                )

            return async_wrapper  # type: ignore
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs) -> T:
                last_exception: Exception | None = None
                for attempt in range(max_retries + 1):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        if attempt == max_retries or not should_retry(
                            e,
                            retry_on=retry_on,
                            retry_on_status_codes=retry_on_status_codes,
                        ):
                            raise
                        delay = calculate_delay(
                            attempt,
                            initial_delay=initial_delay,
                            max_delay=max_delay,
                            exponential_base=exponential_base,
                            jitter=jitter,
                        )
                        logger.warning(
                            "Retry %d/%d for %s after %s: waiting %.2fs",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            type(e).__name__,
                            delay,
                        )
                        if on_retry:
                            on_retry(e, attempt, delay)
                        time.sleep(delay)
                raise RetryError(
                    f"Unexpected state in retry logic for {func.__name__}",
                    last_exception=last_exception,
                    attempts=max_retries + 1,
                )

            return sync_wrapper  # type: ignore

    return decorator


async def retry_async(
    coro_factory: Callable[[], Awaitable[T]] | Awaitable[T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exponential_base: float = DEFAULT_EXPONENTIAL_BASE,
    jitter: bool = DEFAULT_JITTER,
    retry_on: tuple[type[Exception], ...] | None = None,
    retry_on_status_codes: set[int] | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None,
) -> T:
    """Retry an async operation on transient errors.

    This is useful when you want to add retry logic to async operations.
    Pass a coroutine factory function (callable that returns a coroutine)
    for proper retry behavior, since coroutines cannot be reused after awaiting.

    Args:
        coro_factory: Either a callable that returns a coroutine, or a coroutine
            (note: coroutines cannot be reused, so a factory is recommended for retries).
        max_retries: Maximum number of retry attempts.
        initial_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay between retries in seconds.
        exponential_base: Base for exponential backoff.
        jitter: Whether to add random jitter to delays.
        retry_on: Tuple of exception types that should trigger retry.
        retry_on_status_codes: Set of HTTP status codes that should trigger retry.
        on_retry: Optional callback called before each retry.

    Returns:
        The result of the coroutine.

    Raises:
        RetryError: If all retry attempts are exhausted.

    Example:
        >>> # Recommended: pass a factory function
        >>> result = await retry_async(
        ...     lambda: some_async_operation(),
        ...     max_retries=3,
        ...     retry_on=(ConnectionError,)
        ... )
        >>> 
        >>> # Alternative: pass a coroutine directly (single attempt only)
        >>> result = await retry_async(some_async_operation())
    """
    last_exception: Exception | None = None
    
    # Check if we received a coroutine factory or a coroutine
    is_factory = callable(coro_factory) and not asyncio.iscoroutine(coro_factory)
    
    for attempt in range(max_retries + 1):
        try:
            if is_factory:
                coro = coro_factory()
            else:
                # For direct coroutines, only one attempt is possible
                if attempt > 0:
                    raise RetryError(
                        "Cannot retry a coroutine that has already been awaited. "
                        "Pass a factory function instead: retry_async(lambda: your_coroutine())",
                        last_exception=last_exception,
                        attempts=attempt,
                    )
                coro = coro_factory
            return await coro
        except Exception as e:
            last_exception = e
            if attempt == max_retries or not should_retry(
                e,
                retry_on=retry_on,
                retry_on_status_codes=retry_on_status_codes,
            ):
                raise
            if not is_factory:
                raise RetryError(
                    "Cannot retry a coroutine that has already been awaited. "
                    "Pass a factory function instead: retry_async(lambda: your_coroutine())",
                    last_exception=last_exception,
                    attempts=attempt + 1,
                ) from e
            delay = calculate_delay(
                attempt,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
            )
            logger.warning(
                "Retry %d/%d for async operation after %s: waiting %.2fs",
                attempt + 1,
                max_retries,
                type(e).__name__,
                delay,
            )
            if on_retry:
                on_retry(e, attempt, delay)
            await asyncio.sleep(delay)

    raise RetryError(
        "All retry attempts exhausted",
        last_exception=last_exception,
        attempts=max_retries + 1,
    )


class RetryContext:
    """Context manager for retrying operations with manual control.

    Useful when you need more control over the retry loop.

    Example:
        >>> with RetryContext(max_retries=3) as retry_ctx:
        ...     while retry_ctx.should_retry():
        ...         try:
        ...             result = perform_operation()
        ...             break
        ...         except ConnectionError as e:
        ...             retry_ctx.handle_exception(e)
    """

    def __init__(
        self,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_delay: float = DEFAULT_INITIAL_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        exponential_base: float = DEFAULT_EXPONENTIAL_BASE,
        jitter: bool = DEFAULT_JITTER,
        retry_on: tuple[type[Exception], ...] | None = None,
        retry_on_status_codes: set[int] | None = None,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retry_on = retry_on
        self.retry_on_status_codes = retry_on_status_codes
        self.attempt = 0
        self.last_exception: Exception | None = None

    def __enter__(self) -> "RetryContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def should_retry(self) -> bool:
        """Check if we should attempt another retry."""
        return self.attempt <= self.max_retries

    def handle_exception(self, exception: Exception) -> float:
        """Handle an exception and return the delay before next retry.

        Raises:
            The exception if no more retries are allowed.
        """
        self.last_exception = exception
        if self.attempt >= self.max_retries or not should_retry(
            exception,
            retry_on=self.retry_on,
            retry_on_status_codes=self.retry_on_status_codes,
        ):
            raise exception

        delay = calculate_delay(
            self.attempt,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            jitter=self.jitter,
        )
        self.attempt += 1
        return delay

    def get_delay(self) -> float:
        """Get the delay before the next retry attempt."""
        return calculate_delay(
            self.attempt,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            jitter=self.jitter,
        )