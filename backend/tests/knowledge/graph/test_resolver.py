"""Tests for the incremental global entity re-resolution (spec 2026-08-10 D3).

Per-slice normalization only merges aliases inside one chunk's extraction;
this resolver runs after a document's graph indexing and merges cross-slice
aliases (``Model``/``Models`` living on different chunks) with the full
side-effect chain: graph rows → relation endpoints → ``kb_entities`` vectors
→ chunk entity tags (business DB + payload dual write) → wiki lifecycle
(alias entries deleted outright, the representative marked dirty).
Everything is idempotent; failure never blocks the indexing pipeline (the
worker degrades with a visible document error sub-marker).
"""

from __future__ import annotations

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchValue, SparseVector

from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation
from deerflow.knowledge.graph.resolver import ResolutionStats, resolve_entity_aliases
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.vector_store import ChunkUpsert, EntityUpsert, WikiEntryUpsert
from deerflow.knowledge.wiki.store import WikiStore, wiki_entry_id

from ..conftest import requires_qdrant, spy_embed_text


class _TableEmbedder:
    """Fixed vector table keyed by the exact embedded text; records calls."""

    batch_size = 20

    def __init__(self, vectors: dict[str, list[float]] | None = None) -> None:
        self._vectors = vectors or {}
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        self.calls.append(list(texts))
        return [EmbeddingResult(dense=self._vectors.get(text, [0.0] * 1024), sparse=SparseVector(indices=[1], values=[0.5])) for text in texts]


def _dims(mapping: dict[int, float]) -> list[float]:
    dense = [0.0] * 1024
    for dim, value in mapping.items():
        dense[dim] = value
    return dense


async def _seed_chunk_points(vector_store, kb_id: str, doc_id: str) -> None:
    await vector_store.upsert_chunks(
        [
            ChunkUpsert(
                chunk_id=f"{doc_id}-c{i}",
                kb_id=kb_id,
                doc_id=doc_id,
                dense=_dims({999: 1.0}),
                sparse=SparseVector(indices=[1], values=[0.5]),
                doc_name="架构.md",
            )
            for i in range(3)
        ]
    )


