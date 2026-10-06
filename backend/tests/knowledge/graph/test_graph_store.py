"""Tests for the SQLite graph store + NetworkX loader (spec §3.4).

Same-name entities merge LightRAG-style inside one KB (description append +
``source_chunk_ids`` union); the uniqueness scope is ``(kb_id, name)``, so two
KBs keep independent graphs.
"""

from __future__ import annotations

import pytest

from deerflow.knowledge.graph.extractor import ExtractedEntity, ExtractedRelation
from deerflow.knowledge.graph.store import GraphStore


@pytest.mark.asyncio
async def test_upsert_entities_persists_rows_with_source_chunk_ids(session_factory):
    store = GraphStore(session_factory)

    await store.upsert_entities("kb-1", [ExtractedEntity(name="DeerFlow", type="系统", description="智能体框架")], chunk_id="c-1")

    entities = await store.list_entities("kb-1")
    assert len(entities) == 1
    row = entities[0]
    assert row["name"] == "DeerFlow"
    assert row["type"] == "系统"
    assert row["description"] == "智能体框架"
    assert row["source_chunk_ids"] == ["c-1"]
    assert row["status"] == "ready"


@pytest.mark.asyncio
async def test_same_name_entity_merges_description_and_chunk_ids(session_factory):
    store = GraphStore(session_factory)

    await store.upsert_entities("kb-1", [ExtractedEntity(name="DeerFlow", type="系统", description="智能体框架")], chunk_id="c-1")
    await store.upsert_entities("kb-1", [ExtractedEntity(name="DeerFlow", type="系统", description="包含 Gateway")], chunk_id="c-2")

    entities = await store.list_entities("kb-1")
    assert len(entities) == 1
    row = entities[0]
    assert "智能体框架" in row["description"]
    assert "包含 Gateway" in row["description"]  # descriptions appended, not replaced
    assert sorted(row["source_chunk_ids"]) == ["c-1", "c-2"]
    # Re-feeding an identical description must not duplicate it.
    await store.upsert_entities("kb-1", [ExtractedEntity(name="DeerFlow", type="系统", description="智能体框架")], chunk_id="c-1")
    row = (await store.list_entities("kb-1"))[0]
    assert row["description"].count("智能体框架") == 1
    assert row["source_chunk_ids"] == ["c-1", "c-2"]


@pytest.mark.asyncio
async def test_upsert_relations_merge_on_same_triple(session_factory):
    store = GraphStore(session_factory)
    await store.upsert_entities("kb-1", [ExtractedEntity(name="DeerFlow", type="系统", description=""), ExtractedEntity(name="Gateway", type="组件", description="")], chunk_id="c-1")

    await store.upsert_relations("kb-1", [ExtractedRelation(source="DeerFlow", target="Gateway", relation="包含", description="整体包含")], chunk_id="c-1")
    await store.upsert_relations("kb-1", [ExtractedRelation(source="DeerFlow", target="Gateway", relation="包含", description="运行时依赖")], chunk_id="c-2")

    relations = await store.list_relations("kb-1")
    assert len(relations) == 1
    rel = relations[0]
    assert (rel["source"], rel["target"], rel["relation"]) == ("DeerFlow", "Gateway", "包含")
    assert "整体包含" in rel["description"] and "运行时依赖" in rel["description"]
    assert sorted(rel["source_chunk_ids"]) == ["c-1", "c-2"]


@pytest.mark.asyncio
async def test_same_name_in_different_kbs_stays_separate(session_factory):
    store = GraphStore(session_factory)

    await store.upsert_entities("kb-1", [ExtractedEntity(name="DeerFlow", type="系统", description="库一描述")], chunk_id="c-1")
    await store.upsert_entities("kb-2", [ExtractedEntity(name="DeerFlow", type="系统", description="库二描述")], chunk_id="c-9")

    one = await store.list_entities("kb-1")
    two = await store.list_entities("kb-2")
    assert len(one) == 1 and len(two) == 1
    assert one[0]["description"] == "库一描述"
    assert two[0]["description"] == "库二描述"
    assert two[0]["source_chunk_ids"] == ["c-9"]


@pytest.mark.asyncio
async def test_load_networkx_builds_graph(session_factory):
    store = GraphStore(session_factory)
    await store.upsert_entities(
        "kb-1",
        [
            ExtractedEntity(name="DeerFlow", type="系统", description="d1"),
            ExtractedEntity(name="Gateway", type="组件", description="d2"),
            ExtractedEntity(name="Sandbox", type="组件", description="d3"),
        ],
        chunk_id="c-1",
    )
    await store.upsert_relations(
        "kb-1",
        [
            ExtractedRelation(source="DeerFlow", target="Gateway", relation="包含", description=""),
            ExtractedRelation(source="DeerFlow", target="Sandbox", relation="包含", description=""),
        ],
        chunk_id="c-1",
    )

    graph = await store.load_networkx("kb-1")

    assert set(graph.nodes) == {"DeerFlow", "Gateway", "Sandbox"}
    assert graph.nodes["Gateway"]["type"] == "组件"
    assert graph.nodes["Gateway"]["source_chunk_ids"] == ["c-1"]
    assert graph.has_edge("DeerFlow", "Gateway")
    assert graph["DeerFlow"]["Gateway"]["relation"] == "包含"
    assert graph.degree("DeerFlow") == 2


@pytest.mark.asyncio
async def test_load_networkx_empty_kb(session_factory):
    store = GraphStore(session_factory)

    graph = await store.load_networkx("kb-nope")

    assert len(graph.nodes) == 0


