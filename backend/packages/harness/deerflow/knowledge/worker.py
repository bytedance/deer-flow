"""Async indexing worker: drives documents through the status machine (spec §3.6/§3.7).

The upload API only persists the ``documents`` row and enqueues the doc id;
this worker runs the long pipeline in the background with a semaphore cap
(``rag.worker_concurrency``):

    uploaded → parsing → chunking → indexing → ready / failed

Resume semantics (spec §3.7 启动恢复):
- Startup recovery re-enqueues every non-terminal document.
- A crash before ``indexing`` re-runs parse → chunk from scratch after wiping
  the partial chunk/vector/graph output (chunk ids are deterministic).
- A crash inside ``indexing`` re-runs the vector leg (point ids are
  deterministic ``uuid5`` — upserts overwrite in place) and the graph leg,
  which only processes ``pending`` chunks, so ``done`` slices are never
  re-extracted.
- ``progress_percent`` tracks graph-settled/total chunks (the slowest leg).

Wiki: once the KB's completion share crosses the trigger threshold, the first
batch runs full-head generation; afterwards the worker runs the dirty
incremental pass (spec §3.7 触发式批量 → dirty 增量).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import shutil
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from deerflow.config.app_config import get_app_config
from deerflow.knowledge.captioner import apply_captions, caption_images
from deerflow.knowledge.chunker import chunk_markdown, count_tokens
from deerflow.knowledge.dimension_migration import migration_in_progress
from deerflow.knowledge.embed_identity import write_kb_identity
from deerflow.knowledge.embedder import EmbeddingResult, RagConfigurationError
from deerflow.knowledge.embedder_factory import build_embedder, effective_dimension
from deerflow.knowledge.graph.indexer import index_document_graph
from deerflow.knowledge.graph.resolver import resolve_entity_aliases
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.indexer import index_chunks
from deerflow.knowledge.messages import bilingual
from deerflow.knowledge.parser import VIDEO_UPLOAD_SUFFIXES, ParsedDocument, ParsedImage, parse_document
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.sweep import reconcile_files, sweep_generations, sweep_round
from deerflow.knowledge.vector_store import KnowledgeVectorStore, refreshed_store
from deerflow.knowledge.video.asr import AsrError, TranscriptSegment, resolve_leg_provider, transcribe_video
from deerflow.knowledge.video.captioner import caption_shots
from deerflow.knowledge.video.frames import extract_caption_frames, extract_keyframes
from deerflow.knowledge.video.ocr import screen_text_shots
from deerflow.knowledge.video.probe import probe_video
from deerflow.knowledge.video.segmentation import fallback_windows, merge_scene_bounds
from deerflow.knowledge.video.shot_card import assemble_card_body, chunk_id_for_shot, heading_path_for_shot, is_empty_card
from deerflow.knowledge.video.store import VideoShotStore
from deerflow.knowledge.wiki.generator import generate_wiki, mark_dirty_for_entities, wiki_generation_in_progress, wiki_trigger_ready
from deerflow.knowledge.wiki.store import WikiStore
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

#: asr 整腿失败时镜头卡口述段的占位（spec §2 降级：区别于无语音的「（无）」）。
_ASR_FAILED = "（ASR 失败）"

#: caption 临时帧数上界（spec §2「caption 临时可用至多 3 帧」，走 pipe 不持久化）。
_CAPTION_FRAMES = 3

#: keyframe 腿失败率降级阈值（>30% → error 子标记，对齐 graph 30% 规则，spec §2）。
_KEYFRAME_DEGRADE_THRESHOLD = 0.30

#: 视频腿 progress 累积权重（spec §2：asr30 / segment5 / caption35 / materialize5 = 75，
#: 余下 25 由现有 vector/graph 腿在 process_document 里映射，保证整体单调至 100）。
_PROGRESS_AFTER_ASR = 30
_PROGRESS_AFTER_SEGMENT = 35
_PROGRESS_AFTER_CAPTION = 70
_PROGRESS_AFTER_MATERIALIZE = 75

#: 计数型 error 子标记的前缀（spec 2026-09-23 D8/R21 ②）：``_append_error_marker`` 的幂等
#: 判据是子串比较，而计数一变子串就不匹配 ⇒ 这两个标记按前缀刷新，同一阶段只留最新结论。
_CAPTION_MARKER_PREFIX = "image caption degraded:"
_GRAPH_MARKER_PREFIX = "graph degraded:"

#: 索引完整性失败标记（RFC §5.2 表行 4）：索引不完整 / 无可索引内容 ⇒ 文档 failed。
_VECTOR_INCOMPLETE_PREFIX = "向量索引不完整"
_NO_CONTENT_PREFIX = "无可索引内容"


def _drop_error_markers(error: str, prefix: str) -> str:
    """删掉 ``error`` 里以 *prefix* 开头的 ``; `` 分隔子标记，其余原样保留。"""
    parts = [part.strip() for part in error.split(";")]
    return "; ".join(part for part in parts if part and not part.startswith(prefix))


def _is_video_path(storage_path: str) -> bool:
    """文档是否视频（storage_path 后缀 ∈ 冻结视频集）——worker 分支路由的单一判据。"""
    return Path(storage_path).suffix.lower() in VIDEO_UPLOAD_SUFFIXES


def assign_transcript_to_shots(
    segments: Sequence[TranscriptSegment],
    shots: Sequence[tuple[int, int]],
) -> dict[int, str]:
    """把 ASR 段按最大重叠占比投影进镜头桶（spec §3 时间轴对齐规则，materialize 核心纯函数）。

    主时钟是镜头边界（PTS 毫秒轴），ASR 只是被投影进桶的一路：

    - 每段归入重叠占比（重叠 ms / 段长）最大的镜头——保句子完整性、检索单元友好；
    - 占比相同归较早镜头（``enumerate`` 升序 + 严格大于 → 先命中的小 index 保留）；
    - 同镜头多段按 ``start_ms`` 升序、空格拼接（口述段保持单行，对齐冻结卡三行结构）；
    - 与所有镜头重叠均为 0 的段丢弃（防御，不落任何桶）；
    - 无语音镜头缺席结果（调用方 ``.get(index, "")`` 补空 → 卡口述段「（无）」）。
    """
    buckets: dict[int, list[tuple[int, str]]] = {}
    for segment in segments:
        span = segment.end_ms - segment.start_ms
        if span <= 0:
            continue
        best_index = -1
        best_ratio = 0.0
        for index, (start, end) in enumerate(shots):
            overlap = min(segment.end_ms, end) - max(segment.start_ms, start)
            if overlap <= 0:
                continue
            ratio = overlap / span
            if ratio > best_ratio:  # 严格大于 → 平局保留较早镜头（index 小）
                best_ratio = ratio
                best_index = index
        if best_index < 0:
            continue  # 零重叠段丢弃
        buckets.setdefault(best_index, []).append((segment.start_ms, segment.text))
    return {index: " ".join(text for _, text in sorted(items)) for index, items in buckets.items()}


def _detect_scene_cuts(video_path: str) -> list[float]:
    """PySceneDetect ContentDetector → 场景切点（PTS 毫秒）。

    重依赖延迟 import（本机/CI 不装）：缺失（ImportError）或解码/检测失败都抛异常，
    由 worker segment 腿捕获后降级为 ``fallback_windows``（segment=degraded，spec §2）。
    blocking 的视频解码经调用方 ``run_file_io`` 落线程池，不阻塞事件循环。检测器只是
    切点的一个来源（换 TransNetV2 只改此函数，spec §3），下游只吃「毫秒切点列表」。
    """
    from scenedetect import ContentDetector, detect  # 延迟 import：缺失即降级

    scene_list = detect(video_path, ContentDetector())
    cuts: list[float] = []
    for scene in scene_list:
        start_seconds = scene[0].get_seconds()
        if start_seconds > 0:  # 首场景起点 0 是轴起点、非内部切点
            cuts.append(start_seconds * 1000.0)
    return cuts


def _read_frame_bytes(path: Path) -> bytes:
    """读持久化关键帧 bytes 供 OCR；缺帧 / 读失败降级空 bytes（OCR 再降级空串）。"""
    try:
        return path.read_bytes()
    except OSError:
        return b""


class _DocumentDeletedError(Exception):
    """The document row vanished mid-pipeline (user deleted it) — abort quietly."""


class EmptyParseResultError(Exception):
    """The parser returned no text at all — indexing would otherwise walk to a
    ``ready`` document with zero chunks (silent data loss, 2026-09-04 实测：
    MinerU 对纯标题/超短页返回空 full.md), so the pipeline fails loudly with
    an actionable, retryable error instead."""


class _LLM(Protocol):
    async def ainvoke(self, messages: Any) -> Any: ...


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
        graph_store: GraphStore | None = None,
        wiki_store: WikiStore | None = None,
        video_shot_store: VideoShotStore | None = None,
        concurrency: int = 2,
        parse_fn: Callable[[str], Awaitable[ParsedDocument]] | None = None,
        embedder: _Embedder | None = None,
        llm: _LLM | None = None,
        main_llm: _LLM | None = None,
        gleaning_rounds: int = 1,
        resolution_full_scan_threshold: int = 500,
        entity_merge_similarity: float = 0.92,
        sweep_enabled: bool = True,
        sweep_interval_hours: float = 24.0,
        data_dir: str | Path | None = None,
        migration_running_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._store = store
        self._vector_store_held = vector_store
        self._graph_store = graph_store or GraphStore(store._sf)
        self._wiki_store = wiki_store or WikiStore(store._sf)
        self._video_store = video_shot_store or VideoShotStore(store._sf)
        self._parse_fn = parse_fn or parse_document
        self._embedder = embedder
        self._llm = llm
        self._main_llm = main_llm
        self._gleaning_rounds = gleaning_rounds
        self._resolution_full_scan_threshold = resolution_full_scan_threshold
        self._entity_merge_similarity = entity_merge_similarity
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
        self._wiki_tasks: set[asyncio.Task[None]] = set()
        self._wiki_busy: set[str] = set()
        #: kb_id → whether the coalesced run still owes the trigger threshold.
        #: AND-merge: one gate-free trigger (boot scan) makes the merged run
        #: gate-free, so a doc trigger claiming the runner first can never
        #: squeeze the boot intent out (it would re-gate the trailing run and
        #: the resume would silently fail on a below-threshold KB).
        self._wiki_pending: dict[str, bool] = {}

        #: D3=甲 在途合并（2026-10-04）：同一文档并发重复提交收敛为单次运行
        #: 加至多一次补跑（镜像 wiki runner 的 busy/pending 先例）。
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
        await self.scan_dirty_wikis()
        self._dispatcher = asyncio.create_task(self._dispatch_loop(), name="knowledge-index-worker")
        if self._sweep_enabled:
            self._sweep_task = asyncio.create_task(self._sweep_loop(), name="knowledge-orphan-sweep")

    async def scan_dirty_wikis(self) -> None:
        """Boot resume for wiki runs lost to a restart (spec 2026-10-02 Task 3).

        A dirty entry can outlive the process that flagged it (crash between
        the dirty hook and the generation run, or a run cut mid-flight) —
        unlike documents, there is no other resume path. Per D2 this leg skips
        the trigger threshold: the manual button's "有 dirty 就跑" stance, since
        a below-threshold KB would otherwise strand its dirty entries forever.
        Failure is log-only: a Qdrant/config outage must not block startup.
        """
        try:
            kb_ids = await self._wiki_store.list_kb_ids_with_dirty()
            if not kb_ids:
                return
            embedder = self._embedder or build_embedder()
            for kb_id in kb_ids:
                self._spawn_wiki(kb_id, embedder, require_threshold=False)
            logger.info("knowledge worker boot scan: resumed wiki generation for %d KB(s) with dirty entries", len(kb_ids))
        except Exception:
            logger.exception("wiki boot scan failed at worker start; dirty entries stay dirty until the next trigger")

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
        if self._wiki_tasks:
            await asyncio.gather(*list(self._wiki_tasks), return_exceptions=True)

    async def recover(self) -> int:
        """Re-enqueue every non-terminal document; returns the count."""
        documents = await self._store.list_non_terminal_documents()
        for document in documents:
            await self.submit(document["id"])
        return len(documents)

    async def submit(self, doc_id: str) -> None:
        await self._queue.put(doc_id)

    async def submit_recaption(self, doc_id: str) -> None:
        """入队一次子集腿 recaption 运行（spec 2026-09-08 §2 运维重跑入口）。

        故意不走 resume 队列：recaption 是对终态文档的显式运维重跑，``recover()``
        不得在重启时重触它——重启于 recaption 中途改由正常管线的 resume 路恢复
        （service 已把文档翻 ``parsing`` + 镜头重置 ``pending``，resume 恰好重跑
        这些镜头）。与索引共用并发信号量 + inflight 集（``wait_idle``/``stop`` 覆盖）。
        """
        task = asyncio.create_task(self._run_recaption_guarded(doc_id), name=f"kb-recaption-{doc_id}")
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _run_recaption_guarded(self, doc_id: str) -> None:
        document = await self._store.get_document(doc_id)
        kb_id = document["kb_id"] if document is not None else None
        if kb_id is not None:
            self._busy_kbs.add(kb_id)
        try:
            async with self._sem:
                await self.recaption_document(doc_id)
        finally:
            if kb_id is not None:
                self._busy_kbs.discard(kb_id)

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
        # The wiki leg is a tracked task outside the slot (D1): drain it here so
        # "wait_idle returned" still means every trigger has settled.
        while self._wiki_tasks:
            await asyncio.gather(*list(self._wiki_tasks), return_exceptions=True)
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
        """D3=乙 忙库闸输入：文档腿与 wiki 腿在飞时对外声明该库忙（spec 2026-10-04）。

        结构化维护而非“按文档行反推”：文档被删后行会消失，反推会把仍在收尾
        的运行误判成空闲。
        """
        return set(self._busy_kbs) | set(self._wiki_busy)

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
        await sweep_round(store=self._store, vector_store=self._vector_store, graph_store=self._graph_store, wiki_store=self._wiki_store, skip_kb_ids=busy)
        if self._data_dir is not None:
            await reconcile_files(data_dir=self._data_dir, store=self._store, skip_kb_ids=busy)
        await sweep_generations(vector_store=self._vector_store, declared_width=effective_dimension())

    def _spawn_wiki(self, kb_id: str, embedder: _Embedder, *, require_threshold: bool = True) -> None:
        """Fire the wiki leg outside the worker slot (spec 2026-10-02 D1).

        The document is ``ready`` at this point; a whole generation run must not
        eat a ``worker_concurrency`` slot for minutes. Tracked in ``_wiki_tasks``
        so ``wait_idle``/``stop`` still cover the run — the lifecycle contract is
        unchanged, only the slot is released earlier.

        ``require_threshold`` marks whether the merged run still owes the
        trigger threshold (boot scan passes False — see the dict comment in
        ``__init__`` for the AND-merge rule).
        """
        self._wiki_pending[kb_id] = self._wiki_pending.get(kb_id, True) and require_threshold
        if kb_id in self._wiki_busy:
            return
        # Create the runner before claiming: a failed create_task must not leave
        # a dead claim freezing the KB. Safe only while this function stays fully
        # synchronous — keep the claim check and the claim in one unbroken step.
        task = asyncio.create_task(self._wiki_runner(kb_id, embedder), name=f"kb-wiki-{kb_id}")
        self._wiki_busy.add(kb_id)
        self._wiki_tasks.add(task)
        task.add_done_callback(self._wiki_tasks.discard)

    async def _wiki_runner(self, kb_id: str, embedder: _Embedder) -> None:
        """One runner per KB (D2): drain coalesced triggers, never overlap runs.

        The busy/pending claim in ``_spawn_wiki`` is synchronous, so triggers
        landing while a run is live collapse into exactly one trailing run
        instead of overlapping LLM passes over the same entries. Each drained
        trigger carries its own threshold flag.
        """
        try:
            while kb_id in self._wiki_pending:
                require_threshold = self._wiki_pending.pop(kb_id)
                # Cross-path single-flight: while a manual run owns the KB
                # (trigger_wiki_generation refuses while one is live), wait it
                # out: the two must never overlap on the same entries.
                while wiki_generation_in_progress(kb_id):
                    await asyncio.sleep(0.5)
                await self._maybe_generate_wiki(kb_id, embedder, require_threshold=require_threshold)
        finally:
            self._wiki_busy.discard(kb_id)

    # ── pipeline ─────────────────────────────────────────────────────────

    async def process_document(self, doc_id: str) -> dict[str, Any] | None:
        """Run one document through the status machine; never raises."""
        document = await self._store.get_document(doc_id)
        if document is None or document["status"] in ("ready", "failed"):
            return document
        kb_id = document["kb_id"]
        is_video = _is_video_path(document["storage_path"])
        # P3 per-path sub-status (spec 2026-08-11 §5): initialized up front so the
        # hover breakdown exists from the parsing stage on (2026-08-12 UX fix) —
        # only pre-0012 legacy rows stay NULL and render no hover. Partial-merge
        # writes follow as each leg advances; the wiki leg is NOT tracked on the
        # row (library-level mirror injected at read time by the API). Video docs
        # extend the breakdown with the asr/segment/caption legs (spec 2026-09-08
        # §2); text docs never carry them (NULL-safe hover).
        legs: dict[str, str] = {"vector": "pending", "graph": "pending"}
        if is_video:
            legs = {"asr": "pending", "segment": "pending", "caption": "pending", "vector": "pending", "graph": "pending"}
        try:
            if document["status"] in ("uploaded", "parsing", "chunking"):
                if is_video:
                    await self._run_video_legs(doc_id, kb_id, document, legs)
                else:
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

            # Video docs spent 0–75% on the media legs (materialize); the shared
            # vector/graph window maps onto the remaining 25% so progress stays
            # monotonic (spec §2 腿权重). Text docs keep base=0/span=100 (unchanged).
            progress_base, progress_span = (_PROGRESS_AFTER_MATERIALIZE, 100 - _PROGRESS_AFTER_MATERIALIZE) if is_video else (0, 100)

            async def _on_progress(settled: int, total: int) -> None:
                percent = progress_base + ((settled * progress_span) // total if total else progress_span)
                await self._store.update_document_status(doc_id, "indexing", progress_percent=percent)

            legs["graph"] = "indexing"
            await self._store.update_document_status(doc_id, "indexing", path_status={"graph": "indexing"})
            await self._require_alive(doc_id)  # checkpoint: before the (slowest) graph leg
            # Chunk-level extraction concurrency is re-read per document (the
            # table.card_mode precedent), so a config edit applies without a restart.
            extract_concurrency = get_app_config().rag.extract_concurrency
            stats = await index_document_graph(
                self._store,
                self._graph_store,
                self._vector_store,
                kb_id=kb_id,
                doc_id=doc_id,
                chunks=chunks,
                llm=self._llm,
                embedder=embedder,
                gleaning_rounds=self._gleaning_rounds,
                name_similarity_threshold=self._entity_merge_similarity,
                progress_callback=_on_progress,
                concurrency=extract_concurrency,
            )
            # Checkpoint: the graph leg is the longest window for a delete to
            # land in. Entities written before this point CAN still reference a
            # since-deleted doc's chunks — that residual window is acknowledged
            # and covered by the phantom-contribution cleanup (plan Task 9).
            await self._require_alive(doc_id)
            # Same verdict source as the ``graph degraded`` error sub-marker.
            legs["graph"] = "degraded" if stats.degraded else "done"
            await self._store.update_document_status(doc_id, "indexing", path_status={"graph": legs["graph"]})
            if stats.degraded:
                # The marker moved here with the append path (spec 2026-09-23 D8/R8): the
                # indexer used to overwrite ``error``, which erased a degraded caption pass.
                await self._append_error_marker(
                    doc_id,
                    f"{_GRAPH_MARKER_PREFIX} {len(stats.failed_chunk_ids)}/{stats.total} chunks failed extraction",
                    replace_prefix=_GRAPH_MARKER_PREFIX,
                )
            # D3: merge cross-slice entity aliases right after the graph leg.
            # A failing resolution never blocks the pipeline — the document
            # still reaches ``ready`` with a visible error sub-marker.
            try:
                await resolve_entity_aliases(
                    self._store,
                    self._graph_store,
                    self._vector_store,
                    self._wiki_store,
                    embedder,
                    kb_id=kb_id,
                    touched_entities=stats.touched_entities,
                    full_scan_threshold=self._resolution_full_scan_threshold,
                    similarity_threshold=self._entity_merge_similarity,
                )
            except Exception:
                logger.exception("entity re-resolution failed for document %s", doc_id)
                await self._append_error_marker(doc_id, "entity-resolution failed")
            # Task 5b (spec §3.5 2026-08-12 revision): flag the wiki entries of
            # the entities this document touched as ``dirty`` so the following
            # incremental refresh regenerates exactly them. Library-level
            # concern: a failure degrades to a log line only — never blocks
            # ``ready``, never appends an error sub-marker.
            try:
                await mark_dirty_for_entities(self._wiki_store, kb_id, stats.touched_entities)
            except Exception:
                logger.exception("wiki dirty marking failed for kb %s", kb_id)
            if legs["vector"] == "done":
                await self._stamp_library_identity(doc_id, kb_id, embedder)
                await self._store.update_document_status(doc_id, "ready", progress_percent=100)
                self._spawn_wiki(kb_id, embedder)
            else:
                # 索引不完整/无可索引内容 ⇒ 文档 failed（RFC §5.2 表行 4）；wiki 不启动。
                # 标记追加式刷新（replace 同族）——不遮蔽既有 caption/graph 子标记。
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

    async def _wipe_doc_chunks(self, doc_id: str, kb_id: str) -> None:
        """Drop a document's chunks + their vector/graph residue (idempotent).

        Shared by the text re-parse and the video re-materialize: both rebuild
        chunks from scratch, so stale points/entities and phantom chunk
        contributions must go first (chunk ids are deterministic — a rebuild
        would otherwise upsert over half-cleaned residue).
        """
        existing = await self._store.list_chunks(doc_id, limit=1_000_000)
        if not existing:
            return
        chunk_ids = [chunk["chunk_id"] for chunk in existing]
        orphaned, _affected = await self._graph_store.remove_chunk_contributions(kb_id, chunk_ids)
        if orphaned:
            await self._vector_store.delete_entities(kb_id, orphaned)
        await self._vector_store.delete_by_doc(doc_id)
        await self._store.delete_chunks_by_doc(doc_id)

    async def _reparse_and_chunk(self, doc_id: str, kb_id: str, storage_path: str) -> None:
        """Parse → caption → chunk, wiping any partial output first (idempotent)."""
        await self._wipe_doc_chunks(doc_id, kb_id)

        # A new pass re-decides the caption leg, so the previous verdict and its counted
        # marker go before the parse: the wipe above drops chunks and their residue but not
        # ``documents.error``, and the status write below merges per key — neither residue
        # clears itself (spec 2026-09-23 D8/R21 ①).
        await self._clear_error_markers(doc_id, _CAPTION_MARKER_PREFIX)
        await self._store.update_document_status(doc_id, "parsing", path_status={"vector": "pending", "graph": "pending", "caption": None})
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

    # ── video legs (spec 2026-09-08 §2) ──────────────────────────────────

    async def _run_video_legs(self, doc_id: str, kb_id: str, document: dict[str, Any], legs: dict[str, str]) -> None:
        """视频腿序：probe → asr → segment → keyframe+ocr → persist 骨架 → caption →
        materialize（spec §2）。materialize 写 video_shots + 镜头卡 chunks 后，镜头卡即
        普通 chunk，落入 process_document 现有 vector/graph/wiki 腿（零改动）。

        resume（spec §2 caption_status 状态机，对齐 chunks.extract_status 先例）：
        video_shots 骨架已在（上次崩溃于 caption 腿或之后）→ 跳过 probe/asr/segment/
        keyframe（帧已落盘、三路原文已在骨架），只对 pending 镜头重跑 caption，再
        materialize 重建全量镜头卡。骨架 payload 不写 caption_status，遵守 upsert
        「absent keys persist」——已 done 的镜头不被隐式重置（Task 2 冻结契约）。
        """
        storage_path = document["storage_path"]
        video_name = document["name"]
        doc_dir = Path(storage_path).parent
        rag_cfg = get_app_config().rag
        cfg = rag_cfg.video

        if await self._video_store.list_shots(doc_id):
            # resume：probe/asr/segment/keyframe 的产物已固化在骨架，不重跑；标
            # asr/segment done，只补 pending 镜头的 caption 再 materialize。
            legs["asr"] = "done"
            legs["segment"] = "done"
            await self._store.update_document_status(doc_id, "parsing", path_status=legs)
            await self._video_caption_leg(doc_id, kb_id, storage_path, legs)
            await self._video_materialize(doc_id, kb_id, video_name, cfg)
            return

        await self._store.update_document_status(doc_id, "parsing", path_status=legs)

        # ── probe（硬失败腿：不可解码 → 抛出，文档 failed，对齐 EmptyParseResultError）──
        probe = await probe_video(storage_path)
        duration_ms = probe.duration_ms

        # ── asr（降级腿：整腿失败 → asr=failed，口述段写「（ASR 失败）」，文档仍 ready）──
        await self._store.update_document_status(doc_id, "parsing", path_status={"asr": "indexing"})
        asr_failed = False
        # D6：服务档只吃 ≤5 分钟（同步 + base64），更长的整段留在本地腿（一期不投递）。
        asr_leg = resolve_leg_provider(cfg.asr_provider, duration_ms=duration_ms)
        if asr_leg != cfg.asr_provider:
            logger.info("video ASR: %s is a service tier and the audio is %.1f min long ⇒ staying on the local leg (%s, D6)", cfg.asr_provider, duration_ms / 60000, asr_leg)
        if not (cfg.asr_model or "").strip():
            # A-1 (spec 2026-09-30 D1): no default model name any more. Raised outside the try on
            # purpose — the `except AsrError` below degrades a *failure*, a missing declaration is a
            # configuration error and must reach the caller loudly.
            raise RagConfigurationError(bilingual("视频 ASR 需要 rag.video.asr_model（没有默认值，请在 rag.video 段声明）", "Video ASR requires rag.video.asr_model (no default; declare it in the rag.video section)"))
        try:
            segments = await transcribe_video(
                storage_path,
                provider_name=asr_leg,
                model=cfg.asr_model,
                duration_ms=duration_ms,
                base_url=rag_cfg.asr_base_url,
                api_key=rag_cfg.asr_api_key,
            )
        except AsrError as exc:
            logger.warning("video ASR leg failed for document %s (%s); degrading asr=failed", doc_id, exc)
            segments = []
            asr_failed = True
        legs["asr"] = "failed" if asr_failed else "done"
        await self._store.update_document_status(doc_id, "parsing", path_status={"asr": legs["asr"]}, progress_percent=_PROGRESS_AFTER_ASR)

        # ── segment（降级腿：检测器失败 → 等距回退窗，segment=degraded）──
        await self._store.update_document_status(doc_id, "parsing", path_status={"segment": "indexing"})
        shots = await self._video_segment_leg(doc_id, storage_path, duration_ms, cfg, legs)
        await self._store.update_document_status(doc_id, "parsing", path_status={"segment": legs["segment"]}, progress_percent=_PROGRESS_AFTER_SEGMENT)
        if not shots:
            raise EmptyParseResultError("视频切分产出零镜头：场景检测与等距回退窗均未产出有效区间（时长可能非正），无法入库")
        await self._require_alive(doc_id)  # checkpoint: after the long media legs, before any write

        # ── keyframe + ocr（单镜头降级：缺帧 → 无 frame_url、屏幕文字空）──
        keyframes = await extract_keyframes(storage_path, shots, str(doc_dir))
        ocr_texts = await self._video_ocr_leg(doc_dir, keyframes)
        missing = sum(1 for rel in keyframes.values() if rel is None)
        if shots and missing / len(shots) > _KEYFRAME_DEGRADE_THRESHOLD:
            await self._append_error_marker(doc_id, "keyframe degraded")

        # ── asr 投影到镜头桶（spec §3 时间轴对齐：最大重叠占比归桶）──
        asr_by_shot = {index: _ASR_FAILED for index in range(len(shots))} if asr_failed else assign_transcript_to_shots(segments, shots)

        # ── persist video_shots 骨架（caption_status 缺省 pending；不写该键以遵守
        #    upsert「absent keys persist」，resume/recaption 的 done 不被重置）──
        skeleton = [
            {
                "shot_index": index,
                "start_ms": start,
                "end_ms": end,
                "keyframe_path": keyframes.get(index),
                "asr_text": asr_by_shot.get(index, ""),
                "ocr_text": ocr_texts.get(index, ""),
            }
            for index, (start, end) in enumerate(shots)
        ]
        await self._video_store.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=skeleton)

        # ── caption（降级腿：>30% 失败 → caption=degraded）──
        await self._video_caption_leg(doc_id, kb_id, storage_path, legs)

        # ── materialize（组装冻结卡正文 → 镜头卡 chunks）──
        await self._video_materialize(doc_id, kb_id, video_name, cfg)

    async def _video_segment_leg(self, doc_id: str, storage_path: str, duration_ms: int, cfg: Any, legs: dict[str, str]) -> list[tuple[int, int]]:
        """场景检测 → 镜头区间；检测器整腿失败降级等距回退窗（segment=degraded，spec §2）。

        PySceneDetect 的 blocking 解码经 ``run_file_io`` 落线程池（blocking-io-guard 纪律）。
        """
        max_shot_ms = int(cfg.max_shot_seconds * 1000)
        try:
            cuts = await run_file_io(_detect_scene_cuts, storage_path)
            shots = merge_scene_bounds(cuts, duration_ms, max_shot_ms)
            if not shots:
                raise ValueError("场景检测产出空镜头序列")
            legs["segment"] = "done"
            return shots
        except Exception as exc:  # 检测器缺失/解码失败/空产出统一降级
            logger.warning("video segment leg failed for document %s (%s); falling back to uniform windows", doc_id, exc)
            legs["segment"] = "degraded"
            return fallback_windows(duration_ms, int(cfg.fallback_window_seconds * 1000))

    async def _video_ocr_leg(self, doc_dir: Path, keyframes: dict[int, str | None]) -> dict[int, str]:
        """读每镜头持久化中帧 bytes → 屏幕文字（走 `rag.vlm_model`，spec 2026-09-30）。

        缺帧镜头留空串、**不计失败**；整腿失败率 >30% 时打一条 warning——本腿没有自己的
        `path_status` 状态（屏幕文字是可选增强，空即「（无）」），所以信号只有日志。
        """
        frames: dict[int, list[bytes]] = {}
        texts: dict[int, str] = {}
        for index, rel in keyframes.items():
            if rel is None:
                texts[index] = ""
                continue
            frames[index] = [await run_file_io(_read_frame_bytes, doc_dir / rel)]
        if frames:
            outcome = await screen_text_shots(frames)
            texts.update(outcome.captions)
            if outcome.degraded:
                logger.warning("视频屏幕文字腿失败率过高（%d/%d 帧）；本片屏幕文字按空处理", outcome.failed, len(frames))
        return texts

    async def _video_caption_leg(self, doc_id: str, kb_id: str, storage_path: str, legs: dict[str, str]) -> None:
        """对 caption_status=pending 的镜头抽 ≤3 临时帧 → VLM caption → 回填 caption +
        状态（done/failed）。done/failed/empty 镜头不重跑（resume 只跑 pending，spec §2）；
        ``empty`` 由 materialize 依三路全空判定，此处不越权。"""
        legs["caption"] = "indexing"
        await self._store.update_document_status(doc_id, "parsing", path_status={"caption": "indexing"})
        pending = await self._video_store.list_pending_shots(doc_id)
        if pending:
            shot_frames: dict[int, list[bytes]] = {}
            for shot in pending:
                frames = await extract_caption_frames(storage_path, int(shot["start_ms"]), int(shot["end_ms"]), count=_CAPTION_FRAMES)
                shot_frames[int(shot["shot_index"])] = frames
            outcome = await caption_shots(shot_frames)
            legs["caption"] = "degraded" if outcome.degraded else "done"
            updates = [{"shot_index": index, "caption": caption, "caption_status": "done" if caption.strip() else "failed"} for index, caption in outcome.captions.items()]
            if updates:
                await self._video_store.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=updates)
        else:
            legs["caption"] = "done"  # 无 pending（resume 全 done）→ caption 腿视为完成
        await self._store.update_document_status(doc_id, "parsing", path_status={"caption": legs["caption"]}, progress_percent=_PROGRESS_AFTER_CAPTION)

    async def _video_materialize(self, doc_id: str, kb_id: str, video_name: str, cfg: Any) -> None:
        """读 video_shots 全量 → 组装冻结卡正文（不含时间码头，spec §3 嵌入文本契约）→
        幂等 wipe 旧 chunks + insert 镜头卡 chunks；三路全空镜头标 caption_status=empty
        不产 chunk（计数可视，spec §2）。materialize 后镜头卡即普通 chunk，落入现有腿。"""
        shots = await self._video_store.list_shots(doc_id)
        mode = cfg.card_text_mode
        chunk_rows: list[dict[str, Any]] = []
        empty_updates: list[dict[str, Any]] = []
        for shot in shots:
            index = int(shot["shot_index"])
            caption = shot.get("caption") or ""
            asr_text = shot.get("asr_text") or ""
            ocr_text = shot.get("ocr_text") or ""
            if is_empty_card(caption=caption, asr_text=asr_text, ocr_text=ocr_text):
                empty_updates.append({"shot_index": index, "caption_status": "empty"})
                continue
            body = assemble_card_body(caption=caption, asr_text=asr_text, ocr_text=ocr_text, mode=mode)
            chunk_rows.append(
                {
                    "chunk_id": chunk_id_for_shot(doc_id, index),
                    "doc_id": doc_id,
                    "kb_id": kb_id,
                    "chunk_index": index,
                    "text": body,
                    "heading_path": heading_path_for_shot(video_name, index),
                    "page": None,
                    "token_count": count_tokens(body),
                }
            )
        await self._require_alive(doc_id)  # checkpoint: before writing chunks (delete race)
        await self._wipe_doc_chunks(doc_id, kb_id)  # 幂等：resume 重建前清 vector/graph 残留
        if chunk_rows:
            await self._store.insert_chunks(chunk_rows)
        if empty_updates:
            await self._video_store.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=empty_updates)
        await self._store.update_document_status(doc_id, "indexing", chunk_count=len(chunk_rows), progress_percent=_PROGRESS_AFTER_MATERIALIZE)

    # ── recaption 子集腿（spec 2026-09-08 §2 运维重跑入口，plan Task 8b）───────

    async def recaption_document(self, doc_id: str) -> dict[str, Any] | None:
        """caption 模型/prompt 升级的子集腿重跑（spec §2 运维重跑入口）。

        跳过 probe/asr/segment/keyframe——三路原文与持久化关键帧已在 ``video_shots``。
        只对 service 重置为 pending 的镜头重跑 caption，原地重组卡正文（不 wipe），
        **仅文本变更的 chunk** 增量重嵌，受影响实体标 wiki dirty（图谱不重抽）。
        终态恢复 ready；任何失败降级为 ready + 可见 error marker（旧 caption 内容
        仍可达，recaption 是增强非破坏）。
        """
        document = await self._store.get_document(doc_id)
        if document is None or not _is_video_path(document["storage_path"]):
            return None
        kb_id = document["kb_id"]
        cfg = get_app_config().rag.video
        legs: dict[str, str] = {"caption": "pending"}
        try:
            await self._require_alive(doc_id)
            await self._video_caption_leg(doc_id, kb_id, document["storage_path"], legs)
            await self._require_alive(doc_id)  # checkpoint: caption 腿后、写 chunk 前
            await self._video_recaption_materialize(doc_id, kb_id, document["name"], cfg)
            chunk_count = await self._store.count_chunks(doc_id)
            await self._store.update_document_status(doc_id, "ready", progress_percent=100, chunk_count=chunk_count, path_status={"caption": legs["caption"]})
        except _DocumentDeletedError:
            logger.info("document %s deleted mid-recaption; aborted quietly", doc_id)
            return None
        except Exception as exc:
            logger.exception("recaption failed for document %s", doc_id)
            chunk_count = await self._store.count_chunks(doc_id)
            # This pass's verdict lands explicitly: without it the leg's own "indexing" would
            # be what the row keeps, and the admin would read a run that never finished
            # (spec 2026-09-23 D10.5; ready only means the *old* content is still usable).
            await self._store.update_document_status(doc_id, "ready", progress_percent=100, chunk_count=chunk_count, path_status={"caption": "failed"})
            await self._append_error_marker(doc_id, f"recaption failed: {str(exc)[:200]}")
        return await self._store.get_document(doc_id)

    async def _video_recaption_materialize(self, doc_id: str, kb_id: str, video_name: str, cfg: Any) -> None:
        """recaption 后的原地重组：仅变更 chunk 增量重嵌 + 受影响实体标 wiki dirty。

        与 ``_video_materialize``（首次入库的全量 wipe + 重建）不同：此处绝不删图谱
        贡献、绝不重嵌未变更 chunk——caption 升级只动卡正文真正变化的镜头（spec §2
        运维重跑入口：变更 chunk 增量重嵌）。实体列原样保留（图谱腿不重跑），其 wiki
        条目标 dirty 等下次增量刷新吃进新措辞。镜头转为全空（caption-only 镜头重跑
        回空）时退役其卡（对齐单 chunk 删除级联）。
        """
        shots = await self._video_store.list_shots(doc_id)
        mode = cfg.card_text_mode
        existing = {chunk["chunk_id"]: chunk for chunk in await self._store.list_chunks(doc_id, limit=1_000_000)}
        changed: list[dict[str, Any]] = []
        affected_entities: set[str] = set()
        empty_updates: list[dict[str, Any]] = []
        for shot in shots:
            index = int(shot["shot_index"])
            caption = shot.get("caption") or ""
            asr_text = shot.get("asr_text") or ""
            ocr_text = shot.get("ocr_text") or ""
            chunk_id = chunk_id_for_shot(doc_id, index)
            old = existing.get(chunk_id)
            if is_empty_card(caption=caption, asr_text=asr_text, ocr_text=ocr_text):
                empty_updates.append({"shot_index": index, "caption_status": "empty"})
                if old is not None:
                    await self._retire_chunk(kb_id, chunk_id)
                continue
            body = assemble_card_body(caption=caption, asr_text=asr_text, ocr_text=ocr_text, mode=mode)
            if old is not None and old["text"] == body:
                continue  # 正文未变 → 不重嵌（spec §2 增量）
            token_count = count_tokens(body)
            if old is not None:
                await self._store.update_chunk_text(chunk_id, body, token_count)
                entities = list(old.get("entities") or [])
                heading_path = list(old.get("heading_path") or [])
            else:
                heading_path = heading_path_for_shot(video_name, index)
                entities = []
                await self._store.insert_chunks([{"chunk_id": chunk_id, "doc_id": doc_id, "kb_id": kb_id, "chunk_index": index, "text": body, "heading_path": heading_path, "page": None, "token_count": token_count}])
            affected_entities.update(entities)
            changed.append({"chunk_id": chunk_id, "doc_id": doc_id, "kb_id": kb_id, "chunk_index": index, "text": body, "heading_path": heading_path, "page": None, "token_count": token_count, "entities": entities})

        await self._require_alive(doc_id)  # checkpoint: before re-embedding
        if changed:
            embedder = self._embedder or build_embedder()
            # 复用 vector 腿：分批嵌入 + upsert（同 chunk_id → 同点覆盖），保留实体 payload。
            await index_chunks(self._store, self._vector_store, embedder, kb_id=kb_id, doc_id=doc_id, chunks=changed)
        if empty_updates:
            await self._video_store.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=empty_updates)
        if affected_entities:
            await mark_dirty_for_entities(self._wiki_store, kb_id, affected_entities)

    async def _retire_chunk(self, kb_id: str, chunk_id: str) -> None:
        """退役转为全空的镜头卡（caption-only 镜头重跑回空的边界）：对齐单 chunk
        删除级联——图谱贡献 → 孤儿实体向量 → chunk 向量点 → 业务行。"""
        orphaned, _affected = await self._graph_store.remove_chunk_contributions(kb_id, [chunk_id])
        if orphaned:
            await self._vector_store.delete_entities(kb_id, orphaned)
        await self._vector_store.delete_chunks([chunk_id])
        await self._store.delete_chunk(chunk_id)

    async def _maybe_generate_wiki(self, kb_id: str, embedder: _Embedder, *, require_threshold: bool = True) -> None:
        """Triggered batch on first completion, dirty incremental afterwards.

        The model is resolved **per trigger** (spec 2026-09-26 D3): the boot-time instance was
        retired, so a settings change applies without a restart. ``main_llm`` stays as a
        construction-time injection port for tests — production callers must not pass it, since
        it short-circuits the resolution below.

        ``require_threshold=False`` (boot scan only, D2) skips the completion-share
        gate — see ``scan_dirty_wikis`` for why that leg must.
        """
        try:
            if require_threshold and not await wiki_trigger_ready(self._store, kb_id):
                return
            existing = await self._wiki_store.list_entries(kb_id)
            from deerflow.config.app_config import get_app_config
            from deerflow.knowledge.model_target import create_rag_chat_model, require_usable_rag_target

            config = get_app_config()
            llm = self._main_llm or create_rag_chat_model(require_usable_rag_target(config, config.rag.wiki_model, role="百科生成"), thinking=bool(config.rag.wiki_thinking), app_config=config)
            await generate_wiki(
                self._store,
                self._graph_store,
                self._wiki_store,
                self._vector_store,
                kb_id=kb_id,
                llm=llm,
                embedder=embedder,
                only_dirty=bool(existing),
            )
        except Exception:
            logger.exception("wiki generation trigger failed for kb %s", kb_id)
