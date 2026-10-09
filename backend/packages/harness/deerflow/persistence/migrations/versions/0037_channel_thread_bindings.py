"""Shared IM chat -> DeerFlow thread bindings for multi-replica channel routing.

Revision ID: 0037_channel_thread_bindings
Revises: 0036_run_idempotency_request

Creates ``channel_thread_bindings``: one row per unbound IM conversation the
``ChannelManager`` routed to a thread, keyed by the legacy composite
``channel_name:chat_id[:topic_id]`` string from ``channels/store.json``, with
the parsed components, the ``thread_id``, the platform ``user_id`` and the
epoch ``created_at`` / ``updated_at`` stamps the JSON entries carried. Every
Gateway replica sharing the application database reads and writes the same
rows, replacing the per-process JSON file that made a binding created on one
replica invisible to the others (each then created its own thread for the same
chat). ``ChannelService.start()`` imports an existing ``store.json`` once and
renames it to ``store.json.migrated``.

``_helpers.py`` only guards columns, so the table and its index are guarded
with a fresh inspector in both directions: an upgrade that finds the table (an
interrupted earlier attempt, or an empty-database bootstrap that already ran
``create_all``) completes, and a downgrade after the table is gone still moves
the version row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_channel_thread_bindings"
down_revision: str | Sequence[str] | None = "0036_run_idempotency_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "channel_thread_bindings"
_INDEX = "ix_channel_thread_bindings_channel_chat"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(_TABLE)


def _has_index() -> bool:
    if not _has_table():
        return False
    return _INDEX in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)}


def upgrade() -> None:
    if not _has_table():
        op.create_table(
            _TABLE,
            sa.Column("key", sa.String(length=576), nullable=False),
            sa.Column("channel_name", sa.String(length=64), nullable=False),
            sa.Column("chat_id", sa.String(length=255), nullable=False),
            sa.Column("topic_id", sa.String(length=255), nullable=True),
            sa.Column("thread_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.Double(), nullable=False),
            sa.Column("updated_at", sa.Double(), nullable=False),
            sa.PrimaryKeyConstraint("key", name="pk_channel_thread_bindings"),
        )
    # Serves ``list_entries(channel_name)``; guarded separately so a table
    # left behind by an interrupted attempt still gets its index.
    if not _has_index():
        op.create_index(_INDEX, _TABLE, ["channel_name", "chat_id"])


def downgrade() -> None:
    if _has_index():
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_table():
        op.drop_table(_TABLE)
