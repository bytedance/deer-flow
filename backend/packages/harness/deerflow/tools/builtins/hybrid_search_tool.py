"""knowledge_search — the vector path (spec §4.1).

Chain: query → the configured embedding model (dense+sparse in one call) →
Qdrant prefetch top-20 per path → RRF fusion (coarse) → the configured
rerank model → top-k. Chunk text is fetched from the business-DB ``chunks``
table by ``chunk_id``; the Qdrant payload supplies only citation metadata
(doc_name/page/heading_path). A reranker outage degrades to RRF order — the
vector path never hard-fails on the precision stage (spec §4.4).

The tool also emits the shared ``knowledge_sources`` artifact (upstream #5551)
with one record per returned slice, so budget trimming, subagent forwarding,
and the source-collection frontend all see the same provider-qualified
snapshot of what was actually retrieved.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

from langchain.tools import tool

from deerflow.tools.types import Runtime

if TYPE_CHECKING:
    from deerflow_knowledge.store import KnowledgeStore
    from deerflow_knowledge.vector_store import KnowledgeVectorStore

logger = logging.getLogger(__name__)


def _build_source_artifact(pairs: list[tuple[dict[str, Any], dict[str, Any]]], *, kb: dict[str, Any], kb_id: str) -> dict[str, Any] | None:
    """One provider-qualified source record per returned slice (upstream #5551).

    Ids stay provider-independent (``<call-uuid>-<n>``) exactly like the
    RAGFlow formatter's, so the shared frontend/source code needs no new id
    shape; ``provider`` distinguishes built-in KBs from external sources.
    """
    if not pairs:
        return None
    call_id = uuid4().hex
    dataset_name = str(kb.get("name") or "")
    sources: list[dict[str, Any]] = []
    for index, (item, row) in enumerate(pairs, start=1):
        page = item.get("page")
        sources.append(
            {
                "id": f"{call_id}-{index}",
                "provider": "local",
                "dataset_id": kb_id,
                "document_id": str(row.get("doc_id") or ""),
                "chunk_id": str(item.get("chunk_id") or ""),
                "dataset_name": dataset_name,
                "document_name": str(item.get("doc_name") or ""),
                "text": str(item.get("text") or ""),
                "truncated": False,
                "pages": [page] if isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= 1_000_000 else [],
            }
        )
    return {"knowledge_sources": {"version": 1, "sources": sources}}


async def _hybrid_search_impl(
    query: str,
    runtime: Any,
    *,
    store: KnowledgeStore | None = None,
    vector_store: KnowledgeVectorStore | None = None,
    embedder: Any = None,
    reranker: Any = None,
    top_k: int = 5,
    candidate_limit: int = 20,
) -> tuple[dict, dict[str, Any] | None]:
    """Core implementation — testable without the @tool wrapper.

    Imports stay function-level on purpose: this module lives in the host and
    its registration surface must import even when the knowledge extension is
    not installed (the tool only resolves its dependencies when actually called).
    """
    from deerflow_knowledge.access import (
        ACCESS_DENIED_MESSAGE,
        KB_MISSING_MESSAGE,
        NO_KB_GUIDANCE,
        resolve_kb_scope,
    )
    from deerflow_knowledge.citation_counter import claim_citation_range
    from deerflow_knowledge.embedder_factory import build_embedder
    from deerflow_knowledge.reranker import RerankerError
    from deerflow_knowledge.reranker_factory import build_reranker
    from deerflow_knowledge.store import get_knowledge_store
    from deerflow_knowledge.vector_store import get_vector_store

    kb_id, user_id, refusal = resolve_kb_scope(runtime)
    if kb_id is None:
        return {"results": [], "message": refusal or NO_KB_GUIDANCE}, None
    store = store or get_knowledge_store()
    kb = await store.get_kb(kb_id)
    if kb is None:
        return {"results": [], "message": KB_MISSING_MESSAGE}, None
    if kb.get("owner_id") != user_id:
        return {"results": [], "message": ACCESS_DENIED_MESSAGE}, None
    vector_store = vector_store or get_vector_store()
    embedder = embedder or build_embedder()
    reranker = reranker or build_reranker()

    (query_vector,) = await embedder.embed([query], text_type="query")
    candidates = await vector_store.hybrid_query(
        dense=query_vector.dense,
        sparse=query_vector.sparse,
        kb_id=kb_id,
        top_k=candidate_limit,
    )
    if not candidates:
        return {"results": [], "message": "知识库中未检索到与问题相关的内容。"}, None

    chunk_ids = [point.payload["chunk_id"] for point in candidates]
    rows = await store.get_chunks_by_ids(chunk_ids, kb_id=kb_id)
    if not rows:
        return {"results": [], "message": "知识库中未检索到与问题相关的内容。"}, None
    payload_by_chunk = {point.payload["chunk_id"]: point.payload for point in candidates}
    rrf_rank = {chunk_id: rank for rank, chunk_id in enumerate(chunk_ids)}

    degrade_note = ""
    try:
        ranked = await reranker.rerank(query, [row["text"] for row in rows], top_n=top_k)
        ordered: list[tuple[dict, float | None]] = [(rows[index], score) for index, score in ranked]
    except RerankerError as exc:
        logger.warning("rerank unavailable, degrading to RRF order: %s", exc)
        ordered = [(row, None) for row in sorted(rows, key=lambda r: rrf_rank[r["chunk_id"]])[:top_k]]
        degrade_note = "（精排服务暂不可用，已按混合检索粗排顺序返回）"

    results = []
    for row, score in ordered:
        payload = payload_by_chunk.get(row["chunk_id"], {})
        item: dict[str, Any] = {
            "chunk_id": row["chunk_id"],
            "text": row["text"],
            "doc_name": payload.get("doc_name") or "",
            "page": payload.get("page"),
            "heading_path": payload.get("heading_path") or [],
        }
        if score is not None:
            item["score"] = score
        results.append(item)
    # Shared per-run citation counter: the model cites [n] copied from
    # citation_no, and all retrieval tools must agree on one numbering space
    # or the model's marks collapse onto colliding [1]s. The number span is
    # ALSO stated in the message text — JSON fields get far less model
    # attention than prose.
    start = claim_citation_range(runtime, len(results))
    for i, item in enumerate(results):
        item["citation_no"] = start + i + 1
    span = f"[{start + 1}]" if len(results) == 1 else f"[{start + 1}]-[{start + len(results)}]"
    payload_out = {"results": results, "message": f"检索到 {len(results)} 条相关切片（引用编号 {span}，标注时照抄 citation_no）。{degrade_note}"}
    return payload_out, _build_source_artifact(list(zip(results, (row for row, _ in ordered))), kb=kb, kb_id=kb_id)


@tool(parse_docstring=True, response_format="content_and_artifact")
async def knowledge_search(
    runtime: Runtime,
    query: Annotated[str, "The retrieval question, phrased in the user's language."],
    top_k: Annotated[int, "Number of chunks to return after precision ranking (default 5)."] = 5,
) -> tuple[str, dict[str, Any] | None]:
    """Hybrid vector search over the knowledge base bound to this conversation (dense + sparse fused with RRF, then reranked).

    Use this tool when:
    - The user's question needs factual detail, precise wording, or citation-grade evidence from the bound knowledge base

    Each result carries chunk text plus doc_name/page/heading_path for citation. Missing knowledge-base binding returns guidance instead of searching.

    Args:
        runtime: Tool runtime carrying the admitted knowledge scope in its context.
        query: The retrieval question, phrased in the user's language.
        top_k: Number of chunks to return after precision ranking (default 5).
    """
    payload, artifact = await _hybrid_search_impl(query, runtime, top_k=top_k)
    return json.dumps(payload, ensure_ascii=False), artifact
