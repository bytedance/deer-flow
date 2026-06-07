"""Scan the account's currently-joined groups/channels via iter_dialogs()."""

from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger("tg_crawler")


@dataclass
class JoinedGroup:
    chat_id: int
    title: str
    username: str | None
    members_count: int | None
    type: str               # group / supergroup / channel
    # Public groups: "https://t.me/<username>" (str).
    # Private groups (no username): the raw chat_id as int — Telethon's
    # get_entity / events.NewMessage(chats=[...]) accept ints directly.
    # We do NOT use "https://t.me/c/<id>" here: that URL is a web-client
    # internal link and Telethon raises ValueError when asked to resolve it.
    link: str | int


class JoinedGroupsScanner:
    """List the groups & channels this account is currently in."""

    def __init__(self, client):
        self._client = client

    async def list_joined(
        self,
        include_channels: bool = True,
        exclude_usernames: set[str] | None = None,
        exclude_chat_ids: set[int] | None = None,
    ) -> list[JoinedGroup]:
        exclude_usernames = exclude_usernames or set()
        exclude_chat_ids = exclude_chat_ids or set()

        out: list[JoinedGroup] = []
        async for dialog in self._client.iter_dialogs():
            entity = dialog.entity
            if entity is None:
                continue

            # 1. Skip 1-on-1 user / bot dialogs.
            if getattr(dialog, "is_user", False):
                continue
            if getattr(entity, "bot", False):
                continue

            is_channel = getattr(dialog, "is_channel", False)
            is_group = getattr(dialog, "is_group", False)
            broadcast = getattr(entity, "broadcast", False)
            megagroup = getattr(entity, "megagroup", False)

            # 2. Classify type.
            if broadcast:
                gtype = "channel"
            elif megagroup:
                gtype = "supergroup"
            elif is_group:
                gtype = "group"
            elif is_channel:
                # Channel-marked but neither broadcast nor megagroup
                # — treat as channel by default.
                gtype = "channel"
            else:
                continue  # not a group or channel

            # 3. Optionally filter out broadcast channels.
            if not include_channels and gtype == "channel":
                continue

            # 4. Apply exclude lists.
            chat_id = getattr(entity, "id", 0)
            username = getattr(entity, "username", None)
            if chat_id in exclude_chat_ids:
                continue
            if username and username in exclude_usernames:
                continue

            link: str | int = (
                f"https://t.me/{username}" if username else chat_id
            )

            out.append(
                JoinedGroup(
                    chat_id=chat_id,
                    title=getattr(entity, "title", "") or "",
                    username=username,
                    members_count=getattr(entity, "participants_count", None),
                    type=gtype,
                    link=link,
                )
            )

        return out
