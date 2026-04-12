"""SQLAlchemy-backed RunEventStore implementation.

Persists events to the ``run_events`` table. Trace content is truncated
at ``max_trace_content`` bytes to avoid bloating the database.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.models.run_event import RunEventRow
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.user_context import AUTO, _AutoSentinel, get_current_user, resolve_user_id

logger = logging.getLogger(__name__)


class DbRunEventStore(RunEventStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, max_trace_content: int = 10240):
        self._sf = session_factory
        self._max_trace_content = max_trace_content

    @staticmethod
    def _row_to_dict(row: RunEventRow) -> dict:
        d = row.to_dict()
        d["metadata"] = d.pop("event_metadata", {})
        val = d.get("created_at")
        if isinstance(val, datetime):
            d["created_at"] = val.isoformat()
        d.pop("id", None)
        # Restore dict content that was JSON-serialized on write
        raw = d.get("content", "")
        if isinstance(raw, str) and d.get("metadata", {}).get("content_is_dict"):
            try:
                d["content"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                # Content looked like JSON (content_is_dict flag) but failed to parse;
                # keep the raw string as-is.
                logger.debug("Failed to deserialize content as JSON for event seq=%s", d.get("seq"))
        return d

    def _truncate_trace(self, category: str, content: str | dict, metadata: dict | None) -> tuple[str | dict, dict]:
        if category == "trace":
            text = json.dumps(content, default=str, ensure_ascii=False) if isinstance(content, dict) else content
            encoded = text.encode("utf-8")
            if len(encoded) > self._max_trace_content:
                # Truncate by bytes, then decode back (may cut a multi-byte char, so use errors="ignore")
                content = encoded[: self._max_trace_content].decode("utf-8", errors="ignore")
                metadata = {**(metadata or {}), "content_truncated": True, "original_byte_length": len(encoded)}
        return content, metadata or {}

    @staticmethod
    def _user_id_from_context() -> str | None:
        """Soft read of user_id from contextvar for write paths.

        Returns ``None`` (no filter / no stamp) if contextvar is unset,
        which is the expected case for background worker writes. HTTP
        request writes will have the contextvar set by auth middleware
        and get their user_id stamped automatically.

        Coerces ``user.id`` to ``str`` at the boundary: ``User.id`` is
        typed as ``UUID`` by the auth layer, but ``run_events.user_id``
        is ``VARCHAR(64)`` and aiosqlite cannot bind a raw UUID object
        to a VARCHAR column ("type 'UUID' is not supported") — the
        INSERT would silently roll back and the worker would hang.
        """
        user = get_current_user()
        return str(user.id) if user is not None else None

    async def put(self, *, thread_id, run_id, event_type, category, content="", metadata=None, created_at=None):  # noqa: D401
        """Write a single event — low-frequency path only.

        This opens a dedicated transaction with a FOR UPDATE lock to
        assign a monotonic *seq*.  For high-throughput writes use
        :meth:`put_batch`, which acquires the lock once for the whole
        batch.  Currently the only caller is ``worker.run_agent`` for
        the initial ``human_message`` event (once per run).
        """
        content, metadata = self._truncate_trace(category, content, metadata)
        if isinstance(content, dict):
            db_content = json.dumps(content, default=str, ensure_ascii=False)
            metadata = {**(metadata or {}), "content_is_dict": True}
        else:
            db_content = content
        user_id = self._user_id_from_context()
        async with self._sf() as session:
            async with session.begin():
                # Use FOR UPDATE to serialize seq assignment within a thread.
                # NOTE: with_for_update() on aggregates is a no-op on SQLite;
                # the UNIQUE(thread_id, seq) constraint catches races there.
                max_seq = await session.scalar(select(func.max(RunEventRow.seq)).where(RunEventRow.thread_id == thread_id).with_for_update())
                seq = (max_seq or 0) + 1
                row = RunEventRow(
                    thread_id=thread_id,
                    run_id=run_id,
                    user_id=user_id,
                    event_type=event_type,
                    category=category,
                    content=db_content,
                    event_metadata=metadata,
                    seq=seq,
                    created_at=datetime.fromisoformat(created_at) if created_at else datetime.now(UTC),
                )
                session.add(row)
            return self._row_to_dict(row)

    async def put_batch(self, events):
        if not events:
            return []
        user_id = self._user_id_from_context()
        async with self._sf() as session:
            async with session.begin():
                # Get max seq for the thread (assume all events in batch belong to same thread).
                # NOTE: with_for_update() on aggregates is a no-op on SQLite;
                # the UNIQUE(thread_id, seq) constraint catches races there.
                thread_id = events[0]["thread_id"]
                max_seq = await session.scalar(select(func.max(RunEventRow.seq)).where(RunEventRow.thread_id == thread_id).with_for_update())
                seq = max_seq or 0
                rows = []
                for e in events:
                    seq += 1
                    content = e.get("content", "")
                    category = e.get("category", "trace")
                    metadata = e.get("metadata")
                    content, metadata = self._truncate_trace(category, content, metadata)
                    if isinstance(content, dict):
                        db_content = json.dumps(content, default=str, ensure_ascii=False)
                        metadata = {**(metadata or {}), "content_is_dict": True}
                    else:
                        db_content = content
                    row = RunEventRow(
                        thread_id=e["thread_id"],
                        run_id=e["run_id"],
                        user_id=e.get("user_id", user_id),
                        event_type=e["event_type"],
                        category=category,
                        content=db_content,
                        event_metadata=metadata,
                        seq=seq,
                        created_at=datetime.fromisoformat(e["created_at"]) if e.get("created_at") else datetime.now(UTC),
                    )
                    session.add(row)
                    rows.append(row)
            return [self._row_to_dict(r) for r in rows]

    async def list_messages(
        self,
        thread_id,
        *,
        limit=50,
        before_seq=None,
        after_seq=None,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.list_messages")
        stmt = select(RunEventRow).where(RunEventRow.thread_id == thread_id, RunEventRow.category == "message")
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        if before_seq is not None:
            stmt = stmt.where(RunEventRow.seq < before_seq)
        if after_seq is not None:
            stmt = stmt.where(RunEventRow.seq > after_seq)

        if after_seq is not None:
            # Forward pagination: first `limit` records after cursor
            stmt = stmt.order_by(RunEventRow.seq.asc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                return [self._row_to_dict(r) for r in result.scalars()]
        else:
            # before_seq or default (latest): take last `limit` records, return ascending
            stmt = stmt.order_by(RunEventRow.seq.desc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars())
                return [self._row_to_dict(r) for r in reversed(rows)]

    async def list_events(
        self,
        thread_id,
        run_id,
        *,
        event_types=None,
        limit=500,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.list_events")
        stmt = select(RunEventRow).where(RunEventRow.thread_id == thread_id, RunEventRow.run_id == run_id)
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        if event_types:
            stmt = stmt.where(RunEventRow.event_type.in_(event_types))
        stmt = stmt.order_by(RunEventRow.seq.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_messages_by_run(
        self,
        thread_id,
        run_id,
        *,
        limit=50,
        before_seq=None,
        after_seq=None,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.list_messages_by_run")
        stmt = select(RunEventRow).where(
            RunEventRow.thread_id == thread_id,
            RunEventRow.run_id == run_id,
            RunEventRow.category == "message",
        )
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        if before_seq is not None:
            stmt = stmt.where(RunEventRow.seq < before_seq)
        if after_seq is not None:
            stmt = stmt.where(RunEventRow.seq > after_seq)

        if after_seq is not None:
            stmt = stmt.order_by(RunEventRow.seq.asc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                return [self._row_to_dict(r) for r in result.scalars()]
        else:
            stmt = stmt.order_by(RunEventRow.seq.desc()).limit(limit)
            async with self._sf() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars())
                return [self._row_to_dict(r) for r in reversed(rows)]

    async def count_messages(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.count_messages")
        stmt = select(func.count()).select_from(RunEventRow).where(RunEventRow.thread_id == thread_id, RunEventRow.category == "message")
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        async with self._sf() as session:
            return await session.scalar(stmt) or 0

    async def delete_by_thread(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.delete_by_thread")
        async with self._sf() as session:
            count_conditions = [RunEventRow.thread_id == thread_id]
            if resolved_user_id is not None:
                count_conditions.append(RunEventRow.user_id == resolved_user_id)
            count_stmt = select(func.count()).select_from(RunEventRow).where(*count_conditions)
            count = await session.scalar(count_stmt) or 0
            if count > 0:
                await session.execute(delete(RunEventRow).where(*count_conditions))
                await session.commit()
            return count

    async def delete_by_run(
        self,
        thread_id,
        run_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.delete_by_run")
        async with self._sf() as session:
            count_conditions = [RunEventRow.thread_id == thread_id, RunEventRow.run_id == run_id]
            if resolved_user_id is not None:
                count_conditions.append(RunEventRow.user_id == resolved_user_id)
            count_stmt = select(func.count()).select_from(RunEventRow).where(*count_conditions)
            count = await session.scalar(count_stmt) or 0
            if count > 0:
                await session.execute(delete(RunEventRow).where(*count_conditions))
                await session.commit()
            return count
