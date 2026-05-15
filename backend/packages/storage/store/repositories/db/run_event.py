from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from store.repositories.contracts.run_event import RunEvent, RunEventCreate, RunEventRepositoryProtocol
from store.repositories.models.run_event import RunEvent as RunEventModel

_SEQ_COUNTER_BITS = 12
_SEQ_PROCESS_BITS = 9
_SEQ_PROCESS_SALT = secrets.randbits(_SEQ_PROCESS_BITS)
_SEQ_COUNTER_LIMIT = 1 << _SEQ_COUNTER_BITS
_SEQ_TIMESTAMP_SHIFT = _SEQ_COUNTER_BITS + _SEQ_PROCESS_BITS


class _SequenceAllocator:
    def __init__(self) -> None:
        self._last_millis = 0
        self._lock = threading.Lock()

    def allocate_base(self, batch_size: int) -> int:
        if batch_size >= _SEQ_COUNTER_LIMIT:
            raise ValueError(f"Run event batch is too large: {batch_size} >= {_SEQ_COUNTER_LIMIT}")

        now_ms = time.time_ns() // 1_000_000
        with self._lock:
            seq_ms = max(now_ms, self._last_millis + 1)
            self._last_millis = seq_ms
        return (seq_ms << _SEQ_TIMESTAMP_SHIFT) | (_SEQ_PROCESS_SALT << _SEQ_COUNTER_BITS)


_sequence_allocator = _SequenceAllocator()


def _serialize_content(content: Any, metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(content, str):
        next_metadata = {**metadata, "content_is_json": True}
        if isinstance(content, dict):
            next_metadata["content_is_dict"] = True
        return json.dumps(content, default=str, ensure_ascii=False), next_metadata
    return content, metadata


def _deserialize_content(content: str, metadata: dict[str, Any]) -> Any:
    if not (metadata.get("content_is_json") or metadata.get("content_is_dict")):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _to_run_event(model: RunEventModel) -> RunEvent:
    raw_metadata = dict(model.meta or {})
    metadata = {key: value for key, value in raw_metadata.items() if key != "content_is_dict"}
    return RunEvent(
        thread_id=model.thread_id,
        run_id=model.run_id,
        user_id=model.user_id,
        event_type=model.event_type,
        category=model.category,
        content=_deserialize_content(model.content, raw_metadata),
        metadata=metadata,
        seq=model.seq,
        created_at=model.created_at,
    )


class DbRunEventRepository(RunEventRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_batch(self, events: list[RunEventCreate]) -> list[RunEvent]:
        if not events:
            return []

        seq_base = _sequence_allocator.allocate_base(len(events))

        rows: list[RunEventModel] = []

        for index, event in enumerate(events, start=1):
            content, metadata = _serialize_content(event.content, dict(event.metadata))
            row = RunEventModel(
                thread_id=event.thread_id,
                run_id=event.run_id,
                user_id=event.user_id,
                seq=seq_base + index,
                event_type=event.event_type,
                category=event.category,
                content=content,
                meta=metadata,
            )
            if event.created_at is not None:
                row.created_at = event.created_at
            self._session.add(row)
            rows.append(row)

        await self._session.flush()
        return [_to_run_event(row) for row in rows]

    async def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
        user_id: str | None = None,
    ) -> list[RunEvent]:
        stmt = select(RunEventModel).where(
            RunEventModel.thread_id == thread_id,
            RunEventModel.category == "message",
        )
        if user_id is not None:
            stmt = stmt.where(RunEventModel.user_id == user_id)
        if before_seq is not None:
            stmt = stmt.where(RunEventModel.seq < before_seq).order_by(RunEventModel.seq.desc()).limit(limit)
            result = await self._session.execute(stmt)
            return list(reversed([_to_run_event(row) for row in result.scalars().all()]))
        if after_seq is not None:
            stmt = stmt.where(RunEventModel.seq > after_seq).order_by(RunEventModel.seq.asc()).limit(limit)
            result = await self._session.execute(stmt)
            return [_to_run_event(row) for row in result.scalars().all()]

        stmt = stmt.order_by(RunEventModel.seq.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(reversed([_to_run_event(row) for row in result.scalars().all()]))

    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
        user_id: str | None = None,
    ) -> list[RunEvent]:
        stmt = select(RunEventModel).where(
            RunEventModel.thread_id == thread_id,
            RunEventModel.run_id == run_id,
        )
        if user_id is not None:
            stmt = stmt.where(RunEventModel.user_id == user_id)
        if event_types is not None:
            stmt = stmt.where(RunEventModel.event_type.in_(event_types))
        stmt = stmt.order_by(RunEventModel.seq.asc()).limit(limit)
        result = await self._session.execute(stmt)
        return [_to_run_event(row) for row in result.scalars().all()]

    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
        user_id: str | None = None,
    ) -> list[RunEvent]:
        stmt = select(RunEventModel).where(
            RunEventModel.thread_id == thread_id,
            RunEventModel.run_id == run_id,
            RunEventModel.category == "message",
        )
        if user_id is not None:
            stmt = stmt.where(RunEventModel.user_id == user_id)
        if before_seq is not None:
            stmt = stmt.where(RunEventModel.seq < before_seq).order_by(RunEventModel.seq.desc()).limit(limit)
            result = await self._session.execute(stmt)
            return list(reversed([_to_run_event(row) for row in result.scalars().all()]))
        if after_seq is not None:
            stmt = stmt.where(RunEventModel.seq > after_seq).order_by(RunEventModel.seq.asc()).limit(limit)
            result = await self._session.execute(stmt)
            return [_to_run_event(row) for row in result.scalars().all()]

        stmt = stmt.order_by(RunEventModel.seq.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(reversed([_to_run_event(row) for row in result.scalars().all()]))

    async def count_messages(self, thread_id: str, *, user_id: str | None = None) -> int:
        stmt = select(func.count()).select_from(RunEventModel).where(RunEventModel.thread_id == thread_id, RunEventModel.category == "message")
        if user_id is not None:
            stmt = stmt.where(RunEventModel.user_id == user_id)
        count = await self._session.scalar(stmt)
        return int(count or 0)

    async def delete_by_thread(self, thread_id: str, *, user_id: str | None = None) -> int:
        conditions = [RunEventModel.thread_id == thread_id]
        if user_id is not None:
            conditions.append(RunEventModel.user_id == user_id)
        count = await self._session.scalar(select(func.count()).select_from(RunEventModel).where(*conditions))
        await self._session.execute(delete(RunEventModel).where(*conditions))
        return int(count or 0)

    async def delete_by_run(self, thread_id: str, run_id: str, *, user_id: str | None = None) -> int:
        conditions = [RunEventModel.thread_id == thread_id, RunEventModel.run_id == run_id]
        if user_id is not None:
            conditions.append(RunEventModel.user_id == user_id)
        count = await self._session.scalar(select(func.count()).select_from(RunEventModel).where(*conditions))
        await self._session.execute(delete(RunEventModel).where(*conditions))
        return int(count or 0)
