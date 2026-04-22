from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from store.repositories.contracts.thread_meta import ThreadMeta, ThreadMetaCreate, ThreadMetaRepositoryProtocol
from store.repositories.models.thread_meta import ThreadMeta as ThreadMetaModel


def _to_thread_meta(m: ThreadMetaModel) -> ThreadMeta:
    return ThreadMeta(
        thread_id=m.thread_id,
        assistant_id=m.assistant_id,
        user_id=m.user_id,
        display_name=m.display_name,
        status=m.status,
        metadata=dict(m.meta or {}),
        created_time=m.created_time,
        updated_time=m.updated_time,
    )


class DbThreadMetaRepository(ThreadMetaRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_thread_meta(self, data: ThreadMetaCreate) -> ThreadMeta:
        model = ThreadMetaModel(
            thread_id=data.thread_id,
            assistant_id=data.assistant_id,
            user_id=data.user_id,
            display_name=data.display_name,
            status=data.status,
            meta=dict(data.metadata),
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_thread_meta(model)

    async def get_thread_meta(self, thread_id: str) -> ThreadMeta | None:
        result = await self._session.execute(select(ThreadMetaModel).where(ThreadMetaModel.thread_id == thread_id))
        model = result.scalar_one_or_none()
        return _to_thread_meta(model) if model else None

    async def update_thread_meta(
            self,
            thread_id: str,
            *,
            assistant_id: str | None = None,
            display_name: str | None = None,
            status: str | None = None,
            metadata: dict[str, Any] | None = None,
    ) -> None:
        values: dict = {}
        if assistant_id is not None:
            values["assistant_id"] = assistant_id
        if display_name is not None:
            values["display_name"] = display_name
        if status is not None:
            values["status"] = status
        if metadata is not None:
            values["meta"] = dict(metadata)
        if not values:
            return
        await self._session.execute(
            update(ThreadMetaModel).where(ThreadMetaModel.thread_id == thread_id).values(**values))

    async def delete_thread(self, thread_id: str) -> None:
        await self._session.execute(delete(ThreadMetaModel).where(ThreadMetaModel.thread_id == thread_id))

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
        stmt = select(ThreadMetaModel)

        if status is not None:
            stmt = stmt.where(ThreadMetaModel.status == status)
        if user_id is not None:
            stmt = stmt.where(ThreadMetaModel.user_id == user_id)
        if assistant_id is not None:
            stmt = stmt.where(ThreadMetaModel.assistant_id == assistant_id)
        if metadata:
            for key, value in metadata.items():
                stmt = stmt.where(ThreadMetaModel.meta[key].as_string() == str(value))

        stmt = stmt.order_by(ThreadMetaModel.created_time.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await self._session.execute(stmt)
        return [_to_thread_meta(m) for m in result.scalars().all()]
