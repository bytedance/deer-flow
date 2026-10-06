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
import re
import shutil
import time
import uuid
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anyio
import numpy as np

from deerflow.knowledge.embed_identity import identity_diff_fields, identity_from_rag
from deerflow.knowledge.embed_texts import manual_card_embed_text
from deerflow.knowledge.embedder_factory import build_embedder
from deerflow.knowledge.eval import anchor_check, question_bank, synthesis
from deerflow.knowledge.eval.metrics import DEFAULT_FAIL_THRESHOLD
from deerflow.knowledge.eval.ondemand import EvalQuestionBankEmpty, cancel_eval_run, eval_run_in_progress, get_eval_progress, run_full_eval_for_kb, run_layer1_for_kb
from deerflow.knowledge.eval.persistence import ENV_CI, STATUS_COMPLETED
from deerflow.knowledge.eval.synthesis import SynthesisDocNotReady
from deerflow.knowledge.eval.trend import TREND_WINDOW_DAYS, build_run_points, build_sparks, latest_layer_row
from deerflow.knowledge.graph.communities import assign_communities, summarize_communities
from deerflow.knowledge.graph.indexer import extract_single_chunk
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.models import EvalRunRow
from deerflow.knowledge.parser import TABLE_UPLOAD_SUFFIXES, VIDEO_UPLOAD_SUFFIXES, is_supported_suffix, supported_upload_suffixes, table_upload_limit_bytes, video_upload_limit_bytes
from deerflow.knowledge.projection.cache import CachedProjection, ProjectionCache, content_fingerprint
from deerflow.knowledge.projection.fetcher import fetch_projection_vectors
from deerflow.knowledge.projection.reducer import pca_reduce, umap_reduce
from deerflow.knowledge.reindex import reindex_in_progress, reindex_kb, reindex_last_run_status, reindex_progress
from deerflow.knowledge.reranker_factory import build_reranker
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import refreshed_store
from deerflow.knowledge.video.store import VideoShotStore
from deerflow.knowledge.wiki.generator import generate_wiki, regenerate_wiki_entries, wiki_generation_in_progress, wiki_last_run_status
from deerflow.knowledge.wiki.store import WikiStore
from deerflow.tools.builtins.graph_search_tool import _graph_search_impl
from deerflow.tools.builtins.hybrid_search_tool import _hybrid_search_impl
from deerflow.tools.builtins.wiki_search_tool import _wiki_search_impl
from deerflow.uploads.manager import normalize_filename
from deerflow.utils.file_io import run_file_io
from deerflow.utils.time import coerce_iso

#: 历史列表单页上限（spec 2026-08-27 §6.1）——超出直接 clamp，不报错。
MAX_EVAL_RUNS_LIMIT = 200

logger = logging.getLogger(__name__)


class DocumentProcessingError(RuntimeError):
    """Raised when a per-chunk operation collides with an in-flight document pipeline (Phase-3 Batch-1 P3)."""

    def __init__(self, doc_id: str, status: str) -> None:
        super().__init__(f"Document {doc_id} is being processed (status={status})")
        self.doc_id = doc_id
        self.status = status


class NotVideoDocumentError(RuntimeError):
    """Raised when a video-only operation targets a non-video document (spec 2026-09-08 §2 recaption → router 404)."""

    def __init__(self, doc_id: str) -> None:
        super().__init__(f"Document {doc_id} is not a video document")
        self.doc_id = doc_id


class ProjectionNotComputedError(RuntimeError):
    """POST vector-projection/query arrived before any projection was cached."""


class ProjectionModelUnavailableError(RuntimeError):
    """The cached projection has no transform-capable model (umap, spec §4)."""


def _projection_response(kb_id: str, algo: str, dims: int, entry: CachedProjection) -> dict[str, Any]:
    """Assemble the GET response: cached entry → JSON-ready point list.

    Coordinate columns are zipped with the fetched point metadata (row i ↔
    points[i], the fetcher's alignment contract); ``z`` only appears for
    ``dims=3``; optional fields stay absent rather than null.
    """
    coords = np.asarray(entry.coords)
    points: list[dict[str, Any]] = []
    for index, point in enumerate(entry.points):
        item: dict[str, Any] = {
            "id": point.id,
            "source_type": point.source_type,
            "x": float(coords[index][0]),
            "y": float(coords[index][1]),
            "label": point.label,
            "color_key": point.color_key,
            "preview": point.preview,
        }
        if dims == 3:
            item["z"] = float(coords[index][2])
        if point.heading_path:
            item["heading_path"] = list(point.heading_path)
        if point.entity_type is not None:
            item["entity_type"] = point.entity_type
        points.append(item)
    return {
        "kb_id": kb_id,
        "algo": algo,
        "dims": dims,
        "model_version": entry.model.model_version if entry.model is not None else ("umap-v1" if algo == "umap" else "pca-v1"),
        "fingerprint": entry.fingerprint,
        "cached": entry.cached,
        "computed_ms": entry.computed_ms,
        "total_points": entry.total_points,
        "shown_points": len(entry.points),
        "sampled": entry.sampled,
        "points": points,
    }


def _as_utc(value: datetime) -> datetime:
    """SQLite 读出的 DateTime(timezone=True) 是 tz-naive——按单一时钟纪律（§3.1.1）视为 UTC。"""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _layer1_overview_payload(row: EvalRunRow | None) -> dict[str, Any] | None:
    """latest 端点的 Layer 1 块（§3.2）；baseline_diff 仅在该次运行带了 --baseline 时出现。"""
    if row is None:
        return None
    payload: dict[str, Any] = {
        "run_id": row.id,
        "created_at": coerce_iso(row.created_at),
        "metrics": row.layer1_metrics,
    }
    if row.baseline_diff is not None:
        payload["baseline_diff"] = row.baseline_diff
    return payload


def _question_results_payload(rows: Sequence[EvalRunRow]) -> list[dict[str, Any]]:
    """逐题最近一次被测结果（2026-09-07）：跨 run 倒序合并。

    scoped run 的 questions 数组只含本次子集——bank 列若只取 latest run，
    其它题的结果会被「覆盖」成缺失（用户实测：跑别的题后已出数的题消失）。
    故倒序遍历 completed 非 ci 行，每题取首次（即最近）遇到的 slim 记录，
    列语义 = 「该题最近一次被测结果」，与 run 级 latest 解耦。
    """

    latest: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: (r.created_at, r.id), reverse=True):
        if row.status != STATUS_COMPLETED or row.environment == ENV_CI:
            continue
        for question in (row.layer1_metrics or {}).get("questions") or []:
            question_id = question.get("id")
            if not question_id or question_id in latest:
                continue
            latest[question_id] = {
                "id": question_id,
                "recall": question.get("recall"),
                "hit": question.get("hit"),
                "path_correct": question.get("path_correct"),
                "actual_path": question.get("actual_path"),
                "run_id": row.id,
                "created_at": coerce_iso(row.created_at),
            }
    return list(latest.values())


def _layer2_overview_payload(row: EvalRunRow | None) -> dict[str, Any] | None:
    """latest 端点的 Layer 2 块（§3.2）：ragas/arch_specific 等从 layer2_metrics JSON 拆出。"""
    if row is None:
        return None
    metrics = row.layer2_metrics
    payload: dict[str, Any] = {
        "run_id": row.id,
        "created_at": coerce_iso(row.created_at),
        "ragas_available": bool(metrics.get("ragas_available")),
        "ragas": metrics.get("ragas") or {},
        "arch_specific": metrics.get("arch_specific") or {},
        # 路由命中率（真实对话链路选路口径）：存储键 path_accuracy 顶层直取，
        # 展示面键名 routing_hit_rate 与 L1 同名键解耦（总览瓦片数据源）。
        "routing_hit_rate": metrics.get("path_accuracy"),
        "has_graph_questions": bool(metrics.get("has_graph_questions")),
    }
    if metrics.get("ragas_skip_reason"):
        payload["ragas_skip_reason"] = metrics["ragas_skip_reason"]
    if row.langfuse_trace_url:
        payload["langfuse_trace_url"] = row.langfuse_trace_url
    return payload


def _normalized_supplement(value: str | None) -> str | None:
    """空白串与 ``None`` 同义：都表示「这里没有方向」（spec 2026-09-12）。

    保存时的"方向是否变了"用归一后的值比较，否则一次「清空但留了空格」的保存
    会把无方向当成有方向、白跑一次重写。
    """
    text = (value or "").strip()
    return text or None


def has_degraded_leg(document: dict[str, Any]) -> bool:
    """任一腿处于 ``degraded``（RFC §5.2 D1=甲：caption/graph/视频腿统一）——
    降级文档（ready + 标记）可整篇重试；wiki 键为库级读时注入、不参与判定。"""
    return any(state == "degraded" for state in (document.get("path_status") or {}).values())


