"""孤儿向量对账清扫（spec 2026-10-04 / 2026-10-05 D4/D5）用例。

pin 住的契约：
- ``sweep_round(*, store, vector_store, graph_store, wiki_store, skip_kb_ids=None) -> SweepReport``
- 集合级枚举（无过滤 scroll + kb 分组）：kb 行缺 → 整组清（两段式复核）；
  kb 行在 → 逐点查行（两段式）；组内闸（skip_kb_ids ∪ wiki 腿）跳过。
- 卡片判据（D5）：行存在**且**开关开才保留；否则进候选。
- 只删 Qdrant 点；业务行永不触碰；判据=当下业务行（幂等）。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from deerflow.knowledge.graph.extractor import ExtractedEntity
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.sweep import sweep_round
from deerflow.knowledge.wiki.store import WikiStore
from deerflow.knowledge.worker import KnowledgeIndexWorker

KB = "kb-sweep"
OWNER = "u-1"
GONE = "kb-gone"


class FakeVectorStore:
    """四集合极简假体：payload 键与真实现逐字一致（vector_store.py:275/321/361/550）。"""

    chunks_collection = "kb_chunks"
    entities_collection = "kb_entities"
    wiki_entries_collection = "kb_wiki_entries"
    manual_cards_collection = "kb_manual_cards"

    def __init__(self) -> None:
        self.points: dict[str, dict[str, dict]] = {
            self.chunks_collection: {},
            self.entities_collection: {},
            self.wiki_entries_collection: {},
            self.manual_cards_collection: {},
        }
        self.calls: dict[str, list[list[str]]] = {
            "delete_chunks": [],
            "delete_entities": [],
            "delete_wiki_entries": [],
            "delete_manual_cards": [],
        }
        self.raise_on_scroll: set[str] = set()
        self.raise_on_delete: set[str] = set()

    def add(self, collection: str, payload: dict, *, point_id: str) -> None:
        self.points[collection][point_id] = payload

    async def init_collections(self) -> None:
        return None

    async def scroll_collection(self, collection_name: str, kb_id: str | None = None, *, with_vectors: bool = False, batch_size: int = 512):
        if collection_name in self.raise_on_scroll:
            raise RuntimeError("qdrant down (test)")
        items = self.points.get(collection_name, {}).items()
        return [SimpleNamespace(id=point_id, payload=payload) for point_id, payload in items if kb_id is None or payload.get("kb_id") == kb_id]

    async def delete_chunks(self, chunk_ids):
        if self.chunks_collection in self.raise_on_delete:
            raise RuntimeError("qdrant down (test)")
        self.calls["delete_chunks"].append(sorted(chunk_ids))
        self._remove(self.chunks_collection, "chunk_id", chunk_ids)

    async def delete_entities(self, kb_id, names):
        if self.entities_collection in self.raise_on_delete:
            raise RuntimeError("qdrant down (test)")
        self.calls["delete_entities"].append(sorted(names))
        self._remove(self.entities_collection, "name", names)

    async def delete_wiki_entries(self, kb_id, titles):
        if self.wiki_entries_collection in self.raise_on_delete:
            raise RuntimeError("qdrant down (test)")
        self.calls["delete_wiki_entries"].append(sorted(titles))
        self._remove(self.wiki_entries_collection, "title", titles)

    async def delete_manual_cards(self, card_ids):
        if self.manual_cards_collection in self.raise_on_delete:
            raise RuntimeError("qdrant down (test)")
        self.calls["delete_manual_cards"].append(sorted(card_ids))
        self._remove(self.manual_cards_collection, "card_id", card_ids)

    def _remove(self, collection: str, key: str, values) -> None:
        wanted = set(values)
        for point_id, payload in list(self.points[collection].items()):
            if payload.get(key) in wanted:
                self.points[collection].pop(point_id)


async def _seed(session_factory):
    """建一套最小业务数据：1 库 / 1 文档 / 1 切片 / 1 实体 / 1 条目 / 1 卡片（开关开）。"""
    store = KnowledgeStore(session_factory)
    graph = GraphStore(session_factory)
    wiki = WikiStore(session_factory)
    await store.create_kb(kb_id=KB, owner_id=OWNER, name="清扫库")
    await store.create_document(doc_id="doc-1", kb_id=KB, uploader_id=OWNER, name="a.md", size_bytes=1, storage_path="/tmp/a.md")
    await store.insert_chunks([{"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": KB, "chunk_index": 0, "text": "正文", "heading_path": [], "page": 0, "token_count": 2}])
    await graph.upsert_entities(KB, [ExtractedEntity(name="Alpha")], chunk_id="doc-1#0000")
    entry = await wiki.upsert_entry(KB, title="Alpha", content="内容", source_chunk_ids=["doc-1#0000"], status="ready")
    await store.create_manual_card(card_id="card-1", kb_id=KB, owner_id=OWNER, title="卡", content="卡正文", include_in_wiki_search=True)
    return store, graph, wiki, entry


def _fake_with_live_and_ghost(entry_id: str) -> FakeVectorStore:
    fake = FakeVectorStore()
    fake.add(fake.chunks_collection, {"chunk_id": "doc-1#0000", "kb_id": KB}, point_id="p-chunk-live")
    fake.add(fake.chunks_collection, {"chunk_id": "ghost#0000", "kb_id": KB}, point_id="p-chunk-ghost")
    fake.add(fake.entities_collection, {"name": "Alpha", "kb_id": KB}, point_id="p-ent-live")
    fake.add(fake.entities_collection, {"name": "Ghost", "kb_id": KB}, point_id="p-ent-ghost")
    fake.add(fake.wiki_entries_collection, {"entry_id": entry_id, "kb_id": KB, "title": "Alpha"}, point_id="p-wiki-live")
    fake.add(fake.wiki_entries_collection, {"entry_id": "w-ghost", "kb_id": KB, "title": "GhostTitle"}, point_id="p-wiki-ghost")
    fake.add(fake.manual_cards_collection, {"card_id": "card-1", "kb_id": KB, "title": "卡"}, point_id="p-card-live")
    fake.add(fake.manual_cards_collection, {"card_id": "c-ghost", "kb_id": KB, "title": "鬼卡"}, point_id="p-card-ghost")
    return fake


async def _round(store, graph, wiki, fake, **kwargs):
    return await sweep_round(store=store, vector_store=fake, graph_store=graph, wiki_store=wiki, **kwargs)


async def test_sweep_removes_orphans_and_keeps_live_points(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    fake = _fake_with_live_and_ghost(entry["id"])

    report = await _round(store, graph, wiki, fake)

    assert report.failed == []
    assert report.deleted == {"chunks": 1, "entities": 1, "wiki_entries": 1, "manual_cards": 1}
    assert report.deleted_kb_groups == {"chunks": 0, "entities": 0, "wiki_entries": 0, "manual_cards": 0}
    assert set(fake.points[fake.chunks_collection]) == {"p-chunk-live"}
    assert set(fake.points[fake.entities_collection]) == {"p-ent-live"}
    assert set(fake.points[fake.wiki_entries_collection]) == {"p-wiki-live"}
    assert set(fake.points[fake.manual_cards_collection]) == {"p-card-live"}
    assert report.scanned == {"chunks": 2, "entities": 2, "wiki_entries": 2, "manual_cards": 2}
    assert report.skipped == {"chunks": 0, "entities": 0, "wiki_entries": 0, "manual_cards": 0}
    assert fake.calls["delete_chunks"] == [["ghost#0000"]]
    assert fake.calls["delete_entities"] == [["Ghost"]]
    assert fake.calls["delete_wiki_entries"] == [["GhostTitle"]]
    assert fake.calls["delete_manual_cards"] == [["c-ghost"]]
    # 业务行永不触碰
    assert [row["chunk_id"] for row in await store.get_chunks_by_ids(["doc-1#0000", "ghost#0000"], kb_id=KB)] == ["doc-1#0000"]
    assert [row["name"] for row in await graph.list_entities(KB)] == ["Alpha"]
    assert [row["id"] for row in await wiki.list_entries(KB)] == [entry["id"]]
    assert (await store.get_manual_card("card-1")) is not None


async def test_deleted_kb_group_removed_across_collections(session_factory):
    """D4：kb 行没了的点，四个集合里整组清——旧枚举（活库表）看不见的那批。"""
    store, graph, wiki, entry = await _seed(session_factory)
    fake = _fake_with_live_and_ghost(entry["id"])
    fake.add(fake.chunks_collection, {"chunk_id": "g#0000", "kb_id": GONE}, point_id="p-g-chunk")
    fake.add(fake.entities_collection, {"name": "GoneEnt", "kb_id": GONE}, point_id="p-g-ent")
    fake.add(fake.wiki_entries_collection, {"entry_id": "w-gone", "kb_id": GONE, "title": "GoneTitle"}, point_id="p-g-wiki")
    fake.add(fake.manual_cards_collection, {"card_id": "c-gone", "kb_id": GONE, "title": "走卡"}, point_id="p-g-card")

    report = await _round(store, graph, wiki, fake)

    assert report.deleted_kb_groups == {"chunks": 1, "entities": 1, "wiki_entries": 1, "manual_cards": 1}
    assert fake.points[fake.chunks_collection].get("p-g-chunk") is None
    assert fake.points[fake.entities_collection].get("p-g-ent") is None
    assert fake.points[fake.wiki_entries_collection].get("p-g-wiki") is None
    assert fake.points[fake.manual_cards_collection].get("p-g-card") is None
    assert "p-chunk-live" in fake.points[fake.chunks_collection]  # 活库不动
    assert fake.calls["delete_chunks"] == [["ghost#0000"], ["g#0000"]]
    assert fake.calls["delete_entities"] == [["Ghost"], ["GoneEnt"]]
    assert fake.calls["delete_wiki_entries"] == [["GhostTitle"], ["GoneTitle"]]
    assert fake.calls["delete_manual_cards"] == [["c-ghost"], ["c-gone"]]


async def test_deleted_kb_group_recheck_keeps_points_when_kb_row_appears(session_factory):
    """复核守护：候选组第一遍查不到 kb 行、复核时行已落 —— 不删。"""
    store, graph, wiki, entry = await _seed(session_factory)
    fake = FakeVectorStore()
    fake.add(fake.chunks_collection, {"chunk_id": "x#0000", "kb_id": GONE}, point_id="p-x")
    original = store.get_kb
    calls = {"n": 0}

    async def flaky(kb_id):
        if kb_id == GONE:
            calls["n"] += 1
            if calls["n"] >= 2:
                return {"id": GONE, "name": "刚落库"}
            return None
        return await original(kb_id)

    store.get_kb = flaky  # type: ignore[method-assign]

    report = await _round(store, graph, wiki, fake)

    assert "p-x" in fake.points[fake.chunks_collection]
    assert report.deleted_kb_groups["chunks"] == 0
    assert report.skipped["chunks"] == 1
    assert fake.calls["delete_chunks"] == []


async def test_busy_kb_groups_are_skipped(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    fake = _fake_with_live_and_ghost(entry["id"])
    fake.add(fake.chunks_collection, {"chunk_id": "g#0000", "kb_id": GONE}, point_id="p-g-chunk")

    report = await _round(store, graph, wiki, fake, skip_kb_ids={KB, GONE})

    assert "p-chunk-ghost" in fake.points[fake.chunks_collection]  # 忙库逐点也不动
    assert "p-g-chunk" in fake.points[fake.chunks_collection]  # 忙的已删库组也跳过
    assert report.deleted == {"chunks": 0, "entities": 0, "wiki_entries": 0, "manual_cards": 0}
    assert report.deleted_kb_groups == {"chunks": 0, "entities": 0, "wiki_entries": 0, "manual_cards": 0}


async def test_sweep_failure_in_one_collection_does_not_block_others(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    fake = _fake_with_live_and_ghost(entry["id"])
    fake.raise_on_scroll.add(fake.entities_collection)

    report = await _round(store, graph, wiki, fake)

    assert report.failed == ["entities"]
    assert report.deleted == {"chunks": 1, "entities": 0, "wiki_entries": 1, "manual_cards": 1}
    assert "p-ent-ghost" in fake.points[fake.entities_collection]
    assert "p-chunk-ghost" not in fake.points[fake.chunks_collection]


async def test_sweep_delete_failure_recorded_and_others_continue(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    fake = _fake_with_live_and_ghost(entry["id"])
    fake.raise_on_delete.add(fake.chunks_collection)

    report = await _round(store, graph, wiki, fake)

    assert report.failed == ["chunks"]
    assert "p-chunk-ghost" in fake.points[fake.chunks_collection]
    assert report.deleted == {"chunks": 0, "entities": 1, "wiki_entries": 1, "manual_cards": 1}


async def test_candidate_recheck_keeps_point_whose_row_appears_between_passes(session_factory):
    """卡片创建竞态守护：候选点第一遍查不到行、复核时行已落 —— 不删。"""
    store, graph, wiki, entry = await _seed(session_factory)
    fake = _fake_with_live_and_ghost(entry["id"])
    original = store.get_chunks_by_ids
    calls = {"n": 0}

    async def flaky(chunk_ids, *, kb_id=None):
        calls["n"] += 1
        rows = await original(chunk_ids, kb_id=kb_id)
        if calls["n"] >= 2 and "ghost#0000" in chunk_ids:
            rows = rows + [{"chunk_id": "ghost#0000", "doc_id": "doc-1", "kb_id": KB}]
        return rows

    store.get_chunks_by_ids = flaky  # type: ignore[method-assign]

    report = await _round(store, graph, wiki, fake)

    assert "p-chunk-ghost" in fake.points[fake.chunks_collection]
    assert report.deleted["chunks"] == 0
    assert report.skipped["chunks"] == 1
    assert fake.calls["delete_chunks"] == []


async def test_card_flag_off_point_removed_and_flag_on_kept(session_factory):
    """D5：行存在但开关关 ⇒ 残留点进候选（清）；开关开 ⇒ 保留。"""
    store, graph, wiki, entry = await _seed(session_factory)
    await store.create_manual_card(card_id="card-2", kb_id=KB, owner_id=OWNER, title="关卡", content="关正文", include_in_wiki_search=False)
    fake = FakeVectorStore()
    fake.add(fake.manual_cards_collection, {"card_id": "card-1", "kb_id": KB, "title": "卡"}, point_id="p-card-on")
    fake.add(fake.manual_cards_collection, {"card_id": "card-2", "kb_id": KB, "title": "关卡"}, point_id="p-card-off")

    report = await _round(store, graph, wiki, fake)

    assert "p-card-on" in fake.points[fake.manual_cards_collection]
    assert "p-card-off" not in fake.points[fake.manual_cards_collection]
    assert report.deleted["manual_cards"] == 1
    assert fake.calls["delete_manual_cards"] == [["card-2"]]


async def test_card_flag_flip_recheck_keeps_point(session_factory):
    """复核守护：候选时开关关、复核时已开 —— 不删。"""
    store, graph, wiki, entry = await _seed(session_factory)
    await store.create_manual_card(card_id="card-2", kb_id=KB, owner_id=OWNER, title="关卡", content="关正文", include_in_wiki_search=False)
    fake = FakeVectorStore()
    fake.add(fake.manual_cards_collection, {"card_id": "card-2", "kb_id": KB, "title": "关卡"}, point_id="p-card-off")
    original = store.get_manual_card
    calls = {"n": 0}

    async def flaky(card_id):
        card = await original(card_id)
        if card_id == "card-2":
            calls["n"] += 1
            if calls["n"] >= 2 and card is not None:
                card = dict(card, include_in_wiki_search=True)
        return card

    store.get_manual_card = flaky  # type: ignore[method-assign]

    report = await _round(store, graph, wiki, fake)

    assert "p-card-off" in fake.points[fake.manual_cards_collection]
    assert report.deleted["manual_cards"] == 0
    assert report.skipped["manual_cards"] == 1


async def test_fresh_flag_off_point_kept_by_age_gate(session_factory):
    """①合成交错最小复现：toggle-on 的 [upsert→行写] 窗口里新点（龄≈0）不被删——修前此条红。"""
    store, graph, wiki, entry = await _seed(session_factory)
    await store.create_manual_card(card_id="card-2", kb_id=KB, owner_id=OWNER, title="关卡", content="关正文", include_in_wiki_search=False)
    fake = FakeVectorStore()
    fake.add(fake.manual_cards_collection, {"card_id": "card-2", "kb_id": KB, "title": "关卡", "updated_at": time.time()}, point_id="p-card-fresh")

    report = await _round(store, graph, wiki, fake)

    assert "p-card-fresh" in fake.points[fake.manual_cards_collection]
    assert report.deleted["manual_cards"] == 0
    assert fake.calls["delete_manual_cards"] == []


async def test_old_flag_off_point_deleted_by_age_gate(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    await store.create_manual_card(card_id="card-2", kb_id=KB, owner_id=OWNER, title="关卡", content="关正文", include_in_wiki_search=False)
    fake = FakeVectorStore()
    fake.add(fake.manual_cards_collection, {"card_id": "card-2", "kb_id": KB, "title": "关卡", "updated_at": time.time() - 3600}, point_id="p-card-old")

    report = await _round(store, graph, wiki, fake)

    assert "p-card-old" not in fake.points[fake.manual_cards_collection]
    assert report.deleted["manual_cards"] == 1


async def test_fresh_point_with_missing_row_kept(session_factory):
    """行缺 + 新点（create 的 [upsert→行插] 窗口）同样被龄门挡住。"""
    store, graph, wiki, entry = await _seed(session_factory)
    fake = FakeVectorStore()
    fake.add(fake.manual_cards_collection, {"card_id": "card-new", "kb_id": KB, "title": "新卡", "updated_at": time.time()}, point_id="p-card-create-window")

    report = await _round(store, graph, wiki, fake)

    assert "p-card-create-window" in fake.points[fake.manual_cards_collection]
    assert report.deleted["manual_cards"] == 0


async def test_deleted_kb_group_ignores_age_gate(session_factory):
    """已删库组不走龄门：组内新点照清。"""
    store, graph, wiki, entry = await _seed(session_factory)
    fake = FakeVectorStore()
    fake.add(fake.manual_cards_collection, {"card_id": "c-gone", "kb_id": GONE, "title": "走卡", "updated_at": time.time()}, point_id="p-g-card")

    report = await _round(store, graph, wiki, fake)

    assert report.deleted_kb_groups["manual_cards"] == 1
    assert "p-g-card" not in fake.points[fake.manual_cards_collection]


async def test_sweep_is_idempotent(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    fake = _fake_with_live_and_ghost(entry["id"])

    first = await _round(store, graph, wiki, fake)
    second = await _round(store, graph, wiki, fake)

    assert first.deleted == {"chunks": 1, "entities": 1, "wiki_entries": 1, "manual_cards": 1}
    assert second.deleted == {"chunks": 0, "entities": 0, "wiki_entries": 0, "manual_cards": 0}
    assert second.failed == []


# ── 触发接线（worker 挂靠 + 闸） ───────────────────────────────────────


async def test_sweep_loop_not_scheduled_when_disabled(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), graph_store=graph, wiki_store=wiki, sweep_enabled=False)

    await worker.start()
    try:
        assert worker._sweep_task is None
    finally:
        await worker.stop()


async def test_busy_kb_ids_covers_doc_and_wiki_legs(session_factory):
    store, graph, wiki, entry = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), graph_store=graph, wiki_store=wiki, sweep_enabled=False)

    assert worker.busy_kb_ids() == set()
    worker._busy_kbs.add(KB)
    worker._wiki_busy.add("kb-2")
    assert worker.busy_kb_ids() == {KB, "kb-2"}


async def test_sweep_once_skips_busy_and_migration_and_runs_when_idle(session_factory, monkeypatch):
    store, graph, wiki, entry = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), graph_store=graph, wiki_store=wiki, sweep_enabled=False)
    calls: list[set[str]] = []

    async def spy_round(**kwargs):
        calls.append(kwargs.get("skip_kb_ids"))

    async def spy_generations(**kwargs):
        return None

    monkeypatch.setattr("deerflow.knowledge.worker.sweep_round", spy_round)
    monkeypatch.setattr("deerflow.knowledge.worker.sweep_generations", spy_generations)
    monkeypatch.setattr("deerflow.knowledge.worker.migration_in_progress", lambda: False)
    monkeypatch.setattr("deerflow.knowledge.worker.effective_dimension", lambda: 1024)

    # 1) 文档在飞 → skip 集合带该库
    worker._busy_kbs.add(KB)
    await worker._sweep_once()
    assert calls == [{KB}]
    # 2) wiki 腿在飞 → 同上
    worker._busy_kbs.discard(KB)
    worker._wiki_busy.add(KB)
    await worker._sweep_once()
    assert calls == [{KB}, {KB}]
    # 3) 迁移在飞 → 整轮跳过
    worker._wiki_busy.discard(KB)
    monkeypatch.setattr("deerflow.knowledge.worker.migration_in_progress", lambda: True)
    await worker._sweep_once()
    assert len(calls) == 2
    # 4) 全空闲 → 跑（skip 为空集）
    monkeypatch.setattr("deerflow.knowledge.worker.migration_in_progress", lambda: False)
    await worker._sweep_once()
    assert calls == [{KB}, {KB}, set()]


async def test_sweep_once_skips_round_while_migration_app_gate_is_true(session_factory, monkeypatch):
    """D6：app 闸（migration_running_fn）命中 ⇒ 整轮跳过（建完未翻窗口的守护）。"""
    store, graph, wiki, entry = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), graph_store=graph, wiki_store=wiki, sweep_enabled=False, migration_running_fn=lambda: True)
    calls: list[str] = []

    async def spy_round(**kwargs):
        calls.append("round")

    async def spy_generations(**kwargs):
        calls.append("generations")

    monkeypatch.setattr("deerflow.knowledge.worker.sweep_round", spy_round)
    monkeypatch.setattr("deerflow.knowledge.worker.sweep_generations", spy_generations)
    monkeypatch.setattr("deerflow.knowledge.worker.migration_in_progress", lambda: False)

    await worker._sweep_once()
    assert calls == []


async def test_sweep_once_runs_generations_with_declared_width(session_factory, monkeypatch):
    store, graph, wiki, entry = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), graph_store=graph, wiki_store=wiki, sweep_enabled=False, migration_running_fn=lambda: False)
    seen: dict = {}

    async def spy_round(**kwargs):
        return None

    async def spy_generations(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr("deerflow.knowledge.worker.sweep_round", spy_round)
    monkeypatch.setattr("deerflow.knowledge.worker.sweep_generations", spy_generations)
    monkeypatch.setattr("deerflow.knowledge.worker.migration_in_progress", lambda: False)
    monkeypatch.setattr("deerflow.knowledge.worker.effective_dimension", lambda: 1536)

    await worker._sweep_once()

    assert seen["declared_width"] == 1536
    assert seen["vector_store"] is worker._vector_store
