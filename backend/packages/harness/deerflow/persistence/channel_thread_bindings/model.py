"""ORM model for the shared IM chat -> DeerFlow thread binding table (``channel_thread_bindings``).

One row per unbound IM conversation the ``ChannelManager`` has routed to a
thread, keyed by the legacy composite ``channel_name:chat_id[:topic_id]`` string
that ``channels/store.json`` used. Every Gateway replica sharing the application
database reads and writes the same rows, so a conversation created on one
replica continues on the same thread when the next message lands on another.

The shape is deliberately 1:1 with the JSON entries so the one-time import is
lossless: ``created_at`` / ``updated_at`` stay epoch seconds (the JSON stored
``time.time()`` floats), ``user_id`` is the platform sender id the manager
recorded (``""`` when unknown, never NULL), and the component columns
(``channel_name``, ``chat_id``, ``topic_id``) are what the legacy
``list_entries()`` parsed out of the key. Lookups always go through ``key``.

Connection-bound conversations (``channel_conversations``) are a different
table on purpose: those rows belong to a user-owned connection; these are the
global fallback mapping for messages without one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Double, Index, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: Longest component values. ``channel_conversations`` already caps external ids
#: at 128, so 255 leaves every current provider id well inside the limit.
CHANNEL_NAME_LENGTH = 64
CHAT_ID_LENGTH = 255
TOPIC_ID_LENGTH = 255
THREAD_ID_LENGTH = 64
USER_ID_LENGTH = 255
#: ``channel_name:chat_id:topic_id`` at their maximum lengths plus separators.
BINDING_KEY_LENGTH = CHANNEL_NAME_LENGTH + 1 + CHAT_ID_LENGTH + 1 + TOPIC_ID_LENGTH


def binding_key(channel_name: str, chat_id: str, topic_id: str | None = None) -> str:
    """The legacy composite key: an empty or missing topic means "no topic"."""
    if topic_id:
        return f"{channel_name}:{chat_id}:{topic_id}"
    return f"{channel_name}:{chat_id}"


def split_binding_key(key: str) -> tuple[str, str, str | None]:
    """Split a legacy key into ``(channel_name, chat_id, topic_id)``.

    Mirrors the parsing the JSON store's ``list_entries()`` did: the first two
    colons separate the components, so a chat id that itself carries a colon
    lands partly in ``topic_id``. Rows written through the store carry exact
    components; only imported legacy keys inherit this ambiguity, and lookups
    never depend on it because they match the full ``key``.
    """
    parts = key.split(":", 2)
    channel = parts[0]
    chat = parts[1] if len(parts) > 1 else ""
    topic = parts[2] if len(parts) > 2 else None
    return channel, chat, topic


@dataclass(frozen=True, slots=True)
class ChannelThreadBinding:
    """One binding as the store and the import exchange it with the repository."""

    key: str
    channel_name: str
    chat_id: str
    topic_id: str | None
    thread_id: str
    user_id: str
    created_at: float
    updated_at: float

    @classmethod
    def build(cls, channel_name: str, chat_id: str, thread_id: str, *, topic_id: str | None = None, user_id: str = "", now: float) -> ChannelThreadBinding:
        """A fresh binding stamped ``now`` for both timestamps (the upsert keeps an existing ``created_at``)."""
        topic = topic_id or None
        return cls(binding_key(channel_name, chat_id, topic), channel_name, chat_id, topic, thread_id, user_id, now, now)

    def to_entry(self) -> dict[str, Any]:
        """The ``list_entries()`` item shape the JSON store returned (``topic_id`` only when present)."""
        item: dict[str, Any] = {
            "channel_name": self.channel_name,
            "chat_id": self.chat_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.topic_id is not None:
            item["topic_id"] = self.topic_id
        return item


class ChannelThreadBindingRow(Base):
    __tablename__ = "channel_thread_bindings"

    key: Mapped[str] = mapped_column(String(BINDING_KEY_LENGTH), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(CHANNEL_NAME_LENGTH), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(CHAT_ID_LENGTH), nullable=False)
    topic_id: Mapped[str | None] = mapped_column(String(TOPIC_ID_LENGTH), nullable=True)
    thread_id: Mapped[str] = mapped_column(String(THREAD_ID_LENGTH), nullable=False)
    user_id: Mapped[str] = mapped_column(String(USER_ID_LENGTH), nullable=False, default="")
    # Epoch seconds, exactly what the JSON store recorded with ``time.time()``.
    created_at: Mapped[float] = mapped_column(Double, nullable=False)
    updated_at: Mapped[float] = mapped_column(Double, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("key", name="pk_channel_thread_bindings"),
        # Serves ``list_entries(channel_name)``; the prefix ``remove`` walks the primary key.
        Index("ix_channel_thread_bindings_channel_chat", "channel_name", "chat_id"),
    )
