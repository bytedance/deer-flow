"""Visit each bot-given deeplink to fetch the full original message text.

Strategy:
- For each preview that has a (channel_username, msg_id):
  1. await throttle.acquire() to pace requests
  2. resolve channel entity (cache: {username -> entity}, valid this run only)
  3. client.get_messages(entity, ids=msg_id) → message
  4. return full text
- Downgrade gracefully on:
  - no deeplink at all                  → reason='no_deeplink'
  - ChannelPrivateError (etc.)          → reason='private'
  - ValueError ("Cannot find entity")   → reason='invalid_channel'
  - msg deleted / not found             → reason='msg_not_found'
  - FloodWaitError, retried once        → reason='flood_wait' on 2nd failure

The downstream pipeline writes preview text + [preview-only] marker when
degraded, so the LLM can be more conservative.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from tg_intel_crawler.collector.bot_response_parser import BotPreview


logger = logging.getLogger("tg_crawler")


@dataclass
class FetchOutcome:
    success: bool
    degraded: bool
    full_text: str | None
    reason: str | None      # 'ok' / 'no_deeplink' / 'private' / 'invalid_channel'
                            # / 'msg_not_found' / 'flood_wait'


def _default_private_types():
    try:
        from telethon.errors import (  # type: ignore
            ChannelPrivateError,
            ChatAdminRequiredError,
        )
        return (ChannelPrivateError, ChatAdminRequiredError)
    except Exception:
        return ()


def _default_flood_types():
    try:
        from telethon.errors import FloodWaitError  # type: ignore
        return (FloodWaitError,)
    except Exception:
        return ()


class DetailFetcher:
    def __init__(
        self,
        client,
        *,
        throttle,                                          # has .acquire()
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ):
        self._client = client
        self._throttle = throttle
        self._sleep = sleep_fn or asyncio.sleep
        self._entity_cache: dict[str, object] = {}

        self._private_exc_types: tuple = _default_private_types()
        self._flood_exc_types: tuple = _default_flood_types()

    async def fetch(self, preview: BotPreview) -> FetchOutcome:
        if not preview.channel_username or preview.msg_id is None:
            return FetchOutcome(False, True, None, "no_deeplink")

        await self._throttle.acquire()

        # 1. Resolve channel entity (cached).
        try:
            entity = await self._resolve_entity(preview.channel_username)
        except self._private_exc_types:
            logger.info(
                "detail-fetch: %s/%s skipped — channel is private and you're not in it",
                preview.channel_username, preview.msg_id,
            )
            return FetchOutcome(False, True, None, "private")
        except ValueError as e:
            logger.info(
                "detail-fetch: %s/%s skipped — invalid channel (%s)",
                preview.channel_username, preview.msg_id, e,
            )
            return FetchOutcome(False, True, None, "invalid_channel")
        except Exception as e:
            logger.warning(
                "detail-fetch: %s/%s — unexpected get_entity error %s: %s",
                preview.channel_username, preview.msg_id,
                type(e).__name__, e,
            )
            return FetchOutcome(False, True, None, "error")

        # 2. Fetch the message — retry once on FloodWait.
        try:
            msg = await self._client.get_messages(entity, ids=preview.msg_id)
        except self._flood_exc_types as e:
            wait = int(getattr(e, "seconds", 0)) or 60
            logger.warning(
                "detail-fetch: FloodWait fetching %s/%s — sleeping %ds before retry",
                preview.channel_username, preview.msg_id, wait,
            )
            await self._sleep(wait)
            try:
                msg = await self._client.get_messages(entity, ids=preview.msg_id)
            except self._flood_exc_types:
                return FetchOutcome(False, True, None, "flood_wait")
            except Exception as e2:
                logger.warning(
                    "detail-fetch: %s/%s — get_messages retry error %s: %s",
                    preview.channel_username, preview.msg_id,
                    type(e2).__name__, e2,
                )
                return FetchOutcome(False, True, None, "error")
        except self._private_exc_types:
            return FetchOutcome(False, True, None, "private")
        except Exception as e:
            logger.warning(
                "detail-fetch: %s/%s — unexpected get_messages error %s: %s",
                preview.channel_username, preview.msg_id,
                type(e).__name__, e,
            )
            return FetchOutcome(False, True, None, "error")

        if msg is None:
            return FetchOutcome(False, True, None, "msg_not_found")

        full_text = getattr(msg, "text", "") or ""
        return FetchOutcome(True, False, full_text, "ok")

    async def _resolve_entity(self, username: str):
        cached = self._entity_cache.get(username)
        if cached is not None:
            return cached
        entity = await self._client.get_entity(username)
        self._entity_cache[username] = entity
        return entity
