"""Run lifecycle persistence adapters owned by the app layer."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Protocol, TypedDict, Unpack, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from store.repositories import FeedbackCreate, Run, RunCreate, build_feedback_repository, build_run_repository

from deerflow.runtime.actor_context import AUTO, resolve_user_id
from deerflow.runtime.serialization import serialize_lc_object
from deerflow.runtime.runs.observer import LifecycleEventType, RunLifecycleEvent, RunObserver
from deerflow.runtime.stream_bridge import JSONValue

from .thread_meta import ThreadMetaStorage

logger = logging.getLogger(__name__)


class RunCreateFields(TypedDict, total=False):
    status: str
    created_at: str
    started_at: str
    ended_at: str
    assistant_id: str | None
    user_id: str | None
    follow_up_to_run_id: str | None
    metadata: dict[str, JSONValue]
    kwargs: dict[str, JSONValue]


class RunStatusUpdateFields(TypedDict, total=False):
    started_at: str
    ended_at: str
    metadata: dict[str, JSONValue]


class RunCompletionFields(TypedDict, total=False):
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    llm_call_count: int
    lead_agent_tokens: int
    subagent_tokens: int
    middleware_tokens: int
    message_count: int
    last_ai_message: str | None
    first_human_message: str | None
    error: str | None


class RunRow(TypedDict, total=False):
    run_id: str
    thread_id: str
    assistant_id: str | None
    status: str
    multitask_strategy: str
    follow_up_to_run_id: str | None
    metadata: dict[str, JSONValue]
    created_at: str
    updated_at: str
    started_at: str | None
    ended_at: str | None
    error: str | None


class RunReadRepository(Protocol):
    """Protocol for durable run queries."""

    async def get(self, run_id: str, *, user_id: str | None | object = AUTO) -> RunRow | None: ...

    async def list_by_thread(
        self,
        thread_id: str,
        *,
        limit: int = 100,
        user_id: str | None | object = AUTO,
    ) -> list[RunRow]: ...


class RunWriteRepository(Protocol):
    """Protocol for durable run writes."""

    async def create(self, run_id: str, thread_id: str, **kwargs: Unpack[RunCreateFields]) -> None: ...
    async def update_status(
        self,
        run_id: str,
        status: str,
        **kwargs: Unpack[RunStatusUpdateFields],
    ) -> None: ...
    async def set_error(self, run_id: str, error: str) -> None: ...
    async def update_run_completion(
        self,
        run_id: str,
        *,
        status: str,
        **kwargs: Unpack[RunCompletionFields],
    ) -> None: ...


class RunDeleteRepository(Protocol):
    """Protocol for durable run deletion."""

    async def delete(self, run_id: str) -> bool: ...


class _RepositoryContext:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        build_repo: Callable[[AsyncSession], object],
        *,
        commit: bool,
    ) -> None:
        self._session_factory = session_factory
        self._build_repo = build_repo
        self._commit = commit
        self._session: AsyncSession | None = None

    async def __aenter__(self):
        self._session = self._session_factory()
        return self._build_repo(self._session)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is None:
            return
        try:
            if self._commit:
                if exc_type is None:
                    await self._session.commit()
                else:
                    await self._session.rollback()
        finally:
            await self._session.close()


def _run_to_row(row: Run) -> RunRow:
    return {
        "run_id": row.run_id,
        "thread_id": row.thread_id,
        "assistant_id": row.assistant_id,
        "user_id": row.user_id,
        "status": row.status,
        "model_name": row.model_name,
        "multitask_strategy": row.multitask_strategy,
        "follow_up_to_run_id": row.follow_up_to_run_id,
        "metadata": cast(dict[str, JSONValue], row.metadata),
        "kwargs": cast(dict[str, JSONValue], row.kwargs),
        "created_at": row.created_time.isoformat(),
        "updated_at": row.updated_time.isoformat() if row.updated_time else "",
        "total_input_tokens": row.total_input_tokens,
        "total_output_tokens": row.total_output_tokens,
        "total_tokens": row.total_tokens,
        "llm_call_count": row.llm_call_count,
        "lead_agent_tokens": row.lead_agent_tokens,
        "subagent_tokens": row.subagent_tokens,
        "middleware_tokens": row.middleware_tokens,
        "message_count": row.message_count,
        "first_human_message": row.first_human_message,
        "last_ai_message": row.last_ai_message,
        "error": row.error,
    }


class FeedbackStoreAdapter:
    """Expose feedback route semantics on top of storage package repositories."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        run_id: str,
        thread_id: str,
        rating: int,
        owner_id: str | None = None,
        user_id: str | None = None,
        message_id: str | None = None,
        comment: str | None = None,
    ) -> dict[str, object]:
        if rating not in (1, -1):
            raise ValueError(f"rating must be +1 or -1, got {rating}")
        effective_user_id = user_id if user_id is not None else owner_id
        async with self._transaction() as repo:
            row = await repo.create_feedback(
                FeedbackCreate(
                    feedback_id=str(uuid.uuid4()),
                    run_id=run_id,
                    thread_id=thread_id,
                    rating=rating,
                    user_id=effective_user_id,
                    message_id=message_id,
                    comment=comment,
                )
            )
        return _feedback_to_dict(row)

    async def get(self, feedback_id: str) -> dict[str, object] | None:
        async with self._read() as repo:
            row = await repo.get_feedback(feedback_id)
        return _feedback_to_dict(row) if row is not None else None

    async def list_by_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        limit: int = 100,
        user_id: str | None = None,
    ) -> list[dict[str, object]]:
        async with self._read() as repo:
            rows = await repo.list_feedback_by_run(run_id)
        filtered = [row for row in rows if row.thread_id == thread_id]
        if user_id is not None:
            filtered = [row for row in filtered if row.user_id == user_id]
        return [_feedback_to_dict(row) for row in filtered][:limit]

    async def list_by_thread(self, thread_id: str, *, limit: int = 100) -> list[dict[str, object]]:
        async with self._read() as repo:
            rows = await repo.list_feedback_by_thread(thread_id)
        return [_feedback_to_dict(row) for row in rows][:limit]

    async def aggregate_by_run(self, thread_id: str, run_id: str) -> dict[str, object]:
        rows = await self.list_by_run(thread_id, run_id)
        positive = sum(1 for row in rows if row["rating"] == 1)
        negative = sum(1 for row in rows if row["rating"] == -1)
        return {"run_id": run_id, "total": len(rows), "positive": positive, "negative": negative}

    async def delete(self, feedback_id: str) -> bool:
        async with self._transaction() as repo:
            return await repo.delete_feedback(feedback_id)

    async def upsert(
        self,
        *,
        run_id: str,
        thread_id: str,
        rating: int,
        user_id: str,
        comment: str | None = None,
    ) -> dict[str, object]:
        if rating not in (1, -1):
            raise ValueError(f"rating must be +1 or -1, got {rating}")
        async with self._transaction() as repo:
            rows = await repo.list_feedback_by_run(run_id)
            existing = next((row for row in rows if row.thread_id == thread_id and row.user_id == user_id), None)
            feedback_id = existing.feedback_id if existing is not None else str(uuid.uuid4())
            if existing is not None:
                await repo.delete_feedback(existing.feedback_id)
            row = await repo.create_feedback(
                FeedbackCreate(
                    feedback_id=feedback_id,
                    run_id=run_id,
                    thread_id=thread_id,
                    rating=rating,
                    user_id=user_id,
                    comment=comment,
                )
            )
        return _feedback_to_dict(row)

    async def delete_by_run(self, *, thread_id: str, run_id: str, user_id: str) -> bool:
        async with self._transaction() as repo:
            rows = await repo.list_feedback_by_run(run_id)
            existing = next((row for row in rows if row.thread_id == thread_id and row.user_id == user_id), None)
            if existing is None:
                return False
            return await repo.delete_feedback(existing.feedback_id)

    async def list_by_thread_grouped(self, thread_id: str, *, user_id: str) -> dict[str, dict[str, object]]:
        rows = await self.list_by_thread(thread_id)
        return {
            row["run_id"]: row
            for row in rows
            if row["user_id"] == user_id
        }

    def _read(self) -> _RepositoryContext:
        return _RepositoryContext(self._session_factory, build_feedback_repository, commit=False)

    def _transaction(self) -> _RepositoryContext:
        return _RepositoryContext(self._session_factory, build_feedback_repository, commit=True)


