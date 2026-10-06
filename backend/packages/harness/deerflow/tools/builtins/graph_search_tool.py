"""graph_search — the graph path (spec §4.2 + 2026-08-10 phase-2 D1/D2).

Chain: query → local LLM entity/keyword extraction → ``kb_entities`` vector
match → NetworkX 1–2 hop expansion with semantic pruning (D2: neighbor gate
+ node budget + hub guard) → chunk evidence via ``source_chunk_ids`` (precise
recall), ranked by semantic scores: the graph structure only defines the
candidate pool, then dedupe → per-source caps → hop-0 guarantee (round-robin
payout) → pure-score competition decides who gets in (D1). Chunk text always
comes from the business-DB ``chunks`` table. An empty answer is returned
honestly — the navigator never fabricates graph content.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from langchain.tools import tool
from langgraph.config import get_stream_writer

from deerflow.knowledge.access import ACCESS_DENIED_MESSAGE, NO_KB_GUIDANCE, can_access, resolve_kb_scope
from deerflow.knowledge.citation_counter import claim_citation_range
from deerflow.knowledge.embedder_factory import build_embedder
from deerflow.knowledge.graph.extractor import _strip_fence, get_extract_llm
from deerflow.knowledge.graph.normalizer import cosine_similarity
from deerflow.knowledge.graph.retrieval import Candidate, apply_source_caps, collect_candidates, expand_neighborhood, select_evidence
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.reranker import RerankerError
from deerflow.knowledge.reranker_factory import build_reranker
from deerflow.knowledge.store import KnowledgeStore, get_knowledge_store
from deerflow.knowledge.vector_store import KnowledgeVectorStore, get_vector_store
from deerflow.tools.types import Runtime
from deerflow.utils.custom_events import emit_custom_event

logger = logging.getLogger(__name__)

_QUERY_ENTITY_SYSTEM_PROMPT = """从用户问题中抽取需要检索的实体名或关键词（优先使用知识库中可能出现的规范名称），只输出严格 JSON：{"entities": ["...", "..."]}。问题中没有可抽取的实体时输出 {"entities": []}。不要输出任何其他内容。"""

#: Minimum cosine score for a query entity to land on a graph entity — keeps
#: "nothing found" honest instead of returning far-neighbor noise.
ENTITY_MATCH_MIN_SCORE = 0.3

#: Live-channel payload carrying the three-layer retrieval trace to the
#: frontend (spec §7 path highlight). The ToolMessage copy of ``trace`` is
#: what reload-time parsing relies on, but tool-output budgeting may replace
#: oversized tool results with a synopsis preview — the live overlay therefore
#: consumes this event instead of parsing the message.
GRAPH_RETRIEVAL_TRACE_EVENT_TYPE = "graph_retrieval_trace"


def _emit_trace_event(runtime: Any, kb_id: str, trace: dict) -> None:
    """Best-effort publish of the retrieval trace on the custom stream.

    Silently no-ops outside a runnable context (direct/unit-test invocation)
    or when no stream writer is attached — the ToolMessage copy stays the
    source of truth for reload-time parsing either way.
    """
    try:
        emit_custom_event(
            {
                "type": GRAPH_RETRIEVAL_TRACE_EVENT_TYPE,
                "tool_call_id": getattr(runtime, "tool_call_id", None),
                "kb_id": kb_id,
                "trace": trace,
            },
            writer=get_stream_writer(),
        )
    except RuntimeError:
        # get_stream_writer() raises outside a runnable context — direct calls
        # and unit tests run the impl without one by design.
        logger.debug("graph_retrieval_trace event not emitted (no stream context)")


def format_graph_message(
    *,
    matched: int,
    seen: int,
    relations: int,
    evidence: int,
    pool_size: int,
    evidence_limit: int,
    span: str,
) -> str:
    """图谱路消息（2026-09-05 池耗尽说明）：top_k 是上限而非承诺——证据由
    命中子图的源切片并集定义，候选池不足 top_k 时补一句「候选池共 N 片，
    已全量返回」，否则检索测试 UI 里「要 4 给 3」读起来像 bug。"""
    note = f"（候选池共 {pool_size} 片，已全量返回）" if evidence < evidence_limit else ""
    return f"命中 {matched} 个实体，扩展出 {seen} 个节点、{relations} 条关系、{evidence} 条切片证据{note}（引用编号 {span}，标注时照抄 citation_no）。"


def _empty(message: str) -> dict:
    # trace 恒在（空值）：前端路径高亮解析契约统一，不特判缺失字段。
    return {
        "entities": [],
        "relations": [],
        "evidence": [],
        "trace": {"seed_entities": [], "expanded_nodes": [], "evidence_entities": []},
        "message": message,
    }


async def _extract_query_entities(query: str, llm: Any) -> list[str]:
    from langgraph.constants import TAG_NOSTREAM

    response = await llm.ainvoke(
        [
            {"role": "system", "content": _QUERY_ENTITY_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ],
        # Internal helper call: keep its raw JSON tokens off the run's
        # messages stream, otherwise they render as assistant messages.
        config={"tags": [TAG_NOSTREAM]},
    )
    try:
        data = json.loads(_strip_fence(str(response.content)))
    except json.JSONDecodeError:
        logger.warning("graph_search: query entity extraction returned malformed JSON")
        return []
    if not isinstance(data, dict):
        return []
    names = data.get("entities")
    if not isinstance(names, list):
        # Malformed shape (scalar/object/string): the whole-query fallback in the
        # caller is the same landing path an empty list takes — never a throw, never
        # garbage names mined out of a string.
        logger.warning("graph_search: query entity extraction returned a malformed entities field")
        return []
    return [str(name).strip() for name in names if str(name).strip()]


async def _score_candidates(
    query: str,
    query_dense: list[float],
    candidates: dict[str, Candidate],
    *,
    store: KnowledgeStore,
    vector_store: KnowledgeVectorStore,
    reranker: Any,
    graph_rerank: bool,
    rerank_threshold: int,
) -> tuple[dict[str, float], str]:
    """Score every candidate chunk against the query — one global ruler.

    Returns the scores plus **the ruler that was actually used** ("rerank" or
    "cosine", spec 2026-09-24 §4.2): the recall panel renders that word, so it
    must describe this run rather than the configuration's capability.

    Default: embedding cosine against the stored chunk vectors (one batched
    retrieve, zero extra embedding calls). With ``graph_rerank`` enabled and
    a pool above ``rerank_threshold``, the configured rerank model takes over
    (texts fetched from the business DB, candidates fed in chunk-id order for
    a deterministic index mapping); any ``RerankerError`` degrades back to the
    embedding order — and back to the "cosine" ruler with it.
    """
    chunk_ids = list(candidates)
    if graph_rerank and reranker is not None and len(chunk_ids) > rerank_threshold:
        rows = await store.get_chunks_by_ids(sorted(chunk_ids))
        try:
            pairs = await reranker.rerank(query, [row["text"] for row in rows], top_n=len(rows))
        except RerankerError as exc:
            logger.warning("graph_search: reranker failed, falling back to embedding order: %s", exc)
        else:
            scores = {chunk_id: 0.0 for chunk_id in chunk_ids}
            for index, score in pairs:
                if 0 <= index < len(rows):
                    scores[rows[index]["chunk_id"]] = float(score)
            return scores, "rerank"
    vectors = await vector_store.get_chunk_vectors(chunk_ids)
    return {chunk_id: (cosine_similarity(query_dense, vectors[chunk_id]) if chunk_id in vectors else 0.0) for chunk_id in chunk_ids}, "cosine"


async def _graph_search_impl(
    query: str,
    runtime: Any,
    *,
    store: KnowledgeStore | None = None,
    graph_store: GraphStore | None = None,
    vector_store: KnowledgeVectorStore | None = None,
    embedder: Any = None,
    llm: Any = None,
    reranker: Any = None,
    per_entity_match: int = 3,
    hops: int = 2,
    per_entity_cap: int = 3,
    per_edge_cap: int = 2,
    hop0_guarantee: int = 2,
    evidence_limit: int = 8,
    graph_rerank: bool = False,
    rerank_threshold: int = 12,
    hop_penalty: float = 0.0,
    neighbor_min_score: float = 0.4,
    max_expanded_nodes: int = 25,
    hub_degree_threshold: int = 50,
) -> dict:
    """Core implementation — testable without the @tool wrapper."""
    kb_id, user_id = resolve_kb_scope(runtime)
    if not kb_id:
        return _empty(NO_KB_GUIDANCE)
    store = store or get_knowledge_store()
    if not await can_access(store, user_id, kb_id):
        return _empty(ACCESS_DENIED_MESSAGE)
    graph_store = graph_store or GraphStore(store._sf)
    vector_store = vector_store or get_vector_store()
    embedder = embedder or build_embedder()
    llm = llm or get_extract_llm()

    # 1. Query-side entity/keyword extraction (small model).
    query_names = await _extract_query_entities(query, llm)
    if not query_names:
        # The extractor is flaky on terse entity-only queries ("PDF") and may
        # return {"entities": []}. Fall back to the query itself as the
        # landing candidate — the ENTITY_MATCH_MIN_SCORE floor still keeps
        # chit-chat honest (an unrelated query matches no entity).
        stripped = query.strip()
        if stripped:
            query_names = [stripped]
    if not query_names:
        return _empty("未能从问题中识别出可检索的实体；该问题可能更适合向量检索（hybrid_search）。")

    # 2. One query embedding serves all semantic scoring.
    (query_embedding,) = await embedder.embed([query], text_type="query")
    query_dense = query_embedding.dense

    # 3. Land on graph entities via kb_entities vector match; the landing
    # score doubles as the entity score (max when several query entities hit
    # the same graph entity).
    matched_names: list[str] = []
    entity_scores: dict[str, float] = {}
    for name in query_names:
        if name == query.strip():
            # Query-fallback landing: the candidate IS the query — reuse the
            # embedding from step 2 instead of paying a duplicate remote call.
            name_dense = query_dense
        else:
            (name_vector,) = await embedder.embed([name], text_type="query")
            name_dense = name_vector.dense
        for point in await vector_store.query_entities(dense=name_dense, kb_id=kb_id, top_k=per_entity_match, score_threshold=ENTITY_MATCH_MIN_SCORE):
            entity_name = str(point.payload["name"])
            matched_names.append(entity_name)
            entity_scores[entity_name] = max(entity_scores.get(entity_name, 0.0), float(point.score))
    matched_names = list(dict.fromkeys(matched_names))
    if not matched_names:
        return _empty(f"知识图谱中未找到与「{'、'.join(query_names)}」相关的实体。")

    # 4. 1–2 hop expansion over the in-memory graph (both directions) with
    # D2 pruning: semantic gate per neighbour, node budget, hub guard.
    graph = await graph_store.load_networkx(kb_id)

    async def _fetch_entity_vectors(names: list[str]):
        return await vector_store.get_entity_vectors(kb_id, names)

    expansion = await expand_neighborhood(
        graph,
        entity_scores,
        hops=hops,
        query_vector=query_dense,
        fetch_vectors=_fetch_entity_vectors,
        neighbor_min_score=neighbor_min_score,
        max_expanded_nodes=max_expanded_nodes,
        hub_degree_threshold=hub_degree_threshold,
    )
    hop_by_node = expansion.hop_by_node
    entity_scores = expansion.entity_scores
    if not hop_by_node:
        return _empty(f"知识图谱中未找到与「{'、'.join(query_names)}」相关的实体。")
    seen = set(hop_by_node)

    relations = []
    for source, target, data in graph.edges(data=True):
        if source in seen and target in seen:
            relations.append({"source": source, "target": target, "relation": data.get("relation", ""), "description": data.get("description", "")})
    entities = []
    for node in sorted(seen):
        data = graph.nodes[node]
        entities.append({"name": node, "type": data.get("type") or "", "description": data.get("description") or ""})

    # 5. Evidence (D1): the graph defines the pool, semantics decides —
    # dedupe → per-source caps → hop-0 guarantee → pure-score competition.
    candidates = collect_candidates(graph, hop_by_node)
    scores, score_source = await _score_candidates(
        query,
        query_dense,
        candidates,
        store=store,
        vector_store=vector_store,
        reranker=reranker,
        graph_rerank=graph_rerank,
        rerank_threshold=rerank_threshold,
    )
    apply_source_caps(candidates, scores, per_entity_cap=per_entity_cap, per_edge_cap=per_edge_cap)
    selected = select_evidence(
        candidates,
        scores,
        entity_scores,
        [name for name, hop in hop_by_node.items() if hop == 0],
        guarantee=hop0_guarantee,
        limit=evidence_limit,
        hop_penalty=hop_penalty,
    )

    # 6. Evidence text from the business DB in the selected order
    # (get_chunks_by_ids preserves the input order).
    rows = await store.get_chunks_by_ids(selected)
    doc_names: dict[str, str] = {}
    evidence = []
    for row in rows:
        doc_id = row["doc_id"]
        if doc_id not in doc_names:
            document = await store.get_document(doc_id)
            doc_names[doc_id] = document["name"] if document else ""
        evidence.append(
            {
                "chunk_id": row["chunk_id"],
                "text": row["text"],
                "doc_name": doc_names[doc_id],
                "heading_path": row.get("heading_path") or [],
                "page": row.get("page"),
                "score": float(scores.get(row["chunk_id"], 0.0)),
            }
        )

    # Shared per-run citation counter — see hybrid_search_tool. The span is
    # also stated in the message text (prose >> JSON fields for attention).
    start = claim_citation_range(runtime, len(evidence))
    for i, item in enumerate(evidence):
        item["citation_no"] = start + i + 1
    span = f"[{start + 1}]" if len(evidence) == 1 else f"[{start + 1}]-[{start + len(evidence)}]"
    trace = _build_trace(hop_by_node, candidates, selected, entity_scores)
    _emit_trace_event(runtime, kb_id, trace)
    return {
        "entities": entities,
        "relations": relations,
        "evidence": evidence,
        # Which ruler produced the scores above (spec 2026-09-24 §4.2): the
        # recall panel renders it verbatim as the path's badge. Absent on the
        # honest-empty returns — the caller then falls back to the config.
        "score_source": score_source,
        "trace": trace,
        "message": format_graph_message(
            matched=len(matched_names),
            seen=len(seen),
            relations=len(relations),
            evidence=len(evidence),
            pool_size=len(candidates),
            evidence_limit=evidence_limit,
            span=span,
        ),
    }


def _build_trace(
    hop_by_node: dict[str, int],
    candidates: dict[str, Candidate],
    selected: list[str],
    entity_scores: dict[str, float],
) -> dict:
    """Serialize the retrieval trace for the frontend graph overlay (P4).

    Pure serialization of what the pipeline already computed — three layers:
    seed entities (hop-0 landings), expanded nodes with their hop layer, and
    the evidence anchors. Deterministic ordering (seeds/evidence sorted by name,
    expanded by ``(hop, name)``) keeps the response contract stable across runs.

    Evidence anchors: each selected chunk is attributed to its single strongest
    source entity (lowest hop, then highest entity score, then name as the
    deterministic tiebreak) — never the whole co-mention set. Dense chunks are
    routinely sourced by 8–29 entities (median 16 on the 286-entity JVM kb,
    measured 2026-08-20); unioning them would flood the overlay's hit layer and
    paint the entire seen subgraph red.
    """
    evidence_entities: set[str] = set()
    for chunk_id in selected:
        candidate = candidates[chunk_id]
        sources = set(candidate.entity_sources)
        for edge in candidate.edge_sources:
            sources.update(edge)
        if not sources:
            continue
        anchor = min(sources, key=lambda name: (hop_by_node.get(name, 99), -entity_scores.get(name, 0.0), name))
        evidence_entities.add(anchor)
    return {
        "seed_entities": sorted(name for name, hop in hop_by_node.items() if hop == 0),
        "expanded_nodes": [{"name": name, "hop": hop} for name, hop in sorted(hop_by_node.items(), key=lambda item: (item[1], item[0])) if hop > 0],
        "evidence_entities": sorted(evidence_entities),
    }


@tool(parse_docstring=True)
async def graph_search(
    runtime: Runtime,
    query: Annotated[str, "The relationship/structure question, phrased in the user's language."],
    hops: Annotated[int, "Graph expansion depth from the matched entities (1 or 2, default 2)."] = 2,
) -> dict:
    """Search the knowledge graph of the bound knowledge base (entity relations + chunk evidence).

    Use this tool when:
    - The question is about relationships, dependencies, or multi-hop structure between concepts (e.g. "A 和 B 有什么关系")
    - You need to navigate from known entities to their neighborhood before fetching evidence

    Skip this tool when:
    - The question needs factual detail on a single topic — start with hybrid_search
    - The question asks for a conceptual overview of a head entity — use wiki_search

    The graph is a navigator: it returns entity/relation descriptions plus the linked chunk evidence. An empty result means the graph lacks those entities — answer honestly or fall back to hybrid_search; never fabricate relations.

    Args:
        runtime: Tool runtime carrying the bound ``kb_id`` in its context.
        query: The relationship/structure question, phrased in the user's language.
        hops: Graph expansion depth from the matched entities (1 or 2, default 2).
    """
    from deerflow.config.app_config import get_app_config

    rag = get_app_config().rag
    return await _graph_search_impl(
        query,
        runtime,
        hops=hops,
        reranker=build_reranker() if rag.graph_rerank else None,
        per_entity_cap=rag.graph_per_entity_cap,
        per_edge_cap=rag.graph_per_edge_cap,
        hop0_guarantee=rag.graph_hop0_guarantee,
        evidence_limit=rag.graph_evidence_limit,
        graph_rerank=rag.graph_rerank,
        rerank_threshold=rag.graph_rerank_threshold,
        hop_penalty=rag.graph_hop_penalty,
        neighbor_min_score=rag.graph_neighbor_min_score,
        max_expanded_nodes=rag.graph_max_expanded_nodes,
        hub_degree_threshold=rag.graph_hub_degree_threshold,
    )
