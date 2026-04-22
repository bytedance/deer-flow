from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from store.repositories.contracts.run_event import RunEvent, RunEventCreate, RunEventRepositoryProtocol
from store.repositories.models.run_event import RunEvent as RunEventModel


def _serialize_content(content: str | dict[str, Any], metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(content, dict):
        return json.dumps(content, default=str, ensure_ascii=False), {**metadata, "content_is_dict": True}
    return content, metadata


def _deserialize_content(content: str, metadata: dict[str, Any]) -> str | dict[str, Any]:
    if not metadata.get("content_is_dict"):
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

        thread_ids = {event.thread_id for event in events}
        seq_by_thread: dict[str, int] = {}
        for thread_id in thread_ids:
            max_seq = await self._session.scalar(
                select(func.max(RunEventModel.seq))
                .where(RunEventModel.thread_id == thread_id)
                .with_for_update()
            )
            seq_by_thread[thread_id] = max_seq or 0

        rows: list[RunEventModel] = []

        for event in events:
            seq_by_thread[event.thread_id] += 1
            content, metadata = _serialize_content(event.content, dict(event.metadata))
            row = RunEventModel(
                thread_id=event.thread_id,
                run_id=event.run_id,
                seq=seq_by_thread[event.thread_id],
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
    ) -> list[RunEvent]:
        stmt = select(RunEventModel).where(
            RunEventModel.thread_id == thread_id,
            RunEventModel.category == "message",
        )
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
    ) -> list[RunEvent]:
        stmt = select(RunEventModel).where(
            RunEventModel.thread_id == thread_id,
            RunEventModel.run_id == run_id,
        )
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
    ) -> list[RunEvent]:
        stmt = (
            select(RunEventModel)
            .where(
                RunEventModel.thread_id == thread_id,
                RunEventModel.run_id == run_id,
                RunEventModel.category == "message",
            )
        )
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

    async def count_messages(self, thread_id: str) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(RunEventModel)
            .where(RunEventModel.thread_id == thread_id, RunEventModel.category == "message")
        )
        return int(count or 0)

    async def delete_by_thread(self, thread_id: str) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(RunEventModel).where(RunEventModel.thread_id == thread_id)
        )
        await self._session.execute(delete(RunEventModel).where(RunEventModel.thread_id == thread_id))
        return int(count or 0)

    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(RunEventModel)
            .where(RunEventModel.thread_id == thread_id, RunEventModel.run_id == run_id)
        )
        await self._session.execute(
            delete(RunEventModel).where(RunEventModel.thread_id == thread_id, RunEventModel.run_id == run_id)
        )
        return int(count or 0)
