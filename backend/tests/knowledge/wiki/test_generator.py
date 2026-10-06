"""Tests for the wiki path: eligibility selection, entry generation, dirty refresh (spec §3.5).

Entity-level entries only in Phase 1: entities eligible for an entry (hygiene
pass ∧ cross-chunk freq≥2; score only orders generation — 2026-08-12 Task 8)
each get one LLM-written entry (main model), whose full text lives in the
``wiki_entries`` table while its dense vector lands in ``kb_wiki_entries``
(payload: entry_id pointer + title + kb_id). New entries are written in
material-bundle batches (entities sharing chunk sets share one LLM call); a
newly indexed doc marks the affected entries ``dirty`` and regeneration
rewrites them per-entity.
"""

from __future__ import annotations

import json
import re
import zlib
from types import SimpleNamespace

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchValue, SparseVector

from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.graph.extractor import ExtractedEntity
from deerflow.knowledge.wiki.generator import (
    WIKI_DIRECTION_HEADER,
    WikiStats,
    generate_wiki,
    mark_dirty_for_entities,
    plan_entry_batches,
    regenerate_wiki_entries,
    select_eligible_entities,
    wiki_trigger_ready,
)
from deerflow.knowledge.wiki.store import WikiStore, wiki_entry_id

from ..conftest import requires_qdrant, spy_embed_text


