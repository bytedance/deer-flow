"""Throttle for Telegram join_group calls.

Concerns:
- Don't re-join groups the account is already in (`already_joined` set,
  warmable from `iter_dialogs`).
- Space joins out by min/max seconds (random in range).
- Cap joins per day (UTC day rolls counter).
- On Telethon ``FloodWaitError``, sleep and retry once.

Time and sleep are injectable so tests can fast-forward without real waits.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import random
import time as _time
from datetime import datetime, timezone
from typing import Awaitable, Callable

logger = logging.getLogger("tg_crawler")


class JoinThrottleResult(enum.Enum):
    OK = "ok"                       # cleared to join
    ALREADY_JOINED = "already"      # already in this group; skipped


class DailyLimitExceeded(Exception):
    """Raised when the configured per-day join cap is hit."""


def _default_flood_types():
    """Lazily import telethon's FloodWaitError so tests don't need telethon."""
    try:
        from telethon.errors import FloodWaitError  # type: ignore
        return (FloodWaitError,)
    except Exception:
        return ()


class JoinThrottle:
    def __init__(
        self,
        *,
        min_interval: float = 30.0,
        max_interval: float = 90.0,
        daily_limit: int = 20,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        time_fn: Callable[[], float] | None = None,
    ):
        if min_interval > max_interval:
            raise ValueError("min_interval must be <= max_interval")
        self._min = float(min_interval)
        self._max = float(max_interval)
        self._daily_limit = int(daily_limit)

        self._sleep = sleep_fn or asyncio.sleep
        self._time = time_fn or _time.monotonic

        self._already_joined_usernames: set[str] = set()
        self._already_joined_chat_ids: set[int] = set()

        self._last_join_at: float | None = None  # monotonic
        self._joins_today: int = 0
        self._joins_today_date: str = self._today_key()

        self._flood_exc_types: tuple[type[BaseException], ...] = _default_flood_types()

    # ---------- already-joined cache ----------

    def warmup(
        self,
        usernames: set[str] | None = None,
        chat_ids: set[int] | None = None,
    ) -> None:
        if usernames:
            self._already_joined_usernames |= {u.lower() for u in usernames if u}
        if chat_ids:
            self._already_joined_chat_ids |= chat_ids

    def mark_joined(self, username: str | None = None, chat_id: int | None = None) -> None:
        if username:
            self._already_joined_usernames.add(username.lower())
        if chat_id is not None:
            self._already_joined_chat_ids.add(chat_id)

    def is_already_joined(self, username: str | None = None, chat_id: int | None = None) -> bool:
        if username and username.lower() in self._already_joined_usernames:
            return True
        if chat_id is not None and chat_id in self._already_joined_chat_ids:
            return True
        return False

    # ---------- core API ----------

    async def acquire(self, username: str | None = None, chat_id: int | None = None) -> JoinThrottleResult:
        """Block until it's safe to make a join call.

        Returns ALREADY_JOINED (no sleep) if we know we're in the group.
        Raises DailyLimitExceeded if we've hit the daily cap.
        Otherwise sleeps for the spacing interval and returns OK.
        """
        if self.is_already_joined(username=username, chat_id=chat_id):
            return JoinThrottleResult.ALREADY_JOINED

        self._roll_day_if_needed()
        if self._joins_today >= self._daily_limit:
            raise DailyLimitExceeded(
                f"daily join limit reached ({self._daily_limit})"
            )

        # Wait out the inter-join spacing.
        if self._last_join_at is not None:
            interval = random.uniform(self._min, self._max)
            elapsed = self._time() - self._last_join_at
            remaining = interval - elapsed
            if remaining > 0:
                await self._sleep(remaining)

        self._last_join_at = self._time()
        self._joins_today += 1
        return JoinThrottleResult.OK

    async def run_join(
        self,
        target: str,
        join_callable: Callable[[], Awaitable],
        *,
        chat_id: int | None = None,
    ):
        """Acquire → call → mark_joined, with one FloodWait retry.

        Returns whatever join_callable returns, or None if short-circuited
        because we'd already joined.
        """
        result = await self.acquire(username=target, chat_id=chat_id)
        if result is JoinThrottleResult.ALREADY_JOINED:
            logger.debug("Already joined %s — skipping", target)
            return None

        try:
            ret = await join_callable()
        except self._flood_exc_types as e:  # type: ignore[misc]
            wait = int(getattr(e, "seconds", 0)) or 60
            logger.warning("FloodWait on join %s: sleeping %ds before retry", target, wait)
            await self._sleep(wait)
            ret = await join_callable()  # retry exactly once; raises on second failure

        self.mark_joined(username=target, chat_id=chat_id)
        return ret

    # ---------- internals ----------

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day_if_needed(self) -> None:
        today = self._today_key()
        if today != self._joins_today_date:
            self._joins_today_date = today
            self._joins_today = 0
