"""Throttle bot search queries — interval pacing + per-run hard cap.

Distinct from JoinThrottle (which paces JoinChannelRequest) because the
acceptable cadence for "talking to a search bot" is different from
"joining a group" — interrogation is roughly safe at ~10s, joins want 30~90s.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Awaitable, Callable

logger = logging.getLogger("tg_crawler")


class BotQueryLimitExceeded(Exception):
    """Raised when the configured per-run query cap is hit."""


class BotQueryThrottle:
    def __init__(
        self,
        *,
        interval_seconds: float = 10.0,
        max_queries_per_run: int = 30,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        time_fn: Callable[[], float] | None = None,
    ):
        self._interval = float(interval_seconds)
        self._cap = int(max_queries_per_run)
        self._sleep = sleep_fn or asyncio.sleep
        self._time = time_fn or _time.monotonic

        self._last_at: float | None = None
        self._count: int = 0

    async def acquire(self) -> None:
        if self._count >= self._cap:
            raise BotQueryLimitExceeded(
                f"per-run bot-query cap reached ({self._cap})"
            )

        if self._last_at is not None and self._interval > 0:
            elapsed = self._time() - self._last_at
            remaining = self._interval - elapsed
            if remaining > 0:
                await self._sleep(remaining)

        self._last_at = self._time()
        self._count += 1
