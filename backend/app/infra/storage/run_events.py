"""App-owned adapter from runs callbacks to storage run event repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from store.repositories import RunEvent, RunEventCreate, build_run_event_repository, build_thread_meta_repository

from deerflow.runtime.actor_context import get_actor_context


class AppRunEventStore:
    """Implements the harness RunEventStore protocol using storage repositories."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def put_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []

        denied = {str(event["thread_id"]) for event in events if not await self._thread_visible(str(event["thread_id"]))}
        if denied:
            raise PermissionError(f"actor is not allowed to append events for thread(s): {', '.join(sorted(denied))}")

        async with self._session_factory() as session:
            try:
                repo = build_run_event_repository(session)
                rows = await repo.append_batch([_event_create_from_dict(event) for event in events])
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        return [_event_to_dict(row) for row in rows]

    async def list_messages(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        if not await self._thread_visible(thread_id):
            return []
        async with self._session_factory() as session:
            repo = build_run_event_repository(session)
            rows = await repo.list_messages(
                thread_id,
                limit=limit,
                before_seq=before_seq,
                after_seq=after_seq,
            )
        return [_event_to_dict(row) for row in rows]

    async def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not await self._thread_visible(thread_id):
            return []
        async with self._session_factory() as session:
            repo = build_run_event_repository(session)
            rows = await repo.list_events(thread_id, run_id, event_types=event_types, limit=limit)
        return [_event_to_dict(row) for row in rows]

    async def list_messages_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 50,
        before_seq: int | None = None,
        after_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        if not await self._thread_visible(thread_id):
            return []
        async with self._session_factory() as session:
            repo = build_run_event_repository(session)
            rows = await repo.list_messages_by_run(
                thread_id,
                run_id,
                limit=limit,
                before_seq=before_seq,
                after_seq=after_seq,
            )
        return [_event_to_dict(row) for row in rows]

    async def count_messages(self, thread_id: str) -> int:
        if not await self._thread_visible(thread_id):
            return 0
        async with self._session_factory() as session:
            repo = build_run_event_repository(session)
            return await repo.count_messages(thread_id)

    async def delete_by_thread(self, thread_id: str) -> int:
        if not await self._thread_visible(thread_id):
            return 0
        async with self._session_factory() as session:
            try:
                repo = build_run_event_repository(session)
                count = await repo.delete_by_thread(thread_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return count

    async def delete_by_run(self, thread_id: str, run_id: str) -> int:
        if not await self._thread_visible(thread_id):
            return 0
        async with self._session_factory() as session:
            try:
                repo = build_run_event_repository(session)
                count = await repo.delete_by_run(thread_id, run_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return count

    async def _thread_visible(self, thread_id: str) -> bool:
        actor = get_actor_context()
        if actor is None or actor.user_id is None:
            return True

        async with self._session_factory() as session:
            thread_repo = build_thread_meta_repository(session)
            thread = await thread_repo.get_thread_meta(thread_id)

        if thread is None:
            return True
        return thread.user_id is None or thread.user_id == actor.user_id


def _event_create_from_dict(event: dict[str, Any]) -> RunEventCreate:
    created_at = event.get("created_at")
    return RunEventCreate(
        thread_id=str(event["thread_id"]),
        run_id=str(event["run_id"]),
        event_type=str(event["event_type"]),
        category=str(event["category"]),
        content=event.get("content", ""),
        metadata=dict(event.get("metadata") or {}),
        created_at=datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at,
    )


def _event_to_dict(event: RunEvent) -> dict[str, Any]:
    return {
        "thread_id": event.thread_id,
        "run_id": event.run_id,
        "event_type": event.event_type,
        "category": event.category,
        "content": event.content,
        "metadata": event.metadata,
        "seq": event.seq,
        "created_at": event.created_at.isoformat(),
    }
