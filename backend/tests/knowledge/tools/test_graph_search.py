"""Tests for graph_search (spec §4.2 + 2026-08-10 phase-2 D1).

query → local LLM entity extraction → kb_entities vector match → 1–2 hop
expansion → chunk evidence via ``source_chunk_ids`` (precise), ranked by
semantic scores (guarantee-plus-competition). Empty answers stay honest —
the tool must never fabricate graph content.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from deerflow.knowledge.access import ACCESS_DENIED_MESSAGE, NO_KB_GUIDANCE
from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation
from deerflow.knowledge.graph.normalizer import cosine_similarity
from deerflow.knowledge.reranker import RerankerError
from deerflow.tools.builtins.graph_search_tool import _graph_search_impl

from ..conftest import requires_qdrant
from .conftest import CHUNK_TEXTS, DOC_ID, KB_ID, OWNER_ID, KeywordEmbedder, keyword_vector


class _ConfigRecordingLLM:
    """Captures the invoke config so tests can assert stream-isolation tags."""

    def __init__(self) -> None:
        self.configs: list[dict] = []

    async def ainvoke(self, messages, config=None, **kwargs):
        self.configs.append(config or {})
        return SimpleNamespace(content=json.dumps({"entities": ["x"]}, ensure_ascii=False))


@pytest.mark.asyncio
async def test_extract_query_entities_isolated_from_messages_stream():
    """The extractor is an internal LLM call: without langgraph's TAG_NOSTREAM
    its raw JSON tokens leak onto the run's messages stream and render as an
    assistant message in the UI."""
    from langgraph.constants import TAG_NOSTREAM

    from deerflow.tools.builtins.graph_search_tool import _extract_query_entities

    llm = _ConfigRecordingLLM()
    names = await _extract_query_entities("PDF", llm)

    assert names == ["x"]
    assert llm.configs, "the extractor must invoke the llm"
    tags = llm.configs[0].get("tags") or []
    assert TAG_NOSTREAM in tags, "extractor tokens must stay off the messages stream"


class _RawContentLLM:
    """Returns verbatim extractor output — malformed shapes included."""

    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, messages, **_kwargs):
        return SimpleNamespace(content=self._content)


@pytest.mark.asyncio
async def test_malformed_json_degrades_to_no_names():
    """解析失败 ⇒ []（调用方据此走整句候选兜底）——现状即如此，钉住不许回退。"""
    from deerflow.tools.builtins.graph_search_tool import _extract_query_entities

    names = await _extract_query_entities("Gateway", _RawContentLLM("{not json"))
    assert names == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    ['{"entities": 5}', '{"entities": {"x": 1}}', '{"entities": "PDF"}'],
    ids=["scalar", "object", "string"],
)
async def test_malformed_entity_shapes_degrade_to_no_names(content):
    """畸形形状三态（Task 7 D）：标量会 TypeError 抛死整条图路、对象/字符串
    静默产出垃圾名——都应收敛到 []，与解析失败同一兜底。"""
    from deerflow.tools.builtins.graph_search_tool import _extract_query_entities

    names = await _extract_query_entities("Gateway", _RawContentLLM(content))
    assert names == []


def test_graph_message_notes_pool_exhaustion_when_evidence_below_limit():
    """top_k 是上限而非承诺（2026-09-05）：图谱证据由命中子图的源切片并集
    定义，候选池不足 top_k 时消息必须说明「候选池共 N 片，已全量返回」，
    否则检索测试 UI 里「要 4 给 3」看起来像 bug；池子够大时不加噪声。"""
    from deerflow.tools.builtins.graph_search_tool import format_graph_message

    exhausted = format_graph_message(
        matched=3,
        seen=4,
        relations=1,
        evidence=3,
        pool_size=3,
        evidence_limit=4,
        span="[1]-[3]",
    )
    assert "3 条切片证据" in exhausted
    assert "候选池共 3 片" in exhausted and "已全量返回" in exhausted
    assert "引用编号 [1]-[3]" in exhausted

    full = format_graph_message(
        matched=3,
        seen=4,
        relations=1,
        evidence=4,
        pool_size=6,
        evidence_limit=4,
        span="[1]-[4]",
    )
    assert "候选池" not in full


class _QueryLLM:
    """Extracts the keyword found in the query as the entity list."""

    def __init__(self, entities: list[str]) -> None:
        self._entities = entities
        self.calls: list[str] = []

    async def ainvoke(self, messages, **_kwargs):
        self.calls.append(str(messages))
        return SimpleNamespace(content=json.dumps({"entities": self._entities}, ensure_ascii=False))


def _runtime(**context) -> SimpleNamespace:
    return SimpleNamespace(context=context)


class _FixedReranker:
    """Returns a caller-fixed (index, score) order regardless of content."""

    def __init__(self, order: list[tuple[int, float]]) -> None:
        self._order = order

    async def rerank(self, query, documents, *, top_n: int = 5):
        return self._order[:top_n]


class _FailingReranker:
    async def rerank(self, query, documents, *, top_n: int = 5):
        raise RerankerError("boom")


def _impl_args(tools_env, llm):
    return dict(
        store=tools_env["store"],
        graph_store=tools_env["graph_store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        llm=llm,
    )


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_falls_back_to_query_when_extraction_empty(tools_env):
    """Terse entity-only queries ("Gateway") make the LLM extractor flaky — it
    may return {"entities": []}. The query itself must then serve as the
    landing candidate; the cosine floor keeps chit-chat honest."""
    result = await _graph_search_impl(
        "Gateway",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_impl_args(tools_env, _QueryLLM([])),
    )

    names = {e["name"] for e in result["entities"]}
    assert "Gateway" in names, "query fallback must land on the Gateway entity"
    assert result["evidence"], "the landed entity must surface its source chunks as evidence"


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_falls_back_to_query_when_extraction_is_malformed(tools_env):
    """畸形 JSON 不许抛死图路（Task 7 D）——与空抽取同一条兜底：整句当落点候选。"""
    result = await _graph_search_impl(
        "Gateway",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_impl_args(tools_env, _RawContentLLM('{"entities": 5}')),
    )

    names = {e["name"] for e in result["entities"]}
    assert "Gateway" in names, "malformed extraction must fall back to the query candidate"
    assert result["evidence"]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_expands_and_fetches_evidence(tools_env):
    llm = _QueryLLM(["Gateway"])

    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=tools_env["store"],
        graph_store=tools_env["graph_store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        llm=llm,
        hops=2,
        # Phase-1 behaviour restore path: the one-hot keyword embedder makes
        # cross-keyword cosines 0, so the semantic gate must be disabled here.
        neighbor_min_score=0.0,
    )

    # Matched entity plus its 1-2 hop neighborhood.
    entity_names = {e["name"] for e in result["entities"]}
    assert "Gateway" in entity_names
    assert {"DeerFlow", "MinerU"} <= entity_names  # 1-hop both directions
    triples = {(r["source"], r["relation"], r["target"]) for r in result["relations"]}
    assert ("DeerFlow", "包含", "Gateway") in triples
    assert ("Gateway", "调用", "MinerU") in triples

    # Evidence: chunk text from the business DB with citation metadata.
    texts = [e["text"] for e in result["evidence"]]
    assert any("会话管理" in t for t in texts)
    assert any("文档解析" in t for t in texts)
    sample = result["evidence"][0]
    assert {"chunk_id", "text", "doc_name", "heading_path", "page"} <= set(sample)
    assert sample["doc_name"] == "架构.md"


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_honest_when_nothing_matches(tools_env):
    llm = _QueryLLM(["不存在的实体XYZ"])

    result = await _graph_search_impl(
        "不存在的实体XYZ 是什么？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=tools_env["store"],
        graph_store=tools_env["graph_store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        llm=llm,
    )

    assert result["entities"] == []
    assert result["relations"] == []
    assert result["evidence"] == []
    assert "未" in result["message"] or "没有" in result["message"]  # never fabricate


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_empty_query_entities(tools_env):
    llm = _QueryLLM([])

    result = await _graph_search_impl(
        "随便聊聊",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=tools_env["store"],
        graph_store=tools_env["graph_store"],
        vector_store=tools_env["vector_store"],
        embedder=tools_env["embedder"],
        llm=llm,
    )

    assert result["entities"] == []
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_graph_search_without_kb_returns_guidance(session_factory):
    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import KnowledgeStore

    result = await _graph_search_impl(
        "任意",
        _runtime(user_id=OWNER_ID),
        store=KnowledgeStore(session_factory),
        graph_store=GraphStore(session_factory),
        vector_store=None,
        embedder=None,
        llm=_QueryLLM([]),
    )
    assert result["evidence"] == []
    assert result["message"] == NO_KB_GUIDANCE


@pytest.mark.asyncio
async def test_graph_search_denies_non_owner(session_factory):
    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import KnowledgeStore

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-x", owner_id=OWNER_ID, name="私有")

    result = await _graph_search_impl(
        "任意",
        _runtime(kb_id="kb-x", user_id="user-2"),
        store=store,
        graph_store=GraphStore(session_factory),
        vector_store=None,
        embedder=None,
        llm=_QueryLLM([]),
    )
    assert result["evidence"] == []
    assert result["message"] == ACCESS_DENIED_MESSAGE


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_evidence_carries_scores(tools_env):
    """D1: every evidence item carries the raw score of the scoring channel
    (embedding cosine by default) for recall-test / frontend debugging."""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_impl_args(tools_env, _QueryLLM(["Gateway"])),
    )

    assert result["evidence"]
    for item in result["evidence"]:
        assert isinstance(item["score"], float)


def test_elastic_back_query_method_removed():
    """D4: the channel-3 elastic back-query is gone for good — the vector
    store no longer exposes ``scroll_chunks_by_entities`` (the payload
    ``entities`` tag and its KEYWORD index stay: they feed the chunk-drawer
    display and the future true-mention marker)."""
    from deerflow.knowledge.vector_store import KnowledgeVectorStore

    assert not hasattr(KnowledgeVectorStore, "scroll_chunks_by_entities")


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_reranker_decides_order_when_enabled(tools_env):
    """D1 optional precision pass: with graph_rerank on and candidates above
    the threshold, the reranker score decides the evidence order."""
    # Give Gateway a second birth-certificate chunk so its guarantee queue
    # holds two slices and the rerank order becomes observable.
    await tools_env["graph_store"].upsert_entities(
        KB_ID,
        [ExtractedEntity(name="Gateway", type="组件", description="会话管理入口")],
        chunk_id=f"{DOC_ID}-c2",
    )
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_impl_args(tools_env, _QueryLLM(["Gateway"])),
        reranker=_FixedReranker([(2, 0.99), (1, 0.5), (0, 0.01)]),
        graph_rerank=True,
        rerank_threshold=1,
        neighbor_min_score=0.0,
    )

    assert [e["chunk_id"] for e in result["evidence"]] == [f"{DOC_ID}-c2", f"{DOC_ID}-c0", f"{DOC_ID}-c1"]
    assert result["evidence"][0]["score"] == pytest.approx(0.99)


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_reranker_error_falls_back_to_embedding_order(tools_env):
    """D1 degradation: RerankerError falls back to the embedding-cosine order
    instead of failing the search."""
    await tools_env["graph_store"].upsert_entities(
        KB_ID,
        [ExtractedEntity(name="Gateway", type="组件", description="会话管理入口")],
        chunk_id=f"{DOC_ID}-c2",
    )
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_impl_args(tools_env, _QueryLLM(["Gateway"])),
        reranker=_FailingReranker(),
        graph_rerank=True,
        rerank_threshold=1,
        neighbor_min_score=0.0,
    )

    # Cosine order: c0/c1 contain the Gateway keyword (1.0), c2 does not (0.0)
    # — guarantee draws c0 then c2, competition appends c1.
    assert [e["chunk_id"] for e in result["evidence"]] == [f"{DOC_ID}-c0", f"{DOC_ID}-c2", f"{DOC_ID}-c1"]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_prunes_irrelevant_neighbors(tools_env):
    """D2: with the default gate, neighbours orthogonal to the query (cosine 0
    under the one-hot embedder) never enter the seen subgraph."""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_impl_args(tools_env, _QueryLLM(["Gateway"])),
        neighbor_min_score=0.4,
    )

    assert {e["name"] for e in result["entities"]} == {"Gateway"}
    assert result["relations"] == []  # both edges lose one endpoint to pruning
    assert [e["chunk_id"] for e in result["evidence"]] == [f"{DOC_ID}-c0"]


class _BlendEmbedder(KeywordEmbedder):
    """Query embeddings mentioning DeerFlow get its one-hot dim blended in, so
    the DeerFlow neighbour passes the semantic gate (cosine ≈ 0.57) while
    MinerU stays orthogonal."""

    async def embed(self, texts, *, text_type: str = "document"):
        results = await super().embed(texts, text_type=text_type)
        if text_type == "query":
            for result, text in zip(results, texts, strict=True):
                if "DeerFlow" in text:
                    result.dense[30] = 0.7
        return results


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_search_semantic_gate_keeps_related_neighbor(tools_env):
    """D2: a related neighbour passes the gate, an unrelated one is pruned."""
    result = await _graph_search_impl(
        "DeerFlow 的 Gateway 如何交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=tools_env["store"],
        graph_store=tools_env["graph_store"],
        vector_store=tools_env["vector_store"],
        embedder=_BlendEmbedder(),
        llm=_QueryLLM(["Gateway"]),
        neighbor_min_score=0.4,
    )

    assert {e["name"] for e in result["entities"]} == {"Gateway", "DeerFlow"}
    triples = {(r["source"], r["relation"], r["target"]) for r in result["relations"]}
    assert ("DeerFlow", "包含", "Gateway") in triples
    assert ("Gateway", "调用", "MinerU") not in triples  # MinerU pruned
    assert [e["chunk_id"] for e in result["evidence"]] == [f"{DOC_ID}-c0"]


# ── Task 5（P4，2026-08-19 spec §7）：retrieval trace 透传 ──────────────────
# 前端知识图谱的「种子 → 扩展 → 证据」三层路径高亮以工具响应里的 trace 为唯一
# 数据源（只序列化输出，不动检索逻辑）。下列用例走内存 fake vector store，
# 无需 Qdrant——向量打分用与 KeywordEmbedder 相同的 one-hot 关键词向量，语义门
# 行为确定。


class _FakeVectorStore:
    """In-memory vector store for trace tests — no Qdrant needed.

    Entity/chunk vectors use the same one-hot keyword layout as
    ``KeywordEmbedder``, so cosine gating stays deterministic.
    """

    def __init__(self, entity_names: list[str], chunk_texts: list[tuple[str, str]]) -> None:
        self._entity_vectors = {name: keyword_vector(name) for name in entity_names}
        self._chunk_vectors = {chunk_id: keyword_vector(text) for chunk_id, text in chunk_texts}

    async def query_entities(self, *, dense, kb_id, top_k, score_threshold):
        hits = []
        for name, vector in self._entity_vectors.items():
            score = cosine_similarity(list(dense), vector)
            if score >= score_threshold:
                hits.append(SimpleNamespace(payload={"name": name}, score=score))
        hits.sort(key=lambda hit: (-hit.score, hit.payload["name"]))
        return hits[:top_k]

    async def get_entity_vectors(self, kb_id, names):
        return {name: self._entity_vectors[name] for name in names if name in self._entity_vectors}

    async def get_chunk_vectors(self, chunk_ids):
        return {chunk_id: self._chunk_vectors[chunk_id] for chunk_id in chunk_ids if chunk_id in self._chunk_vectors}


@pytest_asyncio.fixture
async def trace_env(session_factory):
    """SQLite-backed graph/chunk fixture + in-memory vector store (no Qdrant)."""
    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import KnowledgeStore

    store = KnowledgeStore(session_factory)
    graph_store = GraphStore(session_factory)
    await store.create_kb(kb_id=KB_ID, owner_id=OWNER_ID, name="trace 测试库")
    await store.create_document(doc_id=DOC_ID, kb_id=KB_ID, uploader_id=OWNER_ID, name="架构.md", size_bytes=10, storage_path="/a.md")
    await store.insert_chunks(
        [
            {
                "chunk_id": f"{DOC_ID}-c{i}",
                "doc_id": DOC_ID,
                "kb_id": KB_ID,
                "chunk_index": i,
                "text": text,
                "heading_path": ["架构"],
                "page": i + 1,
                "token_count": 40,
                "extract_status": "done" if entities else "empty",
                "entities": entities,
            }
            for i, (text, entities) in enumerate(CHUNK_TEXTS)
        ]
    )
    await graph_store.upsert_entities(KB_ID, [ExtractedEntity(name="DeerFlow", type="系统", description="超级智能体")], chunk_id=f"{DOC_ID}-c0")
    await graph_store.upsert_entities(KB_ID, [ExtractedEntity(name="Gateway", type="组件", description="会话管理入口")], chunk_id=f"{DOC_ID}-c0")
    await graph_store.upsert_entities(KB_ID, [ExtractedEntity(name="MinerU", type="服务", description="文档解析服务")], chunk_id=f"{DOC_ID}-c1")
    await graph_store.upsert_relations(KB_ID, [ExtractedRelation(source="DeerFlow", target="Gateway", relation="包含", description="系统包含入口组件")], chunk_id=f"{DOC_ID}-c0")
    await graph_store.upsert_relations(KB_ID, [ExtractedRelation(source="Gateway", target="MinerU", relation="调用", description="解析调用")], chunk_id=f"{DOC_ID}-c1")
    return {
        "store": store,
        "graph_store": graph_store,
        "vector_store": _FakeVectorStore(
            ["DeerFlow", "Gateway", "MinerU"],
            [(f"{DOC_ID}-c{i}", text) for i, (text, _entities) in enumerate(CHUNK_TEXTS)],
        ),
        "embedder": KeywordEmbedder(),
    }


def _trace_impl_args(trace_env, llm):
    return dict(
        store=trace_env["store"],
        graph_store=trace_env["graph_store"],
        vector_store=trace_env["vector_store"],
        embedder=trace_env["embedder"],
        llm=llm,
    )


@pytest.mark.asyncio
async def test_graph_search_response_carries_three_layer_trace(trace_env):
    """P4: the response exposes the seed → expansion → evidence trace — the
    only data source of the frontend retrieval-path overlay (serialization
    only; the retrieval logic itself is untouched)."""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        hops=2,
        neighbor_min_score=0.0,
    )

    trace = result["trace"]
    # 种子 = 向量命中的 hop-0 实体（确定性排序）。
    assert trace["seed_entities"] == ["Gateway"]
    # 扩展节点带 hop 层级（按 hop、名字排序——契约稳定）。
    assert trace["expanded_nodes"] == [
        {"name": "DeerFlow", "hop": 1},
        {"name": "MinerU", "hop": 1},
    ]
    # 证据实体 = 每条选中切片归因的最强来源锚点（hop 最小 → 实体分最高 → 名字
    # 典序），有界于证据条数。真实库中一切片可被 8–29 个实体共同提及（2026-08-20
    # 实测 median 16），若退化为「提及该切片的所有实体」会把命中层洪泛成全图红。
    # c0 来源 {Gateway(hop0), DeerFlow(hop1)} → 锚点 Gateway；c1 同理锚定 Gateway。
    assert trace["evidence_entities"] == ["Gateway"]
    assert len(trace["evidence_entities"]) <= len(result["evidence"])


@pytest.mark.asyncio
async def test_graph_search_emits_retrieval_trace_custom_event(trace_env, monkeypatch):
    """实时通道契约：三层轨迹同时走 custom stream 事件。工具输出预算中间件可能把
    超大 ToolMessage 替换成摘要预览（trace 随之不可解析），前端路径高亮改为消费
    这条事件——它发射于工具内部、任何预算中间件运行之前，不受外置影响。"""
    import deerflow.tools.builtins.graph_search_tool as gst

    captured: list[dict] = []

    class _Writer:
        def __call__(self, payload):
            captured.append(payload)

    monkeypatch.setattr(gst, "get_stream_writer", lambda: _Writer())

    runtime = _runtime(kb_id=KB_ID, user_id=OWNER_ID)
    runtime.tool_call_id = "call_trace_1"

    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        runtime,
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        hops=2,
        neighbor_min_score=0.0,
    )

    assert len(captured) == 1
    event = captured[0]
    assert event["type"] == gst.GRAPH_RETRIEVAL_TRACE_EVENT_TYPE
    assert event["tool_call_id"] == "call_trace_1"
    assert event["kb_id"] == KB_ID
    # 事件里的轨迹与消息里的轨迹逐字一致——两条通道同源，重载解析契约不变。
    assert event["trace"] == result["trace"]
    assert result["trace"]["seed_entities"] == ["Gateway"]


@pytest.mark.asyncio
async def test_graph_search_without_stream_context_stays_silent(trace_env):
    """直接调用/单测没有 runnable 上下文，get_stream_writer 会抛 RuntimeError；
    工具必须静默跳过事件发射，不影响检索结果本身。"""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        hops=2,
        neighbor_min_score=0.0,
    )

    assert result["trace"]["seed_entities"] == ["Gateway"]


@pytest.mark.asyncio
async def test_graph_search_trace_evidence_anchors_stay_bounded(trace_env):
    """证据锚点有界性：每条选中切片最多贡献一个锚点实体（防命中层洪泛）。

    稠密图谱中一切片被大量实体共同提及是常态——锚点归因保证 evidence_entities
    的规模 ≤ 证据条数，而不是实体的笛卡尔洪泛。
    """
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        hops=2,
        neighbor_min_score=0.0,
    )

    trace = result["trace"]
    assert result["evidence"], "fixture 必须有证据切片"
    assert 0 < len(trace["evidence_entities"]) <= len(result["evidence"])
    # 锚点必须落在 seen 子图内（种子 ∪ 扩展）。
    seen = set(trace["seed_entities"]) | {node["name"] for node in trace["expanded_nodes"]}
    assert set(trace["evidence_entities"]) <= seen


@pytest.mark.asyncio
async def test_graph_search_trace_hop_info_complete(trace_env):
    """hop layering: seeds never appear among expanded nodes; hop ≥ 1."""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        hops=2,
        neighbor_min_score=0.0,
    )

    trace = result["trace"]
    seeds = set(trace["seed_entities"])
    assert trace["expanded_nodes"], "expansion must reach neighbours with the gate off"
    assert all(node["hop"] >= 1 for node in trace["expanded_nodes"])
    assert all(node["hop"] <= 2 for node in trace["expanded_nodes"])
    assert seeds.isdisjoint(node["name"] for node in trace["expanded_nodes"])


@pytest.mark.asyncio
async def test_graph_search_trace_reflects_pruning(trace_env):
    """With the semantic gate on, pruned neighbours never enter the trace."""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        neighbor_min_score=0.4,
    )

    trace = result["trace"]
    assert trace["seed_entities"] == ["Gateway"]
    assert trace["expanded_nodes"] == []
    # 仅 Gateway 留在 seen 子图——证据只可能来自它自己的切片 c0。
    assert trace["evidence_entities"] == ["Gateway"]


@pytest.mark.asyncio
async def test_graph_search_empty_response_carries_empty_trace(session_factory):
    """Uniform contract: honest-empty answers still carry an (empty) trace —
    the frontend parser never special-cases a missing field."""
    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import KnowledgeStore

    result = await _graph_search_impl(
        "任意",
        _runtime(user_id=OWNER_ID),
        store=KnowledgeStore(session_factory),
        graph_store=GraphStore(session_factory),
        vector_store=None,
        embedder=None,
        llm=_QueryLLM([]),
    )

    assert result["trace"] == {"seed_entities": [], "expanded_nodes": [], "evidence_entities": []}


# ── Task 3（spec 2026-09-24 §4.2，D2 乙）：图谱路回报这一跑的尺子 ─────────────
# 召回面板的徽标渲染「实际参与打分的那个东西」——只有 impl 知道这一跑真跑了
# 重排没有（小池不触发、RerankerError 降级都落回余弦序），所以由它回报。


@pytest.mark.asyncio
async def test_graph_search_reports_cosine_ruler_for_small_pool(trace_env):
    """池子够不到阈值 ⇒ 根本没跑重排，尺子回报 "cosine"（不是配置的能力）。"""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        reranker=_FixedReranker([(1, 0.99), (0, 0.5)]),
        graph_rerank=True,
        rerank_threshold=99,
        neighbor_min_score=0.0,
    )

    assert result["evidence"], "fixture 必须有证据切片，否则池子为空、结论无意义"
    assert result["score_source"] == "cosine"


@pytest.mark.asyncio
async def test_graph_search_reports_rerank_ruler_when_it_reranked(trace_env):
    """池子超过阈值且重排成功 ⇒ 尺子回报 "rerank"（服务层据此渲染模型名）。"""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        reranker=_FixedReranker([(1, 0.99), (0, 0.5)]),
        graph_rerank=True,
        rerank_threshold=1,
        neighbor_min_score=0.0,
    )

    assert result["evidence"]
    assert result["score_source"] == "rerank"


@pytest.mark.asyncio
async def test_graph_search_reports_cosine_ruler_after_rerank_degradation(trace_env):
    """重排抛 RerankerError ⇒ 回落余弦序，尺子也必须如实回报 "cosine"。"""
    result = await _graph_search_impl(
        "Gateway 和哪些组件交互？",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        **_trace_impl_args(trace_env, _QueryLLM(["Gateway"])),
        reranker=_FailingReranker(),
        graph_rerank=True,
        rerank_threshold=1,
        neighbor_min_score=0.0,
    )

    assert result["evidence"]
    assert result["score_source"] == "cosine"
