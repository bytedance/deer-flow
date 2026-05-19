"""Knowledge base repository — CRUD for KnowledgeBaseRow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
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
        visibility: str = "private",
        embedding_model: str | None = None,
    ) -> dict[str, Any]:
        kb_id = uuid4().hex
        collection_name = f"kb_{uuid4().hex}"
        now = datetime.now(UTC)
        if embedding_model is None:
            from deerflow.config.rag_config import get_rag_config

            embedding_model = get_rag_config().embedding_model
        row = KnowledgeBaseRow(
            id=kb_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            visibility=visibility,
            collection_name=collection_name,
            embedding_model=embedding_model,
            embedding_dim=0,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def update_embedding_binding(
        self,
        kb_id: str,
        *,
        embedding_model: str | None = None,
        embedding_dim: int | None = None,
    ) -> bool:
        """Lazy-backfill the KB's embedding binding after the first index job
        has confirmed the model + dimension. Existing non-zero bindings are
        not overwritten silently — callers asserting a mismatch must raise
        before calling this.
        """
        updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if embedding_model is not None:
            updates["embedding_model"] = embedding_model
        if embedding_dim is not None:
            updates["embedding_dim"] = embedding_dim
        if len(updates) == 1:
            return False
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseRow)
                .where(KnowledgeBaseRow.id == kb_id)
                .values(**updates)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

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
        allowed = {"name", "description", "status"}
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

    async def list_all_active_internal(self) -> list[dict[str, Any]]:
        """List every active KB across all tenants — for startup consistency
        scans. Bypasses visibility filtering, must only be called from
        process-internal admin paths.
        """
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.deleted_at.is_(None),
                    KnowledgeBaseRow.status == "active",
                )
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def set_vector_metric_stale(
        self, kb_id: str, *, stale: bool
    ) -> bool:
        """Mark a KB's underlying vector collection as stale (or fresh)."""
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseRow)
                .where(KnowledgeBaseRow.id == kb_id)
                .values(
                    vector_metric_stale=stale,
                    updated_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    def _build_access_conditions(self, *, tenant_id: str, user_id: str):
        """Build OR conditions for three-level visibility access control."""
        return or_(
            and_(
                KnowledgeBaseRow.visibility == "private",
                KnowledgeBaseRow.owner_user_id == user_id,
                KnowledgeBaseRow.tenant_id == tenant_id,
            ),
            and_(
                KnowledgeBaseRow.visibility == "tenant",
                KnowledgeBaseRow.tenant_id == tenant_id,
            ),
            KnowledgeBaseRow.visibility == "public",
        )

    async def list_accessible(
        self,
        *,
        tenant_id: str,
        user_id: str,
        visibility_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all KBs accessible to the user based on visibility rules."""
        async with self._sf() as session:
            access_conditions = self._build_access_conditions(tenant_id=tenant_id, user_id=user_id)
            conditions = [
                KnowledgeBaseRow.deleted_at.is_(None),
                KnowledgeBaseRow.status == "active",
                access_conditions,
            ]
            if visibility_filter:
                conditions.append(KnowledgeBaseRow.visibility == visibility_filter)
            stmt = (
                select(KnowledgeBaseRow)
                .where(*conditions)
                .order_by(KnowledgeBaseRow.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def get_accessible(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Get a single KB if the user has read access based on visibility rules."""
        async with self._sf() as session:
            access_conditions = self._build_access_conditions(tenant_id=tenant_id, user_id=user_id)
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.id == kb_id,
                    KnowledgeBaseRow.deleted_at.is_(None),
                    access_conditions,
                )
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_dict(row) if row else None

    async def list_admin(
        self,
        *,
        tenant_id: str,
        role: str,
        visibility_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List KBs for admin view. superadmin sees tenant+public; tenant_admin sees tenant."""
        async with self._sf() as session:
            conditions = [
                KnowledgeBaseRow.deleted_at.is_(None),
                KnowledgeBaseRow.status == "active",
            ]
            if role == "superadmin":
                conditions.append(KnowledgeBaseRow.visibility.in_(["tenant", "public"]))
            else:
                conditions.append(KnowledgeBaseRow.visibility == "tenant")
                conditions.append(KnowledgeBaseRow.tenant_id == tenant_id)

            if visibility_filter:
                conditions.append(KnowledgeBaseRow.visibility == visibility_filter)

            stmt = (
                select(KnowledgeBaseRow)
                .where(*conditions)
                .order_by(KnowledgeBaseRow.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def resolve_accessible_by_ids(
        self,
        kb_ids: list[str],
        *,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """Batch-fetch active KBs by ID list with visibility-based access control."""
        if not kb_ids:
            return []
        async with self._sf() as session:
            access_conditions = self._build_access_conditions(tenant_id=tenant_id, user_id=user_id)
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.id.in_(kb_ids),
                    KnowledgeBaseRow.status == "active",
                    KnowledgeBaseRow.deleted_at.is_(None),
                    access_conditions,
                )
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def resolve_accessible_by_collections(
        self,
        collection_names: list[str],
        *,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """Batch-fetch active KBs by collection name with visibility-based access control."""
        if not collection_names:
            return []
        async with self._sf() as session:
            access_conditions = self._build_access_conditions(tenant_id=tenant_id, user_id=user_id)
            stmt = (
                select(KnowledgeBaseRow)
                .where(
                    KnowledgeBaseRow.collection_name.in_(collection_names),
                    KnowledgeBaseRow.status == "active",
                    KnowledgeBaseRow.deleted_at.is_(None),
                    access_conditions,
                )
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]
