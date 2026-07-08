"""Generic retry decorator with pluggable backoff strategies."""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class Backoff:
    """Backoff strategy interface — call delay(attempt) → seconds to sleep."""

    fn: Callable[[int], float]

    def delay(self, attempt: int) -> float:
        return self.fn(attempt)


def exponential(base: float = 2.0, max_delay: float = 10.0) -> Backoff:
    """Standard exponential backoff: base * 2^(attempt-1), capped at max_delay."""

    def _d(attempt: int) -> float:
        return min(base * (2 ** (attempt - 1)), max_delay)

    return Backoff(fn=_d)


def retry(
    *,
    max_attempts: int,
    backoff: Backoff,
    retry_on: tuple[type[BaseException], ...],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry `fn` on listed exception types up to max_attempts times."""

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retry_on as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    time.sleep(backoff.delay(attempt))
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
