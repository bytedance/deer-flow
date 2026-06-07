"""Classify a Telegram username into group/channel vs. user/bot.

Telegram shares ONE username namespace across users, bots, groups and
channels — so a bare ``@clhs9`` mined from a message could equally be a
private contact ("联系 @clhs9 买号") or an actual group. The candidate pool,
being built from pure text, cannot tell them apart.

This resolver does the one thing text can't: a single ``get_entity`` call
per candidate to read the real entity type off Telegram. Used by
``llm-crawl`` to drop personal accounts BEFORE wasting a join + crawl on
something that isn't a group.

Private invite links (``+hash``) are groups by construction and never need
this check.
"""

from __future__ import annotations

import enum
import logging

logger = logging.getLogger("tg_crawler")


class EntityKind(enum.Enum):
    GROUP = "group"          # group / supergroup / megagroup
    CHANNEL = "channel"      # broadcast channel
    USER = "user"            # personal account
    BOT = "bot"              # bot account
    NOT_FOUND = "not_found"  # username doesn't resolve (deleted/typo/banned)
    ERROR = "error"          # transient failure (FloodWait, network, ...)

    @property
    def is_crawlable_group(self) -> bool:
        """True only for things we can join + crawl as a group/channel."""
        return self in (EntityKind.GROUP, EntityKind.CHANNEL)


class EntityClassifier:
    """Resolve a username to its real Telegram entity kind."""

    def __init__(self, client):
        self._client = client

    async def classify(self, username: str) -> EntityKind:
        """One ``get_entity`` call → EntityKind.

        ``username`` may be a bare username, ``@username`` or a
        ``https://t.me/<username>`` link. Returns NOT_FOUND when Telegram
        can't resolve it, ERROR on transient failures (caller decides whether
        to treat ERROR conservatively — we skip, to avoid joining junk).
        """
        target = username.strip()
        if target.startswith("https://t.me/"):
            target = target.rsplit("/", 1)[-1]
        target = target.lstrip("@")

        try:
            entity = await self._client.get_entity(target)
        except (ValueError, TypeError) as e:
            # Telethon raises ValueError for "No user has <username>" etc.
            logger.debug("classify %s → not found: %s", username, e)
            return EntityKind.NOT_FOUND
        except Exception as e:
            exc_name = type(e).__name__
            # Telethon's UsernameNotOccupiedError / UsernameInvalidError mean
            # the username genuinely doesn't resolve → NOT_FOUND (so we reject
            # it), NOT a transient error. Match by class name to avoid a hard
            # telethon import here.
            if exc_name in ("UsernameNotOccupiedError", "UsernameInvalidError"):
                logger.debug("classify %s → not found: %s", username, e)
                return EntityKind.NOT_FOUND
            # FloodWait is a HARD rate limit (often hours). Re-raise so the
            # caller can stop the whole batch instead of hammering it.
            if exc_name == "FloodWaitError":
                raise
            # Other transient issues (ConnectionError, ...) → keep & retry.
            logger.warning("classify %s → error: %s", username, e)
            return EntityKind.ERROR

        return self._kind_of(entity)

    @staticmethod
    def _kind_of(entity) -> EntityKind:
        # Bot is a User with bot=True — check it first.
        if getattr(entity, "bot", False):
            return EntityKind.BOT

        cls_name = type(entity).__name__
        if cls_name == "User":
            return EntityKind.USER

        # Channel covers both broadcast channels and megagroups (supergroups).
        if getattr(entity, "broadcast", False):
            return EntityKind.CHANNEL
        if getattr(entity, "megagroup", False):
            return EntityKind.GROUP
        # Legacy basic group (Chat) or anything else group-shaped.
        if cls_name in ("Chat", "Channel"):
            return EntityKind.GROUP

        return EntityKind.USER
