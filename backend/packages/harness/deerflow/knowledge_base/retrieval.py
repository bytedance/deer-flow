"""Multi-KB fan-out retrieval — parallel search across multiple knowledge base collections."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any

from deerflow.config.rag_config import get_rag_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.knowledge_base.telemetry import get_kb_telemetry
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.thread_meta import make_thread_store
from deerflow.rag.embeddings import get_embedding_provider
from deerflow.rag.job_context import kb_context
from deerflow.rag.retrieval import DocumentRetriever, normalize_scores, rerank
from deerflow.rag.vector_store import SearchResult
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


_VISIBILITY_PRIORITY: dict[str, int] = {"private": 3, "tenant": 2, "public": 1}


def _kb_priority(kb: dict[str, Any]) -> int:
    """Visibility-derived KB priority used to break score ties.

    Why: when two chunks land on the same vector score (common after
    cosine clipping or rerank score quantisation), we want the user's
    own private library to outrank a shared/public one — never the
    reverse — so a high-confidence private hit can't be silently
    pre-empted by a noisier tenant or public KB.
    """
    return _VISIBILITY_PRIORITY.get(str(kb.get("visibility", "")).lower(), 0)


def normalize_kb_selection(selection: Any) -> dict[str, Any] | None:
    if not isinstance(selection, dict):
        return None
    if not selection.get("enabled"):
        return None
    selected_ids = selection.get("selected_ids")
    if not isinstance(selected_ids, list):
        return None
    normalized_ids = [str(item) for item in selected_ids if str(item).strip()]
    if not normalized_ids:
        return None
    return {
        "enabled": True,
        "selected_ids": normalized_ids,
    }


async def resolve_runtime_kb_selection(runtime: Any) -> tuple[dict[str, Any] | None, str | None]:
    context = getattr(runtime, "context", None) or {}
    runtime_selection = normalize_kb_selection(context.get("knowledge_base_selection"))
    if runtime_selection is not None:
        return runtime_selection, "runtime"

    runtime_config = getattr(runtime, "config", None) or {}
    thread_id = context.get("thread_id") or ((runtime_config.get("configurable") or {}).get("thread_id"))
    if not thread_id:
        return None, None

    session_factory = get_session_factory()
    store = getattr(runtime, "store", None)
    if session_factory is None and store is None:
        return None, None

    thread_store = make_thread_store(session_factory, store)
    user_id = context.get("user_id")
    record = await thread_store.get(thread_id, user_id=user_id)
    if record is None:
        return None, None

    metadata = record.get("metadata") or {}
    metadata_selection = normalize_kb_selection(metadata.get("knowledge_base_selection"))
    if metadata_selection is None:
        return None, None
    return metadata_selection, "thread_metadata"


def build_selection_snapshot(
    selection: dict[str, Any],
    knowledge_bases: list[dict[str, Any]],
    *,
    source: str | None,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "selected_ids": list(selection.get("selected_ids") or []),
        "resolved_kbs": [
            {
                "id": str(kb.get("id", "")),
                "name": str(kb.get("name", "")),
                "collection_name": str(kb.get("collection_name", "")),
            }
            for kb in knowledge_bases
            if kb.get("id")
        ],
        "source": source,
    }


def build_retrieval_trace_data(
    *,
    query: str,
    results: list[SearchResult],
    knowledge_bases: list[dict[str, Any]],
    filtered_ids: list[str] | None = None,
    timeouts: list[str] | None = None,
) -> dict[str, Any]:
    kb_name_map = {
        str(kb.get("id", "")): str(kb.get("name", ""))
        for kb in knowledge_bases
        if kb.get("id")
    }
    per_kb_hits: defaultdict[str, int] = defaultdict(int)
    sources: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str]] = set()

    for result in results:
        metadata = result.metadata
        kb_id = str(metadata.get("knowledge_base_id", ""))
        doc_title = str(metadata.get("title", ""))
        if kb_id:
            per_kb_hits[kb_id] += 1
        source_key = (kb_id, doc_title)
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        sources.append(
            {
                "kb_id": kb_id,
                "kb_name": kb_name_map.get(kb_id, str(metadata.get("kb_name", ""))),
                "doc_title": doc_title,
                "score": round(result.score, 3) if result.score is not None else 0,
            }
        )

    return {
        "query": query,
        "per_kb_hits": [
            {
                "kb_id": kb_id,
                "kb_name": kb_name_map.get(kb_id, ""),
                "hit_count": hit_count,
                "latency_ms": None,
            }
            for kb_id, hit_count in per_kb_hits.items()
        ],
        "final_chunk_count": len(results),
        "filtered_ids": list(filtered_ids or []),
        "timeouts": list(timeouts or []),
        "sources": sources,
    }

def multi_kb_retrieve(
    knowledge_bases: list[dict[str, Any]],
    query: str,
    top_k: int = 10,
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> list[SearchResult]:
    """Retrieve from multiple KB collections in parallel, merge by score.

    Each KB retrieval is subject to a per-KB timeout. Results are normalized
    per-KB, merged, deduplicated, and limited by per-document chunk cap.

    B.3.4: each KB is queried with its own embedding model — providers
    are deduped by ``embedding_model`` so 5 KBs across 3 models result
    in 3 embedding calls, not 5.

    Args:
        knowledge_bases: List of KB dicts (must contain ``collection_name`` and ``name``).
        query: The user query to search for.
        top_k: Maximum total results to return after merge.

    Returns:
        Merged, deduplicated, score-sorted list of SearchResult.
    """
    if not knowledge_bases:
        return []

    config = get_rag_config()
    timeout_s = config.per_kb_timeout_ms / 1000.0
    max_chunks_per_doc = config.max_chunks_per_document

    per_kb_k = max(top_k, 5)

    per_kb_results: list[list[SearchResult]] = []
    per_kb_stats: list[dict[str, Any]] = []

    # Filter KBs flagged stale by the startup consistency check; we surface
    # them in per_kb_stats so operators can see *why* they were skipped
    # rather than silently dropping results.
    eligible_kbs: list[dict[str, Any]] = []
    for kb in knowledge_bases:
        if kb.get("vector_metric_stale"):
            per_kb_stats.append(
                {
                    "kb_id": str(kb.get("id", "")),
                    "kb_name": kb.get("name", ""),
                    "raw_max": None,
                    "raw_min": None,
                    "returned": 0,
                    "skipped_reason": "vector_metric_stale",
                }
            )
            continue
        eligible_kbs.append(kb)

    # Build / cache embedders per unique embedding_model so 5 KBs
    # across 3 models = 3 embed calls. Falls back to global default
    # for legacy KBs that haven't been backfilled yet (embedding_model is None).
    embedder_cache: dict[str, Any] = {}

    def _embedder_for(spec: str | None) -> Any:
        key = spec or "__global__"
        if key not in embedder_cache:
            embedder_cache[key] = get_embedding_provider(spec)
        return embedder_cache[key]

    effective_tenant_id = tenant_id or get_current_tenant_id()
    effective_user_id = user_id or get_effective_user_id()

    def _retrieve_one(kb: dict[str, Any]) -> list[SearchResult]:
        collection = kb["collection_name"]
        priority = _kb_priority(kb)
        spec = kb.get("embedding_model")
        embedder = _embedder_for(spec)
        retriever = DocumentRetriever(embedder=embedder)
        if effective_tenant_id:
            with kb_context(tenant_id=effective_tenant_id, user_id=effective_user_id):
                result = retriever.retrieve(query=query, collection=collection, top_k=per_kb_k)
        else:
            result = retriever.retrieve(query=query, collection=collection, top_k=per_kb_k)
        for r in result.results:
            if "kb_name" not in r.metadata:
                r.metadata["kb_name"] = kb.get("name", "")
            if "knowledge_base_id" not in r.metadata:
                r.metadata["knowledge_base_id"] = kb.get("id", "")
            r.metadata.setdefault("kb_priority", priority)
            r.metadata.setdefault("embedding_model", spec or "")
        return result.results

    kb_by_id: dict[str, dict[str, Any]] = {str(kb["id"]): kb for kb in eligible_kbs}
    embedding_models_used = sorted(
        {kb.get("embedding_model") or "__global__" for kb in eligible_kbs}
    )

    # Track per-KB start times for telemetry latency
    _start_times: dict[str, float] = {str(kb["id"]): time.time() for kb in eligible_kbs}

    if not eligible_kbs:
        logger.info(
            "multi_kb_retrieve: per_kb=%s strategy=%s threshold=%s total=0 top_k=%d "
            "embedding_models_used=%s",
            per_kb_stats,
            (getattr(config, "cross_kb_score_strategy", "absolute") or "absolute").lower(),
            getattr(config, "score_threshold", 0.0),
            top_k,
            embedding_models_used,
        )
        return []

    with ThreadPoolExecutor(max_workers=min(len(eligible_kbs), 4)) as executor:
        futures = {executor.submit(_retrieve_one, kb): kb["id"] for kb in eligible_kbs}
        try:
            for future in as_completed(futures, timeout=timeout_s * len(eligible_kbs)):
                kb_id = futures[future]
                kb_meta = kb_by_id.get(str(kb_id), {})
                try:
                    results = future.result(timeout=timeout_s)
                    per_kb_results.append(results)
                    kb_id_str = str(kb_id)
                    latency_ms = (time.time() - _start_times.get(kb_id_str, time.time())) * 1000
                    get_kb_telemetry().record_latency(kb_id_str, round(latency_ms, 2))
                    if results:
                        scores = [r.score for r in results]
                        raw_max = max(scores)
                        raw_min = min(scores)
                    else:
                        raw_max = None
                        raw_min = None
                    per_kb_stats.append(
                        {
                            "kb_id": str(kb_id),
                            "kb_name": kb_meta.get("name", ""),
                            "raw_max": raw_max,
                            "raw_min": raw_min,
                            "returned": len(results),
                            "embedding_model": kb_meta.get("embedding_model") or "",
                        }
                    )
                except TimeoutError:
                    kb_id_str = str(kb_id)
                    latency_ms = (time.time() - _start_times.get(kb_id_str, time.time())) * 1000
                    logger.warning("Retrieval timed out for KB %s (limit: %dms)", kb_id, config.per_kb_timeout_ms)
                    get_kb_telemetry().record_latency(kb_id_str, round(latency_ms, 2))
                    get_kb_telemetry().record_event("retrieval.timeout", {
                        "kb_id": kb_id_str,
                        "timeout_ms": config.per_kb_timeout_ms,
                    })
                    per_kb_stats.append(
                        {
                            "kb_id": str(kb_id),
                            "kb_name": kb_meta.get("name", ""),
                            "raw_max": None,
                            "raw_min": None,
                            "returned": 0,
                            "error": "timeout",
                            "embedding_model": kb_meta.get("embedding_model") or "",
                        }
                    )
                except Exception as e:
                    kb_id_str = str(kb_id)
                    latency_ms = (time.time() - _start_times.get(kb_id_str, time.time())) * 1000
                    logger.warning("Retrieval failed for KB %s: %s", kb_id, e)
                    get_kb_telemetry().record_latency(kb_id_str, round(latency_ms, 2))
                    get_kb_telemetry().record_event("retrieval.failed", {
                        "kb_id": kb_id_str,
                        "error_type": type(e).__name__,
                    })
                    per_kb_stats.append(
                        {
                            "kb_id": str(kb_id),
                            "kb_name": kb_meta.get("name", ""),
                            "raw_max": None,
                            "raw_min": None,
                            "returned": 0,
                            "error": type(e).__name__,
                            "embedding_model": kb_meta.get("embedding_model") or "",
                        }
                    )
        except TimeoutError:
            logger.warning("Overall multi-KB retrieval timed out after %dms", int(timeout_s * len(eligible_kbs) * 1000))
            get_kb_telemetry().record_event("retrieval.timeout", {
                "kb_id": "__overall__",
                "timeout_ms": int(timeout_s * len(eligible_kbs) * 1000),
            })

    all_results: list[SearchResult] = []
    score_strategy = (getattr(config, "cross_kb_score_strategy", "absolute") or "absolute").lower()
    for kb_results in per_kb_results:
        if score_strategy == "per_kb_minmax":
            all_results.extend(normalize_scores(kb_results))
        else:
            all_results.extend(kb_results)

    all_results.sort(
        key=lambda r: (
            r.score,
            r.metadata.get("kb_priority", 0),
            str(r.metadata.get("document_id", "")),
            r.chunk_id or "",
        ),
        reverse=True,
    )

    seen_content: set[str] = set()
    doc_chunk_counts: defaultdict[str, int] = defaultdict(int)
    deduped: list[SearchResult] = []
    for r in all_results:
        content_key = r.content.strip()
        if content_key in seen_content:
            continue
        doc_id = r.metadata.get("document_id", "")
        if doc_id and doc_chunk_counts[doc_id] >= max_chunks_per_doc:
            continue
        seen_content.add(content_key)
        if doc_id:
            doc_chunk_counts[doc_id] += 1
        deduped.append(r)
        if len(deduped) >= top_k:
            break

    if config.reranker_enabled and deduped:
        deduped = rerank(query, deduped)

    logger.info(
        "multi_kb_retrieve: per_kb=%s strategy=%s threshold=%s total=%d top_k=%d "
        "embedding_models_used=%s",
        per_kb_stats,
        score_strategy,
        getattr(config, "score_threshold", 0.0),
        len(deduped),
        top_k,
        embedding_models_used,
    )

    get_kb_telemetry().record_event("retrieval.completed", {
        "total_results": len(deduped),
        "kb_count": len(eligible_kbs),
        "per_kb_hits": {s["kb_id"]: s["returned"] for s in per_kb_stats},
    })

    return deduped
