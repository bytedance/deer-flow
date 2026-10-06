"""Tests for wiki_search manual-card mixing (Phase-3 Batch-1 P6, spec §8).

Cards with ``include_in_wiki_search`` on embed into ``kb_manual_cards`` and
compete with AI wiki entries for the SAME top_k pool — candidates merge, sort
by score desc (stable: wiki wins ties), truncate at top_k, and every hit
carries ``source_type: "wiki" | "manual"`` so the frontend can badge
「百科」/「我的卡片」. Stale points (toggle switched off / card deleted after
a failed vector delete) are skipped at hydration time and never waste a pool
slot.

These are unit tests: the vector store is faked (scripted scored points), the
business store is real SQLite — no Qdrant required.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from qdrant_client.models import SparseVector

from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.wiki.store import WikiStore
from deerflow.tools.builtins.wiki_search_tool import _wiki_search_impl

from .conftest import KB_ID, OWNER_ID


def _runtime(**context) -> SimpleNamespace:
    return SimpleNamespace(context=context)


class _FakeEmbedder:
    """The scripted vector store ignores the vector — any dense blob works."""

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        return [EmbeddingResult(dense=[0.1] * 1024, sparse=SparseVector(indices=[1], values=[0.5])) for _ in texts]


class _FakeVectorStore:
    """Scripted scored points for both wiki and manual-card collections."""

    def __init__(self, wiki_points: list[SimpleNamespace], manual_points: list[SimpleNamespace]) -> None:
        self._wiki_points = wiki_points
        self._manual_points = manual_points
        self.wiki_queries: list[dict[str, Any]] = []
        self.manual_queries: list[dict[str, Any]] = []

    async def query_wiki_entries(self, *, dense, kb_id: str, top_k: int = 3):
        self.wiki_queries.append({"kb_id": kb_id, "top_k": top_k})
        return self._wiki_points

    async def query_manual_cards(self, *, dense, kb_id: str, top_k: int = 3):
        self.manual_queries.append({"kb_id": kb_id, "top_k": top_k})
        return self._manual_points


def _wiki_point(entry_id: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(payload={"entry_id": entry_id}, score=score)


def _manual_point(card_id: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(payload={"card_id": card_id}, score=score)


@pytest.fixture
async def env(session_factory):
    """KB with two wiki entries and two toggle-on manual cards."""
    store = KnowledgeStore(session_factory)
    wiki_store = WikiStore(session_factory)
    await store.create_kb(kb_id=KB_ID, owner_id=OWNER_ID, name="混排测试库")
    wiki_a = await wiki_store.upsert_entry(KB_ID, title="DeerFlow", content="# DeerFlow\n\n超级智能体系统。", source_chunk_ids=["c1"])
    wiki_b = await wiki_store.upsert_entry(KB_ID, title="Gateway", content="# Gateway\n\n会话管理入口。", source_chunk_ids=["c2"])
    card_a = await store.create_manual_card(
        card_id="card-a",
        kb_id=KB_ID,
        owner_id=OWNER_ID,
        title="发布禁令",
        content="周五下午不发布，紧急修复走审批。",
        include_in_wiki_search=True,
    )
    card_b = await store.create_manual_card(
        card_id="card-b",
        kb_id=KB_ID,
        owner_id=OWNER_ID,
        title="值班表",
        content="奇数周张三，偶数周李四。",
        include_in_wiki_search=True,
    )
    return {"store": store, "wiki_store": wiki_store, "wiki_a": wiki_a, "wiki_b": wiki_b, "card_a": card_a, "card_b": card_b}


async def _search(env, fake_vs, *, top_k: int = 3) -> dict:
    return await _wiki_search_impl(
        "任意查询",
        _runtime(kb_id=KB_ID, user_id=OWNER_ID),
        store=env["store"],
        wiki_store=env["wiki_store"],
        vector_store=fake_vs,
        embedder=_FakeEmbedder(),
        top_k=top_k,
    )


@pytest.mark.asyncio
async def test_manual_card_outranks_wiki_in_shared_top_k_pool(env):
    """纯质量竞争：卡片分高则挤占 AI 条目名额（top_k=1 只留卡片）。"""
    fake_vs = _FakeVectorStore(
        wiki_points=[_wiki_point(env["wiki_a"]["id"], 0.5)],
        manual_points=[_manual_point("card-a", 0.95)],
    )

    result = await _search(env, fake_vs, top_k=1)

    assert len(result["entries"]) == 1
    hit = result["entries"][0]
    assert hit["source_type"] == "manual"
    assert hit["entry_id"] == "card-a"
    assert hit["title"] == "发布禁令"
    assert hit["content"] == "周五下午不发布，紧急修复走审批。"
    assert hit["citation_no"] == 1
    # Both paths are queried for up to top_k candidates each.
    assert fake_vs.wiki_queries == [{"kb_id": KB_ID, "top_k": 1}]
    assert fake_vs.manual_queries == [{"kb_id": KB_ID, "top_k": 1}]


@pytest.mark.asyncio
async def test_mixed_results_sorted_by_score_share_one_citation_range(env):
    """合并两路候选按 score 降序；引用编号跨越来源连续编号。"""
    fake_vs = _FakeVectorStore(
        wiki_points=[_wiki_point(env["wiki_a"]["id"], 0.8), _wiki_point(env["wiki_b"]["id"], 0.7)],
        manual_points=[_manual_point("card-a", 0.9)],
    )

    result = await _search(env, fake_vs, top_k=3)

    entries = result["entries"]
    assert [e["entry_id"] for e in entries] == ["card-a", env["wiki_a"]["id"], env["wiki_b"]["id"]]
    assert [e["source_type"] for e in entries] == ["manual", "wiki", "wiki"]
    assert [e["citation_no"] for e in entries] == [1, 2, 3]
    # The message tells the model the mix and the citation span.
    assert "2 篇百科条目" in result["message"]
    assert "1 张人工知识卡片" in result["message"]
    assert "[1]-[3]" in result["message"]


@pytest.mark.asyncio
async def test_shared_pool_truncates_after_merge(env):
    """top_k=2：合并排序后低分 wiki 落选，检索总量恒定。"""
    fake_vs = _FakeVectorStore(
        wiki_points=[_wiki_point(env["wiki_a"]["id"], 0.6), _wiki_point(env["wiki_b"]["id"], 0.8)],
        manual_points=[_manual_point("card-a", 0.9)],
    )

    result = await _search(env, fake_vs, top_k=2)

    entries = result["entries"]
    assert len(entries) == 2
    assert [e["entry_id"] for e in entries] == ["card-a", env["wiki_b"]["id"]]
    assert [e["source_type"] for e in entries] == ["manual", "wiki"]


@pytest.mark.asyncio
async def test_stale_point_skipped_when_toggle_switched_off(env):
    """开关已关的陈旧向量点（删除失败残留）在水合时跳过，不占名额。"""
    await env["store"].update_manual_card("card-a", include_in_wiki_search=False)
    fake_vs = _FakeVectorStore(
        wiki_points=[_wiki_point(env["wiki_a"]["id"], 0.5)],
        manual_points=[_manual_point("card-a", 0.99)],
    )

    result = await _search(env, fake_vs, top_k=2)

    entries = result["entries"]
    assert len(entries) == 1
    assert entries[0]["source_type"] == "wiki"
    assert entries[0]["entry_id"] == env["wiki_a"]["id"]


@pytest.mark.asyncio
async def test_point_of_deleted_card_skipped(env):
    """已删卡片的残留点跳过；跳过后用后续候选补满 top_k。"""
    fake_vs = _FakeVectorStore(
        wiki_points=[_wiki_point(env["wiki_a"]["id"], 0.6), _wiki_point(env["wiki_b"]["id"], 0.5)],
        manual_points=[_manual_point("ghost-card", 0.99)],
    )

    result = await _search(env, fake_vs, top_k=2)

    entries = result["entries"]
    assert [e["entry_id"] for e in entries] == [env["wiki_a"]["id"], env["wiki_b"]["id"]]
    assert all(e["source_type"] == "wiki" for e in entries)


@pytest.mark.asyncio
async def test_no_manual_hits_keeps_legacy_wiki_only_message(env):
    """无卡片命中时保持既有文案与行为（纯 wiki 路径回归）。"""
    fake_vs = _FakeVectorStore(
        wiki_points=[_wiki_point(env["wiki_a"]["id"], 0.8)],
        manual_points=[],
    )

    result = await _search(env, fake_vs, top_k=3)

    assert len(result["entries"]) == 1
    assert result["entries"][0]["source_type"] == "wiki"
    assert result["message"] == "命中 1 篇百科条目（引用编号 [1]，标注时照抄 citation_no）。"


@pytest.mark.asyncio
async def test_manual_only_hits_message_mentions_cards(env):
    """只有卡片命中时文案不含百科条目计数。"""
    fake_vs = _FakeVectorStore(
        wiki_points=[],
        manual_points=[_manual_point("card-a", 0.9), _manual_point("card-b", 0.8)],
    )

    result = await _search(env, fake_vs, top_k=3)

    assert [e["source_type"] for e in result["entries"]] == ["manual", "manual"]
    assert "2 张人工知识卡片" in result["message"]
    assert "百科条目" not in result["message"]


@pytest.mark.asyncio
async def test_empty_still_reports_nothing_found(env):
    fake_vs = _FakeVectorStore(wiki_points=[], manual_points=[])

    result = await _search(env, fake_vs, top_k=3)

    assert result["entries"] == []
    assert "未找到" in result["message"]
