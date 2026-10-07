"""Application service for the knowledge-base API (spec §5.3 / §3.7).

Owns everything between the thin router and the harness layer: upload
persistence (host-side file + ``documents`` row + worker enqueue), cascade
deletes across the three stores (Qdrant → graph → wiki lifecycle → business
rows), failed-document retry, and fire-and-forget wiki generation.

Cascade ordering rule (mirrors ``KnowledgeStore.delete_kb``'s docstring): the
Qdrant cleanup runs first and its failures are logged but swallowed — a vector
store outage must never strand business rows half-deleted.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.knowledge.embedder_factory import build_embedder
from deerflow.knowledge.parser import TABLE_UPLOAD_SUFFIXES, is_supported_suffix, supported_upload_suffixes, table_upload_limit_bytes
from deerflow.knowledge.reindex import reindex_in_progress, reindex_kb, reindex_last_run_status, reindex_progress
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import refreshed_store
from deerflow.uploads.manager import normalize_filename
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)


class DocumentProcessingError(RuntimeError):
    """Raised when a per-chunk operation collides with an in-flight document pipeline (Phase-3 Batch-1 P3)."""

    def __init__(self, doc_id: str, status: str) -> None:
        super().__init__(f"Document {doc_id} is being processed (status={status})")
        self.doc_id = doc_id
        self.status = status


def _as_utc(value: datetime) -> datetime:
    """SQLite 读出的 DateTime(timezone=True) 是 tz-naive——按单一时钟纪律（§3.1.1）视为 UTC。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def has_degraded_leg(document: dict[str, Any]) -> bool:
    """任一腿处于 ``degraded``（RFC §5.2 D1=甲）——降级文档（ready + 标记）可整篇重试。"""
    return any(state == "degraded" for state in (document.get("path_status") or {}).values())


