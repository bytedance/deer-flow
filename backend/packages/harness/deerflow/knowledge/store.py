"""CRUD store over the RAG knowledge-base business tables.

Holds the source of truth for chunk text; Qdrant only mirrors vectors + a
``chunk_id`` pointer (spec §3.2). This store owns the shared lifecycle:
KBs, documents, chunks, and cascading deletes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.knowledge.models import (
    ChunkRow,
    DocumentRow,
    EvalRunRow,
    KnowledgeBaseRow,
)
from deerflow.utils.time import coerce_iso

#: Document status machine (spec §3.6): uploaded → parsing → chunking →
#: indexing → ready / failed.
DOCUMENT_STATUSES: frozenset[str] = frozenset({"uploaded", "parsing", "chunking", "indexing", "ready", "failed"})

#: Per-chunk graph-extract states (spec §3.4); persisted for resume.
CHUNK_EXTRACT_STATUSES: frozenset[str] = frozenset({"pending", "done", "empty", "failed"})


class KnowledgeStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: Any, *, datetime_keys: tuple[str, ...] = ("created_at", "updated_at")) -> dict[str, Any]:
        data = row.to_dict()
        for key in datetime_keys:
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    # ── knowledge_bases ──────────────────────────────────────────────────

    async def create_kb(
        self,
        *,
        kb_id: str,
        owner_id: str,
        name: str,
        description: str | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        row = KnowledgeBaseRow(
            id=kb_id,
            owner_id=owner_id,
            name=name,
            description=description,
            visibility=visibility,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get_kb(self, kb_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(KnowledgeBaseRow, kb_id)
            return None if row is None else self._row_to_dict(row)

    async def list_kbs(self, owner_id: str) -> list[dict[str, Any]]:
        stmt = select(KnowledgeBaseRow).where(KnowledgeBaseRow.owner_id == owner_id).order_by(KnowledgeBaseRow.created_at.desc(), KnowledgeBaseRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars().all()]

    async def list_all_kbs(self) -> list[dict[str, Any]]:
        """Every library, across owners.

        The vector collections are deployment-wide, so an operation that rewrites them
        (the width migration, spec 2026-09-26 D5-2) must cover every owner's libraries —
        the owner-scoped ``list_kbs`` would silently leave the rest behind.
        """
        stmt = select(KnowledgeBaseRow).order_by(KnowledgeBaseRow.created_at, KnowledgeBaseRow.id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars().all()]

    async def update_kb(self, kb_id: str, *, name: str | None = None, description: str | None = None) -> dict[str, Any] | None:
        """Rename / re-describe a KB; ``None`` leaves a field unchanged."""
        async with self._sf() as session:
            row = await session.get(KnowledgeBaseRow, kb_id)
            if row is None:
                return None
            if name is not None:
                row.name = name
            if description is not None:
                row.description = description
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete_kb(self, kb_id: str) -> bool:
        """Delete a KB and cascade across the business tables.

        Vector-side cleanup (its Qdrant collections) is layered on top by
        the API/worker so a vector failure cannot strand business rows
        half-deleted (spec §3.7).
        """
        async with self._sf() as session:
            row = await session.get(KnowledgeBaseRow, kb_id)
            if row is None:
                return False
            for model in (ChunkRow, DocumentRow):
                await session.execute(delete(model).where(model.kb_id == kb_id))
            await session.delete(row)
            await session.commit()
            return True

    # ── documents ────────────────────────────────────────────────────────

    async def create_document(
        self,
        *,
        doc_id: str,
        kb_id: str,
        uploader_id: str,
        name: str,
        size_bytes: int,
        storage_path: str,
        content_hash: str | None = None,
    ) -> dict[str, Any]:
        row = DocumentRow(
            id=doc_id,
            kb_id=kb_id,
            uploader_id=uploader_id,
            name=name,
            size_bytes=size_bytes,
            storage_path=storage_path,
            status="uploaded",
            progress_percent=0,
            content_hash=content_hash,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(DocumentRow, doc_id)
            return None if row is None else self._row_to_dict(row)

    async def list_documents(self, kb_id: str) -> list[dict[str, Any]]:
        stmt = select(DocumentRow).where(DocumentRow.kb_id == kb_id).order_by(DocumentRow.created_at.desc(), DocumentRow.id.desc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars().all()]

    async def list_non_terminal_documents(self) -> list[dict[str, Any]]:
        """Documents not in a terminal state — the worker re-enqueues these on startup (spec §3.7 启动恢复)."""
        stmt = select(DocumentRow).where(DocumentRow.status.not_in(("ready", "failed"))).order_by(DocumentRow.created_at, DocumentRow.id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars().all()]

    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        *,
        progress_percent: int | None = None,
        chunk_count: int | None = None,
        error: str | None = None,
        path_status: dict[str, str | None] | None = None,
    ) -> dict[str, Any] | None:
        """Advance the document status machine; ``None`` leaves a field unchanged.

        ``path_status`` merges **partially** (spec 2026-08-11 §5): only the
        keys passed on this call are updated — the other paths' sub-states
        persist untouched. A wholesale overwrite would violate the contract.
        A ``None`` *value* deletes that key (the merge itself cannot express
        "remove"), which is distinct from the call-level ``None`` arguments.
        """
        async with self._sf() as session:
            row = await session.get(DocumentRow, doc_id)
            if row is None:
                return None
            row.status = status
            if progress_percent is not None:
                row.progress_percent = progress_percent
            if chunk_count is not None:
                row.chunk_count = chunk_count
            if error is not None:
                row.error = error
            if path_status is not None:
                merged = dict(row.path_status or {})
                for key, value in path_status.items():
                    if value is None:
                        merged.pop(key, None)
                    else:
                        merged[key] = value
                row.path_status = merged
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def reset_document_for_retry(self, doc_id: str) -> dict[str, Any] | None:
        """Reset a failed document to ``uploaded`` for re-indexing: clears progress,
        chunk count, and the error (unlike ``update_document_status`` whose ``None``
        means \"leave unchanged\"). The per-path sub-status is cleared too — the
        re-run rebuilds it from scratch (spec 2026-08-11 §5)."""
        async with self._sf() as session:
            row = await session.get(DocumentRow, doc_id)
            if row is None:
                return None
            row.status = "uploaded"
            row.progress_percent = 0
            row.chunk_count = None
            row.error = None
            row.path_status = None
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete_document(self, doc_id: str) -> bool:
        """Delete one document + its chunk rows (business DB).

        Files live outside the DB — the service-layer cascade removes the
        per-doc dir (``_remove_dir``). Vector cleanup is layered on top by the
        caller (``delete_document_cascade``).
        """
        async with self._sf() as session:
            row = await session.get(DocumentRow, doc_id)
            if row is None:
                return False
            await session.execute(delete(ChunkRow).where(ChunkRow.doc_id == doc_id))
            await session.delete(row)
            await session.commit()
            return True

    # ── chunks ───────────────────────────────────────────────────────────

    async def insert_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Bulk-insert freshly chunked rows; extract state starts at ``pending``."""
        rows = [
            ChunkRow(
                chunk_id=chunk["chunk_id"],
                doc_id=chunk["doc_id"],
                kb_id=chunk["kb_id"],
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                heading_path=chunk.get("heading_path") or [],
                page=chunk.get("page"),
                token_count=chunk.get("token_count", 0),
                entities=chunk.get("entities") or [],
                extract_status=chunk.get("extract_status", "pending"),
                extract_error=chunk.get("extract_error"),
            )
            for chunk in chunks
        ]
        async with self._sf() as session:
            session.add_all(rows)
            await session.commit()
            return len(rows)

    async def list_chunks(self, doc_id: str, *, offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        stmt = select(ChunkRow).where(ChunkRow.doc_id == doc_id).order_by(ChunkRow.chunk_index).offset(offset).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row, datetime_keys=()) for row in result.scalars().all()]

    async def count_chunks(self, doc_id: str) -> int:
        stmt = select(func.count()).select_from(ChunkRow).where(ChunkRow.doc_id == doc_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one())

    async def chunk_positions(self, doc_id: str, chunk_indexes: set[int]) -> dict[int, int]:
        """Position (1-based) of each requested chunk_index among the doc's
        live chunks ordered by chunk_index — the same positional order the
        chunk drawer's #K badges use; holes (deleted chunks) occupy no
        position. Requested indexes that are not live are absent from the
        result. Index-column-only query: cheap even for 300-chunk docs.
        """
        stmt = select(ChunkRow.chunk_index).where(ChunkRow.doc_id == doc_id).order_by(ChunkRow.chunk_index)
        async with self._sf() as session:
            live = (await session.execute(stmt)).scalars().all()
        order = {index: position for position, index in enumerate(live, start=1)}
        return {index: order[index] for index in chunk_indexes if index in order}

    async def get_kb_content_stats(self, kb_id: str) -> dict[str, Any]:
        """Cheap invalidation signal for the switch-window fingerprint.

        One aggregate query: chunks ``count + max(last_edited_at)`` (the table
        has no created_at — count covers insert/delete).
        """
        async with self._sf() as session:
            chunks_count, chunks_max = (await session.execute(select(func.count(), func.max(ChunkRow.last_edited_at)).where(ChunkRow.kb_id == kb_id))).one()
        return {"chunks": (int(chunks_count), chunks_max)}

    async def get_chunks_by_ids(self, chunk_ids: list[str], *, kb_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch chunk rows by id (batch reads by chunk id).

        ``kb_id`` narrows the fetch to one knowledge base; callers pass it so
        ids from another KB can never leak through.
        """
        if not chunk_ids:
            return []
        stmt = select(ChunkRow).where(ChunkRow.chunk_id.in_(chunk_ids))
        if kb_id is not None:
            stmt = stmt.where(ChunkRow.kb_id == kb_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = {row.chunk_id: self._row_to_dict(row, datetime_keys=()) for row in result.scalars().all()}
        return [rows[chunk_id] for chunk_id in chunk_ids if chunk_id in rows]

    async def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """Fetch a single chunk row by id."""
        async with self._sf() as session:
            row = await session.get(ChunkRow, chunk_id)
            return None if row is None else self._row_to_dict(row, datetime_keys=())

    async def update_chunk_extract(
        self,
        chunk_id: str,
        status: str,
        *,
        entities: list[str] | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        """Persist a per-chunk extract transition (pending → done/empty/failed).

        ``entities`` carries the normalized-name backfill on ``done`` (spec §3.4).
        """
        async with self._sf() as session:
            row = await session.get(ChunkRow, chunk_id)
            if row is None:
                return None
            row.extract_status = status
            if entities is not None:
                row.entities = entities
            if error is not None:
                row.extract_error = error
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row, datetime_keys=())

    async def delete_chunks_by_doc(self, doc_id: str) -> int:
        """Drop one document's chunk rows (re-parse / retry wipe; spec §3.7)."""
        async with self._sf() as session:
            result = await session.execute(delete(ChunkRow).where(ChunkRow.doc_id == doc_id))
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_chunk(self, chunk_id: str) -> bool:
        """Drop a single chunk row (Task 5 收尾 single-chunk delete cascade).

        Idempotent: deleting an absent row returns False.
        """
        async with self._sf() as session:
            result = await session.execute(delete(ChunkRow).where(ChunkRow.chunk_id == chunk_id))
            await session.commit()
            return int(result.rowcount or 0) > 0

    # ── eval_runs (spec 2026-08-24 §4.2, plan Task 1) ────────────────────────

    async def list_eval_runs(self, kb_id: str) -> list[EvalRunRow]:
        """该 KB 的全量 eval_runs 行（``created_at`` 升序），单 KB 历史通常 <100 条。

        返回的 ORM 行在 session 关闭后处于 detached 状态，但全部列已物化，
        只读访问安全（``persistence.get_baseline_run`` 同一形态）；聚合与
        序列化在 service 层完成。
        """
        stmt = select(EvalRunRow).where(EvalRunRow.kb_id == kb_id).order_by(EvalRunRow.created_at.asc(), EvalRunRow.id.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_eval_run_row(self, kb_id: str, run_id: str) -> EvalRunRow | None:
        """单行查询；跨 kb 访问返回 None（路由层映射 404）。detached 只读，同 list_eval_runs。"""
        async with self._sf() as session:
            row = await session.get(EvalRunRow, run_id)
            if row is None or row.kb_id != kb_id:
                return None
            return row

    async def delete_eval_runs(self, kb_id: str, run_ids: Sequence[str]) -> int:
        """按 kb + id 集批量删 eval_runs 行（2026-09-08 历史删除），返回影响行数。

        ``kb_id`` 条件是跨库删除的硬隔离线（同 ``get_eval_run_row`` 的 None
        语义）；集内不存在的 id 自然忽略（幂等）。逐题 slim 记录住在
        ``layer1_metrics`` JSON 内随行消失——无独立表级联。
        """
        if not run_ids:
            return 0
        stmt = delete(EvalRunRow).where(EvalRunRow.kb_id == kb_id, EvalRunRow.id.in_(list(run_ids)))
        async with self._sf() as session:
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)


def get_knowledge_store() -> KnowledgeStore:
    """Build the store from the globally-initialized persistence engine."""
    from deerflow.persistence.engine import get_session_factory

    session_factory = get_session_factory()
    if session_factory is None:
        raise RuntimeError("persistence engine is not initialized")
    return KnowledgeStore(session_factory)
