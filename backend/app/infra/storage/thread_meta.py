"""Thread metadata storage adapter owned by the app layer."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from store.repositories import build_thread_meta_repository
from store.repositories.contracts import (
    ThreadMeta,
    ThreadMetaCreate,
    ThreadMetaRepositoryProtocol,
)
from deerflow.runtime.actor_context import AUTO, resolve_user_id


class ThreadMetaStoreAdapter:
    """Use storage package thread repositories with per-call sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_thread_meta(self, data: ThreadMetaCreate) -> ThreadMeta:
        async with self._transaction() as repo:
            return await repo.create_thread_meta(data)

    async def get_thread_meta(self, thread_id: str) -> ThreadMeta | None:
        async with self._read() as repo:
            return await repo.get_thread_meta(thread_id)

    async def update_thread_meta(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        display_name: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._transaction() as repo:
            await repo.update_thread_meta(
                thread_id,
                assistant_id=assistant_id,
                display_name=display_name,
                status=status,
                metadata=metadata,
            )

    async def delete_thread(self, thread_id: str) -> None:
        async with self._transaction() as repo:
            await repo.delete_thread(thread_id)

    async def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        user_id: str | None = None,
        assistant_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ThreadMeta]:
        async with self._read() as repo:
            return await repo.search_threads(
                metadata=metadata,
                status=status,
                user_id=user_id,
                assistant_id=assistant_id,
                limit=limit,
                offset=offset,
            )

    def _read(self):
        return _ThreadMetaRepositoryContext(self._session_factory, commit=False)

    def _transaction(self):
        return _ThreadMetaRepositoryContext(self._session_factory, commit=True)


class _ThreadMetaRepositoryContext:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, commit: bool) -> None:
        self._session_factory = session_factory
        self._commit = commit
        self._session: AsyncSession | None = None

    async def __aenter__(self):
        self._session = self._session_factory()
        return build_thread_meta_repository(self._session)

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


class ThreadMetaStorage:
    """App-facing adapter around the storage thread metadata contract."""

    def __init__(self, repo: ThreadMetaRepositoryProtocol) -> None:
        self._repo = repo

    async def get_thread(self, thread_id: str, *, user_id: str | None | object = AUTO) -> ThreadMeta | None:
        thread = await self._repo.get_thread_meta(thread_id)
        if thread is None:
            return None
        effective_user_id = resolve_user_id(user_id, method_name="ThreadMetaStorage.get_thread")
        if effective_user_id is not None and thread.user_id != effective_user_id:
            return None
        return thread

    async def ensure_thread(
        self,
        *,
        thread_id: str,
        assistant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        user_id: str | None | object = AUTO,
    ) -> ThreadMeta:
        effective_user_id = resolve_user_id(user_id, method_name="ThreadMetaStorage.ensure_thread")
        existing = await self.get_thread(thread_id, user_id=effective_user_id)
        if existing is not None:
            return existing

        return await self._repo.create_thread_meta(
            ThreadMetaCreate(
                thread_id=thread_id,
                assistant_id=assistant_id,
                user_id=effective_user_id,
                metadata=metadata or {},
            )
        )

    async def ensure_thread_running(
        self,
        *,
        thread_id: str,
        assistant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ThreadMeta | None:
        existing = await self._repo.get_thread_meta(thread_id)
        if existing is None:
            return await self._repo.create_thread_meta(
                ThreadMetaCreate(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    status="running",
                    metadata=metadata or {},
                )
            )

        await self._repo.update_thread_meta(thread_id, status="running")
        return await self._repo.get_thread_meta(thread_id)

    async def sync_thread_title(self, *, thread_id: str, title: str) -> None:
        await self._repo.update_thread_meta(thread_id, display_name=title)

    async def sync_thread_assistant_id(self, *, thread_id: str, assistant_id: str) -> None:
        await self._repo.update_thread_meta(thread_id, assistant_id=assistant_id)

    async def sync_thread_status(self, *, thread_id: str, status: str) -> None:
        await self._repo.update_thread_meta(thread_id, status=status)

    async def sync_thread_metadata(
        self,
        *,
        thread_id: str,
        metadata: dict[str, Any],
    ) -> None:
        await self._repo.update_thread_meta(thread_id, metadata=metadata)

    async def delete_thread(self, thread_id: str) -> None:
        await self._repo.delete_thread(thread_id)

    async def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        user_id: str | None | object = AUTO,
        assistant_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ThreadMeta]:
        normalized_status = status.strip() if status is not None else None
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaStorage.search_threads")
        normalized_user_id = resolved_user_id.strip() if resolved_user_id is not None else None
        normalized_assistant_id = (
            assistant_id.strip() if assistant_id is not None else None
        )

        return await self._repo.search_threads(
            metadata=metadata,
            status=normalized_status or None,
            user_id=normalized_user_id or None,
            assistant_id=normalized_assistant_id or None,
            limit=limit,
            offset=offset,
        )


__all__ = ["ThreadMetaStorage", "ThreadMetaStoreAdapter"]
