import logging

from telethon import TelegramClient
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel, Chat

logger = logging.getLogger("tg_crawler")


class GroupFinder:
    """Search and discover Telegram groups by keywords."""

    def __init__(self, client: TelegramClient):
        self._client = client

    async def search_groups(self, keywords: list[str], limit: int = 20) -> list[dict]:
        """Search public groups/channels by keywords.

        Returns list of dicts with group info:
        {id, title, username, members_count, type}
        """
        found_groups = []
        seen_ids = set()

        for keyword in keywords:
            try:
                result = await self._client(SearchRequest(
                    q=keyword,
                    limit=limit,
                ))

                for chat in result.chats:
                    if chat.id in seen_ids:
                        continue
                    seen_ids.add(chat.id)

                    group_info = {
                        "id": chat.id,
                        "title": getattr(chat, "title", ""),
                        "username": getattr(chat, "username", None),
                        "members_count": getattr(chat, "participants_count", 0),
                        "type": "channel" if isinstance(chat, Channel) and chat.broadcast else "group",
                    }
                    found_groups.append(group_info)
                    logger.info(
                        f"Found: {group_info['title']} (@{group_info['username']})"
                        f" - {group_info['members_count']} members"
                    )

            except Exception as e:
                logger.error(f"Search failed for keyword '{keyword}': {e}")

        return found_groups

    async def join_group(self, username: str) -> bool:
        """Join a public group by username or invite link."""
        try:
            if username.startswith("https://t.me/"):
                username = username.split("/")[-1]

            entity = await self._client.get_entity(username)
            await self._client(JoinChannelRequest(entity))
            logger.info(f"Joined group: {getattr(entity, 'title', username)}")
            return True
        except Exception as e:
            logger.error(f"Failed to join {username}: {e}")
            return False
