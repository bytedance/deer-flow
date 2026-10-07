"""Async indexing worker: drives documents through the status machine (spec §3.6/§3.7).

The upload API only persists the ``documents`` row and enqueues the doc id;
this worker runs the long pipeline in the background with a semaphore cap
(``rag.worker_concurrency``):

    uploaded → parsing → chunking → indexing → ready / failed

Resume semantics (spec §3.7 启动恢复):
- Startup recovery re-enqueues every non-terminal document.
- A crash before ``indexing`` re-runs parse → chunk from scratch after wiping
  the partial chunk/vector output (chunk ids are deterministic).
- A crash inside ``indexing`` re-runs the vector leg (point ids are
  deterministic ``uuid5`` — upserts overwrite in place).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from deerflow.config.app_config import get_app_config
from deerflow.knowledge.captioner import apply_captions, caption_images
from deerflow.knowledge.chunker import chunk_markdown
from deerflow.knowledge.dimension_migration import migration_in_progress
from deerflow.knowledge.embed_identity import write_kb_identity
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.embedder_factory import build_embedder, effective_dimension
from deerflow.knowledge.indexer import index_chunks
from deerflow.knowledge.parser import ParsedDocument, ParsedImage, parse_document
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.sweep import reconcile_files, sweep_generations, sweep_round
from deerflow.knowledge.vector_store import KnowledgeVectorStore, refreshed_store
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

#: 计数型 error 子标记的前缀（spec 2026-09-23 D8/R21 ②）：``_append_error_marker`` 的幂等
#: 判据是子串比较，而计数一变子串就不匹配 ⇒ 该标记按前缀刷新，同一阶段只留最新结论。
_CAPTION_MARKER_PREFIX = "image caption degraded:"

#: 索引完整性失败标记（RFC §5.2 表行 4）：索引不完整 / 无可索引内容 ⇒ 文档 failed。
_VECTOR_INCOMPLETE_PREFIX = "向量索引不完整"
_NO_CONTENT_PREFIX = "无可索引内容"


def _drop_error_markers(error: str, prefix: str) -> str:
    """删掉 ``error`` 里以 *prefix* 开头的 ``; `` 分隔子标记，其余原样保留。"""
    parts = [part.strip() for part in error.split(";")]
    return "; ".join(part for part in parts if part and not part.startswith(prefix))


class _DocumentDeletedError(Exception):
    """The document row vanished mid-pipeline (user deleted it) — abort quietly."""


class EmptyParseResultError(Exception):
    """The parser returned no text at all — indexing would otherwise walk to a
    ``ready`` document with zero chunks (silent data loss, 2026-09-04 实测：
    MinerU 对纯标题/超短页返回空 full.md), so the pipeline fails loudly with
    an actionable, retryable error instead."""


class _Embedder(Protocol):
    batch_size: int

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]: ...


class KnowledgeIndexWorker:
    """Background asyncio worker for the offline indexing pipeline."""

    def __init__(
        self,
        *,
        store: KnowledgeStore,
        vector_store: KnowledgeVectorStore,
        concurrency: int = 2,
        parse_fn: Callable[[str], Awaitable[ParsedDocument]] | None = None,
        embedder: _Embedder | None = None,
        sweep_enabled: bool = True,
        sweep_interval_hours: float = 24.0,
        data_dir: str | Path | None = None,
        migration_running_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._store = store
        self._vector_store_held = vector_store
        self._parse_fn = parse_fn or parse_document
        self._embedder = embedder
        #: 孤儿向量对账清扫（spec 2026-10-04 D2=甲/D3=乙）：周期任务 + 忙库闸。
        self._sweep_enabled = sweep_enabled
        self._sweep_interval_seconds = max(60.0, float(sweep_interval_hours) * 3600.0)
        #: 文件侧对账的数据根（spec 2026-10-05 §2.2）；None = 不跑文件腿（测试夹具等）。
        self._data_dir = Path(data_dir) if data_dir is not None else None
        #: app 层迁移闸（spec 2026-10-05 D6）：交接窗口里 in-flight 旗已落、旧代仍在服务。
        self._migration_running_fn = migration_running_fn
        self._sweep_task: asyncio.Task[None] | None = None
        self._busy_kbs: set[str] = set()
        self._sem = asyncio.Semaphore(concurrency)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._dispatcher: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[None]] = set()

        #: D3=甲 在途合并（2026-10-04）：同一文档并发重复提交收敛为单次运行
        #: 加至多一次补跑。
        self._active: set[str] = set()
        self._pending: set[str] = set()

    @property
    def _vector_store(self) -> KnowledgeVectorStore:
        """取值口自检（spec 2026-10-05 D1）：配置声明（url/宽度）变了就换新实例。"""
        self._vector_store_held = refreshed_store(self._vector_store_held)
        return self._vector_store_held

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dispatcher after startup-recovery re-enqueues (spec §3.7).

        A Qdrant outage must not block gateway startup: collection init
        failures are logged and the dispatcher still runs — affected documents
        surface as ``failed`` with the connection error, and the next gateway
        restart re-enqueues them.
        """
        if self._dispatcher is not None:
            return
        try:
            await self._vector_store.init_collections()
        except Exception:
            logger.exception("Qdrant collection init failed at worker start; indexing will fail per-document until Qdrant is reachable")
        recovered = await self.recover()
        if recovered:
            logger.info("knowledge worker recovery: re-enqueued %d non-terminal document(s)", recovered)
        self._dispatcher = asyncio.create_task(self._dispatch_loop(), name="knowledge-index-worker")
        if self._sweep_enabled:
            self._sweep_task = asyncio.create_task(self._sweep_loop(), name="knowledge-orphan-sweep")

    async def stop(self) -> None:
        dispatcher, self._dispatcher = self._dispatcher, None
        if dispatcher is not None:
            dispatcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher
        sweep_task, self._sweep_task = self._sweep_task, None
        if sweep_task is not None:
            sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep_task
        if self._inflight:
            await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def recover(self) -> int:
        """Re-enqueue every non-terminal document; returns the count."""
        documents = await self._store.list_non_terminal_documents()
        for document in documents:
            await self.submit(document["id"])
        return len(documents)

    async def submit(self, doc_id: str) -> None:
        await self._queue.put(doc_id)

    async def _require_alive(self, doc_id: str) -> None:
        """Liveness checkpoint against the delete-vs-worker race: a document
        deleted mid-pipeline must not be resurrected by further writes
        (insert_chunks / graph upserts would otherwise recreate zombie rows
        and phantom chunk references; status updates no-op silently)."""
        if await self._store.get_document(doc_id) is None:
            raise _DocumentDeletedError(doc_id)

    async def wait_idle(self) -> None:
        """Block until the queue drains and in-flight documents settle (tests)."""
        await self._queue.join()
        # task_done fires in _run_guarded's finally just before task completion;
        # gather lets those tasks finish and surfaces exceptions. The sleep(0)
        # yields to the loop so done-callbacks (inflight discard) can run —
        # awaiting an already-finished task never yields and would spin forever.
        while self._inflight:
            await asyncio.gather(*list(self._inflight), return_exceptions=True)
            await asyncio.sleep(0)

    async def _dispatch_loop(self) -> None:
        while True:
            doc_id = await self._queue.get()
            task = asyncio.create_task(self._run_guarded(doc_id))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _run_guarded(self, doc_id: str) -> None:
        # D3=甲 在途合并：判档在任何 await 之前完成——同一事件循环内两个任务
        # 先后进入，后到者必见先到者已入档（无同刻竞态）；重复只登记一次补跑，
        # 补跑排在原运行收尾之后（终态复检兜底），绝不并发进入管线。
        already_active = doc_id in self._active
        if already_active:
            self._pending.add(doc_id)
        else:
            self._active.add(doc_id)
        kb_id: str | None = None
        try:
            if not already_active:
                # D3=乙 忙库闸输入（spec 2026-10-04）：运行期间该库对外声明忙，
                # 清扫轮会跳过它；等槽位前就登记，排队中的一跑也算忙。
                document = await self._store.get_document(doc_id)
                if document is not None:
                    kb_id = document["kb_id"]
                    self._busy_kbs.add(kb_id)
                async with self._sem:
                    await self.process_document(doc_id)
        finally:
            if kb_id is not None:
                self._busy_kbs.discard(kb_id)
            if not already_active:
                self._active.discard(doc_id)
                if doc_id in self._pending:
                    self._pending.discard(doc_id)
                    await self.submit(doc_id)
            self._queue.task_done()

    def busy_kb_ids(self) -> set[str]:
        """D3=乙 忙库闸输入：文档腿在飞时对外声明该库忙（spec 2026-10-04）。

        结构化维护而非“按文档行反推”：文档被删后行会消失，反推会把仍在收尾
        的运行误判成空闲。
        """
        return set(self._busy_kbs)

    async def _sweep_loop(self) -> None:
        """周期跑一轮全库清扫（spec §2.3；D2=甲）：启动 jitter 一次再进稳态。"""
        await asyncio.sleep(random.uniform(0.0, min(600.0, self._sweep_interval_seconds)))
        while True:
            try:
                await self._sweep_once()
            except Exception:
                logger.exception("orphan sweep round failed; the next round retries")
            await asyncio.sleep(self._sweep_interval_seconds)

    async def _sweep_once(self) -> None:
        """一轮全库清扫：迁移在飞（含 app 闸的交接窗口）整轮跳过；组内闸逐库跳过；
        文件腿与代次 GC 随同一轮（spec 2026-10-05 §2.3/§2.6）。"""
        if migration_in_progress() or (self._migration_running_fn is not None and self._migration_running_fn()):
            logger.info("orphan sweep round skipped: a migration is in flight or mid hand-off")
            return
        busy = self.busy_kb_ids()
        await sweep_round(store=self._store, vector_store=self._vector_store, skip_kb_ids=busy)
        if self._data_dir is not None:
            await reconcile_files(data_dir=self._data_dir, store=self._store, skip_kb_ids=busy)
        await sweep_generations(vector_store=self._vector_store, declared_width=effective_dimension())

    # ── pipeline ─────────────────────────────────────────────────────────

    async def process_document(self, doc_id: str) -> dict[str, Any] | None:
        """Run one document through the status machine; never raises."""
        document = await self._store.get_document(doc_id)
        if document is None or document["status"] in ("ready", "failed"):
            return document
        kb_id = document["kb_id"]
        # P3 per-path sub-status (spec 2026-08-11 §5): initialized up front so the
        # hover breakdown exists from the parsing stage on (2026-08-12 UX fix) —
        # only pre-0012 legacy rows stay NULL and render no hover. Partial-merge
        # writes follow as each leg advances.
        legs: dict[str, str] = {"vector": "pending"}
        try:
            if document["status"] in ("uploaded", "parsing", "chunking"):
                await self._reparse_and_chunk(doc_id, kb_id, document["storage_path"])

            await self._require_alive(doc_id)  # checkpoint: before the vector leg
            await self._store.update_document_status(doc_id, "indexing", path_status=legs)
            chunks = await self._store.list_chunks(doc_id, limit=1_000_000)
            embedder = self._embedder or build_embedder()
            vector_note: str | None = None
            if chunks:
                index_stats = await index_chunks(self._store, self._vector_store, embedder, kb_id=kb_id, doc_id=doc_id, chunks=chunks)
                if index_stats.indexed == index_stats.total:
                    legs["vector"] = "done"
                else:
                    # 任何批次软失败（EmbedderError 降级）都使索引不完整 → 不 done：
                    # 不能因向量「部分成功」而放行（RFC §5.2 表行 4）。
                    legs["vector"] = "failed"
                    vector_note = f"{_VECTOR_INCOMPLETE_PREFIX}：{index_stats.total - index_stats.indexed}/{index_stats.total} 切片未入库"
            else:
                legs["vector"] = "failed"
                vector_note = f"{_NO_CONTENT_PREFIX}：文档未产生任何可索引切片"
            await self._store.update_document_status(doc_id, "indexing", path_status={"vector": legs["vector"]})

            if legs["vector"] == "done":
                await self._stamp_library_identity(doc_id, kb_id, embedder)
                await self._store.update_document_status(doc_id, "ready", progress_percent=100)
            else:
                # 索引不完整/无可索引内容 ⇒ 文档 failed（RFC §5.2 表行 4）。
                # 标记追加式刷新（replace 同族）——不遮蔽既有 caption 子标记。
                note = vector_note or f"{_VECTOR_INCOMPLETE_PREFIX}：切片未全部入库"
                replace = _NO_CONTENT_PREFIX if note.startswith(_NO_CONTENT_PREFIX) else _VECTOR_INCOMPLETE_PREFIX
                await self._append_error_marker(doc_id, note, replace_prefix=replace)
                await self._store.update_document_status(doc_id, "failed")
        except _DocumentDeletedError:
            logger.info("document %s was deleted mid-indexing; pipeline aborted quietly", doc_id)
            return None
        except Exception as exc:
            logger.exception("knowledge indexing failed for document %s", doc_id)
            # Legs that never reached a terminal state fail with the document;
            # terminal verdicts (done/degraded) are preserved.
            failed_legs = {leg: "failed" for leg, state in legs.items() if state not in ("done", "degraded")}
            await self._store.update_document_status(doc_id, "failed", error=str(exc)[:500], path_status=failed_legs or None)
        return await self._store.get_document(doc_id)

    async def _stamp_library_identity(self, doc_id: str, kb_id: str, embedder: _Embedder) -> None:
        """Stamp the library's embedding identity at its first completed document (D2).

        Only when the library has made no claim yet and no *other* document has settled:
        an earlier document may sit in an older vector space, and a mixed library must
        stay unstamped (``NULL`` = unknown) rather than claim uniformity. Read soft — an
        embedder that cannot say which space it writes into gets no stamp.
        """
        identity = getattr(embedder, "identity", None)
        if not identity:
            return
        try:
            kb = await self._store.get_kb(kb_id)
            if kb is None or kb.get("embedding_identity"):
                return
            for other in await self._store.list_documents(kb_id):
                if other["id"] != doc_id and other["status"] in ("ready", "failed"):
                    return
            await write_kb_identity(self._store._sf, kb_id, identity)
        except Exception:
            logger.exception("library identity stamp failed for kb %s", kb_id)

    async def _append_error_marker(self, doc_id: str, marker: str, *, replace_prefix: str | None = None) -> None:
        """Append a visible sub-marker to the document error field without
        clobbering an existing one (e.g. "graph degraded") — degraded stages
        stack their markers, never silently (spec 2026-08-10 D3 降级).

        ``replace_prefix`` refreshes a *counted* marker of the same stage in place
        instead of stacking a second claim about it (spec 2026-09-23 D8/R21 ②).
        """
        document = await self._store.get_document(doc_id)
        if document is None:
            return
        existing = document.get("error") or ""
        if replace_prefix is not None:
            existing = _drop_error_markers(existing, replace_prefix)
        parts = [part.strip() for part in existing.split(";")]
        parts = [part for part in parts if part]
        if marker in parts:
            return
        parts.append(marker)
        await self._store.update_document_status(doc_id, document["status"], error="; ".join(parts))

    async def _clear_error_markers(self, doc_id: str, prefix: str) -> None:
        """Delete this document's markers sharing *prefix* (the counted ones).

        ``documents.error`` has no delete channel, so the remainder is written back
        explicitly — and only when something was actually dropped, so documents that
        never carried the marker keep their column untouched.
        """
        document = await self._store.get_document(doc_id)
        if document is None:
            return
        existing = document.get("error") or ""
        remaining = _drop_error_markers(existing, prefix)
        if remaining != existing:
            await self._store.update_document_status(doc_id, document["status"], error=remaining)

    async def _wipe_doc_chunks(self, doc_id: str) -> None:
        """Drop a document's chunks + their vector residue (idempotent).

        Shared by the re-parse path: chunks are rebuilt from scratch, so stale
        points must go first (chunk ids are deterministic — a rebuild would
        otherwise upsert over half-cleaned residue).
        """
        existing = await self._store.list_chunks(doc_id, limit=1_000_000)
        if not existing:
            return
        await self._vector_store.delete_by_doc(doc_id)
        await self._store.delete_chunks_by_doc(doc_id)

    async def _reparse_and_chunk(self, doc_id: str, kb_id: str, storage_path: str) -> None:
        """Parse → caption → chunk, wiping any partial output first (idempotent)."""
        await self._wipe_doc_chunks(doc_id)

        # A new pass re-decides the caption leg, so the previous verdict and its counted
        # marker go before the parse: the wipe above drops chunks and their residue but not
        # ``documents.error``, and the status write below merges per key — neither residue
        # clears itself (spec 2026-09-23 D8/R21 ①).
        await self._clear_error_markers(doc_id, _CAPTION_MARKER_PREFIX)
        await self._store.update_document_status(doc_id, "parsing", path_status={"vector": "pending", "caption": None})
        parsed = await self._parse_fn(storage_path)
        if not parsed.markdown.strip():
            raise EmptyParseResultError("解析结果为空：解析服务（MinerU）未从文档中提取到任何文本（常见于纯标题页、扫描页或内容过短），请重试或改传 .md/.txt 文本版本")
        markdown = parsed.markdown
        if parsed.images:
            # The outcome carries its own verdict (spec 2026-09-23 D8/R13): the pass count and
            # the degradation flag are decided in the captioner, so this leg only reads them.
            outcome = await caption_images(parsed.images)
            markdown = apply_captions(markdown, outcome.captions)
            await self._store.update_document_status(doc_id, "parsing", path_status={"caption": "degraded" if outcome.degraded else "done"})
            if outcome.degraded:
                await self._append_error_marker(
                    doc_id,
                    f"{_CAPTION_MARKER_PREFIX} {outcome.failed}/{len(parsed.images)} images failed",
                    replace_prefix=_CAPTION_MARKER_PREFIX,
                )

        await self._require_alive(doc_id)  # checkpoint: after the long external parse, before any write
        if parsed.images:
            # Persist the images the chunk markdown references (``images/…``)
            # so the chunk viewer can serve real files instead of the
            # renderer's broken-image placeholder.
            try:
                await self._save_parsed_images(storage_path, parsed.images)
            except Exception:
                logger.warning("failed to persist parsed images for document %s; continuing without image files", doc_id, exc_info=True)
        await self._store.update_document_status(doc_id, "chunking")
        # Table-aware chunking reads the row-card serialization mode from config
        # (spec §4/§7); the worker only forwards it — no branching here. Non-table
        # documents are unaffected (chunk_markdown ignores card_mode for prose).
        card_mode = get_app_config().rag.table.card_mode
        chunks = chunk_markdown(markdown, doc_id, card_mode=card_mode)
        await self._store.insert_chunks(
            [
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": doc_id,
                    "kb_id": kb_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "heading_path": chunk.heading_path,
                    "page": chunk.page,
                    "token_count": chunk.token_count,
                }
                for chunk in chunks
            ]
        )
        await self._store.update_document_status(doc_id, "indexing", chunk_count=len(chunks))

    async def _save_parsed_images(self, storage_path: str, images: list[ParsedImage]) -> None:
        """Persist parser-extracted images next to the source document.

        Chunk markdown references them as ``images/…``; the gateway serves them
        from the document directory. Re-parses rebuild the ``images/`` directory
        from scratch so a changed image set never leaves stale files. Refs come
        from the MinerU zip and are re-validated against path traversal anyway.
        """
        doc_dir = Path(storage_path).parent

        def _write() -> None:
            root = doc_dir.resolve()
            images_dir = doc_dir / "images"
            if images_dir.exists():
                shutil.rmtree(images_dir, ignore_errors=True)
            for image in images:
                target = (doc_dir / image.ref).resolve()
                if root not in target.parents:
                    logger.warning("skipping unsafe parsed image ref %r", image.ref)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(image.content)

        await run_file_io(_write)