def _feedback_to_dict(row) -> dict[str, object]:
    return {
        "feedback_id": row.feedback_id,
        "run_id": row.run_id,
        "thread_id": row.thread_id,
        "user_id": row.user_id,
        "owner_id": row.user_id,
        "message_id": row.message_id,
        "rating": row.rating,
        "comment": row.comment,
        "created_at": row.created_time.isoformat(),
    }


class RunStoreAdapter:
    """Expose runs facade storage semantics on top of storage package repositories."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, run_id: str, *, user_id: str | None | object = AUTO) -> RunRow | None:
        effective_user_id = resolve_user_id(user_id, method_name="RunStoreAdapter.get")
        async with self._read() as repo:
            row = await repo.get_run(run_id)
        if row is None:
            return None
        if effective_user_id is not None and row.user_id != effective_user_id:
            return None
        return _run_to_row(row)

    async def list_by_thread(
        self,
        thread_id: str,
        *,
        limit: int = 100,
        user_id: str | None | object = AUTO,
    ) -> list[RunRow]:
        effective_user_id = resolve_user_id(user_id, method_name="RunStoreAdapter.list_by_thread")
        async with self._read() as repo:
            rows = await repo.list_runs_by_thread(thread_id, limit=limit, offset=0)
        if effective_user_id is not None:
            rows = [row for row in rows if row.user_id == effective_user_id]
        return [_run_to_row(row) for row in rows]

    async def create(self, run_id: str, thread_id: str, **kwargs: Unpack[RunCreateFields]) -> None:
        metadata = cast(dict[str, JSONValue], serialize_lc_object(kwargs.get("metadata") or {}))
        run_kwargs = cast(dict[str, JSONValue], serialize_lc_object(kwargs.get("kwargs") or {}))
        effective_user_id = resolve_user_id(kwargs.get("user_id", AUTO), method_name="RunStoreAdapter.create")
        async with self._transaction() as repo:
            await repo.create_run(
                RunCreate(
                    run_id=run_id,
                    thread_id=thread_id,
                    assistant_id=kwargs.get("assistant_id"),
                    user_id=effective_user_id,
                    status=kwargs.get("status", "pending"),
                    metadata=dict(metadata),
                    kwargs=dict(run_kwargs),
                    follow_up_to_run_id=kwargs.get("follow_up_to_run_id"),
                )
            )

    async def delete(self, run_id: str, *, user_id: str | None | object = AUTO) -> bool:
        async with self._transaction() as repo:
            existing = await repo.get_run(run_id)
            if existing is None:
                return False
            effective_user_id = resolve_user_id(user_id, method_name="RunStoreAdapter.delete")
            if effective_user_id is not None and existing.user_id != effective_user_id:
                return False
            await repo.delete_run(run_id)
        return True

    async def update_status(
        self,
        run_id: str,
        status: str,
        **kwargs: Unpack[RunStatusUpdateFields],
    ) -> None:
        async with self._transaction() as repo:
            await repo.update_run_status(run_id, status)

    async def set_error(self, run_id: str, error: str) -> None:
        async with self._transaction() as repo:
            await repo.update_run_status(run_id, "error", error=error)

    async def update_run_completion(
        self,
        run_id: str,
        *,
        status: str,
        **kwargs: Unpack[RunCompletionFields],
    ) -> None:
        async with self._transaction() as repo:
            await repo.update_run_completion(
                run_id,
                status=status,
                total_input_tokens=kwargs.get("total_input_tokens", 0),
                total_output_tokens=kwargs.get("total_output_tokens", 0),
                total_tokens=kwargs.get("total_tokens", 0),
                llm_call_count=kwargs.get("llm_call_count", 0),
                lead_agent_tokens=kwargs.get("lead_agent_tokens", 0),
                subagent_tokens=kwargs.get("subagent_tokens", 0),
                middleware_tokens=kwargs.get("middleware_tokens", 0),
                message_count=kwargs.get("message_count", 0),
                last_ai_message=kwargs.get("last_ai_message"),
                first_human_message=kwargs.get("first_human_message"),
                error=kwargs.get("error"),
            )

    def _read(self) -> _RepositoryContext:
        return _RepositoryContext(self._session_factory, build_run_repository, commit=False)

    def _transaction(self) -> _RepositoryContext:
        return _RepositoryContext(self._session_factory, build_run_repository, commit=True)


class StorageRunObserver(RunObserver):
    """Persist run lifecycle state into app-owned repositories."""

    def __init__(
        self,
        run_write_repo: RunWriteRepository | None = None,
        thread_meta_storage: ThreadMetaStorage | None = None,
    ) -> None:
        self._run_write_repo = run_write_repo
        self._thread_meta_storage = thread_meta_storage

    async def on_event(self, event: RunLifecycleEvent) -> None:
        try:
            await self._dispatch(event)
        except Exception:
            logger.exception(
                "StorageRunObserver failed to persist event %s for run %s",
                event.event_type,
                event.run_id,
            )

    async def _dispatch(self, event: RunLifecycleEvent) -> None:
        handlers = {
            LifecycleEventType.RUN_STARTED: self._handle_run_started,
            LifecycleEventType.RUN_COMPLETED: self._handle_run_completed,
            LifecycleEventType.RUN_FAILED: self._handle_run_failed,
            LifecycleEventType.RUN_CANCELLED: self._handle_run_cancelled,
            LifecycleEventType.THREAD_STATUS_UPDATED: self._handle_thread_status,
        }

        handler = handlers.get(event.event_type)
        if handler:
            await handler(event)

    async def _handle_run_started(self, event: RunLifecycleEvent) -> None:
        if self._run_write_repo:
            await self._run_write_repo.update_status(
                run_id=event.run_id,
                status="running",
                started_at=event.occurred_at.isoformat(),
            )

    async def _handle_run_completed(self, event: RunLifecycleEvent) -> None:
        payload = dict(event.payload) if event.payload else {}
        if self._run_write_repo:
            completion_data = payload.get("completion_data")
            if isinstance(completion_data, dict):
                await self._run_write_repo.update_run_completion(
                    run_id=event.run_id,
                    status="success",
                    **cast(RunCompletionFields, completion_data),
                )
            else:
                await self._run_write_repo.update_status(
                    run_id=event.run_id,
                    status="success",
                    ended_at=event.occurred_at.isoformat(),
                )

        if self._thread_meta_storage and "title" in payload:
            await self._thread_meta_storage.sync_thread_title(
                thread_id=event.thread_id,
                title=payload["title"],
            )

    async def _handle_run_failed(self, event: RunLifecycleEvent) -> None:
        if self._run_write_repo:
            payload = dict(event.payload) if event.payload else {}
            error = payload.get("error", "Unknown error")
            completion_data = payload.get("completion_data")
            if isinstance(completion_data, dict):
                await self._run_write_repo.update_run_completion(
                    run_id=event.run_id,
                    status="error",
                    error=str(error),
                    **cast(RunCompletionFields, completion_data),
                )
            else:
                await self._run_write_repo.update_status(
                    run_id=event.run_id,
                    status="error",
                    ended_at=event.occurred_at.isoformat(),
                )
                await self._run_write_repo.set_error(run_id=event.run_id, error=str(error))

    async def _handle_run_cancelled(self, event: RunLifecycleEvent) -> None:
        if self._run_write_repo:
            payload = dict(event.payload) if event.payload else {}
            completion_data = payload.get("completion_data")
            if isinstance(completion_data, dict):
                await self._run_write_repo.update_run_completion(
                    run_id=event.run_id,
                    status="interrupted",
                    **cast(RunCompletionFields, completion_data),
                )
            else:
                await self._run_write_repo.update_status(
                    run_id=event.run_id,
                    status="interrupted",
                    ended_at=event.occurred_at.isoformat(),
                )

    async def _handle_thread_status(self, event: RunLifecycleEvent) -> None:
        if self._thread_meta_storage:
            payload = dict(event.payload) if event.payload else {}
            status = payload.get("status", "idle")
            await self._thread_meta_storage.sync_thread_status(
                thread_id=event.thread_id,
                status=status,
            )
