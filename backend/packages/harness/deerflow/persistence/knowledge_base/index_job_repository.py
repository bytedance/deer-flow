"""Index job repository — CRUD for IndexJobRow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.knowledge_base.model import IndexJobRow


class IndexJobRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: IndexJobRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at", "started_at", "finished_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    async def create(
        self,
        *,
        document_id: str,
        knowledge_base_id: str,
        tenant_id: str,
        owner_user_id: str,
        version: int,
        old_chunk_ids: list | None = None,
    ) -> dict[str, Any]:
        job_id = uuid4().hex
        now = datetime.now(UTC)
        row = IndexJobRow(
            id=job_id,
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            version=version,
            old_chunk_ids=old_chunk_ids or [],
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(IndexJobRow, job_id)
            return self._row_to_dict(row) if row else None

    async def update_status(
        self,
        job_id: str,
        *,
        status: str,
        new_chunk_ids: list | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        updates: dict[str, Any] = {"status": status, "updated_at": datetime.now(UTC)}
        if new_chunk_ids is not None:
            updates["new_chunk_ids"] = new_chunk_ids
        if error is not None:
            updates["error"] = error
        if started_at is not None:
            updates["started_at"] = started_at
        if finished_at is not None:
            updates["finished_at"] = finished_at
        async with self._sf() as session:
            stmt = update(IndexJobRow).where(IndexJobRow.id == job_id).values(**updates)
            await session.execute(stmt)
            await session.commit()

    async def list_by_document(
        self,
        document_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = (
                select(IndexJobRow)
                .where(IndexJobRow.document_id == document_id)
                .order_by(IndexJobRow.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]