class _WikiLLM:
    """Dual-mode fake: batch prompts (实体清单) get a JSON array; single prompts a lone entry."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ainvoke(self, messages):
        # Read the real content string (str(messages) would repr-escape \n and
        # break the roster line parsing below).
        last = messages[-1] if isinstance(messages, list) else messages
        text = str(last["content"] if isinstance(last, dict) else getattr(last, "content", last))
        self.calls.append(text)
        if "实体清单：" in text:
            roster = text.split("实体清单：", 1)[1].split("\n", 1)[0]
            names = [n.strip() for n in roster.split("、") if n.strip()]
            items = [{"title": n, "content": f"# {n}\n\n这是 {n} 的百科综述正文。"} for n in names]
            return SimpleNamespace(content=json.dumps(items, ensure_ascii=False))
        match = re.search(r"实体：([^\n]+)", text)
        title = match.group(1).strip() if match else "条目"
        return SimpleNamespace(content=f"# {title}\n\n这是 {title} 的百科综述正文。")


class _BatchOmitLLM(_WikiLLM):
    """Batch answers that drop one requested title (drives the per-entity fallback)."""

    def __init__(self, omit: str) -> None:
        super().__init__()
        self._omit = omit

    async def ainvoke(self, messages):
        last = messages[-1] if isinstance(messages, list) else messages
        text = str(last["content"] if isinstance(last, dict) else getattr(last, "content", last))
        if "实体清单：" in text:
            self.calls.append(text)
            roster = text.split("实体清单：", 1)[1].split("\n", 1)[0]
            names = [n.strip() for n in roster.split("、") if n.strip() and n.strip() != self._omit]
            items = [{"title": n, "content": f"# {n}\n\n这是 {n} 的百科综述正文。"} for n in names]
            return SimpleNamespace(content=json.dumps(items, ensure_ascii=False))
        return await super().ainvoke(messages)


class _BatchGarbageLLM(_WikiLLM):
    """Batch answers that are not JSON at all (the whole batch falls back)."""

    async def ainvoke(self, messages):
        last = messages[-1] if isinstance(messages, list) else messages
        text = str(last["content"] if isinstance(last, dict) else getattr(last, "content", last))
        if "实体清单：" in text:
            self.calls.append(text)
            return SimpleNamespace(content="这不是 JSON")
        return await super().ainvoke(messages)


async def _add_entity(graph_store, kb_id: str, name: str, chunk_ids: list[str]) -> None:
    """Give ``name`` one contribution per chunk id (drives its frequency)."""
    for chunk_id in chunk_ids:
        await graph_store.upsert_entities(kb_id, [ExtractedEntity(name=name, type="概念", description=f"{name} 描述")], chunk_id=chunk_id)


class _StubEmbedder:
    batch_size = 20

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        self.calls.append(list(texts))
        results = []
        for i, text in enumerate(texts):
            dense = [0.0] * 1024
            dense[zlib.crc32(text.encode("utf-8")) % 1024] = 1.0
            results.append(EmbeddingResult(dense=dense, sparse=SparseVector(indices=[i + 1], values=[0.5])))
        return results


# ── head-entity selection & trigger (pure DB, no Qdrant) ─────────────────────


@pytest.mark.asyncio
async def test_eligible_entities_hygiene_cross_chunk_and_no_ratio_cap(wiki_db_env):
    """Eligibility = hygiene pass ∧ freq≥2, ordered by score only (no ~20% cut)."""
    graph_store, kb_id = wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    # Junk names with freq 2 must still be filtered out.
    for junk in ("&&", '"abc"', "C", "x" * 31):
        await _add_entity(graph_store, kb_id, junk, ["doc-w-c0", "doc-w-c1"])
    # Legit cross-chunk entities all qualify — no ratio truncation (4/11 > 20%).
    for name in ("Alpha", "Beta", "Gamma"):
        await _add_entity(graph_store, kb_id, name, ["doc-w-c0", "doc-w-c1"])

    eligible = await select_eligible_entities(graph_store, kb_id)

    # DeerFlow score 5 (deg 3 + freq 2) first; extras score 2 tie-break by name.
    assert [row["name"] for row in eligible] == ["DeerFlow", "Alpha", "Beta", "Gamma"]
    # Fixture entities with freq 1 (Gateway/LangGraph/Qdrant/MinerU) are out.
    assert set(eligible[0]["source_chunk_ids"]) == {"doc-w-c0", "doc-w-c1"}


@pytest.mark.asyncio
async def test_eligible_entities_empty_graph(session_factory):
    from deerflow.knowledge.graph.store import GraphStore

    selected = await select_eligible_entities(GraphStore(session_factory), "kb-void")
    assert selected == []


@pytest.mark.asyncio
async def test_wiki_trigger_ready_threshold(wiki_db_env):
    store, kb_id, doc_id = wiki_db_env["store"], wiki_db_env["kb_id"], wiki_db_env["doc_id"]

    # Document still indexing → below the 90% completion threshold.
    assert await wiki_trigger_ready(store, kb_id, threshold=0.9) is False

    await store.update_document_status(doc_id, "ready")
    assert await wiki_trigger_ready(store, kb_id, threshold=0.9) is True

    # A KB with no documents never triggers automatically.
    await store.create_kb(kb_id="kb-empty", owner_id="user-1", name="空库")
    assert await wiki_trigger_ready(store, "kb-empty", threshold=0.9) is False


# ── generation + dirty incremental (integration: Qdrant) ─────────────────────


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_wiki_writes_entry_and_vector(wiki_env, monkeypatch):
    store, graph_store = wiki_env["store"], wiki_env["graph_store"]
    vector_store, client, kb_id = wiki_env["vector_store"], wiki_env["client"], wiki_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    llm, embedder = _WikiLLM(), _StubEmbedder()
    helper_calls = spy_embed_text(monkeypatch, "deerflow.knowledge.wiki.generator", "wiki_entry_embed_text")
    # Gateway joins the eligible set once a second chunk references it (freq 2).
    await _add_entity(graph_store, kb_id, "Gateway", ["doc-w-c1"])

    stats = await generate_wiki(store, graph_store, wiki_store, vector_store, kb_id=kb_id, llm=llm, embedder=embedder)

    assert isinstance(stats, WikiStats)
    assert stats.selected == 2
    assert stats.generated == 2
    assert sorted(stats.titles) == ["DeerFlow", "Gateway"]

    # wiki_entries rows: full text + ready status + aggregated source chunks.
    entries = await wiki_store.list_entries(kb_id)
    assert len(entries) == 2
    deerflow = next(e for e in entries if e["title"] == "DeerFlow")
    assert deerflow["status"] == "ready"
    assert "百科综述正文" in deerflow["content"]
    assert sorted(deerflow["source_chunk_ids"]) == ["doc-w-c0", "doc-w-c1"]
    # The LLM prompt aggregated the entity's source chunk texts.
    deerflow_prompt = next(call for call in llm.calls if "DeerFlow" in call)
    assert "超级智能体系统" in deerflow_prompt and "存储向量" in deerflow_prompt

    # kb_wiki_entries: dense vector + pointer-only payload (entry_id/title/kb_id).
    points, _ = await client.scroll(
        vector_store.wiki_entries_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        with_payload=True,
        with_vectors=True,
        limit=10,
    )
    assert len(points) == 2
    payload = next(p for p in points if p.payload["title"] == "DeerFlow").payload
    assert payload["entry_id"] == deerflow["id"]
    assert payload["kb_id"] == kb_id
    assert "content" not in payload  # full text stays in the business DB
    assert embedder.calls, "entry vectors must go through the embedder"
    # Same-source pin (spec 2026-09-24 §4.1): entry vectors embed via the shared helper.
    assert sorted(call[0] for call in helper_calls) == ["DeerFlow", "Gateway"], "entry vectors must embed through the shared helper"


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_new_doc_marks_affected_entries_dirty(wiki_env):
    store, graph_store, wiki_store = wiki_env["store"], wiki_env["graph_store"], WikiStore(wiki_env["store"]._sf)
    kb_id = wiki_env["kb_id"]
    await _add_entity(graph_store, kb_id, "Gateway", ["doc-w-c1"])  # freq 2 → eligible
    await generate_wiki(store, graph_store, wiki_store, wiki_env["vector_store"], kb_id=kb_id, llm=_WikiLLM(), embedder=_StubEmbedder())

    # A newly indexed doc touched DeerFlow → its entry goes dirty, Gateway stays ready.
    marked = await mark_dirty_for_entities(wiki_store, kb_id, ["DeerFlow"])

    assert marked == 1
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert entries["DeerFlow"]["status"] == "dirty"
    assert entries["Gateway"]["status"] == "ready"


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_regeneration_clears_dirty_and_only_touches_dirty(wiki_env):
    store, graph_store, vector_store = wiki_env["store"], wiki_env["graph_store"], wiki_env["vector_store"]
    kb_id = wiki_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await _add_entity(graph_store, kb_id, "Gateway", ["doc-w-c1"])  # freq 2 → eligible
    await generate_wiki(store, graph_store, wiki_store, vector_store, kb_id=kb_id, llm=_WikiLLM(), embedder=_StubEmbedder())
    await mark_dirty_for_entities(wiki_store, kb_id, ["DeerFlow"])

    llm, embedder = _WikiLLM(), _StubEmbedder()
    stats = await generate_wiki(store, graph_store, wiki_store, vector_store, kb_id=kb_id, llm=llm, embedder=embedder, only_dirty=True)

    assert stats.selected == 1
    assert stats.generated == 1
    assert stats.titles == ["DeerFlow"]
    assert len(llm.calls) == 1  # ready entries are NOT regenerated
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert entries["DeerFlow"]["status"] == "ready"  # dirty cleared
    assert entries["Gateway"]["status"] == "ready"
    points, _ = await wiki_env["client"].scroll(
        vector_store.wiki_entries_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        with_payload=True,
        limit=10,
    )
    assert len(points) == 2  # re-upsert overwrote in place, no duplicates


@pytest.mark.asyncio
async def test_generate_wiki_records_last_run_status(session_factory):
    """P1 失败可见性 (2026-08-14): the terminal status of the most recent run
    is observable per KB — ``None`` before the first run, ``succeeded`` after
    a clean run, ``failed`` after a crash — so the UI never toasts 已更新
    after a failed run. Uses a dedicated kb id: the registry is module-level.
    """
    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import KnowledgeStore
    from deerflow.knowledge.wiki.generator import wiki_last_run_status

    store = KnowledgeStore(session_factory)
    graph_store = GraphStore(session_factory)
    kb_id = "kb-lastrun"
    await store.create_kb(kb_id=kb_id, owner_id="user-1", name="lastrun")
    wiki_store = WikiStore(session_factory)

    assert wiki_last_run_status(kb_id) is None

    await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_WikiLLM())
    assert wiki_last_run_status(kb_id) == "succeeded"

    class _BoomLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("boom")

    # An eligible entity forces an LLM call, which now crashes mid-run.
    await _add_entity(graph_store, kb_id, "DeerFlow", ["c1", "c2"])
    with pytest.raises(RuntimeError):
        await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_BoomLLM())
    assert wiki_last_run_status(kb_id) == "failed"


@pytest.mark.asyncio
async def test_empty_graph_generates_nothing(session_factory):
    from deerflow.knowledge.graph.store import GraphStore
    from deerflow.knowledge.store import KnowledgeStore

    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-void", owner_id="user-1", name="空库")
    llm = _WikiLLM()

    stats = await generate_wiki(store, GraphStore(session_factory), WikiStore(session_factory), None, kb_id="kb-void", llm=llm, embedder=None)

    assert stats.selected == 0 and stats.generated == 0
    assert llm.calls == []


# ── Task 5b: incremental targets = dirty ∪ (eligible entities without an entry) ──


@pytest.mark.asyncio
async def test_only_dirty_backfills_newly_eligible_entity(wiki_db_env):
    """An entity that crosses the freq≥2 threshold gets its entry on the next
    incremental run even when nothing is dirty (spec §3.5 2026-08-12 revision).
    Pure-DB: no vector store needed for the target set."""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    # First batch: only DeerFlow is cross-chunk eligible (Gateway has freq 1).
    await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_WikiLLM())
    assert {e["title"] for e in await wiki_store.list_entries(kb_id)} == {"DeerFlow"}

    # Gateway becomes eligible when a second chunk references it (freq 1→2).
    await _add_entity(graph_store, kb_id, "Gateway", ["doc-w-c1"])
    llm = _WikiLLM()
    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True)

    assert stats.selected == 1
    assert stats.generated == 1
    assert stats.titles == ["Gateway"]
    assert len(llm.calls) == 1
    # After the backfill the entry set matches the eligible set exactly.
    eligible = {row["name"] for row in await select_eligible_entities(graph_store, kb_id)}
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert set(entries) == eligible == {"DeerFlow", "Gateway"}
    assert all(entry["status"] == "ready" for entry in entries.values())


@pytest.mark.asyncio
async def test_only_dirty_prunes_disqualified_or_vanished_dirty_entries(wiki_db_env):
    """失格即删闭环 (2026-08-14 拍板, 方案 A): a dirty entry whose entity
    vanished from the graph OR fell below the ≥2-source eligibility bar is
    DELETED by the incremental run — never silently skipped, otherwise the
    dirty badge could never drain (live issue: 切片减少 → 待更新永远挂着).
    Ready entries of ineligible entities stay untouched (see the retained
    test below)."""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_WikiLLM())
    assert {e["title"] for e in await wiki_store.list_entries(kb_id)} == {"DeerFlow"}

    # 飞书: no graph entity at all (vanished); Gateway: entity present but
    # freq 1 (disqualified). DeerFlow: eligible dirty → regenerated, not pruned.
    await wiki_store.upsert_entry(kb_id, title="飞书", content="旧条目", source_chunk_ids=["doc-w-c0"], status="dirty")
    await wiki_store.upsert_entry(kb_id, title="Gateway", content="旧条目", source_chunk_ids=["doc-w-c0"], status="dirty")
    await mark_dirty_for_entities(wiki_store, kb_id, ["DeerFlow"])

    llm = _WikiLLM()
    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True)

    assert stats.pruned == 2
    assert stats.generated == 1
    assert stats.titles == ["DeerFlow"]
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert set(entries) == {"DeerFlow"}
    assert entries["DeerFlow"]["status"] == "ready"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_dirty_prune_removes_vector_point(wiki_env):
    """The prune must also drop the ``kb_wiki_entries`` vector point —
    otherwise wiki_search keeps citing an entry whose business row is gone
    (幽灵引用). Covers the exact user path: 切片减少 → dirty → 更新百科 →
    条目与向量一起消失."""
    store, graph_store, vector_store, kb_id = (
        wiki_env["store"],
        wiki_env["graph_store"],
        wiki_env["vector_store"],
        wiki_env["kb_id"],
    )
    wiki_store = WikiStore(store._sf)
    await generate_wiki(store, graph_store, wiki_store, vector_store, kb_id=kb_id, llm=_WikiLLM(), embedder=_StubEmbedder())

    def wiki_points():
        return wiki_env["client"].scroll(
            vector_store.wiki_entries_collection,
            scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
            limit=10,
        )

    points, _ = await wiki_points()
    assert len(points) == 1  # DeerFlow only

    # DeerFlow loses its second chunk contribution → freq 1 → disqualified.
    await graph_store.remove_chunk_contributions(kb_id, ["doc-w-c1"])
    await mark_dirty_for_entities(wiki_store, kb_id, ["DeerFlow"])

    stats = await generate_wiki(store, graph_store, wiki_store, vector_store, kb_id=kb_id, llm=_WikiLLM(), embedder=_StubEmbedder(), only_dirty=True)

    assert stats.pruned == 1
    assert stats.generated == 0
    assert await wiki_store.list_entries(kb_id) == []
    points, _ = await wiki_points()
    assert len(points) == 0


@pytest.mark.asyncio
async def test_only_dirty_idempotent_and_ineligible_entries_retained(wiki_db_env):
    """Existing entries are never re-written (idempotent); entries whose entity
    lost eligibility (freq back below 2) are retained, never deleted."""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_WikiLLM())
    # An entry written for a now-ineligible entity (freq 1) is kept as-is.
    await wiki_store.upsert_entry(kb_id, title="Qdrant", content="旧条目", source_chunk_ids=["doc-w-c1"], status="ready")

    # Idempotent: every eligible entity already has an entry, nothing dirty → no work.
    llm = _WikiLLM()
    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True)
    assert stats.selected == 0 and stats.generated == 0
    assert llm.calls == []
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert set(entries) == {"DeerFlow", "Qdrant"}
    assert entries["Qdrant"]["status"] == "ready"


# ── Task 8: material-bundle batching ──────────────────────────────────────────


def test_plan_entry_batches_clusters_by_shared_chunks():
    rows = [
        {"name": "A", "source_chunk_ids": ["c1", "c2"]},
        {"name": "B", "source_chunk_ids": ["c1", "c2"]},  # identical set → same bundle
        {"name": "C", "source_chunk_ids": ["c9", "c8"]},  # disjoint → own bundle
        {"name": "D", "source_chunk_ids": ["c2", "c9"]},  # ≤0.5 overlap with both → own bundle
    ]

    batches = plan_entry_batches(rows)

    assert [[row["name"] for row in batch] for batch in batches] == [["A", "B"], ["C"], ["D"]]


def test_plan_entry_batches_size_cap_and_determinism():
    rows = [{"name": f"E{i}", "source_chunk_ids": ["c1", "c2"]} for i in range(5)]

    batches = plan_entry_batches(rows, batch_size=2)

    assert [len(batch) for batch in batches] == [2, 2, 1]
    rerun = plan_entry_batches(rows, batch_size=2)
    assert [[row["name"] for row in batch] for batch in batches] == [[row["name"] for row in batch] for batch in rerun]


@pytest.mark.asyncio
async def test_batch_generation_shares_one_call_per_bundle(wiki_db_env):
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await _add_entity(graph_store, kb_id, "Alpha", ["doc-w-c0", "doc-w-c1"])
    await _add_entity(graph_store, kb_id, "Beta", ["doc-w-c0", "doc-w-c1"])
    llm = _WikiLLM()

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm)

    assert stats.selected == 3 and stats.generated == 3
    assert sorted(stats.titles) == ["Alpha", "Beta", "DeerFlow"]
    assert len(llm.calls) == 1  # three entities share ONE material-bundle call
    assert "实体清单：" in llm.calls[0]
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert set(entries) == {"DeerFlow", "Alpha", "Beta"}
    assert all(entry["status"] == "ready" for entry in entries.values())


@pytest.mark.asyncio
async def test_batch_missing_title_falls_back_to_single(wiki_db_env):
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await _add_entity(graph_store, kb_id, "Alpha", ["doc-w-c0", "doc-w-c1"])
    llm = _BatchOmitLLM(omit="Alpha")

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm)

    assert sorted(stats.titles) == ["Alpha", "DeerFlow"]
    assert len(llm.calls) == 2  # one bundle call + one single-call fallback
    assert {e["title"] for e in await wiki_store.list_entries(kb_id)} == {"DeerFlow", "Alpha"}


@pytest.mark.asyncio
async def test_batch_garbage_response_falls_back_for_all(wiki_db_env):
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await _add_entity(graph_store, kb_id, "Alpha", ["doc-w-c0", "doc-w-c1"])
    llm = _BatchGarbageLLM()

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm)

    assert sorted(stats.titles) == ["Alpha", "DeerFlow"]
    assert len(llm.calls) == 3  # garbage bundle call + two single-call fallbacks
    assert {e["title"] for e in await wiki_store.list_entries(kb_id)} == {"DeerFlow", "Alpha"}


@pytest.mark.asyncio
async def test_backfill_limit_paces_new_entries_but_not_dirty(wiki_db_env):
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await _add_entity(graph_store, kb_id, "Alpha", ["doc-w-c0", "doc-w-c1"])
    await _add_entity(graph_store, kb_id, "Beta", ["doc-w-c0", "doc-w-c1"])
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0"], status="dirty")
    llm = _WikiLLM()

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True, backfill_limit=1)

    # Dirty regeneration is never capped; only one new entry written this run.
    assert sorted(stats.titles) == ["Alpha", "DeerFlow"]
    assert {e["title"] for e in await wiki_store.list_entries(kb_id)} == {"DeerFlow", "Alpha"}
    # The queued remainder is picked up by the next trigger.
    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True, backfill_limit=1)
    assert stats.titles == ["Beta"]


# ── 竞态防护：生成途中文档被删 → 写入前资格重验拦截（2026-08-23）──────────────


class _RaceLLM:
    """LLM fake：首次被调用时模拟「用户删除了文档的贡献」——实体从合格掉到失格。

    复刻生产竞态：generate_wiki 读资格快照（DeerFlow freq=2 合格）→ LLM 生成
    （耗时几十秒，期间用户删了文档）→ 快照过时 → 若无写入前重验，upsert 会把
    失格实体的条目写回来（幽灵条目）。
    """

    def __init__(self, graph_store, kb_id: str) -> None:
        self._graph_store = graph_store
        self._kb_id = kb_id
        self._removed = False

    async def ainvoke(self, messages):
        if not self._removed:
            # 生成中途：删除 doc-w-c0 的贡献 → DeerFlow freq 2→1 失格
            await self._graph_store.remove_chunk_contributions(self._kb_id, ["doc-w-c0"])
            self._removed = True
        last = messages[-1] if isinstance(messages, list) else messages
        text = str(last["content"] if isinstance(last, dict) else getattr(last, "content", last))
        if "实体清单：" in text:
            roster = text.split("实体清单：", 1)[1].split("\n", 1)[0]
            items = [{"title": n.strip(), "content": f"# {n.strip()}\n\n正文"} for n in roster.split("、") if n.strip()]
            return SimpleNamespace(content=json.dumps(items, ensure_ascii=False))
        m = re.search(r"实体：([^\n]+)", text)
        title = m.group(1).strip() if m else "条目"
        return SimpleNamespace(content=f"# {title}\n\n正文")


@pytest.mark.asyncio
async def test_write_skipped_when_entity_loses_eligibility_mid_run(wiki_db_env):
    """全量路径：快照合格但写入时已失格 → 拦截，不产生幽灵条目。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    llm = _RaceLLM(graph_store, kb_id)

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm)

    assert stats.generated == 0
    assert stats.skipped_stale == 1
    assert await wiki_store.list_entries(kb_id) == []


