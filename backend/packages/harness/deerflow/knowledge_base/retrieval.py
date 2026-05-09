"""Multi-KB fan-out retrieval — parallel search across multiple knowledge base collections."""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any

from deerflow.config.rag_config import get_rag_config
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.thread_meta import make_thread_store
from deerflow.rag.retrieval import DocumentRetriever, normalize_scores, rerank
from deerflow.rag.vector_store import SearchResult

logger = logging.getLogger(__name__)


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
) -> list[SearchResult]:
    """Retrieve from multiple KB collections in parallel, merge by score.

    Each KB retrieval is subject to a per-KB timeout. Results are normalized
    per-KB, merged, deduplicated, and limited by per-document chunk cap.

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

    retriever = DocumentRetriever()
    per_kb_k = max(top_k, 5)

    per_kb_results: list[list[SearchResult]] = []

    def _retrieve_one(kb: dict[str, Any]) -> list[SearchResult]:
        collection = kb["collection_name"]
        result = retriever.retrieve(query=query, collection=collection, top_k=per_kb_k)
        for r in result.results:
            if "kb_name" not in r.metadata:
                r.metadata["kb_name"] = kb.get("name", "")
            if "knowledge_base_id" not in r.metadata:
                r.metadata["knowledge_base_id"] = kb.get("id", "")
        return result.results

    with ThreadPoolExecutor(max_workers=min(len(knowledge_bases), 4)) as executor:
        futures = {executor.submit(_retrieve_one, kb): kb["id"] for kb in knowledge_bases}
        try:
            for future in as_completed(futures, timeout=timeout_s * len(knowledge_bases)):
                kb_id = futures[future]
                try:
                    results = future.result(timeout=timeout_s)
                    per_kb_results.append(results)
                except TimeoutError:
                    logger.warning("Retrieval timed out for KB %s (limit: %dms)", kb_id, config.per_kb_timeout_ms)
                except Exception as e:
                    logger.warning("Retrieval failed for KB %s: %s", kb_id, e)
        except TimeoutError:
            logger.warning("Overall multi-KB retrieval timed out after %dms", int(timeout_s * len(knowledge_bases) * 1000))

    all_results: list[SearchResult] = []
    for kb_results in per_kb_results:
        normalized = normalize_scores(kb_results)
        all_results.extend(normalized)

    all_results.sort(key=lambda r: r.score, reverse=True)

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

    return deduped
