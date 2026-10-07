"""The width migration (spec 2026-09-26 D1 乙 / D5-2 / D5-6 / D5-7).

Changing the width is not a settings edit: every stored vector belongs to the old vector
space, so the library is re-embedded into a *new* generation and the switch happens only
once that generation is complete. The order **is** the contract:

1. the new generation is built fresh — a leftover from an interrupted run is dropped first,
2. **every** library is re-embedded into it (the collections are deployment-wide while the
   rebuild entry is per library),
3. anything the switch window added or changed is re-embedded too (D5-6), *including* a
   document still moving through the worker: until the switch, the worker's own writes
   still land in the old generation, which is exactly the case ``reindex_kb`` skips,
4. the caller flips the configuration and drops the old generation. This module never
   writes config — that is the app layer's move (D5-7).

Nothing here talks to Qdrant or to a model: the vector store is a recorder and the embedder
is deterministic, so the assertions are about *what the migration decided*, not about
transport.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from qdrant_client.models import SparseVector

from deerflow.knowledge.dimension_migration import migrate_collections, migration_in_progress, migration_last_run, migration_progress
from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.store import KnowledgeStore

OWNER_A = str(uuid.UUID(int=11))
OWNER_B = str(uuid.UUID(int=22))
KB_A = "kb-a"
KB_B = "kb-b"


class _Generations:
    """A vector store double that records the *order* of what the migration did to it."""

    def __init__(self, *, on_first_upsert: Callable[[], Awaitable[None]] | None = None) -> None:
        self.events: list[str] = []
        self.chunk_ids: list[str] = []
        self.deleted_docs: list[str] = []
        self._on_first_upsert = on_first_upsert

    async def drop_collections(self) -> list[str]:
        self.events.append("drop")
        return ["kb_chunks_1536"]

    async def create_collections(self) -> None:
        self.events.append("create")

    async def upsert_chunks(self, items) -> None:
        if self._on_first_upsert is not None:
            hook, self._on_first_upsert = self._on_first_upsert, None
            await hook()
        self.events.append("chunks")
        self.chunk_ids.extend(item.chunk_id for item in items)

    async def delete_by_doc(self, doc_id: str) -> None:
        self.events.append(f"delete:{doc_id}")
        self.deleted_docs.append(doc_id)


class _DeterministicEmbedder:
    batch_size = 4
    identity = "space-target"

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        return [EmbeddingResult(dense=[float(len(text)), float(sum(map(ord, text)) % 97)], sparse=SparseVector(indices=[0, 1], values=[0.5, 0.25])) for text in texts]


async def _seed_kb(store: KnowledgeStore, *, kb_id: str, owner_id: str, name: str) -> None:
    await store.create_kb(kb_id=kb_id, owner_id=owner_id, name=name)


async def _seed_doc(store: KnowledgeStore, *, kb_id: str, doc_id: str, texts: list[str], status: str = "ready") -> None:
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id=OWNER_A, name=f"{doc_id}.pdf", size_bytes=1, storage_path="gone.pdf")
    await store.update_document_status(doc_id, status)
    await store.insert_chunks([{"chunk_id": f"{doc_id}#{index:04d}", "doc_id": doc_id, "kb_id": kb_id, "chunk_index": index, "text": text, "heading_path": ["H"], "page": index} for index, text in enumerate(texts)])


@pytest.fixture(autouse=True)
def _clean_state():
    from deerflow.knowledge import dimension_migration as migration_mod

    yield
    migration_mod._IN_FLIGHT = False
    migration_mod._PROGRESS = None
    migration_mod._LAST_RUN = None
    migration_mod._DETAIL = None


@pytest.mark.asyncio
async def test_the_migration_rebuilds_every_library_into_a_fresh_generation(session_factory):
    """两个库、两个所有者：迁移都要覆盖，且新代是先删残留再建、建完才写点。"""
    store = KnowledgeStore(session_factory)
    await _seed_kb(store, kb_id=KB_A, owner_id=OWNER_A, name="甲库")
    await _seed_kb(store, kb_id=KB_B, owner_id=OWNER_B, name="乙库")
    await _seed_doc(store, kb_id=KB_A, doc_id="doc-a", texts=["甲一", "甲二"])
    await _seed_doc(store, kb_id=KB_B, doc_id="doc-b", texts=["乙一"])

    generations = _Generations()
    report = await migrate_collections(store, vector_store=generations, embedder=_DeterministicEmbedder())

    assert generations.events[0] == "drop", "上次中断留下的半成品要先删（先删后建）"
    assert generations.events[1] == "create"
    assert set(generations.chunk_ids) == {"doc-a#0000", "doc-a#0001", "doc-b#0000"}, "两个库的切片都要进新代"
    assert report.kbs_total == 2
    assert report.kbs_done == 2
    assert report.chunks_indexed == 3
    assert report.delta_documents == 0, "窗口里没有东西动过，就不该有补嵌这一遍"


@pytest.mark.asyncio
async def test_a_document_that_arrives_during_the_migration_is_embedded_before_the_switch(session_factory):
    """窗口内新入库的文档（D5-6）：主遍之后、翻配置之前必须被补进新代。"""
    store = KnowledgeStore(session_factory)
    await _seed_kb(store, kb_id=KB_A, owner_id=OWNER_A, name="甲库")
    await _seed_doc(store, kb_id=KB_A, doc_id="doc-a", texts=["旧一"])

    async def _arrive() -> None:
        await _seed_doc(store, kb_id=KB_A, doc_id="doc-new", texts=["新来的一篇"])

    generations = _Generations(on_first_upsert=_arrive)
    report = await migrate_collections(store, vector_store=generations, embedder=_DeterministicEmbedder())

    assert "doc-new#0000" in generations.chunk_ids
    # 差量以"库"为单位：动过的库整遍重来（含它已有的文档），没动过的库一次都不跑。
    assert report.delta_documents == 2
    assert report.delta_chunks_indexed == 2


@pytest.mark.asyncio
async def test_a_document_still_moving_through_the_worker_is_not_left_behind(session_factory):
    """仍在管线里的文档也在窗口内 —— 切换前它的写入还落在旧代，所以必须补嵌（不能按"终态"筛掉）。"""
    store = KnowledgeStore(session_factory)
    await _seed_kb(store, kb_id=KB_A, owner_id=OWNER_A, name="甲库")
    await _seed_doc(store, kb_id=KB_A, doc_id="doc-a", texts=["旧一"])

    async def _arrive() -> None:
        await _seed_doc(store, kb_id=KB_A, doc_id="doc-moving", texts=["还在抽取"], status="indexing")

    generations = _Generations(on_first_upsert=_arrive)
    report = await migrate_collections(store, vector_store=generations, embedder=_DeterministicEmbedder())

    assert "doc-moving#0000" in generations.chunk_ids, "非终态文档的切片也要补进新代"
    assert report.delta_documents == 2


@pytest.mark.asyncio
async def test_a_document_deleted_during_the_window_drops_its_points_from_the_new_generation(session_factory):
    """窗口内被删掉的文档：它旧代的点被删除路径清掉了，新代不能留孤儿。"""
    store = KnowledgeStore(session_factory)
    await _seed_kb(store, kb_id=KB_A, owner_id=OWNER_A, name="甲库")
    await _seed_doc(store, kb_id=KB_A, doc_id="doc-a", texts=["留下的"])
    await _seed_doc(store, kb_id=KB_A, doc_id="doc-gone", texts=["要删掉的"])

    async def _delete() -> None:
        await store.delete_document("doc-gone")

    generations = _Generations(on_first_upsert=_delete)
    await migrate_collections(store, vector_store=generations, embedder=_DeterministicEmbedder())

    assert "doc-gone" in generations.deleted_docs
    assert "doc-gone#0000" not in generations.chunk_ids or generations.events.index("delete:doc-gone") > generations.events.index("chunks")


@pytest.mark.asyncio
async def test_a_pass_that_breaks_aborts_and_records_the_failure(session_factory, monkeypatch):
    """跑不完就不许当作跑完：异常向上抛（调用方据此决定不翻配置），状态记 failed。"""
    store = KnowledgeStore(session_factory)
    await _seed_kb(store, kb_id=KB_A, owner_id=OWNER_A, name="甲库")
    await _seed_kb(store, kb_id=KB_B, owner_id=OWNER_B, name="乙库")
    await _seed_doc(store, kb_id=KB_A, doc_id="doc-a", texts=["甲"])
    await _seed_doc(store, kb_id=KB_B, doc_id="doc-b", texts=["乙"])

    real = KnowledgeStore.list_documents
    seen: dict[str, int] = {}

    async def _flaky(self, kb_id):
        seen[kb_id] = seen.get(kb_id, 0) + 1
        if kb_id == KB_B and seen[kb_id] > 1:  # 快照那次放过，主遍那次炸
            raise RuntimeError("库读坏了")
        return await real(self, kb_id)

    monkeypatch.setattr(KnowledgeStore, "list_documents", _flaky)
    generations = _Generations()

    with pytest.raises(RuntimeError, match="库读坏了"):
        await migrate_collections(store, vector_store=generations, embedder=_DeterministicEmbedder())

    verdict, detail = migration_last_run()
    assert verdict == "failed"
    assert "库读坏了" in (detail or "")
    assert migration_in_progress() is False
    assert migration_progress() is None


@pytest.mark.asyncio
async def test_the_state_is_readable_while_it_runs_and_cleared_when_it_is_done(session_factory):
    store = KnowledgeStore(session_factory)
    await _seed_kb(store, kb_id=KB_A, owner_id=OWNER_A, name="甲库")
    await _seed_doc(store, kb_id=KB_A, doc_id="doc-a", texts=["甲"])

    seen: list[dict | None] = []
    generations = _Generations()

    async def _snapshot_state() -> None:
        assert migration_in_progress() is True
        seen.append(migration_progress())

    generations._on_first_upsert = _snapshot_state
    await migrate_collections(store, vector_store=generations, embedder=_DeterministicEmbedder())

    assert seen and seen[0] is not None and seen[0]["kbs_total"] == 1
    assert migration_in_progress() is False
    assert migration_progress() is None
    assert migration_last_run()[0] == "succeeded"


def test_the_migration_refuses_to_report_success_without_a_run():
    """没跑过就是没跑过 —— 状态面不许把'从未迁移'说成别的。"""
    assert migration_last_run() == (None, None)
    assert migration_in_progress() is False
    assert migration_progress() is None