@pytest.mark.asyncio
async def test_write_skipped_when_entity_vanishes_mid_run(wiki_db_env):
    """增量路径：dirty 条目生成途中实体彻底消失（两个贡献都被删）→ 拦截。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty")

    class _VanishLLM(_RaceLLM):
        async def ainvoke(self, messages):
            if not self._removed:
                await self._graph_store.remove_chunk_contributions(self._kb_id, ["doc-w-c0", "doc-w-c1"])
                self._removed = True
            return await super()._respond(messages) if hasattr(self, "_respond") else await _RaceLLM.ainvoke(self, messages)

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_VanishLLM(graph_store, kb_id), only_dirty=True)

    # 消失实体的 dirty 条目被失格即删清掉，且绝不重新写入
    assert stats.generated == 0
    assert await wiki_store.list_entries(kb_id) == []


@pytest.mark.asyncio
async def test_write_proceeds_when_entity_still_eligible(wiki_db_env):
    """对照组：无删除干扰时正常写入（重验不误伤正常路径）。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_WikiLLM())

    assert stats.generated == 1
    assert stats.skipped_stale == 0
    assert {e["title"] for e in await wiki_store.list_entries(kb_id)} == {"DeerFlow"}


# ── per-entry regenerate (局部更新/重建, 2026-09-02) ──────────────────────────


