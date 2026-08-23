"""SQLAlchemy-backed RunEventStore implementation.

Persists events to the ``run_events`` table. Trace content is truncated
at ``max_trace_content`` bytes to avoid bloating the database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.models.run_event import RunEventRow
from deerflow.runtime.events.message_identity import message_identity
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.user_context import AUTO, _AutoSentinel, get_current_user, resolve_user_id
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class DbRunEventStore(RunEventStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, max_trace_content: int = 10240):
        self._sf = session_factory
        self._max_trace_content = max_trace_content
        # Per-thread asyncio locks serialize seq assignment for concurrent
        # in-process writers on the same thread. The DB-level FOR UPDATE /
        # advisory lock guards cross-process races; this guards the common
        # single-process case where two coroutines interleave between the
        # max(seq) read and the INSERT and would otherwise collide on seq.
        self._write_locks: dict[str, asyncio.Lock] = {}

    def _get_write_lock(self, thread_id: str) -> asyncio.Lock:
        """Return (creating if needed) the per-thread seq-assignment lock."""
        lock = self._write_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._write_locks[thread_id] = lock
        return lock

    @staticmethod
    def _row_to_dict(row: RunEventRow) -> dict:
        d = row.to_dict()
        d["metadata"] = d.pop("event_metadata", {})
        val = d.get("created_at")
        if isinstance(val, datetime):
            # SQLite drops tzinfo on read despite ``DateTime(timezone=True)``;
            # ``coerce_iso`` normalizes naive datetimes as UTC.
            d["created_at"] = coerce_iso(val)
        d.pop("id", None)
        # Restore structured content that was JSON-serialized on write.
        raw = d.get("content", "")
        metadata = d.get("metadata", {})
        if isinstance(raw, str) and (metadata.get("content_is_json") or metadata.get("content_is_dict")):
            try:
                d["content"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                # Content looked like JSON but failed to parse;
                # keep the raw string as-is.
                logger.debug("Failed to deserialize content as JSON for event seq=%s", d.get("seq"))
        return d

    def _truncate_trace(self, category: str, content: Any, metadata: dict | None) -> tuple[Any, dict]:
        if category == "trace":
            text = content if isinstance(content, str) else json.dumps(content, default=str, ensure_ascii=False)
            encoded = text.encode("utf-8")
            if len(encoded) > self._max_trace_content:
                # Truncate by bytes, then decode back (may cut a multi-byte char, so use errors="ignore")
                content = encoded[: self._max_trace_content].decode("utf-8", errors="ignore")
                metadata = {**(metadata or {}), "content_truncated": True, "original_byte_length": len(encoded)}
        return content, metadata or {}

    @staticmethod
    def _content_to_db(content: Any, metadata: dict | None) -> tuple[str, dict]:
        metadata = metadata or {}
        if isinstance(content, str):
            return content, metadata

        db_content = json.dumps(content, default=str, ensure_ascii=False)
        metadata = {**metadata, "content_is_json": True}
        if isinstance(content, dict):
            metadata["content_is_dict"] = True
        return db_content, metadata

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

    #: Characters json.dumps escapes in the stored content (``ensure_ascii``
    #: is False, so non-ASCII survives verbatim and stays matchable).
    _LIKE_UNSAFE_ID = re.compile(r'["\\\x00-\x1f]')

    @classmethod
    def _prefilter_substrings(cls, wanted: set[str]) -> list[str] | None:
        """Return the raw ids to LIKE-match in ``content``, or ``None`` to full-scan.

        An identity is ``kind:raw_id`` and the raw id appears verbatim in the
        stored JSON string (``u1`` is a substring of a re-keyed ``u1__user``
        copy too), so a row not containing any wanted id cannot resolve any
        wanted identity. An id json.dumps would escape breaks that verbatim
        guarantee — one such id falls the whole set back to the full scan
        rather than silently missing it. LIKE wildcards are escaped, not
        rejected.
        """
        ids = []
        for identity in wanted:
            _kind, _sep, raw_id = identity.partition(":")
            if not raw_id or cls._LIKE_UNSAFE_ID.search(raw_id):
                return None
            ids.append(raw_id)
        return ids

    @staticmethod
    async def _max_seq_for_thread(session: AsyncSession, thread_id: str) -> int | None:
        """Return the current max seq while serializing writers per thread.

        PostgreSQL rejects ``SELECT max(...) FOR UPDATE`` because aggregate
        results are not lockable rows. As a release-safe workaround, take a
        transaction-level advisory lock keyed by thread_id before reading the
        aggregate. Other dialects keep the existing row-locking statement.
        """
        stmt = select(func.max(RunEventRow.seq)).where(RunEventRow.thread_id == thread_id)
        bind = session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        if dialect_name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(CAST(:thread_id AS text))::bigint)"),
                {"thread_id": thread_id},
            )
            return await session.scalar(stmt)

        return await session.scalar(stmt.with_for_update())

    async def put(self, *, thread_id, run_id, event_type, category, content="", metadata=None, created_at=None):  # noqa: D401
        """Write a single event — low-frequency path only.

        This opens a dedicated transaction with a FOR UPDATE lock to
        assign a monotonic *seq*.  For high-throughput writes use
        :meth:`put_batch`, which acquires the lock once for the whole
        batch.  Currently the only caller is ``worker.run_agent`` for
        the initial ``human_message`` event (once per run).
        """
        content, metadata = self._truncate_trace(category, content, metadata)
        db_content, metadata = self._content_to_db(content, metadata)
        user_id = self._user_id_from_context()
        async with self._get_write_lock(thread_id):
            async with self._sf() as session:
                async with session.begin():
                    max_seq = await self._max_seq_for_thread(session, thread_id)
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
        thread_ids = {e["thread_id"] for e in events}
        if len(thread_ids) > 1:
            raise ValueError(f"put_batch requires all events to belong to the same thread; got {thread_ids!r}")
        user_id = self._user_id_from_context()
        # All events belong to the same thread (validated above).
        thread_id = events[0]["thread_id"]
        async with self._get_write_lock(thread_id):
            async with self._sf() as session:
                async with session.begin():
                    max_seq = await self._max_seq_for_thread(session, thread_id)
                    seq = max_seq or 0
                    rows = []
                    for e in events:
                        seq += 1
                        content = e.get("content", "")
                        category = e.get("category", "trace")
                        metadata = e.get("metadata")
                        content, metadata = self._truncate_trace(category, content, metadata)
                        db_content, metadata = self._content_to_db(content, metadata)
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

    async def put_if_absent(
        self,
        *,
        thread_id,
        run_id,
        event_type,
        category,
        content="",
        metadata=None,
        created_at=None,
    ):
        """Idempotently insert a run-scoped singleton event.

        ``_max_seq_for_thread`` takes the same PostgreSQL advisory lock used by
        every normal writer (and the in-process lock covers SQLite), so the
        existence check cannot race another ``put_if_absent`` or journal write.
        Terminal delivery receipts use this method on both the worker and
        recovery paths; ordinary event types remain append-only.
        """
        content, metadata = self._truncate_trace(category, content, metadata)
        db_content, metadata = self._content_to_db(content, metadata)
        user_id = self._user_id_from_context()
        async with self._get_write_lock(thread_id):
            async with self._sf() as session:
                async with session.begin():
                    max_seq = await self._max_seq_for_thread(session, thread_id)
                    stmt = (
                        select(RunEventRow)
                        .where(
                            RunEventRow.thread_id == thread_id,
                            RunEventRow.run_id == run_id,
                            RunEventRow.event_type == event_type,
                        )
                        .order_by(RunEventRow.seq.asc())
                        .limit(1)
                    )
                    existing = await session.scalar(stmt)
                    if existing is not None:
                        return self._row_to_dict(existing), False
                    row = RunEventRow(
                        thread_id=thread_id,
                        run_id=run_id,
                        user_id=user_id,
                        event_type=event_type,
                        category=category,
                        content=db_content,
                        event_metadata=metadata,
                        seq=(max_seq or 0) + 1,
                        created_at=datetime.fromisoformat(created_at) if created_at else datetime.now(UTC),
                    )
                    session.add(row)
                return self._row_to_dict(row), True

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
        task_id=None,
        limit=500,
        after_seq=None,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.list_events")
        stmt = select(RunEventRow).where(RunEventRow.thread_id == thread_id, RunEventRow.run_id == run_id)
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        if event_types:
            stmt = stmt.where(RunEventRow.event_type.in_(event_types))
        if task_id is not None:
            # Filter on metadata["task_id"] in SQL (before LIMIT) so cursor
            # pagination over a single subagent task stays correct (#3779). The
            # query is already scoped to (thread_id, run_id), so the JSON probe
            # only runs over this run's small candidate set; ``.as_string()``
            # renders to json_extract (SQLite) / ->> (Postgres).
            stmt = stmt.where(RunEventRow.event_metadata["task_id"].as_string() == task_id)
        if after_seq is not None:
            stmt = stmt.where(RunEventRow.seq > after_seq)
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

    async def get_last_visible_ai_seq_by_run(
        self,
        thread_id,
        run_ids,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        if not run_ids:
            return {}
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.get_last_visible_ai_seq_by_run")
        caller = RunEventRow.event_metadata["caller"].as_string()
        # RunJournal canonically persists AI message rows as
        # ``llm.ai.response``; ``ai_message`` remains for legacy compatibility.
        stmt = (
            select(RunEventRow.run_id, func.max(RunEventRow.seq))
            .where(
                RunEventRow.thread_id == thread_id,
                RunEventRow.run_id.in_(run_ids),
                RunEventRow.category == "message",
                RunEventRow.event_type.in_(("llm.ai.response", "ai_message")),
                ~func.coalesce(caller, "").like("middleware:%"),
            )
            .group_by(RunEventRow.run_id)
        )
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {run_id: seq for run_id, seq in result if isinstance(seq, int)}

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

    async def get_message_seqs(
        self,
        thread_id,
        identities,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        wanted = set(identities)
        if not wanted:
            return {}
        resolved_user_id = resolve_user_id(user_id, method_name="DbRunEventStore.get_message_seqs")
        # ``content`` is a TEXT column holding a JSON *string* (see
        # ``_content_to_db``), not a JSON column, so the identity fields cannot
        # be projected in SQL — matching rows are decoded here instead. The
        # ``content`` column carries full tool outputs, and a wanted identity
        # absent from the feed (a message still streaming) defeats the early
        # exit below — so without a prefilter a `/state`/`/history` read of a
        # long thread pays a full fetch-and-decode of every message row. The
        # LIKE prefilter keeps that cost in SQL: only rows containing a wanted
        # id as a raw substring are fetched (false positives are re-checked by
        # ``message_identity``; ids the prefilter cannot express fall back to
        # the full scan).
        stmt = select(RunEventRow.seq, RunEventRow.content).where(RunEventRow.thread_id == thread_id, RunEventRow.category == "message").order_by(RunEventRow.seq)
        if resolved_user_id is not None:
            stmt = stmt.where(RunEventRow.user_id == resolved_user_id)
        prefilter_ids = self._prefilter_substrings(wanted)
        if prefilter_ids is not None:
            stmt = stmt.where(or_(*[RunEventRow.content.like(f"%{i.replace('%', '\\%').replace('_', '\\_')}%", escape="\\") for i in prefilter_ids]))

        found: dict[str, int] = {}
        async with self._sf() as session:
            result = await session.execute(stmt)
            for seq, raw in result:
                # Plain-text content (never a message dict) is skipped without
                # paying for a failed JSON parse.
                if not isinstance(raw, str) or not raw.startswith("{"):
                    continue
                try:
                    content = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(content, dict):
                    continue
                identity = message_identity(content)
                # Earliest seq wins: a message re-persisted later keeps the
                # position it first occupied in the feed.
                if identity in wanted and identity not in found:
                    found[identity] = seq
                    # Later rows can only be re-persisted copies that already
                    # lose that tiebreak, so the scan (and its JSON decoding)
                    # ends with the last wanted seq instead of the thread's
                    # full message count.
                    if len(found) == len(wanted):
                        break
        return found

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
            # Evict the per-thread seq-assignment lock so ``_write_locks`` does
            # not grow unbounded over the (long-lived, singleton) store's
            # lifetime. Only pop when no writer is mid-flight; a later write
            # recreates the lock lazily and seq restarts correctly from the
            # now-deleted thread.
            lock = self._write_locks.get(thread_id)
            if lock is not None and not lock.locked():
                self._write_locks.pop(thread_id, None)
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
