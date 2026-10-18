"""SQL repository for ``channel_thread_bindings`` (SQLite or PostgreSQL).

Concurrency contract, shared with ``app.channels.store.SqlChannelStore``:

- ``upsert`` is one dialect-native ``INSERT ... ON CONFLICT (key) DO UPDATE``
  that replaces ``thread_id`` / ``user_id`` / ``updated_at`` and keeps the
  existing ``created_at`` — the overwrite semantics the JSON store had — so two
  replicas recording the same conversation never produce two rows and never
  lose the first stamp.
- ``insert_missing`` is the one-time import primitive: ``INSERT ... ON CONFLICT
  DO NOTHING`` in bounded batches, returning only the rows it actually inserted,
  so two replicas importing the same ``store.json`` concurrently can neither
  duplicate nor clobber a binding that already exists (including one a peer
  wrote live between the emptiness check and the insert).
- ``delete_prefix`` removes ``key == prefix`` and every ``key`` starting with
  ``prefix + ":"`` (``startswith(autoescape=True)``, so ``%`` / ``_`` in a chat
  id match literally) — exact parity with the JSON ``remove()`` that cleared a
  chat's base mapping and all its topics by key prefix, independent of how a
  legacy key was split into components.

Database errors propagate: the manager cannot route an IM message without the
database anyway, and failing loudly beats silently splitting a conversation
across two threads.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.channel_thread_bindings.model import ChannelThreadBinding, ChannelThreadBindingRow

#: Rows per ``INSERT`` statement during the import; keeps bind-parameter counts small on both dialects.
IMPORT_BATCH_SIZE = 500

_COLUMNS = (
    ChannelThreadBindingRow.key,
    ChannelThreadBindingRow.channel_name,
    ChannelThreadBindingRow.chat_id,
    ChannelThreadBindingRow.topic_id,
    ChannelThreadBindingRow.thread_id,
    ChannelThreadBindingRow.user_id,
    ChannelThreadBindingRow.created_at,
    ChannelThreadBindingRow.updated_at,
)


def _insert_for(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert
    if dialect == "sqlite":
        return sqlite_insert
    raise ValueError(f"Unsupported channel thread binding database dialect: {dialect}")


def _values(binding: ChannelThreadBinding) -> dict[str, object]:
    return {
        "key": binding.key,
        "channel_name": binding.channel_name,
        "chat_id": binding.chat_id,
        "topic_id": binding.topic_id,
        "thread_id": binding.thread_id,
        "user_id": binding.user_id,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def _binding(row) -> ChannelThreadBinding:
    key, channel_name, chat_id, topic_id, thread_id, user_id, created_at, updated_at = row
    return ChannelThreadBinding(key, channel_name, chat_id, topic_id, thread_id, user_id or "", float(created_at), float(updated_at))


class SqlChannelThreadBindingRepository:
    """Persistence facade for ``channel_thread_bindings``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_thread_id(self, key: str) -> str | None:
        async with self._sf() as session:
            return (await session.execute(select(ChannelThreadBindingRow.thread_id).where(ChannelThreadBindingRow.key == key))).scalar_one_or_none()

    async def upsert(self, binding: ChannelThreadBinding) -> None:
        """Create or overwrite the binding; an existing row keeps its ``created_at``."""
        async with self._sf() as session:
            stmt = _insert_for(session)(ChannelThreadBindingRow).values(**_values(binding))
            stmt = stmt.on_conflict_do_update(
                index_elements=[ChannelThreadBindingRow.key],
                set_={"thread_id": stmt.excluded.thread_id, "user_id": stmt.excluded.user_id, "updated_at": stmt.excluded.updated_at},
            )
            await session.execute(stmt)
            await session.commit()

    async def delete(self, key: str) -> bool:
        async with self._sf() as session:
            result = await session.execute(delete(ChannelThreadBindingRow).where(ChannelThreadBindingRow.key == key))
            await session.commit()
            return result.rowcount > 0

    async def delete_prefix(self, prefix: str) -> int:
        """Delete ``prefix`` itself and every ``prefix:*`` key; returns the number of rows removed."""
        async with self._sf() as session:
            predicate = or_(ChannelThreadBindingRow.key == prefix, ChannelThreadBindingRow.key.startswith(prefix + ":", autoescape=True))
            result = await session.execute(delete(ChannelThreadBindingRow).where(predicate))
            await session.commit()
            return int(result.rowcount or 0)

    async def list(self, channel_name: str | None = None) -> list[ChannelThreadBinding]:
        stmt = select(*_COLUMNS).order_by(ChannelThreadBindingRow.created_at, ChannelThreadBindingRow.key)
        if channel_name:
            stmt = stmt.where(ChannelThreadBindingRow.channel_name == channel_name)
        async with self._sf() as session:
            rows = (await session.execute(stmt)).all()
        return [_binding(row) for row in rows]

    async def count(self) -> int:
        async with self._sf() as session:
            return int((await session.execute(select(func.count()).select_from(ChannelThreadBindingRow))).scalar_one())

    async def insert_missing(self, bindings: Iterable[ChannelThreadBinding]) -> int:
        """``INSERT ... ON CONFLICT DO NOTHING`` in batches; returns how many rows this call inserted."""
        rows = [_values(binding) for binding in bindings]
        if not rows:
            return 0
        inserted = 0
        async with self._sf() as session:
            insert = _insert_for(session)
            for start in range(0, len(rows), IMPORT_BATCH_SIZE):
                batch = rows[start : start + IMPORT_BATCH_SIZE]
                result = await session.execute(insert(ChannelThreadBindingRow).values(batch).on_conflict_do_nothing(index_elements=[ChannelThreadBindingRow.key]))
                inserted += int(result.rowcount or 0)
            await session.commit()
        return inserted