@pytest.mark.asyncio
async def test_regenerate_rewrites_only_selected_entries(wiki_db_env):
    """局部更新：regenerate 只重写选中的 entry_id，其余 dirty 条目原样保留
    —— 对应用户诉求『不能所有待更新一起更新，要能选中指定条目更新』。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await _add_entity(graph_store, kb_id, "Gateway", ["doc-w-c1"])  # freq 1→2 → eligible
    await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_WikiLLM())
    # Both entries go dirty (a new doc touched both entities).
    await mark_dirty_for_entities(wiki_store, kb_id, ["DeerFlow", "Gateway"])

    llm = _WikiLLM()
    stats = await regenerate_wiki_entries(store, graph_store, wiki_store, None, kb_id=kb_id, entry_ids=[wiki_entry_id(kb_id, "DeerFlow")], llm=llm)

    # Only DeerFlow regenerated; Gateway stays dirty (never touched).
    assert stats.selected == 1
    assert stats.generated == 1
    assert stats.titles == ["DeerFlow"]
    assert len(llm.calls) == 1 and "DeerFlow" in llm.calls[0]
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert entries["DeerFlow"]["status"] == "ready"  # dirty cleared
    assert entries["Gateway"]["status"] == "dirty"  # untouched


@pytest.mark.asyncio
async def test_regenerate_preserves_supplement_layer(wiki_db_env):
    """局部更新走 _write_entry → upsert_entry（supplement 默认 _UNSET）：主内容
    重写、dirty 清除，但人工补充层原样保留（与 dirty 增量刷新同源语义）。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    entry_id = wiki_entry_id(kb_id, "DeerFlow")
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty", supplement_content="人工批注")

    stats = await regenerate_wiki_entries(store, graph_store, wiki_store, None, kb_id=kb_id, entry_ids=[entry_id], llm=_WikiLLM())

    assert stats.generated == 1
    entry = await wiki_store.get_entry(entry_id)
    assert entry["status"] == "ready"
    assert "百科综述正文" in entry["content"]  # rewritten by the LLM
    assert entry["supplement_content"] == "人工批注"  # preserved across the rewrite


