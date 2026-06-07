"""Talk to a Telegram search bot (e.g. @JISOU) via Telethon Conversation API."""

from __future__ import annotations

import asyncio
import logging


logger = logging.getLogger("tg_crawler")


class BotUnavailable(Exception):
    """Raised when the bot username can't be resolved (typo / banned / blocked)."""


class BotSearchClient:
    """Wrap the bot conversation pattern so callers don't have to deal with
    timeouts / exception types inline."""

    def __init__(self, client, *, bot: str, timeout: float = 15.0):
        self._client = client
        self._bot = bot
        self._timeout = float(timeout)

    async def ensure_available(self) -> None:
        """Resolve the bot's entity once at startup so we fail fast if the
        username is wrong or the bot has been blocked / banned."""
        try:
            await self._client.get_entity(self._bot)
        except Exception as e:
            raise BotUnavailable(f"cannot resolve bot {self._bot}: {e}") from e

    async def query(self, keyword: str) -> str | None:
        """Send a query to the bot and return the FIRST response text.

        Returns None on timeout. Lets other unexpected exceptions propagate so
        the caller can decide whether to skip the query or abort the run.
        """
        try:
            async with self._client.conversation(self._bot, timeout=self._timeout) as conv:
                await conv.send_message(keyword)
                response = await conv.get_response(timeout=self._timeout)
                return getattr(response, "text", "") or ""
        except asyncio.TimeoutError:
            logger.warning("bot %s timed out on query %r", self._bot, keyword)
            return None