class KnowledgeService:
    """Coordinates stores + worker for the knowledge-base endpoints."""

    def __init__(
        self,
        *,
        store: KnowledgeStore,
        vector_store: Any,
        worker: Any = None,
        data_dir: str | Path,
        reindex_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store
        self._vector_store_held = vector_store
        self.worker = worker
        self.data_dir = Path(data_dir)
        self.reindex_fn = reindex_fn or self._schedule_reindex
        self._reindex_tasks: set[asyncio.Task[None]] = set()

    @property
    def vector_store(self) -> Any:
        """取值口自检（spec 2026-10-05 D1）：配置声明（url/宽度）变了就换新实例。"""
        self._vector_store_held = refreshed_store(self._vector_store_held)
        return self._vector_store_held

    # ── documents ────────────────────────────────────────────────────────

    async def list_documents(self, kb_id: str) -> list[dict[str, Any]]:
        """Documents with the per-path sub-status (phase-2 batch-1 P3, spec §5)."""
        return await self.store.list_documents(kb_id)

    async def resolve_source_document(self, *, kb_id: str, doc_id: str) -> Path | None:
        """原始上传文件绝对路径（2026-09-10 下载回环）；不可服务则 ``None``（router → 404）。

        ``None`` 覆盖：文档不属于该 kb / 文件缺失或非常规文件。鉴权由 router 的
        ``_require_kb_access`` 承载（与文档读取同源）；路由不接受用户路径段，
        只服务行内记录的路径，穿越结构性不可能。
        """
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return None
        target = Path(document["storage_path"])
        if not target.is_file():
            return None
        return target

    async def list_document_chunks(self, *, kb_id: str, doc_id: str, offset: int, limit: int) -> dict[str, Any]:
        """文档切片分页（切片抽屉数据源，spec 2026-09-08 §5）。"""
        items = await self.store.list_chunks(doc_id, offset=offset, limit=limit)
        total = await self.store.count_chunks(doc_id)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    async def upload_document(self, *, kb_id: str, uploader_id: str, filename: str, content: bytes) -> dict[str, Any]:
        """Persist the file, create the ``uploaded`` row, enqueue indexing."""
        import hashlib

        doc_id = uuid.uuid4().hex
        safe_name = normalize_filename(filename or "document")
        # Task 6 (spec §6): upload allowlist gate — reject before any file I/O.
        suffix = Path(safe_name).suffix.lower()
        if not is_supported_suffix(suffix):
            supported = ", ".join(sorted(supported_upload_suffixes()))
            raise ValueError(f"unsupported file type '{suffix or '(none)'}'; supported formats: {supported}")

        # 表格体积门（spec 2026-09-09 §4）：超 rag.table.max_size_mb 的电子表格门口
        # 即拒，防巨型表行爆炸。只管被门控的三后缀（.xlsx/.xls/.tsv）；.csv 是既有
        # 文本集成员、不门控，也不因本特性新增体积限制。
        if suffix in TABLE_UPLOAD_SUFFIXES:
            limit = table_upload_limit_bytes()
            if limit is not None and len(content) > limit:
                raise ValueError(f"table file too large: {len(content)} bytes exceeds the {limit // (1024 * 1024)} MB limit (rag.table.max_size_mb)")

        # 空文件拦截 (2026-08-30): 0 字节文件照收会白送云端解析，
        # MinerU 重试耗尽后回吐晦涩的 'retry limit reached'——在门口直接拒。
        if not content:
            raise ValueError(f"file is empty: {safe_name}")

        # Task 11: compute SHA-256 hash for duplicate detection
        content_hash = hashlib.sha256(content).hexdigest()

        doc_dir = self.data_dir / "knowledge" / kb_id / doc_id
        dest = doc_dir / safe_name

        def _write() -> None:
            doc_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

        # 文件→行半段（spec 2026-10-05 §2.1）：行没落地就把已写的文件带走，异常路径
        # 不留无主文件；行落地即止（行→入队半段由 worker.recover 兜）。
        try:
            await run_file_io(_write)
            document = await self.store.create_document(
                doc_id=doc_id,
                kb_id=kb_id,
                uploader_id=uploader_id,
                name=safe_name,
                size_bytes=len(content),
                storage_path=str(dest),
                content_hash=content_hash,
            )
        except Exception:
            await self._remove_dir(doc_dir)
            raise
        if self.worker is not None:
            await self.worker.submit(doc_id)
        return document

    async def delete_document_cascade(self, *, kb_id: str, doc_id: str) -> bool:
        """Delete one document across the vector store and the business rows.

        Order: vectors first (failures logged, never blocking), then the
        business rows, then the files — the first-phase cascade.
        """
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return False
        try:
            await self.vector_store.delete_by_doc(doc_id)
        except Exception:
            logger.exception("qdrant delete_by_doc failed for %s; continuing business-row cleanup", doc_id)
        await self.store.delete_document(doc_id)
        await self._remove_dir(self.data_dir / "knowledge" / kb_id / doc_id)
        return True

    async def retry_document(self, *, kb_id: str, doc_id: str) -> dict[str, Any] | None:
        """Wipe a failed or degraded document's derived state and re-enqueue indexing."""
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return None
        chunks = await self.store.list_chunks(doc_id, limit=1_000_000)
        if chunks:
            try:
                await self.vector_store.delete_by_doc(doc_id)
            except Exception:
                logger.exception("qdrant delete_by_doc failed during retry of %s", doc_id)
            await self.store.delete_chunks_by_doc(doc_id)
        reset = await self.store.reset_document_for_retry(doc_id)
        if self.worker is not None:
            await self.worker.submit(doc_id)
        return reset

    # ── knowledge base ───────────────────────────────────────────────────

    async def delete_kb_cascade(self, *, kb_id: str) -> bool:
        """Delete the whole KB: its Qdrant collections + all business rows."""
        try:
            await self.vector_store.delete_by_kb(kb_id)
        except Exception:
            logger.exception("qdrant delete_by_kb failed for %s; continuing business-row cleanup", kb_id)
        deleted = await self.store.delete_kb(kb_id)
        if deleted:
            await self._remove_dir(self.data_dir / "knowledge" / kb_id)
        return deleted

    async def _chunk_position_map(self, chunk_ids: Iterable[str]) -> dict[str, int]:
        """chunk_id → 文档存活切片中的位次（1-based，chunk_index 升序，空洞不占位）。

        畸形 id（无 #NNNN 后缀）与已删除的切片缺键——调用方诚实缺省不显。
        每文档一次索引列轻查询（store.chunk_positions，与切片抽屉 #K 同源）。
        """
        by_doc: dict[str, list[tuple[str, int]]] = {}
        for chunk_id in chunk_ids:
            doc_id, _, suffix = str(chunk_id or "").partition("#")
            if doc_id and suffix.isdigit():
                by_doc.setdefault(doc_id, []).append((chunk_id, int(suffix)))
        positions: dict[str, int] = {}
        for doc_id, entries in by_doc.items():
            doc_positions = await self.store.chunk_positions(doc_id, {index for _, index in entries})
            for chunk_id, index in entries:
                position = doc_positions.get(index)
                if position is not None:
                    positions[chunk_id] = position
        return positions

    async def chunk_positions(self, *, chunk_ids: list[str]) -> dict[str, Any]:
        """POST /chunk-positions：批量切片位次查询（切片抽屉行内「切片 #K」数据源）。

        与切片抽屉 #K 同源（_chunk_position_map）；空列表返回空映射。
        """
        return {"positions": await self._chunk_position_map(chunk_ids)}

    def trigger_reindex(self, kb_id: str) -> bool:
        """Fire-and-forget library-level re-embed (spec 2026-09-14 §5 / P4).

        The only exit from a changed embedding provider or dimension: it re-embeds the
        stored chunks and never re-parses. Refused while a rebuild is already in flight
        for this KB, so the router reports ``already_running`` instead of queueing a
        second pass over the same vectors.
        """
        if reindex_in_progress(kb_id):
            return False
        self.reindex_fn(kb_id)
        return True

    def reindex_status(self, kb_id: str) -> dict[str, Any]:
        """Poll payload for the rebuild entry (progress while running)."""
        return {"in_progress": reindex_in_progress(kb_id), "last_run": reindex_last_run_status(kb_id), "progress": reindex_progress(kb_id)}

    def _schedule_reindex(self, kb_id: str) -> None:
        task = asyncio.create_task(self._run_reindex(kb_id), name=f"kb-reindex-{kb_id}")
        self._reindex_tasks.add(task)
        task.add_done_callback(self._reindex_tasks.discard)

    async def _run_reindex(self, kb_id: str) -> None:
        try:
            # Same embedder wiring as the worker's vector leg: the rebuild must land in
            # the vector space the *current* configuration describes, that being the
            # whole point of the entry.
            await reindex_kb(self.store, self.vector_store, build_embedder(), kb_id=kb_id)
        except Exception:
            logger.exception("reindex failed for kb %s", kb_id)

    # ── internals ────────────────────────────────────────────────────────

    async def _remove_dir(self, path: Path) -> None:
        def _rm() -> None:
            shutil.rmtree(path, ignore_errors=True)

        try:
            await run_file_io(_rm)
        except Exception:
            logger.warning("failed to remove knowledge dir %s", path, exc_info=True)