@pytest.mark.asyncio
async def test_regenerate_prunes_orphan_entry(wiki_db_env):
    """选中条目的实体已从图谱消失（孤儿）→ 失格即删：条目被 prune，不进 LLM。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await wiki_store.upsert_entry(kb_id, title="飞书", content="旧条目", source_chunk_ids=["doc-w-c0"], status="dirty")

    llm = _WikiLLM()
    stats = await regenerate_wiki_entries(store, graph_store, wiki_store, None, kb_id=kb_id, entry_ids=[wiki_entry_id(kb_id, "飞书")], llm=llm)

    assert stats.selected == 0
    assert stats.pruned == 1
    assert llm.calls == []  # an orphan never reaches the LLM
    assert await wiki_store.list_entries(kb_id) == []


@pytest.mark.asyncio
async def test_regenerate_prunes_ineligible_entity_entry(wiki_db_env):
    """选中条目的实体仍在图谱但已失格（freq<2）→ 写前重验拦截并 prune。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    # LangGraph exists in the graph but spans a single chunk (freq 1 → ineligible).
    await wiki_store.upsert_entry(kb_id, title="LangGraph", content="旧条目", source_chunk_ids=["doc-w-c0"], status="ready")

    stats = await regenerate_wiki_entries(store, graph_store, wiki_store, None, kb_id=kb_id, entry_ids=[wiki_entry_id(kb_id, "LangGraph")], llm=_WikiLLM())

    assert stats.selected == 1  # entity found → queued for rewrite
    assert stats.generated == 0  # blocked at the write-time eligibility re-check
    assert stats.skipped_stale == 1
    assert stats.pruned == 1
    assert await wiki_store.list_entries(kb_id) == []


