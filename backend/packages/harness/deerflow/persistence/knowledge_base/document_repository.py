"""Document repository — CRUD for KnowledgeBaseDocumentRow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.knowledge_base.model import KnowledgeBaseDocumentRow


class DocumentRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: KnowledgeBaseDocumentRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at", "deleted_at", "last_indexed_at", "index_queued_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    async def create(
        self,
        *,
        knowledge_base_id: str,
        tenant_id: str,
        owner_user_id: str,
        title: str,
        content: str,
        content_hash: str,
        content_format: str = "markdown",
        source_name: str | None = None,
        metadata_json: dict | None = None,
    ) -> dict[str, Any]:
        doc_id = uuid4().hex
        now = datetime.now(UTC)
        row = KnowledgeBaseDocumentRow(
            id=doc_id,
            knowledge_base_id=knowledge_base_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title=title,
            content=content,
            content_format=content_format,
            source_name=source_name,
            content_hash=content_hash,
            content_length=len(content),
            metadata_json=metadata_json or {},
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
        doc_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.id == doc_id,
                    KnowledgeBaseDocumentRow.tenant_id == tenant_id,
                    KnowledgeBaseDocumentRow.owner_user_id == owner_user_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_dict(row) if row else None

    async def list_by_kb(
        self,
        knowledge_base_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseDocumentRow.tenant_id == tenant_id,
                    KnowledgeBaseDocumentRow.owner_user_id == owner_user_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .order_by(KnowledgeBaseDocumentRow.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def update(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        allowed = {"title", "content", "content_format", "content_hash", "content_length", "version", "source_name", "metadata_json"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return await self.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        updates["updated_at"] = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.id == doc_id,
                    KnowledgeBaseDocumentRow.tenant_id == tenant_id,
                    KnowledgeBaseDocumentRow.owner_user_id == owner_user_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .values(**updates)
            )
            await session.execute(stmt)
            await session.commit()
        return await self.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

    async def soft_delete(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.id == doc_id,
                    KnowledgeBaseDocumentRow.tenant_id == tenant_id,
                    KnowledgeBaseDocumentRow.owner_user_id == owner_user_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .values(deleted_at=now, updated_at=now)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def soft_delete_by_kb(
        self,
        knowledge_base_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> int:
        """Soft-delete all documents in a knowledge base."""
        now = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseDocumentRow.tenant_id == tenant_id,
                    KnowledgeBaseDocumentRow.owner_user_id == owner_user_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .values(deleted_at=now, updated_at=now)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount

    async def update_index_status(
        self,
        doc_id: str,
        *,
        index_status: str,
        index_error: str | None = None,
        index_job_id: str | None = None,
        chunk_ids: list | None = None,
        chunk_count: int | None = None,
        last_indexed_at: datetime | None = None,
        index_queued_at: datetime | None = None,
    ) -> None:
        updates: dict[str, Any] = {"index_status": index_status, "updated_at": datetime.now(UTC)}
        if index_error is not None:
            updates["index_error"] = index_error
        if index_job_id is not None:
            updates["index_job_id"] = index_job_id
        if chunk_ids is not None:
            updates["chunk_ids"] = chunk_ids
        if chunk_count is not None:
            updates["chunk_count"] = chunk_count
        if last_indexed_at is not None:
            updates["last_indexed_at"] = last_indexed_at
        if index_queued_at is not None:
            updates["index_queued_at"] = index_queued_at
        async with self._sf() as session:
            stmt = update(KnowledgeBaseDocumentRow).where(KnowledgeBaseDocumentRow.id == doc_id).values(**updates)
            await session.execute(stmt)
            await session.commit()

    async def list_pending_or_running(self) -> list[dict[str, Any]]:
        """Return active docs whose index_status is queued or running.

        Why: dispatcher startup needs to scan for orphaned jobs left behind
        by a crashed process and re-enqueue them. We treat ``pending`` as
        "queued but worker hadn't picked it up" and ``indexing`` as
        "worker started but didn't finish" — both are safe to retry given
        ``execute_index_job`` is idempotent (cleans old chunks, writes new).
        """
        async with self._sf() as session:
            stmt = select(KnowledgeBaseDocumentRow).where(
                KnowledgeBaseDocumentRow.deleted_at.is_(None),
                KnowledgeBaseDocumentRow.index_status.in_(["pending", "indexing"]),
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def get_by_id_internal(self, doc_id: str) -> dict[str, Any] | None:
        """Get document without owner filter — for internal service use."""
        async with self._sf() as session:
            stmt = select(KnowledgeBaseDocumentRow).where(KnowledgeBaseDocumentRow.id == doc_id, KnowledgeBaseDocumentRow.deleted_at.is_(None))
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_dict(row) if row else None

    async def get_by_kb(self, doc_id: str, *, knowledge_base_id: str) -> dict[str, Any] | None:
        """Get a document by ID scoped to a KB (no owner filter). Use after access control check."""
        async with self._sf() as session:
            stmt = select(KnowledgeBaseDocumentRow).where(
                KnowledgeBaseDocumentRow.id == doc_id,
                KnowledgeBaseDocumentRow.knowledge_base_id == knowledge_base_id,
                KnowledgeBaseDocumentRow.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return self._row_to_dict(row) if row else None

    async def list_by_kb_accessible(
        self,
        knowledge_base_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List documents in a KB without owner filter. Use after access control check."""
        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .order_by(KnowledgeBaseDocumentRow.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def update_by_kb(
        self,
        doc_id: str,
        *,
        knowledge_base_id: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        """Update a document scoped to KB (no owner filter). Use after write permission check."""
        allowed = {"title", "content", "content_format", "content_hash", "content_length", "version", "source_name", "metadata_json"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return await self.get_by_kb(doc_id, knowledge_base_id=knowledge_base_id)
        updates["updated_at"] = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.id == doc_id,
                    KnowledgeBaseDocumentRow.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .values(**updates)
            )
            await session.execute(stmt)
            await session.commit()
        return await self.get_by_kb(doc_id, knowledge_base_id=knowledge_base_id)

    async def soft_delete_by_kb_doc(
        self,
        doc_id: str,
        *,
        knowledge_base_id: str,
    ) -> bool:
        """Soft-delete a document scoped to KB (no owner filter). Use after write permission check."""
        now = datetime.now(UTC)
        async with self._sf() as session:
            stmt = (
                update(KnowledgeBaseDocumentRow)
                .where(
                    KnowledgeBaseDocumentRow.id == doc_id,
                    KnowledgeBaseDocumentRow.knowledge_base_id == knowledge_base_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .values(deleted_at=now, updated_at=now)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def count_docs_by_status_for_kb(self, kb_id: str) -> dict[str, int]:
        """Count non-deleted documents grouped by index_status for a KB."""
        from sqlalchemy import func

        async with self._sf() as session:
            stmt = (
                select(KnowledgeBaseDocumentRow.index_status, func.count(KnowledgeBaseDocumentRow.id))
                .where(
                    KnowledgeBaseDocumentRow.knowledge_base_id == kb_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .group_by(KnowledgeBaseDocumentRow.index_status)
            )
            result = await session.execute(stmt)
            return dict(result.all())

    async def count_docs_by_status_for_kbs(self, kb_ids: list[str]) -> dict[str, dict[str, int]]:
        """Count non-deleted documents grouped by (kb_id, index_status) for multiple KBs."""
        from sqlalchemy import func

        if not kb_ids:
            return {}
        async with self._sf() as session:
            stmt = (
                select(
                    KnowledgeBaseDocumentRow.knowledge_base_id,
                    KnowledgeBaseDocumentRow.index_status,
                    func.count(KnowledgeBaseDocumentRow.id),
                )
                .where(
                    KnowledgeBaseDocumentRow.knowledge_base_id.in_(kb_ids),
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
                .group_by(KnowledgeBaseDocumentRow.knowledge_base_id, KnowledgeBaseDocumentRow.index_status)
            )
            result = await session.execute(stmt)
            grouped: dict[str, dict[str, int]] = {}
            for kb_id, status, count in result.all():
                grouped.setdefault(kb_id, {})[status] = count
            return grouped