def _resolver_env(graph_env) -> dict:
    store = graph_env["store"]
    return {
        "store": store,
        "graph_store": GraphStore(store._sf),
        "vector_store": graph_env["vector_store"],
        "wiki_store": WikiStore(store._sf),
        "client": graph_env["client"],
        "kb_id": graph_env["kb_id"],
        "doc_id": graph_env["doc_id"],
    }


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_merges_surface_aliases_and_rewrites_everything(graph_env, monkeypatch):
    env = _resolver_env(graph_env)
    store, graph_store, vector_store, wiki_store, client = env["store"], env["graph_store"], env["vector_store"], env["wiki_store"], env["client"]
    kb_id, doc_id = env["kb_id"], env["doc_id"]
    c0, c1 = f"{doc_id}-c0", f"{doc_id}-c1"
    await _seed_chunk_points(vector_store, kb_id, doc_id)

    # Cross-slice alias state: two rows for one real-world entity.
    await graph_store.upsert_entities(kb_id, [ExtractedEntity(name="Model", type="概念", description="模型片段A")], chunk_id=c0)
    await graph_store.upsert_entities(kb_id, [ExtractedEntity(name="Models", type="概念", description="模型片段B")], chunk_id=c1)
    await graph_store.upsert_entities(kb_id, [ExtractedEntity(name="Trainer", type="概念", description="训练器")], chunk_id=c0)
    await graph_store.upsert_relations(kb_id, [ExtractedRelation(source="Model", target="Trainer", relation="依赖", description="关系A")], chunk_id=c0)
    await graph_store.upsert_relations(kb_id, [ExtractedRelation(source="Models", target="Trainer", relation="依赖", description="关系B")], chunk_id=c1)
    await graph_store.upsert_relations(kb_id, [ExtractedRelation(source="Model", target="Models", relation="同义", description="自环伏笔")], chunk_id=c0)
    await store.update_chunk_extract(c0, "done", entities=["Model", "Trainer"])
    await store.update_chunk_extract(c1, "done", entities=["Models"])
    await vector_store.upsert_entities(
        [
            EntityUpsert(name="Model", kb_id=kb_id, type="概念", description="模型片段A", dense=_dims({0: 1.0})),
            EntityUpsert(name="Models", kb_id=kb_id, type="概念", description="模型片段B", dense=_dims({1: 1.0})),
            EntityUpsert(name="Trainer", kb_id=kb_id, type="概念", description="训练器", dense=_dims({2: 1.0})),
        ]
    )
    await wiki_store.upsert_entry(kb_id, title="Model", content="# Model", source_chunk_ids=[c0])
    await wiki_store.upsert_entry(kb_id, title="Models", content="# Models", source_chunk_ids=[c1])
    await vector_store.upsert_wiki_entries(
        [
            WikiEntryUpsert(entry_id=wiki_entry_id(kb_id, "Model"), kb_id=kb_id, title="Model", dense=_dims({5: 1.0})),
            WikiEntryUpsert(entry_id=wiki_entry_id(kb_id, "Models"), kb_id=kb_id, title="Models", dense=_dims({6: 1.0})),
        ]
    )
    embedder = _TableEmbedder()
    helper_calls = spy_embed_text(monkeypatch, "deerflow.knowledge.graph.resolver", "entity_embed_text")

    stats = await resolve_entity_aliases(store, graph_store, vector_store, wiki_store, embedder, kb_id=kb_id, touched_entities={"Model", "Models"})

    assert isinstance(stats, ResolutionStats)
    assert stats.merged_groups == 1
    assert stats.merged_entities == 1
    # ① Entity rows: representative (name-order first) absorbs the alias.
    by_name = {e["name"]: e for e in await graph_store.list_entities(kb_id)}
    assert sorted(by_name) == ["Model", "Trainer"]
    assert "模型片段A" in by_name["Model"]["description"] and "模型片段B" in by_name["Model"]["description"]
    assert sorted(by_name["Model"]["source_chunk_ids"]) == sorted([c0, c1])
    # ② Relations: endpoints rewritten, duplicate triple merged, self-loop dropped.
    relations = await graph_store.list_relations(kb_id)
    assert [(r["source"], r["target"], r["relation"]) for r in relations] == [("Model", "Trainer", "依赖")]
    assert "关系A" in relations[0]["description"] and "关系B" in relations[0]["description"]
    assert sorted(relations[0]["source_chunk_ids"]) == sorted([c0, c1])
    # ③ kb_entities: alias vector deleted, representative re-embedded.
    epoints, _ = await client.scroll(
        vector_store.entities_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        with_payload=True,
        limit=10,
    )
    assert sorted(p.payload["name"] for p in epoints) == ["Model", "Trainer"]
    assert embedder.calls[-1][0].startswith("Model\n")
    # Same-source pin (spec 2026-09-24 §4.1): the representative re-embed goes through the shared helper.
    assert [call[0] for call in helper_calls] == ["Model"], "representative re-embed must use the shared helper"
    # ④ Dual write: business-DB column and Qdrant payload both rewritten.
    rows = {c["chunk_id"]: c for c in await store.list_chunks(doc_id, limit=10)}
    assert sorted(rows[c0]["entities"]) == ["Model", "Trainer"]
    assert rows[c1]["entities"] == ["Model"]
    points, _ = await client.scroll(
        vector_store.chunks_collection,
        scroll_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        with_payload=True,
        limit=10,
    )
    by_chunk = {p.payload["chunk_id"]: p for p in points}
    assert sorted(by_chunk[c0].payload["entities"]) == ["Model", "Trainer"]
    assert by_chunk[c1].payload["entities"] == ["Model"]
    # ⑤ Wiki lifecycle: the merged-away alias entry is deleted outright —
    #    business row and kb_wiki_entries vector point both go (its entity no
    #    longer exists, so the title has nothing left to regenerate from);
    #    the representative's entry turns dirty for incremental regeneration.
    assert {e["title"]: e["status"] for e in await wiki_store.list_entries(kb_id)} == {"Model": "dirty"}
    wpoints, _ = await client.scroll(
        vector_store.wiki_entries_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        with_payload=True,
        limit=10,
    )
    assert [p.payload["title"] for p in wpoints] == ["Model"]

    # Idempotent: a second run finds nothing to merge.
    second = await resolve_entity_aliases(store, graph_store, vector_store, wiki_store, embedder, kb_id=kb_id, touched_entities={"Model"})
    assert second.merged_groups == 0
    assert second.merged_entities == 0


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_similarity_merge_respects_threshold(graph_env):
    env = _resolver_env(graph_env)
    graph_store, vector_store = env["graph_store"], env["vector_store"]
    kb_id = env["kb_id"]
    for name in ("Qdrant", "Qdrant向量库", "数据库", "数据仓库"):
        await graph_store.upsert_entities(kb_id, [ExtractedEntity(name=name, type="概念", description=f"{name} 描述")], chunk_id=f"{env['doc_id']}-c0")
    await vector_store.upsert_entities(
        [
            EntityUpsert(name="Qdrant", kb_id=kb_id, dense=_dims({0: 1.0})),
            EntityUpsert(name="Qdrant向量库", kb_id=kb_id, dense=_dims({0: 0.95, 1: 0.3122})),  # cos ≈ 0.95 ≥ 0.92
            EntityUpsert(name="数据库", kb_id=kb_id, dense=_dims({2: 1.0})),
            EntityUpsert(name="数据仓库", kb_id=kb_id, dense=_dims({2: 0.8, 3: 0.6})),  # cos = 0.8 < 0.92
        ]
    )

    stats = await resolve_entity_aliases(env["store"], graph_store, vector_store, env["wiki_store"], _TableEmbedder(), kb_id=kb_id, touched_entities={"Qdrant"})

    assert stats.merged_groups == 1
    by_name = {e["name"]: e for e in await graph_store.list_entities(kb_id)}
    # only the ≥0.92 pair merged ("数据仓库" sorts before "数据库": U+4ED3 < U+5E93)
    assert sorted(by_name) == ["Qdrant", "数据仓库", "数据库"]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_parenthetical_fold_merges_cross_language_pair(graph_env):
    """Task 10: ``String``/``字符串（String）`` share a parenthetical fold key, so
    they merge even with orthogonal vectors, and the parenthetical full name
    becomes the representative (name order would pick the pure-ASCII ``String``)."""
    env = _resolver_env(graph_env)
    store, graph_store, vector_store, wiki_store, client = env["store"], env["graph_store"], env["vector_store"], env["wiki_store"], env["client"]
    kb_id, doc_id = env["kb_id"], env["doc_id"]
    c0, c1 = f"{doc_id}-c0", f"{doc_id}-c1"
    await _seed_chunk_points(vector_store, kb_id, doc_id)

    await graph_store.upsert_entities(kb_id, [ExtractedEntity(name="String", type="概念", description="字符串类型片段A")], chunk_id=c0)
    await graph_store.upsert_entities(kb_id, [ExtractedEntity(name="字符串（String）", type="概念", description="字符串类型片段B")], chunk_id=c1)
    await graph_store.upsert_entities(kb_id, [ExtractedEntity(name="JVM", type="组件", description="运行时")], chunk_id=c0)
    await graph_store.upsert_relations(kb_id, [ExtractedRelation(source="String", target="JVM", relation="运行于", description="关系A")], chunk_id=c0)
    await store.update_chunk_extract(c0, "done", entities=["String", "JVM"])
    await store.update_chunk_extract(c1, "done", entities=["字符串（String）"])
    # Orthogonal vectors: only the parenthetical fold can merge this pair.
    await vector_store.upsert_entities(
        [
            EntityUpsert(name="String", kb_id=kb_id, type="概念", description="字符串类型片段A", dense=_dims({0: 1.0})),
            EntityUpsert(name="字符串（String）", kb_id=kb_id, type="概念", description="字符串类型片段B", dense=_dims({1: 1.0})),
            EntityUpsert(name="JVM", kb_id=kb_id, type="组件", description="运行时", dense=_dims({2: 1.0})),
        ]
    )
    await wiki_store.upsert_entry(kb_id, title="String", content="# String", source_chunk_ids=[c0])
    await wiki_store.upsert_entry(kb_id, title="字符串（String）", content="# 字符串（String）", source_chunk_ids=[c1])
    await vector_store.upsert_wiki_entries(
        [
            WikiEntryUpsert(entry_id=wiki_entry_id(kb_id, "String"), kb_id=kb_id, title="String", dense=_dims({5: 1.0})),
            WikiEntryUpsert(entry_id=wiki_entry_id(kb_id, "字符串（String）"), kb_id=kb_id, title="字符串（String）", dense=_dims({6: 1.0})),
        ]
    )

    stats = await resolve_entity_aliases(store, graph_store, vector_store, wiki_store, _TableEmbedder(), kb_id=kb_id, touched_entities={"String"})

    assert stats.merged_groups == 1
    assert stats.merged_entities == 1
    # ① Entity rows: full name absorbs the ASCII alias; descriptions/chunks union.
    by_name = {e["name"]: e for e in await graph_store.list_entities(kb_id)}
    assert sorted(by_name) == ["JVM", "字符串（String）"]
    assert "字符串类型片段A" in by_name["字符串（String）"]["description"] and "字符串类型片段B" in by_name["字符串（String）"]["description"]
    assert sorted(by_name["字符串（String）"]["source_chunk_ids"]) == sorted([c0, c1])
    # ② Relation endpoint rewritten onto the representative.
    relations = await graph_store.list_relations(kb_id)
    assert [(r["source"], r["target"]) for r in relations] == [("字符串（String）", "JVM")]
    # ③ kb_entities: alias vector deleted; only representative + JVM remain.
    epoints, _ = await client.scroll(
        vector_store.entities_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        with_payload=True,
        limit=10,
    )
    assert sorted(p.payload["name"] for p in epoints) == ["JVM", "字符串（String）"]
    # ④ Chunk entity tags rewritten (business DB + Qdrant payload dual write).
    rows = {c["chunk_id"]: c for c in await store.list_chunks(doc_id, limit=10)}
    assert sorted(rows[c0]["entities"]) == ["JVM", "字符串（String）"]
    assert rows[c1]["entities"] == ["字符串（String）"]
    # ⑤ Wiki lifecycle: alias entry + vector point deleted; representative dirty.
    assert {e["title"]: e["status"] for e in await wiki_store.list_entries(kb_id)} == {"字符串（String）": "dirty"}
    wpoints, _ = await client.scroll(
        vector_store.wiki_entries_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        with_payload=True,
        limit=10,
    )
    assert [p.payload["title"] for p in wpoints] == ["字符串（String）"]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_scope_limited_to_touched_plus_one_hop_on_large_graph(graph_env):
    env = _resolver_env(graph_env)
    graph_store = env["graph_store"]
    kb_id = env["kb_id"]
    # "Node" / "Nodes" share the alias key; only B is connected to Node.
    for name in ("Node", "Nodes", "B"):
        await graph_store.upsert_entities(kb_id, [ExtractedEntity(name=name, type="概念", description=f"{name} 描述")], chunk_id=f"{env['doc_id']}-c0")
    await graph_store.upsert_relations(kb_id, [ExtractedRelation(source="Node", target="B", relation="关联", description="")], chunk_id=f"{env['doc_id']}-c0")

    # Graph size 3 ≥ threshold 2 → scoped mode: {Node} + 1-hop = {Node, B}; "Nodes" out of scope.
    stats = await resolve_entity_aliases(env["store"], graph_store, env["vector_store"], env["wiki_store"], _TableEmbedder(), kb_id=kb_id, touched_entities={"Node"}, full_scan_threshold=2)

    assert stats.scanned == 2
    assert stats.merged_groups == 0
    assert sorted(e["name"] for e in await graph_store.list_entities(kb_id)) == ["B", "Node", "Nodes"]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_scan_below_threshold_merges_regardless_of_touched(graph_env):
    env = _resolver_env(graph_env)
    graph_store = env["graph_store"]
    kb_id = env["kb_id"]
    for name in ("Node", "Nodes"):
        await graph_store.upsert_entities(kb_id, [ExtractedEntity(name=name, type="概念", description=f"{name} 描述")], chunk_id=f"{env['doc_id']}-c0")

    # Graph size 2 < default threshold 500 → full table scan, touched irrelevant.
    stats = await resolve_entity_aliases(env["store"], graph_store, env["vector_store"], env["wiki_store"], _TableEmbedder(), kb_id=kb_id, touched_entities=set())

    assert stats.merged_groups == 1
    assert sorted(e["name"] for e in await graph_store.list_entities(kb_id)) == ["Node"]


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_empty_touched_skips_scoped_mode(graph_env):
    env = _resolver_env(graph_env)
    graph_store = env["graph_store"]
    kb_id = env["kb_id"]
    for name in ("Node", "Nodes", "B"):
        await graph_store.upsert_entities(kb_id, [ExtractedEntity(name=name, type="概念", description=f"{name} 描述")], chunk_id=f"{env['doc_id']}-c0")

    stats = await resolve_entity_aliases(env["store"], graph_store, env["vector_store"], env["wiki_store"], _TableEmbedder(), kb_id=kb_id, touched_entities=set(), full_scan_threshold=2)

    assert stats.scanned == 0
    assert stats.merged_groups == 0