@pytest.mark.asyncio
async def test_regenerate_ignores_unknown_and_foreign_entry_ids(wiki_db_env):
    """未知 id 与属于别的库的 id 都被静默跳过（不报错、不误删）。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=_WikiLLM())
    # A foreign-kb entry id that must never be touched by this kb's run.
    await wiki_store.upsert_entry("kb-other", title="DeerFlow", content="别的库", source_chunk_ids=["x"], status="ready")
    foreign_id = wiki_entry_id("kb-other", "DeerFlow")

    llm = _WikiLLM()
    stats = await regenerate_wiki_entries(store, graph_store, wiki_store, None, kb_id=kb_id, entry_ids=["does-not-exist", foreign_id], llm=llm)

    assert stats.selected == 0 and stats.generated == 0 and stats.pruned == 0
    assert llm.calls == []
    # The foreign entry survives untouched.
    assert (await wiki_store.get_entry(foreign_id))["content"] == "别的库"


@requires_qdrant
@pytest.mark.integration
@pytest.mark.asyncio
async def test_regenerate_reembeds_vector_point_in_place(wiki_env):
    """局部更新也要重嵌：kb_wiki_entries 向量点原地覆盖（无重复），否则
    wiki_search 命中的仍是旧向量。"""
    store, graph_store, vector_store, kb_id = wiki_env["store"], wiki_env["graph_store"], wiki_env["vector_store"], wiki_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await generate_wiki(store, graph_store, wiki_store, vector_store, kb_id=kb_id, llm=_WikiLLM(), embedder=_StubEmbedder())
    await mark_dirty_for_entities(wiki_store, kb_id, ["DeerFlow"])

    embedder = _StubEmbedder()
    stats = await regenerate_wiki_entries(store, graph_store, wiki_store, vector_store, kb_id=kb_id, entry_ids=[wiki_entry_id(kb_id, "DeerFlow")], llm=_WikiLLM(), embedder=embedder)

    assert stats.generated == 1
    assert embedder.calls  # the rewritten entry went back through the embedder
    points, _ = await wiki_env["client"].scroll(
        vector_store.wiki_entries_collection,
        scroll_filter=Filter(must=[FieldCondition(key="kb_id", match=MatchValue(value=kb_id))]),
        limit=10,
    )
    assert len(points) == 1  # in-place overwrite, no duplicate point
    entries = {e["title"]: e for e in await wiki_store.list_entries(kb_id)}
    assert entries["DeerFlow"]["status"] == "ready"


# ── 补充层即生成方向 (spec 2026-09-12) ──────────────────────────────────────
#
# 此前只有「保留」落地（test_regenerate_preserves_supplement_layer），spec A7 的
# 「重生成时作为额外参考材料提供」没有 —— 下面钉住"被消费"这一半。


@pytest.mark.asyncio
async def test_dirty_regeneration_injects_supplement_as_direction(wiki_db_env):
    """dirty 增量重写把补充层原文带进 user message（方向必须真的到达模型）。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    direction = "语气严谨些，多介绍相关概念"
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty", supplement_content=direction)

    llm = _WikiLLM()
    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True)

    assert stats.generated == 1
    assert len(llm.calls) == 1
    assert WIKI_DIRECTION_HEADER in llm.calls[0]
    assert direction in llm.calls[0]


