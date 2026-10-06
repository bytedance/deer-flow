"""Tests for the graph indexing stage (spec §3.4).

Per chunk: extract (small model) → normalize → merge into the graph store →
backfill normalized entity names onto the chunk row and the ``kb_chunks``
Qdrant payload. Per-chunk status transitions (pending → done/empty/failed)
persist for resume; entity vectors land in ``kb_entities``; a document with
>30% failed chunks gets the "graph degraded" flag.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchValue, SparseVector

from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.graph.indexer import GraphIndexStats, index_document_graph
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.vector_store import ChunkUpsert

from ..conftest import requires_qdrant, spy_embed_text


def _payload(entities: list[dict], relations: list[dict] | None = None) -> str:
    return json.dumps({"entities": entities, "relations": relations or []}, ensure_ascii=False)


class _RoutingLLM:
    """Routes canned responses by a needle in the prompt; gleaning disabled in these tests."""

    def __init__(self, routes: list[tuple[str, str]], default: str) -> None:
        self.routes = routes
        self.default = default
        self.calls: list[str] = []

    async def ainvoke(self, messages):
        text = str(messages)
        self.calls.append(text)
        for needle, response in self.routes:
            if needle in text:
                return SimpleNamespace(content=response)
        return SimpleNamespace(content=self.default)


class _StubEmbedder:
    """Deterministic one-hot dense vectors (crc32 of the text picks the
    dimension) — same text always lands on the same axis, distinct texts on
    near-certainly distinct axes, so cosine stays 0 unless names are equal."""

    batch_size = 20

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        import zlib

        self.calls.append(list(texts))
        results = []
        for i, text in enumerate(texts):
            dense = [0.0] * 1024
            dense[zlib.crc32(text.encode("utf-8")) % 1024] = 1.0
            results.append(EmbeddingResult(dense=dense, sparse=SparseVector(indices=[i + 1], values=[0.5])))
        return results


_HAPPY_ROUTES = [
    (
        "DeerFlow 是一个基于 LangGraph",
        _payload(
            [
                {"name": "DeerFlow", "type": "系统", "description": "超级智能体"},
                {"name": "Gateway", "type": "组件", "description": "会话管理"},
            ],
            [{"source": "DeerFlow", "target": "Gateway", "relation": "包含", "description": "系统包含组件"}],
        ),
    ),
    (
        "索引流水线由 Parser",
        _payload(
            [{"name": "Parser", "type": "组件", "description": "文档解析"}, {"name": "parser", "type": "组件", "description": "别名应合并"}],
            [{"source": "Parser", "target": "MinerU", "relation": "调用", "description": "解析服务"}],
        ),
    ),
]


async def _seed_chunk_points(vector_store, kb_id: str, doc_id: str, chunks: list[dict]) -> None:
    """Simulate the completed vector-path leg (Task 4) so the graph backfill has targets."""
    await vector_store.upsert_chunks(
        [
            ChunkUpsert(
                chunk_id=c["chunk_id"],
                kb_id=kb_id,
                doc_id=doc_id,
                dense=[0.0] * 1023 + [1.0],
                sparse=SparseVector(indices=[1], values=[0.5]),
                doc_name="架构.md",
                heading_path=c.get("heading_path") or [],
                page=c.get("page"),
            )
            for c in chunks
        ]
    )


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_status_backfill_and_entity_vectors(graph_env, monkeypatch):
    env = graph_env
    store, vector_store, client = env["store"], env["vector_store"], env["client"]
    kb_id, doc_id = env["kb_id"], env["doc_id"]
    graph_store = GraphStore(store._sf)
    llm = _RoutingLLM(_HAPPY_ROUTES, default=_payload([], []))
    embedder = _StubEmbedder()
    helper_calls = spy_embed_text(monkeypatch, "deerflow.knowledge.graph.indexer", "entity_embed_text")
    chunks = await store.list_chunks(doc_id, limit=10)
    await _seed_chunk_points(vector_store, kb_id, doc_id, chunks)

    stats = await index_document_graph(store, graph_store, vector_store, kb_id=kb_id, doc_id=doc_id, chunks=chunks, llm=llm, embedder=embedder, gleaning_rounds=0)

    assert isinstance(stats, GraphIndexStats)
    assert stats.total == 3
    assert stats.done == 2
    assert stats.empty == 1  # default route yields no entities
    assert stats.failed_chunk_ids == []
    assert stats.degraded is False
    # D3 hook: the resolver consumes the touched entity set after indexing.
    assert stats.touched_entities == {"DeerFlow", "Gateway", "Parser"}

    # Per-chunk status + normalized entity names persisted on the chunk rows.
    rows = {c["chunk_id"]: c for c in await store.list_chunks(doc_id, limit=10)}
    assert rows[f"{doc_id}-c0"]["extract_status"] == "done"
    assert sorted(rows[f"{doc_id}-c0"]["entities"]) == ["DeerFlow", "Gateway"]
    # Case alias merged by the normalizer before persisting.
    assert rows[f"{doc_id}-c1"]["entities"] == ["Parser"]
    assert rows[f"{doc_id}-c2"]["extract_status"] == "empty"

    # Graph store: alias merge happened, chunk ids attached.
    entities = await graph_store.list_entities(kb_id)
    assert sorted(e["name"] for e in entities) == ["DeerFlow", "Gateway", "Parser"]
    relations = await graph_store.list_relations(kb_id)
    assert {(r["source"], r["target"], r["relation"]) for r in relations} == {("DeerFlow", "Gateway", "包含"), ("Parser", "MinerU", "调用")}

    # kb_chunks payload backfilled with the normalized names (spec §3.4 双向链接).
    points, _ = await client.scroll(
        vector_store.chunks_collection,
        scroll_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        with_payload=True,
        limit=10,
    )
    by_chunk = {p.payload["chunk_id"]: p for p in points}
    assert sorted(by_chunk[f"{doc_id}-c0"].payload["entities"]) == ["DeerFlow", "Gateway"]
    assert by_chunk[f"{doc_id}-c1"].payload["entities"] == ["Parser"]

    # Entity vectors upserted into kb_entities with pointer payload.
    epoints, _ = await client.scroll(
        vector_store.entities_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        with_payload=True,
        limit=10,
    )
    assert sorted(p.payload["name"] for p in epoints) == ["DeerFlow", "Gateway", "Parser"]
    assert embedder.calls, "entity embedding should go through the embedder"
    # Same-source pin (spec 2026-09-24 §4.1): the entity-vector pass embeds via the shared helper.
    assert sorted(call[0] for call in helper_calls) == ["DeerFlow", "Gateway", "Parser"], "entity vectors must embed through the shared helper"


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_chunk_marked_failed_and_others_continue(graph_env):
    env = graph_env
    store, graph_store = env["store"], GraphStore(env["store"]._sf)
    kb_id, doc_id = env["kb_id"], env["doc_id"]
    llm = _RoutingLLM([("DeerFlow 是一个基于 LangGraph", _HAPPY_ROUTES[0][1])], default="这不是 JSON")
    chunks = await store.list_chunks(doc_id, limit=10)

    stats = await index_document_graph(store, graph_store, env["vector_store"], kb_id=kb_id, doc_id=doc_id, chunks=chunks, llm=llm, embedder=_StubEmbedder(), gleaning_rounds=0)

    assert stats.done == 1
    assert stats.failed_chunk_ids == [f"{doc_id}-c1", f"{doc_id}-c2"]
    rows = {c["chunk_id"]: c for c in await store.list_chunks(doc_id, limit=10)}
    assert rows[f"{doc_id}-c1"]["extract_status"] == "failed"
    assert "JSON" in rows[f"{doc_id}-c1"]["extract_error"] or "parse" in rows[f"{doc_id}-c1"]["extract_error"].lower()
    # 2/3 failed > 30% → the degraded verdict; the *marker* belongs to the worker since
    # spec 2026-09-23 D8/R8, so the indexer alone must leave ``documents.error`` untouched.
    assert stats.degraded is True
    doc = await store.get_document(doc_id)
    assert doc["error"] is None


@pytest.mark.asyncio
async def test_resume_skips_non_pending_chunks(session_factory):
    from deerflow.knowledge.store import KnowledgeStore

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-r", owner_id="user-1", name="续跑库")
    await store.create_document(doc_id="doc-r", kb_id="kb-r", uploader_id="user-1", name="续跑.md", size_bytes=1, storage_path="/r.md")
    await store.insert_chunks(
        [
            {"chunk_id": "doc-r-c0", "doc_id": "doc-r", "kb_id": "kb-r", "chunk_index": 0, "text": "DeerFlow 是一个基于 LangGraph 的超级智能体系统", "extract_status": "done", "entities": ["DeerFlow"]},
            {"chunk_id": "doc-r-c1", "doc_id": "doc-r", "kb_id": "kb-r", "chunk_index": 1, "text": "索引流水线由 Parser 与 Chunker 组成", "extract_status": "pending"},
        ]
    )
    graph_store = GraphStore(session_factory)
    llm = _RoutingLLM(_HAPPY_ROUTES, default=_payload([], []))
    chunks = await store.list_chunks("doc-r", limit=10)

    stats = await index_document_graph(store, graph_store, None, kb_id="kb-r", doc_id="doc-r", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0)

    # Only the pending chunk is processed; the done one is untouched.
    assert stats.total == 1
    assert len(llm.calls) == 1
    assert "索引流水线" in llm.calls[0]
    assert stats.touched_entities == {"Parser"}
    rows = {c["chunk_id"]: c for c in await store.list_chunks("doc-r", limit=10)}
    assert rows["doc-r-c0"]["entities"] == ["DeerFlow"]  # unchanged
    assert rows["doc-r-c1"]["extract_status"] == "done"
    assert rows["doc-r-c1"]["entities"] == ["Parser"]


@pytest.mark.asyncio
async def test_degraded_threshold_boundary_not_flagged_at_exactly_30_percent(session_factory):
    from deerflow.knowledge.store import KnowledgeStore

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-t", owner_id="user-1", name="阈值库")
    await store.create_document(doc_id="doc-t", kb_id="kb-t", uploader_id="user-1", name="阈值.md", size_bytes=1, storage_path="/t.md")
    # 10 chunks: 3 fail = exactly 30% → NOT degraded (rule is ">30%").
    await store.insert_chunks([{"chunk_id": f"doc-t-c{i}", "doc_id": "doc-t", "kb_id": "kb-t", "chunk_index": i, "text": ("DeerFlow 是一个基于 LangGraph 的智能体" if i >= 3 else f"坏切片{i}")} for i in range(10)])
    llm = _RoutingLLM(_HAPPY_ROUTES, default="broken json")
    chunks = await store.list_chunks("doc-t", limit=20)

    stats = await index_document_graph(store, GraphStore(session_factory), None, kb_id="kb-t", doc_id="doc-t", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0)

    assert stats.done == 7 and len(stats.failed_chunk_ids) == 3
    assert stats.degraded is False
    doc = await store.get_document("doc-t")
    assert doc["error"] is None


@pytest.mark.asyncio
async def test_a_degraded_run_writes_no_error_itself(session_factory):
    """R8: the marker's producer moved to the worker (spec 2026-09-23 D8) — calling the
    indexer alone must not overwrite ``documents.error`` the way ``:209`` used to."""
    from deerflow.knowledge.store import KnowledgeStore

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-w", owner_id="user-1", name="写入点库")
    await store.create_document(doc_id="doc-w", kb_id="kb-w", uploader_id="user-1", name="写入点.md", size_bytes=1, storage_path="/w.md")
    await store.insert_chunks(
        [
            {"chunk_id": "doc-w-c0", "doc_id": "doc-w", "kb_id": "kb-w", "chunk_index": 0, "text": "DeerFlow 是一个基于 LangGraph 的智能体"},
            {"chunk_id": "doc-w-c1", "doc_id": "doc-w", "kb_id": "kb-w", "chunk_index": 1, "text": "坏切片的索引流水线"},
        ]
    )
    llm = _RoutingLLM([("DeerFlow 是一个基于 LangGraph", _payload([], []))], default="broken json")
    chunks = await store.list_chunks("doc-w", limit=20)

    stats = await index_document_graph(store, GraphStore(session_factory), None, kb_id="kb-w", doc_id="doc-w", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0)

    assert stats.degraded is True  # 1/2 failed > 30%: the verdict is still the indexer's
    doc = await store.get_document("doc-w")
    assert doc["error"] is None  # …but the marker is the worker's to write


# ── chunk-level concurrency (spec 2026-10-01 D1/D2) ─────────────────────────


class _InflightLLM:
    """_RoutingLLM plus in-flight peak tracking and per-needle delays.

    The delay table lets a test force completion order to differ from input
    order (so the ordered-merge contract has teeth).
    """

    def __init__(self, routes: list[tuple[str, str]], default: str, delays: list[tuple[str, float]] | None = None) -> None:
        self.routes = routes
        self.default = default
        self.delays = list(delays or [])
        self.inflight = 0
        self.peak = 0
        self.finished: list[str] = []

    async def ainvoke(self, messages):
        text = str(messages)
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        delay = 0.005  # unconditional yield so tasks genuinely overlap
        for needle, seconds in self.delays:
            if needle in text:
                delay = max(delay, seconds)
                break
        try:
            await asyncio.sleep(delay)
        finally:
            self.inflight -= 1
        self.finished.append(text)
        for needle, response in self.routes:
            if needle in text:
                return SimpleNamespace(content=response)
        return SimpleNamespace(content=self.default)


async def _setup_chunks(session_factory, kb_id: str, doc_id: str, specs: list[tuple[str, str]]):
    from deerflow.knowledge.store import KnowledgeStore

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id=kb_id, owner_id="user-1", name=f"并发{kb_id}")
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id="user-1", name="并发.md", size_bytes=1, storage_path="/c.md")
    await store.insert_chunks([{"chunk_id": f"{doc_id}-{suffix}", "doc_id": doc_id, "kb_id": kb_id, "chunk_index": i, "text": text} for i, (suffix, text) in enumerate(specs)])
    return store, GraphStore(session_factory)


@pytest.mark.asyncio
async def test_concurrency_bounds_inflight_extractions(session_factory):
    specs = [(f"c{i}", f"填充切片{i} 没有可抽取内容") for i in range(12)]
    store, graph_store = await _setup_chunks(session_factory, "kb-k", "doc-k", specs)
    llm = _InflightLLM(routes=[], default=_payload([], []))
    chunks = await store.list_chunks("doc-k", limit=20)

    stats = await index_document_graph(store, graph_store, None, kb_id="kb-k", doc_id="doc-k", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0, concurrency=4)

    assert llm.peak > 1, "N=4 must actually overlap extractions"
    assert llm.peak <= 4, "in-flight extractions must never exceed the semaphore"
    assert stats.total == 12 and stats.empty == 12 and stats.done == 0


@pytest.mark.asyncio
async def test_concurrent_results_match_serial_including_order(session_factory):
    specs = [
        ("c0", "第一条 DeerFlow 是一个基于 LangGraph 的智能体"),
        ("c1", "慢的坏切片 坏一"),
        ("c2", "空切片甲 没有实体"),
        ("c3", "第二条 索引流水线由 Parser 与 Chunker 组成"),
        ("c4", "快的坏切片 坏二"),
        ("c5", "空切片乙 没有实体"),
    ]
    store, graph_store = await _setup_chunks(session_factory, "kb-x", "doc-x", specs)
    llm = _InflightLLM(
        routes=[
            ("DeerFlow 是一个基于 LangGraph", _HAPPY_ROUTES[0][1]),
            ("索引流水线由 Parser", _HAPPY_ROUTES[1][1]),
            ("空切片甲", _payload([], [])),
            ("空切片乙", _payload([], [])),
        ],
        default="这不是 JSON",
        delays=[("坏一", 0.05), ("坏二", 0.001)],
    )
    chunks = await store.list_chunks("doc-x", limit=20)

    stats = await index_document_graph(store, graph_store, None, kb_id="kb-x", doc_id="doc-x", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0, concurrency=4)

    # The forced inversion actually happened (completion order != input order)…
    first_failed_pos = next(i for i, t in enumerate(llm.finished) if "坏一" in t)
    second_failed_pos = next(i for i, t in enumerate(llm.finished) if "坏二" in t)
    assert first_failed_pos > second_failed_pos

    # …yet results equal the serial baseline item by item, INCLUDING order.
    assert stats.done == 2 and stats.empty == 2
    assert stats.failed_chunk_ids == ["doc-x-c1", "doc-x-c4"]  # input order, not completion order
    rows = {c["chunk_id"]: c for c in await store.list_chunks("doc-x", limit=20)}
    assert rows["doc-x-c0"]["extract_status"] == "done"
    assert sorted(rows["doc-x-c0"]["entities"]) == ["DeerFlow", "Gateway"]
    assert rows["doc-x-c1"]["extract_status"] == "failed"
    assert rows["doc-x-c2"]["extract_status"] == "empty"
    assert rows["doc-x-c3"]["extract_status"] == "done"
    assert rows["doc-x-c3"]["entities"] == ["Parser"]
    assert rows["doc-x-c4"]["extract_status"] == "failed"
    assert rows["doc-x-c5"]["extract_status"] == "empty"
    assert stats.touched_entities == {"DeerFlow", "Gateway", "Parser"}
    assert stats.degraded is True  # 2/6 failed = 33% > 30%


@pytest.mark.asyncio
async def test_progress_callback_monotonic_under_concurrency(session_factory):
    specs = [(f"c{i}", ("第一条 DeerFlow 是一个基于 LangGraph 的智能体" if i % 2 == 0 else "坏切片 坏一")) for i in range(6)]
    store, graph_store = await _setup_chunks(session_factory, "kb-p", "doc-p", specs)
    llm = _InflightLLM(routes=[("DeerFlow 是一个基于 LangGraph", _HAPPY_ROUTES[0][1])], default="这不是 JSON", delays=[("坏一", 0.03)])
    snapshots: list[tuple[int, int]] = []

    async def _on_progress(settled: int, total: int) -> None:
        snapshots.append((settled, total))

    chunks = await store.list_chunks("doc-p", limit=20)

    await index_document_graph(store, graph_store, None, kb_id="kb-p", doc_id="doc-p", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0, concurrency=4, progress_callback=_on_progress)

    settled_seq = [s for s, _ in snapshots]
    assert snapshots, "progress must fire per settled chunk"
    assert all(t == 6 for _, t in snapshots)
    assert settled_seq == sorted(settled_seq), "settled must never decrease under concurrency"
    assert settled_seq[-1] == 6


class _FlakyLLM:
    """Serves routed responses, but raises a call-level error for the first N hits of a needle.

    Models the transient API failures D3 backs off from (429/timeouts): the same
    request succeeds once the hiccup passes.
    """

    def __init__(self, routes: list[tuple[str, str]], default: str, failures: list[tuple[str, int]]) -> None:
        self.routes = routes
        self.default = default
        self.failures = {needle: remaining for needle, remaining in failures}
        self.calls: list[str] = []

    async def ainvoke(self, messages):
        text = str(messages)
        self.calls.append(text)
        for needle, remaining in self.failures.items():
            if needle in text and remaining > 0:
                self.failures[needle] = remaining - 1
                raise RuntimeError(f"simulated transient API error ({needle})")
        for needle, response in self.routes:
            if needle in text:
                return SimpleNamespace(content=response)
        return SimpleNamespace(content=self.default)


@pytest.mark.asyncio
async def test_transient_llm_error_retries_then_recovers(session_factory):
    specs = [
        ("c0", "DeerFlow 是一个基于 LangGraph 的超级智能体系统"),
        ("c1", "索引流水线由 Parser 与 Chunker 组成"),
    ]
    store, graph_store = await _setup_chunks(session_factory, "kb-f", "doc-f", specs)
    llm = _FlakyLLM(
        routes=[("DeerFlow 是一个基于 LangGraph", _HAPPY_ROUTES[0][1]), ("索引流水线由 Parser", _HAPPY_ROUTES[1][1])],
        default=_payload([], []),
        failures=[("DeerFlow 是一个基于 LangGraph", 1)],
    )
    chunks = await store.list_chunks("doc-f", limit=10)

    stats = await index_document_graph(store, graph_store, None, kb_id="kb-f", doc_id="doc-f", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0)

    assert stats.done == 2 and stats.failed_chunk_ids == []
    assert stats.touched_entities == {"DeerFlow", "Gateway", "Parser"}
    rows = {c["chunk_id"]: c for c in await store.list_chunks("doc-f", limit=10)}
    assert rows["doc-f-c0"]["extract_status"] == "done"
    assert sorted(rows["doc-f-c0"]["entities"]) == ["DeerFlow", "Gateway"]
    # The hiccupped chunk recovered on exactly one retry (2 attempts).
    assert sum("DeerFlow 是一个基于 LangGraph" in text for text in llm.calls) == 2


@pytest.mark.asyncio
async def test_transient_llm_error_soft_fails_chunk_not_document(session_factory):
    specs = [
        ("c0", "坏切片的索引流水线由 Parser 组成"),
        ("c1", "DeerFlow 是一个基于 LangGraph 的超级智能体系统"),
        ("c2", "空切片甲 没有实体"),
    ]
    store, graph_store = await _setup_chunks(session_factory, "kb-g", "doc-g", specs)
    llm = _FlakyLLM(
        routes=[
            ("DeerFlow 是一个基于 LangGraph", _HAPPY_ROUTES[0][1]),
            ("索引流水线由 Parser", _HAPPY_ROUTES[1][1]),
            ("空切片甲", _payload([], [])),
        ],
        default=_payload([], []),
        failures=[("坏切片", 99)],
    )
    chunks = await store.list_chunks("doc-g", limit=10)

    stats = await index_document_graph(store, graph_store, None, kb_id="kb-g", doc_id="doc-g", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0)

    assert stats.failed_chunk_ids == ["doc-g-c0"]
    assert stats.done == 1 and stats.empty == 1
    rows = {c["chunk_id"]: c for c in await store.list_chunks("doc-g", limit=10)}
    assert rows["doc-g-c0"]["extract_status"] == "failed"
    assert "simulated transient API error" in rows["doc-g-c0"]["extract_error"]
    assert rows["doc-g-c1"]["extract_status"] == "done"
    assert rows["doc-g-c2"]["extract_status"] == "empty"
    doc = await store.get_document("doc-g")
    assert doc["error"] is None  # one bad chunk must not fail the document


@pytest.mark.asyncio
async def test_transient_llm_error_retry_budget_is_two_retries(session_factory):
    specs = [("c0", "坏切片 永远失败")]
    store, graph_store = await _setup_chunks(session_factory, "kb-h", "doc-h", specs)
    llm = _FlakyLLM(routes=[], default=_payload([], []), failures=[("坏切片", 99)])
    chunks = await store.list_chunks("doc-h", limit=10)

    stats = await index_document_graph(store, graph_store, None, kb_id="kb-h", doc_id="doc-h", chunks=chunks, llm=llm, embedder=None, gleaning_rounds=0)

    assert stats.failed_chunk_ids == ["doc-h-c0"]
    assert sum("坏切片" in text for text in llm.calls) == 3  # initial attempt + 2 retries, then give up
