import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Callable, Optional

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.types import Channel, Chat

from tg_intel_crawler.utils.rate_limiter import RateLimiter

logger = logging.getLogger("tg_crawler")


class MessageData:
    """Unified message structure."""

    def __init__(self, msg):
        self.msg_id: int = msg.id
        self.group_id: int = msg.chat_id
        self.group_name: str = getattr(msg.chat, "title", str(msg.chat_id))
        self.sender_id: int = msg.sender_id or 0
        self.sender_name: str = self._get_sender_name(msg)
        self.sender_username: str = self._get_sender_username(msg)
        self.text: str = msg.text or ""
        self.date: datetime = msg.date
        self.media_type: Optional[str] = self._get_media_type(msg)
        self.media_path: Optional[str] = None
        self.forward_from: Optional[str] = None
        self.reply_to: Optional[int] = msg.reply_to_msg_id if msg.reply_to else None

        if msg.forward:
            self.forward_from = str(msg.forward.chat_id or msg.forward.sender_id or "unknown")

    @staticmethod
    def _get_sender_name(msg) -> str:
        """Get sender's display name."""
        sender = msg.sender
        if sender is None:
            return ""
        if hasattr(sender, "title"):  # Channel/Group
            return sender.title or ""
        first = getattr(sender, "first_name", "") or ""
        last = getattr(sender, "last_name", "") or ""
        return f"{first} {last}".strip()

    @staticmethod
    def _get_sender_username(msg) -> str:
        """Get sender's @username."""
        sender = msg.sender
        if sender is None:
            return ""
        return getattr(sender, "username", "") or ""

    @staticmethod
    def _get_media_type(msg) -> Optional[str]:
        if msg.photo:
            return "photo"
        elif msg.document:
            return "document"
        elif msg.video:
            return "video"
        return None

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "sender_username": self.sender_username,
            "text": self.text,
            "date": self.date.isoformat(),
            "media_type": self.media_type,
            "media_path": self.media_path,
            "forward_from": self.forward_from,
            "reply_to": self.reply_to,
        }


class MessageFetcher:
    """Fetch historical messages and listen for realtime messages."""

    def __init__(self, client: TelegramClient, rate_limiter: RateLimiter):
        self._client = client
        self._rate_limiter = rate_limiter

    async def fetch_history(
        self,
        group,
        days: int = 7,
        limit: int = None,
        on_progress: Callable[[int, int], None] = None,
    ) -> list[MessageData]:
        """Fetch historical messages from a group."""
        offset_date = datetime.now(timezone.utc) - timedelta(days=days)
        messages = []
        total = 0

        try:
            entity = await self._client.get_entity(group)
            group_name = getattr(entity, "title", str(group))
            logger.info(f"Fetching history from: {group_name} (last {days} days)")

            async for msg in self._client.iter_messages(
                entity, offset_date=offset_date, limit=limit, reverse=True
            ):
                if msg.text:
                    messages.append(MessageData(msg))
                total += 1

                if on_progress and total % 200 == 0:
                    on_progress(total, -1)

                if total % 100 == 0:
                    await self._rate_limiter.wait()

        except FloodWaitError as e:
            logger.warning(f"Rate limited. Waiting {e.seconds}s...")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"Error fetching history from {group}: {e}")

        logger.info(f"Fetched {len(messages)} text messages from {group}")
        return messages

    def start_realtime(
        self,
        groups: list,
        callback: Callable[[MessageData], None],
    ) -> None:
        """Register event handler for new messages in specified groups."""

        @self._client.on(events.NewMessage(chats=groups))
        async def handler(event):
            if event.message.text:
                msg_data = MessageData(event.message)
                await callback(msg_data)

        logger.info(f"Realtime listener registered for {len(groups)} groups")
