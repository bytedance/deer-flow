"""IndexingService — orchestrates document indexing into the vector store."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from deerflow.persistence.knowledge_base.document_repository import DocumentRepository
from deerflow.persistence.knowledge_base.index_job_repository import IndexJobRepository
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(
        self,
        kb_repo: KnowledgeBaseRepository,
        doc_repo: DocumentRepository,
        job_repo: IndexJobRepository,
    ) -> None:
        self._kb_repo = kb_repo
        self._doc_repo = doc_repo
        self._job_repo = job_repo

    async def execute_index_job(
        self,
        document: dict[str, Any],
        knowledge_base: dict[str, Any],
    ) -> dict[str, Any]:
        """Run ingestion for a document and update status accordingly."""
        from deerflow.rag.ingestion import DocumentIngestor
        from deerflow.rag.vector_store import get_vector_store

        doc_id = document["id"]
        kb_id = knowledge_base["id"]
        collection_name = knowledge_base["collection_name"]
        version = document["version"]
        old_chunk_ids = document.get("chunk_ids") or []

        job = await self._job_repo.create(
            document_id=doc_id,
            knowledge_base_id=kb_id,
            tenant_id=document["tenant_id"],
            owner_user_id=document["owner_user_id"],
            version=version,
            old_chunk_ids=old_chunk_ids,
        )
        job_id = job["id"]

        now = datetime.now(UTC)
        await self._job_repo.update_status(job_id, status="running", started_at=now)
        await self._doc_repo.update_index_status(doc_id, index_status="indexing", index_job_id=job_id)

        try:
            ingestor = DocumentIngestor()
            chunk_metadata = {
                "document_id": doc_id,
                "knowledge_base_id": kb_id,
                "tenant_id": document["tenant_id"],
                "owner_user_id": document["owner_user_id"],
                "title": document["title"],
                "source_name": document.get("source_name") or "",
                "kb_name": knowledge_base.get("name", ""),
            }
            result = await asyncio.to_thread(
                ingestor.ingest_text,
                document["content"],
                document.get("source_name") or document["title"],
                collection_name,
                chunk_metadata,
            )

            if result.error:
                raise RuntimeError(result.error)

            # Version guard: re-read document to ensure version hasn't changed
            current_doc = await self._doc_repo.get_by_id_internal(doc_id)
            if current_doc is None or current_doc["version"] != version:
                logger.warning("Version mismatch for doc %s (expected %d), discarding index result", doc_id, version)
                store = get_vector_store()
                if result.chunk_ids:
                    store.delete(collection_name, result.chunk_ids)
                await self._job_repo.update_status(job_id, status="cancelled", finished_at=datetime.now(UTC))
                return job

            finished = datetime.now(UTC)
            await self._doc_repo.update_index_status(
                doc_id,
                index_status="ready",
                index_error=None,
                index_job_id=job_id,
                chunk_ids=result.chunk_ids,
                chunk_count=result.chunk_count,
                last_indexed_at=finished,
            )
            await self._job_repo.update_status(
                job_id,
                status="completed",
                new_chunk_ids=result.chunk_ids,
                finished_at=finished,
            )

            # Clean up old chunks asynchronously
            if old_chunk_ids:
                try:
                    store = get_vector_store()
                    store.delete(collection_name, old_chunk_ids)
                except Exception as e:
                    logger.warning("Failed to delete old chunks for doc %s: %s", doc_id, e)

            # Update KB stats
            await self._update_kb_stats(kb_id)

            return await self._job_repo.get(job_id) or job

        except Exception as e:
            logger.error("Index job %s failed: %s", job_id, e)
            await self._doc_repo.update_index_status(doc_id, index_status="failed", index_error=str(e), index_job_id=job_id)
            await self._job_repo.update_status(job_id, status="failed", error=str(e), finished_at=datetime.now(UTC))
            return await self._job_repo.get(job_id) or job

    async def _update_kb_stats(self, kb_id: str) -> None:
        """Recalculate document_count and chunk_count for a knowledge base."""
        kb = await self._kb_repo.get_by_id_internal(kb_id)
        if kb is None:
            return
        # Fetch all active docs for this KB to compute stats
        from sqlalchemy import func, select

        from deerflow.persistence.knowledge_base.model import KnowledgeBaseDocumentRow

        async with self._doc_repo._sf() as session:
            stmt = (
                select(
                    func.count(KnowledgeBaseDocumentRow.id),
                    func.coalesce(func.sum(KnowledgeBaseDocumentRow.chunk_count), 0),
                )
                .where(
                    KnowledgeBaseDocumentRow.knowledge_base_id == kb_id,
                    KnowledgeBaseDocumentRow.deleted_at.is_(None),
                )
            )
            result = await session.execute(stmt)
            row = result.one()
            doc_count, total_chunks = int(row[0]), int(row[1])

        await self._kb_repo.update_stats(
            kb_id,
            document_count=doc_count,
            chunk_count=total_chunks,
            last_indexed_at=datetime.now(UTC),
        )