class KnowledgeService:
    """Coordinates stores + worker for the knowledge-base endpoints."""

    def __init__(
        self,
        *,
        store: KnowledgeStore,
        vector_store: Any,
        graph_store: GraphStore | None = None,
        wiki_store: WikiStore | None = None,
        video_shot_store: VideoShotStore | None = None,
        worker: Any = None,
        data_dir: str | Path,
        wiki_generate_fn: Callable[[str, bool], None] | None = None,
        wiki_regenerate_fn: Callable[[str, list[str]], None] | None = None,
        eval_trigger_fn: Callable[..., None] | None = None,
        synthesis_trigger_fn: Callable[..., None] | None = None,
        reindex_fn: Callable[[str], None] | None = None,
        projection_cache: ProjectionCache | None = None,
    ) -> None:
        self.store = store
        self._vector_store_held = vector_store
        self.graph_store = graph_store or GraphStore(store._sf)
        self.wiki_store = wiki_store or WikiStore(store._sf)
        self.video_shot_store = video_shot_store or VideoShotStore(store._sf)
        self.worker = worker
        self.data_dir = Path(data_dir)
        self.wiki_generate_fn = wiki_generate_fn or self._schedule_wiki_generation
        self.wiki_regenerate_fn = wiki_regenerate_fn or self._schedule_wiki_regeneration
        self.eval_trigger_fn = eval_trigger_fn or self._schedule_eval_run
        self.synthesis_trigger_fn = synthesis_trigger_fn or self._schedule_question_synthesis
        self.reindex_fn = reindex_fn or self._schedule_reindex
        self.projection_cache = projection_cache or ProjectionCache()
        self._wiki_tasks: set[asyncio.Task[None]] = set()
        self._eval_tasks: set[asyncio.Task[None]] = set()
        self._synthesis_tasks: set[asyncio.Task[None]] = set()
        self._reindex_tasks: set[asyncio.Task[None]] = set()

    @property
    def vector_store(self) -> Any:
        """取值口自检（spec 2026-10-05 D1）：配置声明（url/宽度）变了就换新实例。"""
        self._vector_store_held = refreshed_store(self._vector_store_held)
        return self._vector_store_held

    # ── documents ────────────────────────────────────────────────────────

    async def list_documents(self, kb_id: str) -> list[dict[str, Any]]:
        """Documents with the per-path sub-status (phase-2 batch-1 P3, spec §5).

        The stored ``path_status`` carries vector/graph only; the wiki leg is a
        **library-level mirror** injected here at assembly time. The mirror
        only applies to terminal documents (ready/failed): a document still in
        the indexing pipeline has not been digested by the wiki leg at all, so
        its wiki line reports ``pending`` instead of mirroring the library's
        stale ``ready`` (2026-08-13 口径——否则新文档在索引期间会错误显示旧内容
        的「已生成」). Rows whose stored path_status is NULL (legacy) stay NULL
        so the frontend renders no hover for them.
        """
        documents = await self.store.list_documents(kb_id)
        wiki_status = await self._wiki_path_status(kb_id)
        for document in documents:
            path_status = document.get("path_status")
            if path_status is not None:
                wiki = wiki_status if document["status"] in ("ready", "failed") else "pending"
                document["path_status"] = {**path_status, "wiki": wiki}
            await self._inject_video_summary(document)
        return documents

    async def _inject_video_summary(self, document: dict[str, Any]) -> None:
        """视频文档列表行补 ``duration_ms`` + ``shot_count``（spec 2026-09-08 §5 读时
        聚合，**不加列**）。判据 = ``storage_path`` 后缀 ∈ 冻结视频集（与 worker
        分支同源）；文本文档、或视频文档在 materialize 之前（``video_shots`` 尚未
        物化）都不注入这两键——payload 对旧渲染零回归，前端诚实缺省。
        """
        if not self._is_video_document(document):
            return
        shots = await self.video_shot_store.list_shots(document["id"])
        if not shots:
            return
        document["duration_ms"] = max(int(shot["end_ms"]) for shot in shots)
        document["shot_count"] = len(shots)

    @staticmethod
    def _is_video_document(document: dict[str, Any]) -> bool:
        """文档是否视频（``storage_path`` 后缀 ∈ 冻结视频集）——与 worker 分支同源判据。"""
        return Path(document["storage_path"]).suffix.lower() in VIDEO_UPLOAD_SUFFIXES

    async def resolve_shot_frame(self, *, kb_id: str, doc_id: str, shot_index: int) -> Path | None:
        """镜头持久化关键帧的绝对路径；缺则 ``None``（router → 404，spec §4）。

        ``None`` 覆盖全部降级面：文档不属于该 kb / 非视频文档（无 ``video_shots``）/
        镜头不存在 / 镜头缺帧（keyframe_path NULL）/ ``keyframe_path`` 越出 doc 目录
        （防御，对齐 ``files`` 路由的穿越守卫）/ 磁盘帧已丢失。鉴权由 router 的
        ``_require_kb_access`` 承载（与文档读取同源），此处不重复门禁。
        """
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return None
        shots = await self.video_shot_store.list_shots(doc_id)
        shot = next((row for row in shots if int(row["shot_index"]) == shot_index), None)
        if shot is None or not shot.get("keyframe_path"):
            return None
        doc_dir = Path(document["storage_path"]).parent.resolve()
        target = (doc_dir / shot["keyframe_path"]).resolve()
        if not target.is_relative_to(doc_dir) or not target.is_file():
            return None
        return target

    async def resolve_video_stream(self, *, kb_id: str, doc_id: str) -> Path | None:
        """源视频文件绝对路径；不可流则 ``None``（router → 404，spec 2026-09-08 §4/§5）。

        ``None`` 覆盖：文档不属于该 kb / 非视频文档（后缀 ∉ VIDEO_UPLOAD_SUFFIXES，
        复用 ``_is_video_document``）/ 文件缺失或非常规文件。Range 协商
        （200/206/416/400）由 Starlette ``FileResponse`` 原生承担，此处只定位 + 校验；
        鉴权由 router 的 ``_require_kb_access`` 承载（与文档读取同源）。
        """
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return None
        if not self._is_video_document(document):
            return None
        target = Path(document["storage_path"])
        if not target.is_file():
            return None
        return target

    async def resolve_source_document(self, *, kb_id: str, doc_id: str) -> Path | None:
        """原始上传文件绝对路径（2026-09-10 下载回环）；不可服务则 ``None``（router → 404）。

        与 ``resolve_video_stream`` 不同：不看后缀——任何文档的源都可下载（上传时
        字节已固化在 ``storage_path``）。``None`` 覆盖：文档不属于该 kb / 文件缺失
        或非常规文件。鉴权由 router 的 ``_require_kb_access`` 承载（与文档读取同源）；
        路由不接受用户路径段，只服务行内记录的路径，穿越结构性不可能。
        """
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return None
        target = Path(document["storage_path"])
        if not target.is_file():
            return None
        return target

    async def list_document_chunks(self, *, kb_id: str, doc_id: str, offset: int, limit: int) -> dict[str, Any]:
        """文档切片分页（切片抽屉数据源，spec 2026-09-08 §5）：在 store 行之上为
        视频镜头 chunk 补时间码四字段 + ``frame_url``——复用 recall-test 同款
        ``_inject_video_citations``（按 chunk_id 扁平序 ``{doc_id}#{shot_index:04d}``
        join ``video_shots``）；文本 chunk 字段一字不动（前端旧渲染零回归）。
        正文 ``text`` 不含时间码头（spec §3 嵌入文本契约），时间码由展示层合成。
        """
        items = await self.store.list_chunks(doc_id, offset=offset, limit=limit)
        total = await self.store.count_chunks(doc_id)
        await self._inject_video_citations(kb_id, items)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    async def _wiki_path_status(self, kb_id: str) -> str:
        """Library-level wiki status (shared by all documents of the KB).

        An in-flight run (manual button or worker auto trigger) reports
        ``generating`` — checked FIRST, otherwise the state could only ever
        appear on an empty library's very first generation and every later
        incremental digest would be invisible (2026-08-13 口径调整).
        Otherwise ready/dirty entries mean generated content is available
        (dirty = generated-but-stale still counts as ready, 2026-08-12 口径);
        nothing at all reports ``pending``.
        """
        if wiki_generation_in_progress(kb_id):
            return "generating"
        entries = await self.wiki_store.list_entries(kb_id)
        if any(entry["status"] in ("ready", "dirty") for entry in entries):
            return "ready"
        return "pending"

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

        # 视频体积门（spec 2026-09-08 §7）：超 rag.video.max_size_mb 的视频
        # 门口即拒，不白跑 probe/ASR 预算。
        if suffix in VIDEO_UPLOAD_SUFFIXES:
            limit = video_upload_limit_bytes()
            if limit is not None and len(content) > limit:
                raise ValueError(f"video file too large: {len(content)} bytes exceeds the {limit // (1024 * 1024)} MB limit (rag.video.max_size_mb)")

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
        """Delete one document across vector/graph/wiki/business stores."""
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return False
        chunks = await self.store.list_chunks(doc_id, limit=1_000_000)
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        try:
            await self.vector_store.delete_by_doc(doc_id)
        except Exception:
            logger.exception("qdrant delete_by_doc failed for %s; continuing business-row cleanup", doc_id)
        orphaned, affected = await self.graph_store.remove_chunk_contributions(kb_id, chunk_ids)
        if orphaned:
            try:
                await self.vector_store.delete_entities(kb_id, orphaned)
            except Exception:
                logger.exception("qdrant delete_entities failed for %s orphans", doc_id)
        # 条目生命周期（spec §3.5：资格即条目存在理由，失格即删）：剩余
        # freq ≥ 2 的受影响实体仅标 dirty 等增量重生成；跌下阈值的失格实体
        # 与消失实体（孤儿）的条目连行带向量一并删除。实体节点与
        # kb_entities 不动 —— 剩余活切片仍由向量路直接服务。
        disqualified = list(orphaned)
        if affected:
            remaining = {row["name"]: len(row.get("source_chunk_ids") or []) for row in await self.graph_store.list_entities(kb_id)}
            still_eligible = [name for name in affected if remaining.get(name, 0) >= 2]
            if still_eligible:
                await self.wiki_store.mark_dirty_for_titles(kb_id, still_eligible)
            disqualified.extend(name for name in affected if remaining.get(name, 0) < 2)
        if disqualified:
            await self._delete_wiki_entries(kb_id, disqualified)
        await self.store.delete_document(doc_id)
        await self._remove_dir(self.data_dir / "knowledge" / kb_id / doc_id)
        return True

    async def _delete_wiki_entries(self, kb_id: str, titles: Collection[str]) -> None:
        """Delete wiki entries whose entity lost eligibility or vanished.

        Qdrant first, failures logged and swallowed (the module-level cascade
        ordering rule); the business row always goes so a vector outage never
        strands the lifecycle half-applied. Idempotent.
        """
        titles = list(titles)
        if not titles:
            return
        try:
            await self.vector_store.delete_wiki_entries(kb_id, titles)
        except Exception:
            logger.exception("qdrant delete_wiki_entries failed for kb %s (%d titles)", kb_id, len(titles))
        await self.wiki_store.delete_entries(kb_id, titles)

    async def retry_document(self, *, kb_id: str, doc_id: str) -> dict[str, Any] | None:
        """Wipe a failed or degraded document's derived state and re-enqueue indexing."""
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return None
        chunks = await self.store.list_chunks(doc_id, limit=1_000_000)
        chunk_ids = [chunk["chunk_id"] for chunk in chunks]
        if chunk_ids:
            try:
                await self.vector_store.delete_by_doc(doc_id)
            except Exception:
                logger.exception("qdrant delete_by_doc failed during retry of %s", doc_id)
            orphaned, affected = await self.graph_store.remove_chunk_contributions(kb_id, chunk_ids)
            if orphaned:
                try:
                    await self.vector_store.delete_entities(kb_id, orphaned)
                except Exception:
                    logger.exception("qdrant delete_entities failed during retry of %s", doc_id)
            if affected:
                # Retry re-indexes the same document right away, so plain
                # dirty suffices — no eligibility cascade on this path.
                await self.wiki_store.mark_dirty_for_titles(kb_id, affected)
            await self.store.delete_chunks_by_doc(doc_id)
        reset = await self.store.reset_document_for_retry(doc_id)
        shots = await self.video_shot_store.list_shots(doc_id)
        requeue = [{"shot_index": int(shot["shot_index"]), "caption_status": "pending"} for shot in shots if shot.get("caption_status") in ("failed", "empty")]
        if requeue:
            # 视频重试走 resume 路（骨架已在），只补跑 pending 镜头 ⇒ 无图说的镜头
            # 必须在这里翻回 pending 才会补跑（RFC §5.2 L162「覆盖原先未成功的
            # 图片说明」，2026-10-04 验收补口）：failed=尝试过但空；empty=三路俱空
            # 但 caption 同样缺失——VLM 故障恢复后本可补出（静默视频否则永远停在
            # 零切片失败）。done 保持：重刷已有图说是 recaption 的职责。
            await self.video_shot_store.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=requeue)
        if self.worker is not None:
            await self.worker.submit(doc_id)
        return reset

    async def trigger_recaption(self, *, kb_id: str, doc_id: str) -> dict[str, Any] | None:
        """Recaption 运维重跑入口（spec 2026-09-08 §2，plan Task 8b）。

        caption 模型/prompt 升级后的血统入口（类比 ``re_extract_chunk`` /
        ``regenerate_wiki_entries``）：把 ``video_shots.caption_status`` 重置
        （done/failed → pending，empty 保持——三路俱空的镜头重跑无意义）→ 翻文档
        状态标记在飞 → 入队 worker 子集腿（只重跑 caption + materialize + 仅变更
        chunk 增量重嵌 + wiki dirty，帧/ASR/segment 跳过）。

        Returns ``None`` when the document is missing / cross-kb (router → 404);
        raises :class:`NotVideoDocumentError` for a text document (router → 404)
        and :class:`DocumentProcessingError` while the pipeline is in flight
        (router → 409).
        """
        document = await self.store.get_document(doc_id)
        if document is None or document["kb_id"] != kb_id:
            return None
        if not self._is_video_document(document):
            raise NotVideoDocumentError(doc_id)
        if document["status"] not in ("ready", "failed"):
            raise DocumentProcessingError(doc_id, document["status"])
        shots = await self.video_shot_store.list_shots(doc_id)
        reset = [{"shot_index": int(shot["shot_index"]), "caption_status": "pending"} for shot in shots if shot.get("caption_status") in ("done", "failed")]
        if reset:
            # upsert「present keys overwrite / absent keys persist」→ 只翻
            # caption_status，三路原文/关键帧/区间保持（Task 2 冻结契约）。
            await self.video_shot_store.bulk_upsert_shots(doc_id, kb_id=kb_id, shots=reset)
        # 同步翻状态标记在飞（镜像 retry 的 status flip）：二次触发 / retry 据此 409；
        # 置 parsing → 若 gateway 在 worker 接手前重启，recover() 走 resume 路重新
        # caption 这些 pending 镜头（正确恢复）。caption 腿置 pending 可见排队。
        await self.store.update_document_status(doc_id, "parsing", path_status={"caption": "pending"})
        if self.worker is not None:
            await self.worker.submit_recaption(doc_id)
        return {"status": "enqueued", "reset_shots": len(reset)}

    # ── knowledge base ───────────────────────────────────────────────────

    async def delete_kb_cascade(self, *, kb_id: str) -> bool:
        """Delete the whole KB: three Qdrant collections + all business rows."""
        try:
            await self.vector_store.delete_by_kb(kb_id)
        except Exception:
            logger.exception("qdrant delete_by_kb failed for %s; continuing business-row cleanup", kb_id)
        deleted = await self.store.delete_kb(kb_id)
        if deleted:
            await self._remove_dir(self.data_dir / "knowledge" / kb_id)
        return deleted

    # ── wiki ─────────────────────────────────────────────────────────────

    def trigger_wiki_generation(self, kb_id: str, *, only_dirty: bool = True) -> bool:
        """Fire-and-forget wiki generation (Task 14: incremental by default;
        ``only_dirty=False`` rebuilds every eligible entry).

        Returns False when a run is already in flight — manual or worker
        auto, both share the in-flight counter — so the router reports
        ``already_running`` instead of queueing a duplicate LLM run
        (P1 触发幂等, 2026-08-14).
        """
        if wiki_generation_in_progress(kb_id):
            return False
        self.wiki_generate_fn(kb_id, only_dirty)
        return True

    def trigger_wiki_regeneration(self, kb_id: str, entry_ids: list[str]) -> bool:
        """Fire-and-forget per-entry regeneration (局部更新/重建).

        Shares the in-flight counter with the library-level runs, so a
        regeneration is skipped while any generate run is draining (and vice
        versa) — the router reports ``already_running`` instead of queueing an
        overlapping LLM run on the same KB.
        """
        if not entry_ids:
            return False
        if wiki_generation_in_progress(kb_id):
            return False
        self.wiki_regenerate_fn(kb_id, entry_ids)
        return True

    async def list_wiki_entries(self, kb_id: str) -> dict[str, Any]:
        """Summary-only listing for the wiki tab (phase-2 batch-1).

        Full content stays out of the list payload — the drawer fetches it via
        the detail endpoint. ``summary`` is a plain content prefix.

        Wiki 更新状态可见 (2026-08-14): the payload also carries the
        library-level ``generation`` flag (same in-flight source as
        ``path_status.wiki``) so the wiki tab itself can render 更新中 and
        poll until the run drains — previously the badge only refreshed on
        tab re-entry.
        """
        entries = await self.wiki_store.list_entries(kb_id)
        return {
            "entries": [
                {
                    "id": entry["id"],
                    "title": entry["title"],
                    "summary": entry["content"][:120],
                    "status": entry["status"],
                    "updated_at": entry["updated_at"],
                }
                for entry in entries
            ],
            "generation": "generating" if wiki_generation_in_progress(kb_id) else "idle",
            # P1 失败可见性: terminal status of the most recent run (None =
            # never ran in this process) — the completion toast keys off it.
            "last_run": wiki_last_run_status(kb_id),
        }

    async def get_wiki_entry(self, *, kb_id: str, entry_id: str) -> dict[str, Any] | None:
        """Full entry for the drawer; None when missing or owned by another kb."""
        entry = await self.wiki_store.get_entry(entry_id)
        if entry is None or entry["kb_id"] != kb_id:
            return None
        return entry

    async def delete_wiki_entry(self, *, kb_id: str, entry_id: str) -> bool:
        """Manually delete one wiki entry: business row + vector point (Task 13).

        The entity node and its ``kb_entities`` vector stay untouched.
        Regeneration semantics (2026-08-13 拍板): if the entity is still
        eligible, the next ``generate_wiki`` backfill recreates the entry
        from current material — a manual delete is a *reset* for eligible
        entries and permanent only for disqualified/vanished ones.
        """
        entry = await self.wiki_store.get_entry(entry_id)
        if entry is None or entry["kb_id"] != kb_id:
            return False
        await self._delete_wiki_entries(kb_id, [entry["title"]])
        return True

    async def update_wiki_entry(
        self,
        *,
        kb_id: str,
        entry_id: str,
        content: str,
        supplement_content: str | None,
    ) -> dict | None:
        """Update wiki entry content and supplement layer (Phase-3 Batch-1 P1).

        Main content can be replaced by next LLM re-generation. The supplement
        layer persists across regeneration cycles **and steers them** (spec
        2026-09-12): a changed direction queues one per-entry rewrite right away,
        falling back to a ``dirty`` mark when a library-level run holds the
        in-flight lock — so a saved direction is never silently lost.
        """
        # Verify entry exists and belongs to this kb
        entry = await self.wiki_store.get_entry(entry_id)
        if entry is None or entry["kb_id"] != kb_id:
            return None

        direction_changed = _normalized_supplement(supplement_content) != _normalized_supplement(entry.get("supplement_content"))

        # Update via store (title comes from existing entry)
        updated = await self.wiki_store.upsert_entry(
            kb_id=kb_id,
            title=entry["title"],
            content=content,
            source_chunk_ids=entry["source_chunk_ids"],
            status=entry["status"],
            supplement_content=supplement_content,
        )
        # Queue strictly AFTER the write: the rewrite task reads the stored
        # supplement, so triggering first would hand it the previous direction.
        # Only a direction change qualifies — queueing on a main-content edit
        # would let the user's own save overwrite the edit they just made.
        if direction_changed and not self.trigger_wiki_regeneration(kb_id, [entry_id]):
            await self.wiki_store.mark_dirty_for_titles(kb_id, [entry["title"]])
        return updated

    async def update_chunk_text(self, *, kb_id: str, chunk_id: str, text: str) -> dict | None:
        """Update chunk text with re-embedding (Phase-3 Batch-1 P2).

        Recalculates token_count, writes last_edited_at, and re-embeds into
        Qdrant — same chunk_id maps to the same point id, so the upsert
        overwrites the stale vector in place (Task 4 收尾, 2026-08-14).
        Entities JSON column remains unchanged (ID 引用 preserved).

        Ordering: embed BEFORE the DB write so an embedder outage leaves the
        stored text untouched; a Qdrant upsert failure after the write
        surfaces as 500 — visible, and a retry converges (no silent
        DB/vector divergence).
        """
        # Get existing chunk to verify it exists and belongs to kb
        chunk = await self.store.get_chunk(chunk_id)
        if chunk is None or chunk["kb_id"] != kb_id:
            return None

        # Recalculate token count
        from deerflow.knowledge.chunker import count_tokens

        new_token_count = count_tokens(text)

        # Re-embed first (see docstring for the ordering rationale).

        embeddings = await build_embedder().embed([text])

        # Update in DB (entities unchanged - ID 引用 preserved)
        updated = await self.store.update_chunk_text(
            chunk_id=chunk_id,
            text=text,
            token_count=new_token_count,
        )
        if updated is None:
            return None

        from deerflow.knowledge.vector_store import ChunkUpsert

        document = await self.store.get_document(chunk["doc_id"])
        await self.vector_store.upsert_chunks(
            [
                ChunkUpsert(
                    chunk_id=chunk_id,
                    kb_id=kb_id,
                    doc_id=chunk["doc_id"],
                    dense=embeddings[0].dense,
                    sparse=embeddings[0].sparse,
                    doc_name=document["name"] if document else "",
                    heading_path=list(chunk.get("heading_path") or []),
                    page=chunk.get("page"),
                    entities=list(chunk.get("entities") or []),
                )
            ]
        )

        return updated

    async def preview_chunk_deletion(self, *, kb_id: str, chunk_ids: list[str]) -> dict[str, Any] | None:
        """Calculate deletion impact without actually deleting (Phase-3 Batch-1 P5).

        Returns orphaned entities, affected entities, and relation deletions
        for preview in delete confirmation dialog.
        """
        if not chunk_ids:
            return {"orphaned_entities": [], "affected_entities": [], "relation_deletions": []}

        # Verify all chunks exist and belong to this kb
        for chunk_id in chunk_ids:
            chunk = await self.store.get_chunk(chunk_id)
            if chunk is None or chunk["kb_id"] != kb_id:
                return None  # Any invalid chunk → 404

        # Call graph store's pure calculation
        impact = await self.graph_store.calculate_deletion_impact(kb_id, chunk_ids)
        return impact

    async def delete_chunk_cascade(self, *, kb_id: str, chunk_id: str) -> bool | None:
        """Delete one chunk across graph/wiki/vector/business stores (Task 5 收尾).

        Reuses the same cascade pieces as ``re_extract_chunk`` /
        ``delete_document_cascade`` — nothing rewritten: strip graph
        contributions → orphan entities lose ``kb_entities`` vectors + wiki
        entries → affected entities re-checked against the ≥2-source bar
        (dirty vs disqualify) → chunk vector point → business row, then the
        document's chunk_count is refreshed. Vector failures are logged and
        swallowed (module cascade ordering rule); the business row always goes.

        Same concurrency guard as re-extraction: only terminal document
        states (ready/failed) may lose a chunk.
        """
        chunk = await self.store.get_chunk(chunk_id)
        if chunk is None or chunk["kb_id"] != kb_id:
            return None
        document = await self.store.get_document(chunk["doc_id"])
        if document is not None and document["status"] not in ("ready", "failed"):
            raise DocumentProcessingError(chunk["doc_id"], document["status"])

        orphaned, affected = await self.graph_store.remove_chunk_contributions(kb_id, [chunk_id])
        if orphaned:
            try:
                await self.vector_store.delete_entities(kb_id, orphaned)
            except Exception:
                logger.exception("qdrant delete_entities failed for chunk-delete orphans of %s", chunk_id)
            await self._delete_wiki_entries(kb_id, orphaned)
        if affected:
            remaining = {row["name"]: len(row.get("source_chunk_ids") or []) for row in await self.graph_store.list_entities(kb_id)}
            still_eligible = [name for name in affected if remaining.get(name, 0) >= 2]
            disqualified = [name for name in affected if remaining.get(name, 0) < 2]
            if still_eligible:
                await self.wiki_store.mark_dirty_for_titles(kb_id, still_eligible)
            if disqualified:
                await self._delete_wiki_entries(kb_id, disqualified)

        try:
            await self.vector_store.delete_chunks([chunk_id])
        except Exception:
            logger.exception("qdrant delete_chunks failed for %s", chunk_id)
        deleted = await self.store.delete_chunk(chunk_id)
        if deleted and document is not None:
            remaining_chunks = await self.store.list_chunks(chunk["doc_id"], limit=1_000_000)
            await self.store.update_document_status(chunk["doc_id"], document["status"], chunk_count=len(remaining_chunks))
        return deleted

    async def re_extract_chunk(self, *, kb_id: str, chunk_id: str) -> dict[str, Any] | None:
        """Re-extract entities/relations for a single chunk (Phase-3 Batch-1 P3, Spec §5).

        Five-step flow (reuses existing cascade pieces — nothing rewritten):
        1. ``remove_chunk_contributions`` strips this chunk's old graph contributions.
        2. Orphaned entities → delete ``kb_entities`` vectors + wiki disqualification chain.
        3. Per-chunk extraction on the chunk's CURRENT text (never re-parses the
           source file — manual edits would be clobbered, spec §1 fact 3).
        4. Reverse link: normalized names onto the ``kb_chunks`` Qdrant payload.
        5. Still-eligible affected ∪ new entities → wiki dirty chain (资格制 ≥2 sources).

        Concurrency guard (spec §5 A3): only terminal document states (ready/failed)
        may trigger a re-extraction.
        """
        chunk = await self.store.get_chunk(chunk_id)
        if chunk is None or chunk["kb_id"] != kb_id:
            return None

        document = await self.store.get_document(chunk["doc_id"])
        if document is not None and document["status"] not in ("ready", "failed"):
            raise DocumentProcessingError(chunk["doc_id"], document["status"])

        # Step 1: strip old graph contributions for this chunk only
        orphaned, affected = await self.graph_store.remove_chunk_contributions(kb_id, [chunk_id])

        # Mark extraction as pending (for cross-session progress tracking)
        await self.store.update_chunk_extract(chunk_id, "pending")

        # Step 2: orphaned entities lose their vectors + wiki entries (失格链)
        if orphaned:
            try:
                await self.vector_store.delete_entities(kb_id, orphaned)
            except Exception:
                logger.exception("qdrant delete_entities failed for re-extract orphans of %s", chunk_id)
            await self._delete_wiki_entries(kb_id, orphaned)

        # Step 3: re-extract on the current (possibly manually edited) text

        embedder = build_embedder()
        new_names = await extract_single_chunk(
            self.store,
            self.graph_store,
            kb_id=kb_id,
            chunk_id=chunk_id,
            text=chunk["text"],
            embedder=embedder,
        )

        # Step 4: reverse link — normalized names onto the kb_chunks payload
        if new_names:
            try:
                await self.vector_store.set_chunk_entities({chunk_id: new_names})
            except Exception:
                logger.exception("qdrant set_chunk_entities failed for %s", chunk_id)
            # Re-embed the touched entity name+description into kb_entities so
            # graph_search keeps matching them (same as the document leg).
            try:
                rows = await self.graph_store.list_entities(kb_id)
                targets = [row for row in rows if row["name"] in set(new_names)]
                if targets:
                    from deerflow.knowledge.vector_store import EntityUpsert

                    embeddings = await embedder.embed([f"{row['name']}\n{row.get('description') or ''}" for row in targets])
                    await self.vector_store.upsert_entities(
                        [
                            EntityUpsert(
                                name=row["name"],
                                kb_id=kb_id,
                                type=row.get("type") or "",
                                description=row.get("description") or "",
                                dense=embedding.dense,
                            )
                            for row, embedding in zip(targets, embeddings, strict=True)
                        ]
                    )
            except Exception:
                logger.exception("qdrant upsert_entities failed during re-extract of %s", chunk_id)

        # Step 5: wiki dirty chain — affected entities keep eligibility only
        # with ≥2 remaining sources (资格制, mirrors delete_document_cascade);
        # new entities join the dirty set so incremental wiki picks them up.
        if affected:
            remaining = {row["name"]: len(row.get("source_chunk_ids") or []) for row in await self.graph_store.list_entities(kb_id)}
            still_eligible = [name for name in affected if remaining.get(name, 0) >= 2]
            disqualified = [name for name in affected if remaining.get(name, 0) < 2]
            if disqualified:
                await self._delete_wiki_entries(kb_id, disqualified)
        else:
            still_eligible = []
        dirty_titles = sorted(set(still_eligible) | set(new_names))
        if dirty_titles:
            await self.wiki_store.mark_dirty_for_titles(kb_id, dirty_titles)

        return await self.store.get_chunk(chunk_id)

    # ── manual knowledge cards (Phase-3 Batch-1 P6, spec §8) ─────────────

    async def create_manual_card(
        self,
        *,
        kb_id: str,
        owner_id: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        include_in_wiki_search: bool = False,
    ) -> dict[str, Any]:
        """Create a manual knowledge card.

        Cards with the wiki-search toggle on are embedded and upserted into
        ``kb_manual_cards`` so the Task-8 wiki-path merge can retrieve them.
        Ordering (2026-08-16 fix): embed → upsert → DB insert. An upsert
        failure surfaces as 500 with NO row left behind (retry = recreate, no
        stuck flag-on vectorless card); a DB failure after the upsert leaves
        an orphan point, which the wiki-path hydration simply skips (the row
        lookup returns None).
        """
        embedding = None
        if include_in_wiki_search:
            embedding = (await build_embedder().embed([manual_card_embed_text(title, content)]))[0]

        card_id = uuid.uuid4().hex
        if embedding is not None:
            from deerflow.knowledge.vector_store import ManualCardUpsert

            await self.vector_store.upsert_manual_cards([ManualCardUpsert(card_id=card_id, kb_id=kb_id, title=title, dense=embedding.dense, updated_at=time.time())])
        return await self.store.create_manual_card(
            card_id=card_id,
            kb_id=kb_id,
            owner_id=owner_id,
            title=title,
            content=content,
            tags=tags,
            include_in_wiki_search=include_in_wiki_search,
        )

    async def list_manual_cards(
        self,
        *,
        kb_id: str,
        offset: int = 0,
        limit: int = 50,
        include_in_wiki_search: bool | None = None,
    ) -> dict[str, Any]:
        """Summary-only listing (wiki-list pattern): full content stays out of
        the list payload — the panel fetches it via the detail endpoint."""
        items = await self.store.list_manual_cards(kb_id, offset=offset, limit=limit, include_in_wiki_search=include_in_wiki_search)
        total = await self.store.count_manual_cards(kb_id, include_in_wiki_search=include_in_wiki_search)
        return {
            "items": [
                {
                    "id": card["id"],
                    "title": card["title"],
                    "summary": card["content"][:120],
                    "tags": card["tags"],
                    "include_in_wiki_search": card["include_in_wiki_search"],
                    "created_at": card["created_at"],
                    "updated_at": card["updated_at"],
                }
                for card in items
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    async def get_manual_card(self, *, kb_id: str, card_id: str) -> dict[str, Any] | None:
        """Full card for the editor; None when missing or owned by another kb."""
        card = await self.store.get_manual_card(card_id)
        if card is None or card["kb_id"] != kb_id:
            return None
        return card

    async def update_manual_card(
        self,
        *,
        kb_id: str,
        card_id: str,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        include_in_wiki_search: bool | None = None,
    ) -> dict[str, Any] | None:
        """PATCH a card; the toggle drives the vector-point lifecycle.

        - toggle on / title+content edit while on → re-embed + upsert
          (same point id, overwrite in place);
        - toggle off → the point goes (the card stays management-only);
        - flag off and no flag change → zero vector work.
        """
        card = await self.store.get_manual_card(card_id)
        if card is None or card["kb_id"] != kb_id:
            return None

        effective_flag = include_in_wiki_search if include_in_wiki_search is not None else card["include_in_wiki_search"]
        effective_title = title if title is not None else card["title"]
        effective_content = content if content is not None else card["content"]
        turning_off = include_in_wiki_search is False and card["include_in_wiki_search"]
        text_changed = (title is not None and title != card["title"]) or (content is not None and content != card["content"])
        # 显式传 on 时总是重 embed+upsert（同点幂等覆盖）——既覆盖 turning_on
        # 与文本变更，也让历史「on 但无向量点」的残留卡片在下一次显式 on 时自愈。
        needs_vector = effective_flag and (include_in_wiki_search is True or text_changed)

        # Ordering (2026-08-16 fix): embed → upsert → DB write. An upsert
        # failure surfaces as 500 with the flag UNCHANGED in the DB — retrying
        # the same toggle converges. (The old DB-first order stranded cards:
        # flag on, no point, and re-PATCHing on never re-upserted.)
        embedding = None
        if needs_vector:
            embedding = (await build_embedder().embed([manual_card_embed_text(effective_title, effective_content)]))[0]

        if embedding is not None:
            from deerflow.knowledge.vector_store import ManualCardUpsert

            await self.vector_store.upsert_manual_cards([ManualCardUpsert(card_id=card_id, kb_id=kb_id, title=effective_title, dense=embedding.dense, updated_at=time.time())])

        updated = await self.store.update_manual_card(
            card_id,
            title=title,
            content=content,
            tags=tags,
            include_in_wiki_search=include_in_wiki_search,
        )
        if updated is None:
            return None

        if turning_off:
            try:
                await self.vector_store.delete_manual_cards([card_id])
            except Exception:
                logger.exception("qdrant delete_manual_cards failed for toggle-off of %s", card_id)
        return updated

    async def delete_manual_card(self, *, kb_id: str, card_id: str) -> bool:
        """Delete one card: vector point first (failures logged + swallowed,
        module cascade rule), the business row always goes."""
        card = await self.store.get_manual_card(card_id)
        if card is None or card["kb_id"] != kb_id:
            return False
        try:
            await self.vector_store.delete_manual_cards([card_id])
        except Exception:
            logger.exception("qdrant delete_manual_cards failed for %s; continuing row cleanup", card_id)
        return await self.store.delete_manual_card(card_id)

    # ── recall test (P1, phase-2 batch-1) ────────────────────────────────

    @staticmethod
    def _recall_score_types(rag: Any, graph_source: str | None) -> dict[str, str]:
        """召回面板徽标（spec 2026-09-24 §4.2，D2 乙）：渲染这一跑实际参与打分的那个东西。

        vector 恒为配置的重排模型（该路每次必过重排；重排降级时分数为 null、徽标
        不变）；graph 以 impl 回报的尺子为准，缺键（老 stub / 未升级调用方）才按
        配置兜底；wiki 恒余弦。分数语义逐路不同——跨路永不可比，标签只说明
        「这些数字是什么」。
        """
        rerank_label = f"{rag.rerank_model} relevance" if rag.rerank_model else "rerank relevance"
        source = graph_source if graph_source is not None else ("rerank" if rag.graph_rerank else "cosine")
        return {"vector": rerank_label, "graph": rerank_label if source == "rerank" else "embedding cosine", "wiki": "embedding cosine"}

    async def recall_test(self, *, kb_id: str, user_id: str, query: str, top_k: int) -> dict[str, Any]:
        """Fan one query out to the three retrieval paths (spec P1).

        Reuses the online tools' ``_*_impl`` verbatim — the only difference
        from the agent path is that no LLM answer synthesis happens and raw
        hits/scores/elapsed are returned. A single path's failure degrades to
        empty hits with a failure note instead of failing the whole response.
        """
        from deerflow.config.app_config import get_app_config

        rag = get_app_config().rag
        runtime = SimpleNamespace(context={"kb_id": kb_id, "user_id": user_id})

        async def _timed(coro) -> tuple[Any, int]:
            start = time.monotonic()
            try:
                return await coro, int((time.monotonic() - start) * 1000)
            except Exception as exc:  # degradation is the contract — one path must not sink the response
                logger.exception("recall-test path failed for kb %s", kb_id)
                return exc, int((time.monotonic() - start) * 1000)

        (vector_raw, vector_ms), (graph_raw, graph_ms), (wiki_raw, wiki_ms) = await asyncio.gather(
            _timed(_hybrid_search_impl(query, runtime, store=self.store, vector_store=self.vector_store, top_k=top_k)),
            _timed(
                _graph_search_impl(
                    query,
                    runtime,
                    store=self.store,
                    graph_store=self.graph_store,
                    vector_store=self.vector_store,
                    # mirror the online wrapper's config-driven parameters;
                    # the recall test's top_k maps to evidence_limit
                    reranker=build_reranker() if rag.graph_rerank else None,
                    per_entity_cap=rag.graph_per_entity_cap,
                    per_edge_cap=rag.graph_per_edge_cap,
                    hop0_guarantee=rag.graph_hop0_guarantee,
                    evidence_limit=top_k,
                    graph_rerank=rag.graph_rerank,
                    rerank_threshold=rag.graph_rerank_threshold,
                    hop_penalty=rag.graph_hop_penalty,
                    neighbor_min_score=rag.graph_neighbor_min_score,
                    max_expanded_nodes=rag.graph_max_expanded_nodes,
                    hub_degree_threshold=rag.graph_hub_degree_threshold,
                )
            ),
            _timed(_wiki_search_impl(query, runtime, store=self.store, wiki_store=self.wiki_store, vector_store=self.vector_store, top_k=top_k)),
        )

        def _failure_note(exc: BaseException) -> str:
            return f"该路检索失败（{type(exc).__name__}），详情见服务端日志。"

        # Impl messages carry a model-directed citation-span note（引用编号…
        # 照抄 citation_no）— prompt plumbing for the answering model. The
        # recall-test UI shows messages to humans, so strip the note here.
        span_note = re.compile(r"（引用编号 [^）]*）")

        def _user_facing(message: str) -> str:
            return span_note.sub("", message)

        if isinstance(vector_raw, BaseException):
            vector_path: dict[str, Any] = {"hits": [], "message": _failure_note(vector_raw)}
        else:
            vector_path = {
                "hits": [
                    {
                        "chunk_id": item["chunk_id"],
                        "doc_name": item.get("doc_name") or "",
                        "text": item.get("text", ""),
                        "heading_path": item.get("heading_path") or [],
                        "page": item.get("page"),
                        # rerank 降级时 impl 不返回 score 键 → 显式 null（schema 可空）
                        "score": item.get("score"),
                        "rank": rank,
                    }
                    for rank, item in enumerate(vector_raw.get("results", []), start=1)
                ],
                "message": _user_facing(vector_raw.get("message", "")),
            }

        if isinstance(graph_raw, BaseException):
            graph_path: dict[str, Any] = {"entities": [], "relations": [], "evidence": [], "message": _failure_note(graph_raw)}
        else:
            graph_path = {
                "entities": graph_raw.get("entities", []),
                "relations": graph_raw.get("relations", []),
                "evidence": graph_raw.get("evidence", []),
                "message": _user_facing(graph_raw.get("message", "")),
            }

        if isinstance(wiki_raw, BaseException):
            wiki_path: dict[str, Any] = {"hits": [], "message": _failure_note(wiki_raw)}
        else:
            entries = wiki_raw.get("entries", [])

            async def _source_chunks(entry: dict) -> list[str] | None:
                # 百科锚定通道（spec 2026-08-28 §5）：词条带源切片供前端勾选锚定，
                # 与 runner.wiki_fn 的 get_entry 读取同源；人工卡片无切片映射 → None（不注入）。
                # wiki_store 由构造器保证非 None（`wiki_store or WikiStore(...)`）。
                if (entry.get("source_type") or "wiki") != "wiki":
                    return None
                stored = await self.wiki_store.get_entry(entry["entry_id"])
                return list((stored or {}).get("source_chunk_ids") or [])

            chunks_by_entry = await asyncio.gather(*(_source_chunks(entry) for entry in entries))

            wiki_hits: list[dict[str, Any]] = []
            for rank, (entry, chunks) in enumerate(zip(entries, chunks_by_entry), start=1):
                hit = {
                    "entry_id": entry["entry_id"],
                    "title": entry["title"],
                    "summary": (entry.get("content") or "")[:120],
                    "score": entry.get("score"),
                    "rank": rank,
                    # Phase-3 P6（spec §8 混排）：人工卡片也走 wiki 路，
                    # 透传 source_type 供前端分流「条目抽屉 / 卡片抽屉」；
                    # 缺键回退 wiki（旧 impl 形态）。
                    "source_type": entry.get("source_type") or "wiki",
                }
                if chunks is not None:
                    hit["source_chunk_ids"] = chunks
                wiki_hits.append(hit)
            wiki_path = {
                "hits": wiki_hits,
                "message": _user_facing(wiki_raw.get("message", "")),
            }

        # 切片文档内序号（2026-09-05）：命中行标题名后挂 chunk_position =
        # 该切片在文档存活切片中的位次（与切片总览抽屉 #K 同源）——同名
        # 文档的不同切片一眼可辨。解析/查询逻辑已提至 _chunk_position_map
        # （与 POST /chunk-positions 端点共用单一源）。
        async def _inject_chunk_positions(hits: list[dict[str, Any]]) -> None:
            positions = await self._chunk_position_map(str(hit.get("chunk_id") or "") for hit in hits)
            for hit in hits:
                position = positions.get(str(hit.get("chunk_id") or ""))
                if position is not None:
                    hit["chunk_position"] = position

        await _inject_chunk_positions(vector_path["hits"])
        await _inject_chunk_positions(graph_path["evidence"])
        # 视频镜头引用 join（spec 2026-09-08 §4）：chunk 级引用行（vector hits +
        # graph evidence）补时间码四字段 + frame_url；wiki 命中是条目级，不 join。
        await self._inject_video_citations(kb_id, vector_path["hits"])
        await self._inject_video_citations(kb_id, graph_path["evidence"])

        # D4 失配检测（spec 2026-10-04 §2.4）：库的向量空间身份 ≠ 当前配置 ⇒ 响应带
        # 标记 + warning 点名差异字段（无密钥），查询照常返回（不锁定——混用可查、
        # 质量不保证）。身份未记（NULL）= 不做声明：既不说失配，也不说一致。
        diff = identity_diff_fields((await self.store.get_kb(kb_id) or {}).get("embedding_identity"), identity_from_rag(rag))
        mismatch_flag = {"embedding_mismatch": True} if diff else {}
        if diff:
            logger.warning("kb %s: vectors were embedded under a different embedding space (%s changed); serving results anyway, but retrieval quality is degraded until the library is rebuilt", kb_id, "/".join(diff))

        return {
            "query": query,
            "paths": {"vector": vector_path, "graph": graph_path, "wiki": wiki_path},
            "score_type": self._recall_score_types(rag, graph_raw.get("score_source") if isinstance(graph_raw, dict) else None),
            "elapsed_ms": {"vector": vector_ms, "graph": graph_ms, "wiki": wiki_ms},
            **mismatch_flag,
        }

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
        """POST /chunk-positions：批量切片位次查询（图谱实体抽屉行内「切片 #K」数据源）。

        与 recall-test 的 chunk_position 注入同源同词汇（_chunk_position_map）；
        空列表返回空映射。
        """
        return {"positions": await self._chunk_position_map(chunk_ids)}

    async def _inject_video_citations(self, kb_id: str, hits: list[dict[str, Any]]) -> None:
        """chunk 级引用行 join ``video_shots``（spec 2026-09-08 §4）：视频镜头补
        ``media``/``shot_index``/``start_ms``/``end_ms``/``frame_url``；文本引用字段
        一字不动（前端旧渲染零回归）。缺帧镜头不带 ``frame_url``（spec §2 降级）。
        """
        fields = await self._video_citation_fields(kb_id, (str(hit.get("chunk_id") or "") for hit in hits))
        for hit in hits:
            extra = fields.get(str(hit.get("chunk_id") or ""))
            if extra:
                hit.update(extra)

    async def _video_citation_fields(self, kb_id: str, chunk_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """chunk_id → 视频引用字段；只有映射到已物化 ``video_shots`` 行的 chunk 入选。

        chunk_id 扁平序 ``{doc_id}#{shot_index:04d}``（spec §3）→ 按 doc 分组，每
        文档一次 ``list_shots``（文本文档返回空 → 其全部 chunk 自然缺省，不注入）。
        畸形 id（无 ``#NNNN`` 后缀）与已删镜头同样缺键。
        """
        by_doc: dict[str, list[tuple[str, int]]] = {}
        for chunk_id in chunk_ids:
            doc_id, _, suffix = str(chunk_id or "").partition("#")
            if doc_id and suffix.isdigit():
                by_doc.setdefault(doc_id, []).append((chunk_id, int(suffix)))
        fields: dict[str, dict[str, Any]] = {}
        for doc_id, entries in by_doc.items():
            shots = await self.video_shot_store.list_shots(doc_id)
            if not shots:
                continue
            shot_by_index = {int(shot["shot_index"]): shot for shot in shots}
            for chunk_id, index in entries:
                shot = shot_by_index.get(index)
                if shot is None:
                    continue
                item: dict[str, Any] = {
                    "media": "video",
                    "shot_index": index,
                    "start_ms": int(shot["start_ms"]),
                    "end_ms": int(shot["end_ms"]),
                }
                if shot.get("keyframe_path"):
                    item["frame_url"] = f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/shots/{index}/frame"
                fields[chunk_id] = item
        return fields

    # ── vector-space projection (spec 2026-08-15 §7 P4) ───────────────────

    async def get_knowledge_graph(self, kb_id: str) -> dict[str, Any]:
        """图可视化端点（graph visualization spec §4）：全量实体/关系 + Louvain 社区标注。

        无缓存——百级图的读取 + 社区检测是毫秒级，现算永远最新（与向量投影
        的重计算+指纹缓存是不同处境）。mention_count 无专列，取
        len(source_chunk_ids)（提及切片数即重要度）。
        """
        entities = await self.graph_store.list_entities(kb_id)
        relations = await self.graph_store.list_relations(kb_id)
        community_by_name = assign_communities(
            [row["name"] for row in entities],
            [(row["source"], row["target"]) for row in relations],
        )
        return {
            "kb_id": kb_id,
            "nodes": [
                {
                    "id": row["name"],
                    "type": row.get("type") or "",
                    "description": row.get("description") or "",
                    "mention_count": len(row.get("source_chunk_ids") or []),
                    "community": community_by_name[row["name"]],
                    # 钻取链路数据源（Task 3）：chunk_id 内嵌 doc_id，前端点击实体
                    # 列切片并直跳文档抽屉，无需二次查询。
                    "source_chunk_ids": list(row.get("source_chunk_ids") or []),
                }
                for row in entities
            ],
            "edges": [
                {
                    "source": row["source"],
                    "target": row["target"],
                    "relation": row["relation"],
                    "description": row.get("description") or "",
                }
                for row in relations
            ],
            "stats": {
                "node_count": len(entities),
                "edge_count": len(relations),
                "community_count": len(set(community_by_name.values())),
            },
            # Task 7b LOD：社区级汇总（SuperNode 聚合/主导类型着色的数据源；
            # 分层加载契约的 super 层）。
            "communities": summarize_communities(entities, community_by_name),
        }

    async def get_vector_projection(
        self,
        kb_id: str,
        *,
        collections: list[str],
        algo: str,
        dims: int,
        sample_size: int,
        refresh: bool,
    ) -> dict[str, Any]:
        """Cached 2D/3D projection of the KB's four collections (spec §7).

        The fingerprint is recomputed per request (cheap); only a moved
        fingerprint — or ``refresh=True`` — reruns fetch→reduce. The SVD
        itself runs off the event loop (``anyio.to_thread``, blockbuster 纪律).
        """
        stats = await self.store.get_kb_content_stats(kb_id)
        fingerprint = content_fingerprint(stats)
        key = (kb_id, algo, dims, sample_size, tuple(collections))

        async def compute() -> CachedProjection:
            started = time.perf_counter()
            fetched = await fetch_projection_vectors(self.vector_store, self.store, kb_id, collections=collections, sample_size=sample_size)
            if not fetched.points:
                return CachedProjection(
                    coords=np.empty((0, dims), dtype=np.float64),
                    points=(),
                    total_points=fetched.total_points,
                    sampled=fetched.sampled,
                )
            reduce = partial(umap_reduce, fetched.matrix, dims) if algo == "umap" else partial(pca_reduce, fetched.matrix, dims)
            coords, model = await anyio.to_thread.run_sync(reduce)
            return CachedProjection(
                coords=coords,
                points=fetched.points,
                # Query overlay is PCA-only: umap has no stable transform (spec §4).
                model=model if algo == "pca" else None,
                total_points=fetched.total_points,
                sampled=fetched.sampled,
                computed_ms=int((time.perf_counter() - started) * 1000),
            )

        entry = await self.projection_cache.get_or_compute(key, fingerprint=fingerprint, refresh=refresh, compute=compute)
        return _projection_response(kb_id, algo, dims, entry)

    async def project_query_vector(
        self,
        kb_id: str,
        *,
        text: str,
        collections: list[str],
        algo: str,
        dims: int,
        sample_size: int,
    ) -> dict[str, Any]:
        """Transform query text into the cached projection's coordinate system.

        Never triggers a projection compute (spec §7): the PCA model must
        already be cached — 409 otherwise — so the retrieval overlay adds
        nothing beyond one embedding call + a matrix multiply.
        """
        key = (kb_id, algo, dims, sample_size, tuple(collections))
        entry = self.projection_cache.peek(key)
        if entry is None:
            raise ProjectionNotComputedError("Projection not computed yet; open the vector space tab first")
        if entry.model is None:
            raise ProjectionModelUnavailableError("Query projection requires a PCA model (algo=umap has no stable transform)")

        # embed 返回 EmbeddingResult（dense+sparse 对），query 侧必须 text_type=
        # "query"（对齐检索链路 hybrid/graph/wiki 的用法）；取 .dense 进 transform。
        # 2026-08-19 修复：曾直接 np.asarray(EmbeddingResult) → 生产 500。
        (query_embedding,) = await build_embedder().embed([text], text_type="query")
        coords = entry.model.transform(np.asarray(query_embedding.dense, dtype=np.float64))
        result: dict[str, Any] = {
            "x": float(coords[0]),
            "y": float(coords[1]),
            "model_version": entry.model.model_version,
            "fingerprint": entry.fingerprint,
        }
        if dims == 3:
            result["z"] = float(coords[2])
        return result

    # ── eval runs (spec 2026-08-24 §4.2, plan Task 1) ────────────────────────

    async def get_latest_eval_metrics(self, kb_id: str) -> dict[str, Any]:
        """MetricsOverview（§3.2）：两层各自最近一次 completed 且 metrics 非空且非 ci 的运行。

        两层时间戳天然错位（Layer 1 每天 CI、Layer 2 每周 nightly），合并视图
        保留各自来源（run_id + created_at 分开展示）。
        """
        rows = await self.store.list_eval_runs(kb_id)
        return {
            "kb_id": kb_id,
            "layer1": _layer1_overview_payload(latest_layer_row(rows, "layer1")),
            "layer2": _layer2_overview_payload(latest_layer_row(rows, "layer2")),
            "question_results": _question_results_payload(rows),
        }

    async def get_eval_trend(self, kb_id: str, *, include_ci: bool) -> dict[str, Any]:
        """TrendResponse（contract v4，spec 2026-09-07 §2）：run 级点 + baseline 块 + 顶层 ``sparks``。

        单 KB 历史 <100 条，读全量行内存计算。固定窗口 = 近
        ``TREND_WINDOW_DAYS`` 天（滚轮缩小上限）；日/周/月是前端客户端
        视窗预设，本端点不再接受 granularity/窗口参数。baseline 块读该
        KB 的 ``is_baseline`` 行——与 CI ``--fail-threshold`` 默认值同源
        （DEFAULT_FAIL_THRESHOLD × 100）。``sparks``（spec §6.2，服务瓦片
        sparkline）取**全量** ``rows`` 而非 ``windowed``——run 级近 10 非空
        值与趋势窗口解耦。
        """
        rows = await self.store.list_eval_runs(kb_id)
        cutoff = datetime.now(UTC) - timedelta(days=TREND_WINDOW_DAYS)
        windowed = [row for row in rows if _as_utc(row.created_at) >= cutoff]
        points = build_run_points(windowed, include_ci=include_ci)
        sparks = build_sparks(rows, include_ci=include_ci)
        baseline: dict[str, Any] | None = None
        baseline_row = next((row for row in rows if row.is_baseline), None)
        if baseline_row is not None:
            recall_at_k = (baseline_row.layer1_metrics.get("summary") or {}).get("recall_at_k")
            if recall_at_k is not None:
                baseline = {"recall_at_k": recall_at_k, "threshold_percent": DEFAULT_FAIL_THRESHOLD * 100}
        return {
            "points": points,
            "baseline": baseline,
            "has_data": bool(points),
            "sparks": sparks,
        }

    async def get_eval_run(self, kb_id: str, run_id: str) -> dict[str, Any] | None:
        """EvalRunDetail（§4.2）：单行完整 JSON，drawer 数据源；跨 kb 访问由 store 层返回 None。"""
        row = await self.store.get_eval_run_row(kb_id, run_id)
        if row is None:
            return None
        payload = KnowledgeStore._row_to_dict(row, datetime_keys=("created_at", "completed_at"))
        payload["run_id"] = payload.pop("id")
        return payload

    # ── eval question bank (spec 2026-08-27 §4) ──────────────────────────

    def _golden_path(self, kb_id: str) -> Path:
        """Per-KB golden 文件与上传文档同目录树（§4.1 存储约定）。"""
        return self.data_dir / "knowledge" / kb_id / "golden.jsonl"

    async def list_eval_questions(self, kb_id: str) -> dict[str, Any]:
        questions = await question_bank.load_questions(self._golden_path(kb_id))
        rows = [asdict(question) for question in questions]
        # 悬空派生（spec 2026-10-05 anchor-edit 对 D1=甲）：读时现算不落盘——
        # 全部锚 id 并集一次取行，缺行即悬空（重切片/删片的静默失效由此可见）。
        anchor_ids = list(dict.fromkeys(chunk_id for question in questions for chunk_id in question.relevant_chunk_ids))
        chunk_rows = await self.store.get_chunks_by_ids(anchor_ids, kb_id=kb_id) if anchor_ids else []
        present = {row["chunk_id"] for row in chunk_rows}
        # 落空派生（§2④，Task 5）：同一 store_fetch 顺带取同文档切片（找对照 B），
        # check_anchor 原判据原豁免跑一遍——零命中/mismatch 记「存疑」。
        texts = (
            await anchor_check.store_fetch(
                self.store,
                kb_id,
                anchor_ids,
                known={row["chunk_id"]: row.get("text") or "" for row in chunk_rows},
            )
            if anchor_ids
            else {}
        )
        for row, question in zip(rows, questions):
            row["missing_chunk_ids"] = [chunk_id for chunk_id in question.relevant_chunk_ids if chunk_id not in present]
            row["anchor_mismatch"] = self._anchor_mismatch_of(question, texts)
        return {"questions": rows, "total": len(rows)}

    @staticmethod
    def _anchor_mismatch_of(question: Any, texts: Mapping[str, str]) -> dict[str, Any] | None:
        """落空判定（spec 2026-10-05 §2④）：豁免照抄门禁——无参考答案（skipped）、
        无锚（ok）、悬空（missing 短路同一判定）都不记，一题至多显一类警示；
        |K|<2 不豁免（B2=乙：标记非拦截）。"""
        verdict = anchor_check.check_anchor(
            reference_answer=question.reference_answer,
            anchor_chunk_ids=question.relevant_chunk_ids,
            chunk_texts=texts,
        )
        if verdict.reason not in (anchor_check.REASON_MISMATCH, anchor_check.REASON_ZERO_HIT):
            return None
        return {**verdict.detail, "chunk_ids": list(verdict.chunk_ids)}

    async def create_eval_question(
        self,
        kb_id: str,
        *,
        query: str,
        category: str,
        expected_paths: Collection[str],
        relevant_chunk_ids: Collection[str],
        relevant_entities: Collection[str],
        reference_answer: str | None,
        anchor_ack: bool = False,
    ) -> dict[str, Any]:
        # 一次取行喂两处：实体派生 + 锚定核验（spec 2026-10-05 收口）。
        rows = await self.store.get_chunks_by_ids(list(relevant_chunk_ids), kb_id=kb_id) if relevant_chunk_ids else []
        if not relevant_entities:
            # 实体标注派生（2026-09-08，与合成路同源）：造题面（存为考题/添加
            # dialog）本无实体输入，空标注会让 seed_hit_rate 永久不适用——
            # 有锚定时取锚定切片 entities 保序去重并集；body 显式非空尊重
            # 原值（API 契约）。
            relevant_entities = synthesis.chunk_entities_union(rows)
        question = await question_bank.add_question(
            self._golden_path(kb_id),
            query=query,
            category=category,
            expected_paths=expected_paths,
            relevant_chunk_ids=relevant_chunk_ids,
            relevant_entities=relevant_entities,
            reference_answer=reference_answer,
            anchor_guard=anchor_check.build_anchor_guard(
                self.store,
                kb_id,
                anchor_texts={row["chunk_id"]: row.get("text") or "" for row in rows},
            ),
            anchor_ack=anchor_ack,
        )
        return asdict(question)

    async def delete_eval_question(self, kb_id: str, question_id: str) -> None:
        await question_bank.delete_question(self._golden_path(kb_id), question_id)

    async def update_eval_question(
        self,
        kb_id: str,
        question_id: str,
        *,
        relevant_chunk_ids: Collection[str],
        anchor_ack: bool = False,
    ) -> dict[str, Any]:
        """改锚（spec 2026-10-05 anchor-edit 对）：与 create 同一道锚定核验 +
        实体跟锚收缩（D4=甲′）。一次取行喂两处。"""
        rows = await self.store.get_chunks_by_ids(list(relevant_chunk_ids), kb_id=kb_id) if relevant_chunk_ids else []
        current = next(
            (question for question in await question_bank.load_questions(self._golden_path(kb_id)) if question.id == question_id),
            None,
        )
        if current is None:
            raise KeyError(question_id)
        # 跟锚收缩：旧实体 ∩ 新锚实体词汇表——只删失去支撑的、不新增（合成题
        # 精选子集保住；实体编辑不进本端点，改锚只是不让标注与锚脱钩）。
        supported = set(synthesis.chunk_entities_union(rows))
        shrunk = [name for name in current.relevant_entities if name in supported]
        question = await question_bank.update_question(
            self._golden_path(kb_id),
            question_id,
            relevant_chunk_ids=relevant_chunk_ids,
            relevant_entities=shrunk,
            anchor_guard=anchor_check.build_anchor_guard(
                self.store,
                kb_id,
                anchor_texts={row["chunk_id"]: row.get("text") or "" for row in rows},
            ),
            anchor_ack=anchor_ack,
        )
        return asdict(question)

    # ── question synthesis（spec 2026-08-28 §6）───────────────────────

    def _synthesis_staging_path(self, kb_id: str) -> Path:
        """候选暂存与 golden.jsonl 同目录树；单一 JSON 文档（Task 6 偏差①：
        元数据需在候选全部审核后仍可读）。"""
        return self.data_dir / "knowledge" / kb_id / "eval_candidates.json"

    async def trigger_question_synthesis(self, kb_id: str, *, doc_ids: Sequence[str], count: int) -> bool:
        """Fire-and-forget 多篇联合合成（复刻评测触发幂等模式，spec §6.1）。

        Returns False when a run is already in flight. 任一篇不存在/不属于该
        KB/无切片 → :class:`SynthesisDocNotReady`（router → 409），在调度前
        同步检查——宁可明确拒绝，不产出半截合成。
        """

        if synthesis.synthesis_in_progress(kb_id):
            return False
        ordered = list(dict.fromkeys(doc_ids))
        for doc_id in ordered:
            doc = await self.store.get_document(doc_id)
            if doc is None or doc.get("kb_id") != kb_id:
                raise SynthesisDocNotReady(f"document {doc_id} not found in kb {kb_id}")
            if await self.store.count_chunks(doc_id) == 0:
                raise SynthesisDocNotReady(f"document {doc_id} has no indexed chunks")
        if not synthesis.begin_synthesis(kb_id):
            return False
        self.synthesis_trigger_fn(kb_id, doc_ids=ordered, count=count)
        return True

    def _schedule_question_synthesis(self, kb_id: str, *, doc_ids: Sequence[str], count: int) -> None:
        task = asyncio.create_task(self._run_question_synthesis(kb_id, doc_ids=doc_ids, count=count), name=f"kb-synth-{kb_id}")
        self._synthesis_tasks.add(task)
        task.add_done_callback(self._synthesis_tasks.discard)

    async def _run_question_synthesis(self, kb_id: str, *, doc_ids: Sequence[str], count: int) -> None:
        """后台编排：逐篇拉全量切片 → 联合合成写暂存。异常只记日志并 drain
        in-flight，不动既有暂存（合成失败不清空上一次成果，spec §6.1）。"""
        try:
            docs: list[tuple[str, str, list[dict[str, Any]]]] = []
            for doc_id in doc_ids:
                doc = await self.store.get_document(doc_id)
                name = (doc or {}).get("name") or doc_id
                docs.append((doc_id, name, await self._all_chunks(doc_id)))
            await synthesis.synthesize_for_docs(kb_id, docs=docs, count=count, staging_path=self._synthesis_staging_path(kb_id))
        except Exception:
            logger.exception("question synthesis failed for kb %s docs %s", kb_id, list(doc_ids))
        finally:
            synthesis.end_synthesis(kb_id)

    async def _all_chunks(self, doc_id: str) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.store.list_chunks(doc_id, offset=offset)
            chunks.extend(page)
            if len(page) < 50:
                break
            offset += 50
        return chunks

    async def get_synthesis_status(self, kb_id: str) -> dict[str, Any]:
        """状态端点数据源：in_progress 标志 + 暂存候选 + 合成元数据。"""
        data = await synthesis.load_staging(self._synthesis_staging_path(kb_id))
        return {
            "in_progress": synthesis.synthesis_in_progress(kb_id),
            "candidates": data["candidates"],
            "generated_at": data.get("generated_at"),
            "doc_ids": data.get("doc_ids") or [],
            "dropped": data.get("dropped", 0),
        }

    async def accept_synthesis_candidate(self, kb_id: str, candidate_id: str, anchor_ack: bool = False) -> dict[str, Any]:
        question = await synthesis.accept_candidate(
            self._golden_path(kb_id),
            self._synthesis_staging_path(kb_id),
            candidate_id,
            anchor_guard=anchor_check.build_anchor_guard(self.store, kb_id),
            anchor_ack=anchor_ack,
        )
        return asdict(question)

    async def reject_synthesis_candidate(self, kb_id: str, candidate_id: str) -> None:
        await synthesis.reject_candidate(self._synthesis_staging_path(kb_id), candidate_id)

    async def trigger_eval_run(self, kb_id: str, *, layers: str = "l1", question_ids: Collection[str] | None = None) -> bool:
        """Fire-and-forget 评测触发（spec 2026-08-27 §5.1 + 2026-09-01 B 方案，wiki 幂等同款）。

        ``layers="l1"`` 快速档（纯检索静态指标）；``layers="l1_l2"`` 完整档（+
        judge-backed Layer 2，单行双层指标）。``question_ids`` 选题运行，调度前
        同步校验过滤后非空。Returns False when a run is already in flight —
        the router reports ``already_running`` instead of queueing a duplicate
        run. An empty (post-filter) question bank raises
        :class:`EvalQuestionBankEmpty` (router → 409) *before* anything is
        scheduled — the check runs synchronously so the caller gets a
        definitive answer rather than a doomed background task.
        """

        if eval_run_in_progress(kb_id):
            return False
        bank = await question_bank.load_questions(self._golden_path(kb_id))
        if question_ids is not None:
            wanted = set(question_ids)
            bank = [question for question in bank if question.id in wanted]
        if not bank:
            raise EvalQuestionBankEmpty(f"eval question bank is empty for kb {kb_id}")
        self.eval_trigger_fn(kb_id, layers=layers, question_ids=question_ids)
        return True

    async def cancel_eval_run(self, kb_id: str) -> bool:
        """终止在飞按需评测（spec 2026-09-06 §11）；False = 无在飞 run（router → 409）。

        取消注入 CancelledError 后 runner 自落 cancelled 行并弹注册表 →
        already_running 锁立即释放，可立即再触发。
        """
        return cancel_eval_run(kb_id)

    def _schedule_eval_run(self, kb_id: str, *, layers: str = "l1", question_ids: Collection[str] | None = None) -> None:
        runner = run_full_eval_for_kb if layers == "l1_l2" else run_layer1_for_kb
        task = asyncio.create_task(runner(kb_id, golden_path=self._golden_path(kb_id), question_ids=question_ids), name=f"kb-eval-{kb_id}")
        self._eval_tasks.add(task)
        task.add_done_callback(self._eval_tasks.discard)

    async def list_eval_runs(self, kb_id: str, *, limit: int = 50, include_ci: bool = False) -> dict[str, Any]:
        """历史列表（spec 2026-08-27 §6.1）：倒序轻量摘要 + 顶层 ``in_flight``。

        默认排除 ci 行（与 trend 同口径）；``limit`` 只做分页切片，``total``
        反映过滤后的全量行数——in-flight 运行不产生伪行（落库后才有行），
        运行中状态只由顶层标志表达。顶层 ``progress``（spec 2026-09-06
        run-progress）透出内存注册表的活进度快照，空闲时为 null。
        """

        rows = await self.store.list_eval_runs(kb_id)
        if not include_ci:
            rows = [row for row in rows if row.environment != ENV_CI]
        rows.reverse()  # created_at asc → desc（最新在前）
        summaries = [self._eval_run_summary(row) for row in rows]
        return {
            "in_flight": eval_run_in_progress(kb_id),
            "progress": get_eval_progress(kb_id),
            "runs": summaries[: min(limit, MAX_EVAL_RUNS_LIMIT)],
            "total": len(summaries),
        }

    async def delete_eval_runs(self, kb_id: str, run_ids: Sequence[str]) -> int:
        """历史删除（2026-09-08）：按选中集批量删 eval_runs 行，返回删除行数。

        趋势主图点 / sparks / 总览 / 题库召回列均为查询时对剩余行的实时
        聚合——删除后三面自然收敛，无伴随写；删基线行使后续 run 的
        baseline_diff 失参照（门禁降级为无 diff 放过），警示由前端确认框承载。
        """
        return await self.store.delete_eval_runs(kb_id, run_ids)

    @staticmethod
    def _eval_run_summary(row: EvalRunRow) -> dict[str, Any]:
        layer1_present = bool(row.layer1_metrics)
        layer2_present = bool(row.layer2_metrics)
        baseline_diff = row.baseline_diff or {}
        return {
            "run_id": row.id,
            # SQLite 读回剥 tz → naive；必须经 coerce_iso 补 UTC 偏移，否则前端把
            # naive ISO 当本地时间解析（UTC+8 环境偏 8 小时，2026-09-06 用户实测）。
            "created_at": coerce_iso(row.created_at) if row.created_at else None,
            "completed_at": coerce_iso(row.completed_at) if row.completed_at else None,
            "environment": row.environment,
            "status": row.status,
            "is_baseline": row.is_baseline,
            "has_layer1": layer1_present,
            "has_layer2": layer2_present,
            "regression_detected": bool(baseline_diff.get("regression_detected")),
            "langfuse_trace_url": row.langfuse_trace_url,
        }

    def _schedule_wiki_generation(self, kb_id: str, only_dirty: bool = True) -> None:
        task = asyncio.create_task(self._run_wiki_generation(kb_id, only_dirty=only_dirty), name=f"kb-wiki-{kb_id}")
        self._wiki_tasks.add(task)
        task.add_done_callback(self._wiki_tasks.discard)

    async def _run_wiki_generation(self, kb_id: str, *, only_dirty: bool = True) -> None:
        try:
            # generate_wiki silently skips the vector upsert without an embedder —
            # entries would exist but wiki_search could never find them.
            await generate_wiki(self.store, self.graph_store, self.wiki_store, self.vector_store, kb_id=kb_id, embedder=build_embedder(), only_dirty=only_dirty)
        except Exception:
            logger.exception("wiki generation failed for kb %s", kb_id)

    def _schedule_wiki_regeneration(self, kb_id: str, entry_ids: list[str]) -> None:
        task = asyncio.create_task(self._run_wiki_regeneration(kb_id, entry_ids), name=f"kb-wiki-regen-{kb_id}")
        self._wiki_tasks.add(task)
        task.add_done_callback(self._wiki_tasks.discard)

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
            await reindex_kb(self.store, self.vector_store, build_embedder(), kb_id=kb_id, graph_store=self.graph_store, wiki_store=self.wiki_store)
        except Exception:
            logger.exception("reindex failed for kb %s", kb_id)

    async def _run_wiki_regeneration(self, kb_id: str, entry_ids: list[str]) -> None:
        try:
            # Same embedder wiring as the library-level run: without it the
            # rewritten entry would keep a stale vector in kb_wiki_entries.
            await regenerate_wiki_entries(self.store, self.graph_store, self.wiki_store, self.vector_store, kb_id=kb_id, entry_ids=entry_ids, embedder=build_embedder())
        except Exception:
            logger.exception("wiki entry regeneration failed for kb %s", kb_id)

    # ── internals ────────────────────────────────────────────────────────

    async def _remove_dir(self, path: Path) -> None:
        def _rm() -> None:
            shutil.rmtree(path, ignore_errors=True)

        try:
            await run_file_io(_rm)
        except Exception:
            logger.warning("failed to remove knowledge dir %s", path, exc_info=True)