@pytest.mark.asyncio
async def test_remove_chunk_contributions_orphans_and_survivors(session_factory):
    store = GraphStore(session_factory)
    await store.upsert_entities("kb-1", [ExtractedEntity(name="孤儿实体", type="概念", description="仅来自 c-1")], chunk_id="c-1")
    await store.upsert_entities("kb-1", [ExtractedEntity(name="幸存实体", type="概念", description="来自 c-1")], chunk_id="c-1")
    await store.upsert_entities("kb-1", [ExtractedEntity(name="幸存实体", type="概念", description="也来自 c-2")], chunk_id="c-2")
    await store.upsert_entities("kb-1", [ExtractedEntity(name="无关实体", type="概念", description="仅 c-2")], chunk_id="c-2")
    await store.upsert_relations("kb-1", [ExtractedRelation(source="孤儿实体", target="幸存实体", relation="关联", description="")], chunk_id="c-1")
    await store.upsert_relations("kb-1", [ExtractedRelation(source="幸存实体", target="无关实体", relation="引用", description="")], chunk_id="c-2")

    orphaned, affected = await store.remove_chunk_contributions("kb-1", ["c-1"])

    assert orphaned == ["孤儿实体"]
    assert sorted(affected) == ["幸存实体"]
    names = {e["name"] for e in await store.list_entities("kb-1")}
    assert names == {"幸存实体", "无关实体"}
    survivor = {e["name"]: e for e in await store.list_entities("kb-1")}["幸存实体"]
    assert survivor["source_chunk_ids"] == ["c-2"]
    relations = await store.list_relations("kb-1")
    assert [(r["source"], r["target"], r["relation"]) for r in relations] == [("幸存实体", "无关实体", "引用")]


@pytest.mark.asyncio
async def test_remove_chunk_contributions_scoped_per_kb(session_factory):
    store = GraphStore(session_factory)
    await store.upsert_entities("kb-1", [ExtractedEntity(name="共享名", type="概念", description="kb-1 的")], chunk_id="c-1")
    await store.upsert_entities("kb-2", [ExtractedEntity(name="共享名", type="概念", description="kb-2 的")], chunk_id="c-1")

    orphaned, _ = await store.remove_chunk_contributions("kb-1", ["c-1"])

    assert orphaned == ["共享名"]
    assert [e["name"] for e in await store.list_entities("kb-2")] == ["共享名"]


# ── D3 merge primitives ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_entities_absorbs_alias_into_representative(session_factory):
    store = GraphStore(session_factory)
    await store.upsert_entities("kb-1", [ExtractedEntity(name="Model", type="概念", description="片段A")], chunk_id="c-1")
    await store.upsert_entities("kb-1", [ExtractedEntity(name="Models", type="概念", description="片段B")], chunk_id="c-2")

    merged = await store.merge_entities("kb-1", "Model", ["Models"])

    entities = await store.list_entities("kb-1")
    assert len(entities) == 1
    row = entities[0]
    assert row["name"] == "Model"
    assert "片段A" in row["description"] and "片段B" in row["description"]
    assert sorted(row["source_chunk_ids"]) == ["c-1", "c-2"]
    assert merged is not None
    assert merged["name"] == "Model"
    assert "片段B" in merged["description"]

    # Idempotent: the alias row is gone, re-running is a no-op.
    again = await store.merge_entities("kb-1", "Model", ["Models"])
    assert again is not None
    assert len(await store.list_entities("kb-1")) == 1


@pytest.mark.asyncio
async def test_merge_entities_missing_representative_returns_none(session_factory):
    store = GraphStore(session_factory)

    assert await store.merge_entities("kb-1", "不存在", ["Models"]) is None


@pytest.mark.asyncio
async def test_rewrite_relation_endpoints_merges_duplicates_and_drops_self_loops(session_factory):
    store = GraphStore(session_factory)
    await store.upsert_entities(
        "kb-1",
        [
            ExtractedEntity(name="Model", type="概念", description=""),
            ExtractedEntity(name="Models", type="概念", description=""),
            ExtractedEntity(name="Trainer", type="概念", description=""),
        ],
        chunk_id="c-1",
    )
    await store.upsert_relations("kb-1", [ExtractedRelation(source="Model", target="Trainer", relation="依赖", description="d1")], chunk_id="c-1")
    await store.upsert_relations("kb-1", [ExtractedRelation(source="Models", target="Trainer", relation="依赖", description="d2")], chunk_id="c-2")
    await store.upsert_relations("kb-1", [ExtractedRelation(source="Model", target="Models", relation="同义", description="loop")], chunk_id="c-1")

    await store.rewrite_relation_endpoints("kb-1", {"Models": "Model"})

    relations = await store.list_relations("kb-1")
    assert [(r["source"], r["target"], r["relation"]) for r in relations] == [("Model", "Trainer", "依赖")]
    relation = relations[0]
    assert "d1" in relation["description"] and "d2" in relation["description"]
    assert sorted(relation["source_chunk_ids"]) == ["c-1", "c-2"]

    # Idempotent: no alias endpoints left to rewrite.
    await store.rewrite_relation_endpoints("kb-1", {"Models": "Model"})
    assert len(await store.list_relations("kb-1")) == 1


@pytest.mark.asyncio
async def test_rewrite_relation_endpoints_noop_without_hits(session_factory):
    store = GraphStore(session_factory)
    await store.upsert_entities("kb-1", [ExtractedEntity(name="A", type="t", description=""), ExtractedEntity(name="B", type="t", description="")], chunk_id="c-1")
    await store.upsert_relations("kb-1", [ExtractedRelation(source="A", target="B", relation="r", description="")], chunk_id="c-1")

    await store.rewrite_relation_endpoints("kb-1", {"无关": "A"})

    relations = await store.list_relations("kb-1")
    assert [(r["source"], r["target"]) for r in relations] == [("A", "B")]
