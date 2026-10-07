"""孤儿向量对账清扫（spec 2026-10-04 / 2026-10-05 D4/D5）用例。

pin 住的契约：
- ``sweep_round(*, store, vector_store, skip_kb_ids=None) -> SweepReport``
- 集合级枚举（无过滤 scroll + kb 分组）：kb 行缺 → 整组清（两段式复核）；
  kb 行在 → 逐点查行（两段式）；组内闸（skip_kb_ids）跳过。
- 只删 Qdrant 点；业务行永不触碰；判据=当下业务行（幂等）。
"""

from __future__ import annotations

from types import SimpleNamespace

from deerflow_knowledge.store import KnowledgeStore
from deerflow_knowledge.sweep import sweep_round
from deerflow_knowledge.worker import KnowledgeIndexWorker

KB = "kb-sweep"
OWNER = "u-1"
GONE = "kb-gone"


class FakeVectorStore:
    """单集合极简假体：payload 键与真实现逐字一致（vector_store.py）。"""

    chunks_collection = "kb_chunks"

    def __init__(self) -> None:
        self.points: dict[str, dict[str, dict]] = {
            self.chunks_collection: {},
        }
        self.calls: dict[str, list[list[str]]] = {
            "delete_chunks": [],
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

    def _remove(self, collection: str, key: str, values) -> None:
        wanted = set(values)
        for point_id, payload in list(self.points[collection].items()):
            if payload.get(key) in wanted:
                self.points[collection].pop(point_id)


async def _seed(session_factory):
    """建一套最小业务数据：1 库 / 1 文档 / 1 切片。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id=KB, owner_id=OWNER, name="清扫库")
    await store.create_document(doc_id="doc-1", kb_id=KB, uploader_id=OWNER, name="a.md", size_bytes=1, storage_path="/tmp/a.md")
    await store.insert_chunks([{"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": KB, "chunk_index": 0, "text": "正文", "heading_path": [], "page": 0, "token_count": 2}])
    return store


def _fake_with_live_and_ghost() -> FakeVectorStore:
    fake = FakeVectorStore()
    fake.add(fake.chunks_collection, {"chunk_id": "doc-1#0000", "kb_id": KB}, point_id="p-chunk-live")
    fake.add(fake.chunks_collection, {"chunk_id": "ghost#0000", "kb_id": KB}, point_id="p-chunk-ghost")
    return fake


async def _round(store, fake, **kwargs):
    return await sweep_round(store=store, vector_store=fake, **kwargs)


async def test_sweep_removes_orphans_and_keeps_live_points(session_factory):
    store = await _seed(session_factory)
    fake = _fake_with_live_and_ghost()

    report = await _round(store, fake)

    assert report.failed == []
    assert report.deleted == {"chunks": 1}
    assert report.deleted_kb_groups == {"chunks": 0}
    assert set(fake.points[fake.chunks_collection]) == {"p-chunk-live"}
    assert report.scanned == {"chunks": 2}
    assert report.skipped == {"chunks": 0}
    assert fake.calls["delete_chunks"] == [["ghost#0000"]]
    # 业务行永不触碰
    assert [row["chunk_id"] for row in await store.get_chunks_by_ids(["doc-1#0000", "ghost#0000"], kb_id=KB)] == ["doc-1#0000"]


async def test_deleted_kb_group_removed_across_collections(session_factory):
    """D4：kb 行没了的点，整组清——旧枚举（活库表）看不见的那批。"""
    store = await _seed(session_factory)
    fake = _fake_with_live_and_ghost()
    fake.add(fake.chunks_collection, {"chunk_id": "g#0000", "kb_id": GONE}, point_id="p-g-chunk")

    report = await _round(store, fake)

    assert report.deleted_kb_groups == {"chunks": 1}
    assert fake.points[fake.chunks_collection].get("p-g-chunk") is None
    assert "p-chunk-live" in fake.points[fake.chunks_collection]  # 活库不动
    assert fake.calls["delete_chunks"] == [["ghost#0000"], ["g#0000"]]


async def test_deleted_kb_group_recheck_keeps_points_when_kb_row_appears(session_factory):
    """复核守护：候选组第一遍查不到 kb 行、复核时行已落 —— 不删。"""
    store = await _seed(session_factory)
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

    report = await _round(store, fake)

    assert "p-x" in fake.points[fake.chunks_collection]
    assert report.deleted_kb_groups["chunks"] == 0
    assert report.skipped["chunks"] == 1
    assert fake.calls["delete_chunks"] == []


async def test_busy_kb_groups_are_skipped(session_factory):
    store = await _seed(session_factory)
    fake = _fake_with_live_and_ghost()
    fake.add(fake.chunks_collection, {"chunk_id": "g#0000", "kb_id": GONE}, point_id="p-g-chunk")

    report = await _round(store, fake, skip_kb_ids={KB, GONE})

    assert "p-chunk-ghost" in fake.points[fake.chunks_collection]  # 忙库逐点也不动
    assert "p-g-chunk" in fake.points[fake.chunks_collection]  # 忙的已删库组也跳过
    assert report.deleted == {"chunks": 0}
    assert report.deleted_kb_groups == {"chunks": 0}


async def test_sweep_failure_in_one_collection_does_not_block_others(session_factory):
    store = await _seed(session_factory)
    fake = _fake_with_live_and_ghost()
    fake.raise_on_scroll.add(fake.chunks_collection)

    report = await _round(store, fake)

    assert report.failed == ["chunks"]
    assert report.deleted == {"chunks": 0}
    assert "p-chunk-ghost" in fake.points[fake.chunks_collection]


async def test_sweep_delete_failure_recorded_and_others_continue(session_factory):
    store = await _seed(session_factory)
    fake = _fake_with_live_and_ghost()
    fake.raise_on_delete.add(fake.chunks_collection)

    report = await _round(store, fake)

    assert report.failed == ["chunks"]
    assert "p-chunk-ghost" in fake.points[fake.chunks_collection]
    assert report.deleted == {"chunks": 0}


async def test_candidate_recheck_keeps_point_whose_row_appears_between_passes(session_factory):
    """切片创建竞态守护：候选点第一遍查不到行、复核时行已落 —— 不删。"""
    store = await _seed(session_factory)
    fake = _fake_with_live_and_ghost()
    original = store.get_chunks_by_ids
    calls = {"n": 0}

    async def flaky(chunk_ids, *, kb_id=None):
        calls["n"] += 1
        rows = await original(chunk_ids, kb_id=kb_id)
        if calls["n"] >= 2 and "ghost#0000" in chunk_ids:
            rows = rows + [{"chunk_id": "ghost#0000", "doc_id": "doc-1", "kb_id": KB}]
        return rows

    store.get_chunks_by_ids = flaky  # type: ignore[method-assign]

    report = await _round(store, fake)

    assert "p-chunk-ghost" in fake.points[fake.chunks_collection]
    assert report.deleted["chunks"] == 0
    assert report.skipped["chunks"] == 1
    assert fake.calls["delete_chunks"] == []


async def test_sweep_is_idempotent(session_factory):
    store = await _seed(session_factory)
    fake = _fake_with_live_and_ghost()

    first = await _round(store, fake)
    second = await _round(store, fake)

    assert first.deleted == {"chunks": 1}
    assert second.deleted == {"chunks": 0}
    assert second.failed == []


# ── 触发接线（worker 挂靠 + 闸） ───────────────────────────────────────


async def test_sweep_loop_not_scheduled_when_disabled(session_factory):
    store = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), sweep_enabled=False)

    await worker.start()
    try:
        assert worker._sweep_task is None
    finally:
        await worker.stop()


async def test_busy_kb_ids_covers_doc_leg(session_factory):
    store = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), sweep_enabled=False)

    assert worker.busy_kb_ids() == set()
    worker._busy_kbs.add(KB)
    assert worker.busy_kb_ids() == {KB}


async def test_sweep_once_skips_busy_and_migration_and_runs_when_idle(session_factory, monkeypatch):
    store = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), sweep_enabled=False)
    calls: list[set[str]] = []

    async def spy_round(**kwargs):
        calls.append(kwargs.get("skip_kb_ids"))

    async def spy_generations(**kwargs):
        return None

    monkeypatch.setattr("deerflow_knowledge.worker.sweep_round", spy_round)
    monkeypatch.setattr("deerflow_knowledge.worker.sweep_generations", spy_generations)
    monkeypatch.setattr("deerflow_knowledge.worker.migration_in_progress", lambda: False)
    monkeypatch.setattr("deerflow_knowledge.worker.effective_dimension", lambda: 1024)

    # 1) 文档在飞 → skip 集合带该库
    worker._busy_kbs.add(KB)
    await worker._sweep_once()
    assert calls == [{KB}]
    # 2) 迁移在飞 → 整轮跳过
    worker._busy_kbs.discard(KB)
    monkeypatch.setattr("deerflow_knowledge.worker.migration_in_progress", lambda: True)
    await worker._sweep_once()
    assert len(calls) == 1
    # 3) 全空闲 → 跑（skip 为空集）
    monkeypatch.setattr("deerflow_knowledge.worker.migration_in_progress", lambda: False)
    await worker._sweep_once()
    assert calls == [{KB}, set()]


async def test_sweep_once_skips_round_while_migration_app_gate_is_true(session_factory, monkeypatch):
    """D6：app 闸（migration_running_fn）命中 ⇒ 整轮跳过（建完未翻窗口的守护）。"""
    store = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), sweep_enabled=False, migration_running_fn=lambda: True)
    calls: list[str] = []

    async def spy_round(**kwargs):
        calls.append("round")

    async def spy_generations(**kwargs):
        calls.append("generations")

    monkeypatch.setattr("deerflow_knowledge.worker.sweep_round", spy_round)
    monkeypatch.setattr("deerflow_knowledge.worker.sweep_generations", spy_generations)
    monkeypatch.setattr("deerflow_knowledge.worker.migration_in_progress", lambda: False)

    await worker._sweep_once()
    assert calls == []


async def test_sweep_once_runs_generations_with_declared_width(session_factory, monkeypatch):
    store = await _seed(session_factory)
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), sweep_enabled=False, migration_running_fn=lambda: False)
    seen: dict = {}

    async def spy_round(**kwargs):
        return None

    async def spy_generations(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr("deerflow_knowledge.worker.sweep_round", spy_round)
    monkeypatch.setattr("deerflow_knowledge.worker.sweep_generations", spy_generations)
    monkeypatch.setattr("deerflow_knowledge.worker.migration_in_progress", lambda: False)
    monkeypatch.setattr("deerflow_knowledge.worker.effective_dimension", lambda: 1536)

    await worker._sweep_once()

    assert seen["declared_width"] == 1536
    assert seen["vector_store"] is worker._vector_store
