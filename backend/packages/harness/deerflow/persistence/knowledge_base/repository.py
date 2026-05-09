"""Knowledge base repository — CRUD for KnowledgeBaseRow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.knowledge_base.model import KnowledgeBaseRow


class KnowledgeBaseRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: KnowledgeBaseRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at", "deleted_at", "last_indexed_at", "last_search_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    async def create(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        kb_id = uuid4().hex
        collection_name = f"kb_{uuid4().hex}"
        now = datetime.now(UTC)
        row = KnowledgeBaseRow(
            id=kb_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            collection_name=collection_name,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.id == kb_id,
                    KnowledgeBaseRow.tenant_id == tenant_id,
                    KnowledgeBaseRow.owner_user_id == owner_user_id,
                    KnowledgeBaseRow.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_dict(row) if row else None

    async def list_by_owner(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.tenant_id == tenant_id,
                    KnowledgeBaseRow.owner_user_id == owner_user_id,
                    KnowledgeBaseRow.deleted_at.is_(None),
                )
                .order_by(KnowledgeBaseRow.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def update(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        allowed = {"name", "description", "visibility", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return await self.get(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        updates["updated_at"] = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.id == kb_id,
                    KnowledgeBaseRow.tenant_id == tenant_id,
                    KnowledgeBaseRow.owner_user_id == owner_user_id,
                    KnowledgeBaseRow.deleted_at.is_(None),
                )
                .values(**updates)
            )
            await session.execute(stmt)
            await session.commit()
        return await self.get(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

    async def soft_delete(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.id == kb_id,
                    KnowledgeBaseRow.tenant_id == tenant_id,
                    KnowledgeBaseRow.owner_user_id == owner_user_id,
                    KnowledgeBaseRow.deleted_at.is_(None),
                )
                .values(deleted_at=now, updated_at=now)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def update_stats(
        self,
        kb_id: str,
        *,
        document_count: int | None = None,
        chunk_count: int | None = None,
        last_indexed_at: datetime | None = None,
    ) -> None:
        updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if document_count is not None:
            updates["document_count"] = document_count
        if chunk_count is not None:
            updates["chunk_count"] = chunk_count
        if last_indexed_at is not None:
            updates["last_indexed_at"] = last_indexed_at
        async with self._sf() as session:
            stmt = update(KnowledgeBaseRow).where(KnowledgeBaseRow.id == kb_id).values(**updates)
            await session.execute(stmt)
            await session.commit()

    async def get_by_id_internal(self, kb_id: str) -> dict[str, Any] | None:
        """Get KB without owner filter — for internal service use."""
        async with self._sf() as session:
            stmt = select(KnowledgeBaseRow).where(KnowledgeBaseRow.id == kb_id, KnowledgeBaseRow.deleted_at.is_(None))
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_dict(row) if row else None

    async def resolve_active_by_ids(
        self,
        kb_ids: list[str],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> list[dict[str, Any]]:
        """Batch-fetch active KBs by ID list with tenant+owner isolation."""
        if not kb_ids:
            return []
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.id.in_(kb_ids),
                    KnowledgeBaseRow.tenant_id == tenant_id,
                    KnowledgeBaseRow.owner_user_id == owner_user_id,
                    KnowledgeBaseRow.status == "active",
                    KnowledgeBaseRow.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def resolve_active_by_collections(
        self,
        collection_names: list[str],
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> list[dict[str, Any]]:
        """Batch-fetch active KBs by collection name with tenant+owner isolation."""
        if not collection_names:
            return []
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.collection_name.in_(collection_names),
                    KnowledgeBaseRow.tenant_id == tenant_id,
                    KnowledgeBaseRow.owner_user_id == owner_user_id,
                    KnowledgeBaseRow.status == "active",
                    KnowledgeBaseRow.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]
