"""文件侧孤儿对账（spec 2026-10-05 §2.2）用例。

pin 住的契约：
- ``reconcile_files(*, data_dir, store, skip_kb_ids=None) -> FileReconcileReport``
- walk ``knowledge/``：doc 行缺（或 kb_id 不匹配）→ 整目录清；kb 行缺 → 整棵清；
  kb 级直挂文件不属对账面；两段式（收集 → 复核 → 删）。
- 只删文件目录；业务行永不触碰；忙库整库跳过；失败仅记录、下轮重试。
"""

from __future__ import annotations

from pathlib import Path

from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.sweep import reconcile_files
from deerflow.knowledge.worker import KnowledgeIndexWorker

KB = "kb-files"
OWNER = "u-1"


def _tree(tmp_path: Path, kb_id: str, doc_id: str, name: str = "a.md") -> Path:
    doc_dir = tmp_path / "knowledge" / kb_id / doc_id
    doc_dir.mkdir(parents=True)
    (doc_dir / name).write_bytes(b"x")
    return doc_dir


async def _seed(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id=KB, owner_id=OWNER, name="文件库")
    await store.create_document(doc_id="doc-1", kb_id=KB, uploader_id=OWNER, name="a.md", size_bytes=1, storage_path="/tmp/a.md")
    await store.create_kb(kb_id="kb-other", owner_id=OWNER, name="别库")
    await store.create_document(doc_id="doc-2", kb_id="kb-other", uploader_id=OWNER, name="b.md", size_bytes=1, storage_path="/tmp/b.md")
    return store


async def test_orphan_doc_dir_removed_live_and_kb_level_files_kept(session_factory, tmp_path):
    store = await _seed(session_factory)
    live = _tree(tmp_path, KB, "doc-1")
    ghost = _tree(tmp_path, KB, "ghost")
    mismatch = _tree(tmp_path, KB, "doc-2")  # 行在别库 ⇒ kb_id 不匹配
    kb_level = tmp_path / "knowledge" / KB / "golden.jsonl"
    kb_level.write_text("{}")

    report = await reconcile_files(data_dir=tmp_path, store=store)

    assert not ghost.exists() and not mismatch.exists()
    assert live.exists() and (live / "a.md").exists()
    assert kb_level.exists()
    assert report.removed_docs == 2
    assert report.removed_kbs == 0
    assert report.failed == []


async def test_kb_dir_without_row_removed_whole_tree(session_factory, tmp_path):
    store = await _seed(session_factory)
    live = _tree(tmp_path, KB, "doc-1")
    dead = tmp_path / "knowledge" / "kb-dead"
    (dead / "doc-x").mkdir(parents=True)
    (dead / "doc-x" / "f.md").write_bytes(b"x")
    (dead / "golden.jsonl").write_text("{}")

    report = await reconcile_files(data_dir=tmp_path, store=store)

    assert not dead.exists()
    assert report.removed_kbs == 1
    assert live.exists()  # 活库不动


async def test_candidate_recheck_keeps_dir_whose_row_appears_between_passes(session_factory, tmp_path):
    """上传 write→insert 在途窗口守护：第一遍查不到行、复核时行已落 —— 不删。"""
    store = await _seed(session_factory)
    live = _tree(tmp_path, KB, "late-doc")
    original = store.get_document
    calls = {"n": 0}

    async def flaky(doc_id):
        calls["n"] += 1
        if doc_id == "late-doc" and calls["n"] >= 2:
            return {"id": "late-doc", "kb_id": KB}
        return await original(doc_id)

    store.get_document = flaky  # type: ignore[method-assign]

    report = await reconcile_files(data_dir=tmp_path, store=store)

    assert live.exists()
    assert report.removed_docs == 0
    assert report.kept == 1


async def test_busy_kb_dirs_are_skipped(session_factory, tmp_path):
    store = await _seed(session_factory)
    ghost = _tree(tmp_path, KB, "ghost")

    report = await reconcile_files(data_dir=tmp_path, store=store, skip_kb_ids={KB})

    assert ghost.exists()
    assert report.removed_docs == 0
    assert report.doc_dirs == 0  # 整库跳过，连扫都不扫


# ── 接线：_sweep_once 带 data_dir 跑文件腿 ─────────────────────────────


class FakeVectorStore:
    chunks_collection = "kb_chunks"
    entities_collection = "kb_entities"
    wiki_entries_collection = "kb_wiki_entries"
    manual_cards_collection = "kb_manual_cards"

    async def init_collections(self) -> None:
        return None

    async def scroll_collection(self, collection_name, kb_id=None, *, with_vectors=False, batch_size=512):
        return []


async def test_sweep_once_reconciles_files_for_idle_kbs_only(session_factory, tmp_path, monkeypatch):
    store = await _seed(session_factory)
    idle_ghost = _tree(tmp_path, "kb-other", "ghost-2")
    busy_ghost = _tree(tmp_path, KB, "ghost-1")
    worker = KnowledgeIndexWorker(store=store, vector_store=FakeVectorStore(), sweep_enabled=False, data_dir=tmp_path)

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("deerflow.knowledge.worker.migration_in_progress", lambda: False)
    monkeypatch.setattr("deerflow.knowledge.worker.sweep_generations", _noop)
    monkeypatch.setattr("deerflow.knowledge.worker.effective_dimension", lambda: 1024)

    worker._busy_kbs.add(KB)
    await worker._sweep_once()

    assert not idle_ghost.exists()  # 空闲库的孤儿被收
    assert busy_ghost.exists()  # 忙库跳过