@pytest.mark.asyncio
async def test_regeneration_without_supplement_omits_direction_block(wiki_db_env):
    """护栏：没有补充层时不得凭空多出一段"用户要求"。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty")

    llm = _WikiLLM()
    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True)

    assert stats.generated == 1
    assert len(llm.calls) == 1
    assert WIKI_DIRECTION_HEADER not in llm.calls[0]


@pytest.mark.asyncio
async def test_blank_supplement_is_not_injected(wiki_db_env):
    """护栏：只有空白的补充层等同未填写。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty", supplement_content="   ")

    llm = _WikiLLM()
    await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True)

    assert len(llm.calls) == 1
    assert WIKI_DIRECTION_HEADER not in llm.calls[0]


@pytest.mark.asyncio
async def test_full_rebuild_sends_guided_entries_through_single_call(wiki_db_env):
    """全量重建走的是批量 prompt，而批量 prompt 读不到补充层 —— 有方向的条目
    必须回到单实体路径，否则一次「全量更新」会静默丢掉所有方向（spec 2026-09-12）。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await _add_entity(graph_store, kb_id, "Gateway", ["doc-w-c1"])  # freq 1→2 → eligible
    direction = "只讲关系，别展开实现细节"
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="ready", supplement_content=direction)

    llm = _WikiLLM()
    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm)

    assert stats.generated == 2  # DeerFlow（有方向）+ Gateway（无条目）
    guided = [call for call in llm.calls if WIKI_DIRECTION_HEADER in call]
    batched = [call for call in llm.calls if "实体清单：" in call]
    assert len(guided) == 1
    assert "DeerFlow" in guided[0] and direction in guided[0]
    assert len(batched) == 1
    roster = batched[0].split("实体清单：", 1)[1].split("\n", 1)[0]
    assert "DeerFlow" not in roster  # 有方向的条目不再进批量名单
    assert "Gateway" in roster


class _MidRunEditLLM(_WikiLLM):
    """生成途中"用户保存了方向"：模拟 PATCH 落在这次 run 的 LLM 调用期间。

    KnowledgeService.update_wiki_entry 在库级 run 在跑时只能标脏（待更新），
    所以这里也写 status="dirty"。
    """

    def __init__(self, wiki_store: WikiStore, kb_id: str, *, title: str, new_supplement: str) -> None:
        super().__init__()
        self._wiki_store = wiki_store
        self._kb_id = kb_id
        self._title = title
        self._new_supplement = new_supplement
        self._edited = False

    async def ainvoke(self, messages):
        response = await super().ainvoke(messages)
        if not self._edited:
            self._edited = True
            await self._wiki_store.upsert_entry(self._kb_id, title=self._title, content="此刻的正文", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty", supplement_content=self._new_supplement)
        return response


@pytest.mark.asyncio
async def test_write_keeps_dirty_when_direction_changed_mid_run(wiki_db_env):
    """在飞的那次写入不得擦掉"期间保存过方向"的待更新标记。

    真栈实测缺陷（2026-09-12）：保存补充层时若有 run 在跑，PATCH 会兜底标脏；
    该 run 收尾写库却照旧写 ready ⇒ 待更新没了，方向躺在库里永不生效。
    """
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="ready", supplement_content="旧方向")
    llm = _MidRunEditLLM(wiki_store, kb_id, title="DeerFlow", new_supplement="新方向：语气严谨些")

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm)

    assert stats.generated == 1
    entry = await wiki_store.get_entry(wiki_entry_id(kb_id, "DeerFlow"))
    assert entry["supplement_content"] == "新方向：语气严谨些"  # 用户的方向保住了
    assert entry["status"] == "dirty"  # ……而且待更新记号也保住了
    assert "百科综述正文" in entry["content"]  # 本次生成仍然落了库


@pytest.mark.asyncio
async def test_write_keeps_dirty_mid_run_on_dirty_refresh(wiki_db_env):
    """同一条规则在 dirty 增量路径上成立（该路径本来就是 dirty→ready 清标）。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty", supplement_content="旧方向")
    llm = _MidRunEditLLM(wiki_store, kb_id, title="DeerFlow", new_supplement="新方向：补上适用范围")

    stats = await generate_wiki(store, graph_store, wiki_store, None, kb_id=kb_id, llm=llm, only_dirty=True)

    assert stats.generated == 1
    entry = await wiki_store.get_entry(wiki_entry_id(kb_id, "DeerFlow"))
    assert entry["supplement_content"] == "新方向：补上适用范围"
    assert entry["status"] == "dirty"


@pytest.mark.asyncio
async def test_per_entry_regenerate_injects_direction(wiki_db_env):
    """局部更新（用户手选条目重写）同样把补充层当作方向。"""
    store, graph_store, kb_id = wiki_db_env["store"], wiki_db_env["graph_store"], wiki_db_env["kb_id"]
    wiki_store = WikiStore(store._sf)
    direction = "补上版本适用范围"
    entry_id = wiki_entry_id(kb_id, "DeerFlow")
    await wiki_store.upsert_entry(kb_id, title="DeerFlow", content="旧内容", source_chunk_ids=["doc-w-c0", "doc-w-c1"], status="dirty", supplement_content=direction)

    llm = _WikiLLM()
    stats = await regenerate_wiki_entries(store, graph_store, wiki_store, None, kb_id=kb_id, entry_ids=[entry_id], llm=llm)

    assert stats.generated == 1
    assert len(llm.calls) == 1
    assert WIKI_DIRECTION_HEADER in llm.calls[0]
    assert direction in llm.calls[0]
