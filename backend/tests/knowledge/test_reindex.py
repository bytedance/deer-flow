"""Tests for the re-embed reindex entry (spec 2026-09-14 §5 / P4).

The reindex is the *only* way out of "I changed the embedding provider / dimension":
it walks the library's existing chunks and re-embeds them through ``index_chunks`` — the
same part the worker uses — and **never re-parses** the source document. That is the
difference from ``POST /documents/{id}/retry``, which re-runs the whole pipeline: a
retry on a document whose original file is gone cannot help, while a re-embed can.

Point ids are deterministic (``uuid5``) and the upsert overwrites in place, so a rebuild
with the same embedder must reproduce the same point set — the idempotency self-check
below is the acceptance test for "reindex changes nothing but the vectors".
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import SparseVector

from app.gateway.services import knowledge_service as ks_module
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge import parser as parser_mod
from deerflow.knowledge import reindex as reindex_mod
from deerflow.knowledge.embed_texts import entity_embed_text, manual_card_embed_text, wiki_entry_embed_text
from deerflow.knowledge.embedder import EmbedderError, EmbeddingResult
from deerflow.knowledge.graph.extractor import ExtractedEntity
from deerflow.knowledge.graph.store import GraphStore
from deerflow.knowledge.indexer import index_chunks
from deerflow.knowledge.reindex import reindex_in_progress, reindex_kb, reindex_last_run_status, reindex_progress, reindex_status
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.vector_store import ChunkUpsert, EntityUpsert, KnowledgeVectorStore, ManualCardUpsert, WikiEntryUpsert
from deerflow.knowledge.wiki.store import WikiStore, wiki_entry_id

OWNER_ID = str(uuid.UUID(int=1234567890))
KB_ID = "kb-1"


class _FakeVectorStore:
    """Records the upserts instead of talking to Qdrant (no service needed in CI)."""

    def __init__(self) -> None:
        self.upserts: list[ChunkUpsert] = []
        self.entities: list[EntityUpsert] = []
        self.wiki_entries: list[WikiEntryUpsert] = []
        self.manual_cards: list[ManualCardUpsert] = []

    async def upsert_chunks(self, items) -> None:
        self.upserts.extend(items)

    async def upsert_entities(self, items) -> None:
        self.entities.extend(items)

    async def upsert_wiki_entries(self, items) -> None:
        self.wiki_entries.extend(items)

    async def upsert_manual_cards(self, items) -> None:
        self.manual_cards.extend(items)

    def points(self) -> dict[str, tuple[tuple[float, ...], tuple[int, ...]]]:
        """The observable point set: id → (dense, sparse indices)."""
        return {item.chunk_id: (tuple(item.dense), tuple(item.sparse.indices)) for item in self.upserts}

    def point_ids(self) -> dict[str, set[str]]:
        """Deterministic point ids per collection, derived the way the real store does."""
        return {
            "chunks": set(self.points()),
            "entities": {KnowledgeVectorStore._entity_point_id(item.kb_id, item.name) for item in self.entities},
            "wiki": {KnowledgeVectorStore._wiki_point_id(item.entry_id) for item in self.wiki_entries},
            "cards": {KnowledgeVectorStore._manual_card_point_id(item.card_id) for item in self.manual_cards},
        }


class _DeterministicEmbedder:
    """Text → a stable vector, so the same chunk must always land on the same point."""

    batch_size = 2
    identity = "space-test"

    def __init__(self, *, fail_texts: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail_texts or set()

    async def embed(self, texts, *, text_type: str = "document") -> list[EmbeddingResult]:
        self.calls.append(list(texts))
        if self._fail & set(texts):
            raise EmbedderError("embedding service down")
        return [
            EmbeddingResult(
                dense=[float(len(text)), float(sum(map(ord, text)) % 97)],
                sparse=SparseVector(indices=[index, index + 10], values=[0.5, 0.25]),
            )
            for index, text in enumerate(texts)
        ]


def _flatten(calls: list[list[str]]) -> list[str]:
    return [text for call in calls for text in call]


async def _seed_doc(store: KnowledgeStore, *, doc_id: str, texts: list[str], status: str = "ready", storage_path: str = "gone.pdf") -> None:
    await store.create_document(doc_id=doc_id, kb_id=KB_ID, uploader_id=OWNER_ID, name=f"{doc_id}.pdf", size_bytes=1, storage_path=storage_path)
    await store.update_document_status(doc_id, status)
    await store.insert_chunks([{"chunk_id": f"{doc_id}#{index:04d}", "doc_id": doc_id, "kb_id": KB_ID, "chunk_index": index, "text": text, "heading_path": ["H"], "page": index} for index, text in enumerate(texts)])


async def _kb(store: KnowledgeStore) -> None:
    await store.create_kb(kb_id=KB_ID, owner_id=OWNER_ID, name="库")


def _stores(store: KnowledgeStore) -> dict:
    """The two stores the shared-collection passes read from (same session factory)."""
    return {"graph_store": GraphStore(store._sf), "wiki_store": WikiStore(store._sf)}


async def _seed_entity(graph_store: GraphStore, name: str, description: str | None, *, type_: str = "概念") -> None:
    await graph_store.upsert_entities(KB_ID, [ExtractedEntity(name=name, type=type_, description=description)], chunk_id="doc-1#0000")


async def _seed_entry(wiki_store: WikiStore, title: str, content: str, *, status: str = "ready") -> None:
    await wiki_store.upsert_entry(KB_ID, title=title, content=content, source_chunk_ids=[], status=status)


async def _seed_card(store: KnowledgeStore, card_id: str, *, title: str, content: str, flag: bool) -> None:
    await store.create_manual_card(card_id=card_id, kb_id=KB_ID, owner_id=OWNER_ID, title=title, content=content, include_in_wiki_search=flag)


@pytest.fixture(autouse=True)
def _clean_inflight():
    """Module-level in-flight state must not leak between tests."""
    yield
    reindex_mod._IN_FLIGHT.pop(KB_ID, None)
    reindex_mod._LAST_RUN.pop(KB_ID, None)
    reindex_mod._PROGRESS.pop(KB_ID, None)


# ── orchestration ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reindex_reproduces_the_same_vector_points(session_factory, monkeypatch):
    """幂等自检：同一 embedder 重建后，向量点集合与重建前逐点一致。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["风急天高", "渚清沙白", "无边落木"])
    chunks = await store.list_chunks("doc-1", limit=100)

    vector_store = _FakeVectorStore()
    await index_chunks(store, vector_store, _DeterministicEmbedder(), kb_id=KB_ID, doc_id="doc-1", chunks=chunks)
    before = vector_store.points()
    assert len(before) == 3

    vector_store.upserts.clear()
    report = await reindex_kb(store, vector_store, _DeterministicEmbedder(), kb_id=KB_ID, **_stores(store))

    assert vector_store.points() == before, "重建必须逐点覆盖成同一组点（确定性 id + 同一 embedder）"
    assert report.documents_reindexed == 1
    assert report.chunks_indexed == 3


@pytest.mark.asyncio
async def test_reindex_never_reparses_the_source_document(session_factory, monkeypatch):
    """与 ``retry`` 的关键区别：重建只读 chunk，重解析一次都不能发生。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    # storage_path 指向不存在的文件：任何重解析尝试都会当场炸响
    await _seed_doc(store, doc_id="doc-1", texts=["正文一", "正文二"], storage_path="missing-on-disk.pdf")

    def _bomb(*args, **kwargs):
        raise AssertionError("重建不得重解析源文件")

    monkeypatch.setattr(parser_mod, "parse_document", _bomb)
    embedder = _DeterministicEmbedder()
    report = await reindex_kb(store, _FakeVectorStore(), embedder, kb_id=KB_ID, **_stores(store))

    assert report.documents_reindexed == 1
    assert sorted(_flatten(embedder.calls)) == ["正文一", "正文二"], "喂给嵌入器的必须就是库里那两段文本"


@pytest.mark.asyncio
async def test_reindex_pages_chunk_reads_and_writes_the_final_chunk_count(session_factory, monkeypatch):
    """分页读 chunk；``index_chunks`` 的 chunk_count 是「本次索引数」，分页后由编排层写最终值。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=[f"切片{i}" for i in range(5)])

    reads: list[tuple[int, int]] = []
    real_read = store.list_chunks

    async def _spy(doc_id: str, *, offset: int = 0, limit: int = 50):
        reads.append((offset, limit))
        return await real_read(doc_id, offset=offset, limit=limit)

    monkeypatch.setattr(store, "list_chunks", _spy)
    report = await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(), kb_id=KB_ID, page_size=2, **_stores(store))

    assert reads == [(0, 2), (2, 2), (4, 2)]
    assert report.chunks_indexed == 5
    assert (await store.get_document("doc-1"))["chunk_count"] == 5, "分页重建后 chunk_count 必须是总数，不是最后一页的大小"


@pytest.mark.asyncio
async def test_reindex_embed_failure_marks_chunks_but_continues(session_factory):
    """沿用既有降级契约：单批嵌入失败标脏该批，不中断整库。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-bad", texts=["会失败的文本"])
    await _seed_doc(store, doc_id="doc-ok", texts=["正常文本"])

    report = await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(fail_texts={"会失败的文本"}), kb_id=KB_ID, **_stores(store))

    assert report.documents_reindexed == 2, "一批失败不等于跳过这个文档"
    assert report.chunks_indexed == 1
    failed = await store.get_chunk("doc-bad#0000")
    assert failed["extract_status"] == "failed", "失败批次的 chunk 要标 failed（与 worker 同口径）"
    assert (await store.get_chunk("doc-ok#0000"))["extract_status"] != "failed"


@pytest.mark.asyncio
async def test_reindex_one_document_error_does_not_stop_the_library(session_factory, monkeypatch):
    """单文档异常（非嵌入错误）只记账，后面的文档照常重建。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    # list_documents 按 created_at desc 排（后建的先跑）：把会炸的文档放在后面建，
    # 它就先被访问 —— 这样「失败之后还在继续」才真的被验到，而不是失败发生在最后一条。
    await _seed_doc(store, doc_id="doc-ok", texts=["好"])
    await _seed_doc(store, doc_id="doc-boom", texts=["炸"])

    real_index = reindex_mod.index_chunks
    seen: list[str] = []

    async def _flaky(store_, vector_store_, embedder_, *, kb_id, doc_id, chunks):
        seen.append(doc_id)
        if doc_id == "doc-boom":
            raise RuntimeError("qdrant 掉线")
        return await real_index(store_, vector_store_, embedder_, kb_id=kb_id, doc_id=doc_id, chunks=chunks)

    monkeypatch.setattr(reindex_mod, "index_chunks", _flaky)
    vector_store = _FakeVectorStore()
    report = await reindex_kb(store, vector_store, _DeterministicEmbedder(), kb_id=KB_ID, **_stores(store))

    assert seen == ["doc-boom", "doc-ok"], "一个文档失败后必须继续下一个"
    assert report.documents_failed == 1
    assert report.documents_reindexed == 1
    assert set(vector_store.points()) == {"doc-ok#0000"}, "失败的文档不留半成品向量"
    assert reindex_last_run_status(KB_ID) == "succeeded", "降级与「整库失败」是两回事"


@pytest.mark.asyncio
async def test_reindex_skips_documents_still_in_the_pipeline(session_factory):
    """worker 在飞的文档不碰（它的腿会自己按新配置跑完）。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-ready", texts=["就绪"])
    await _seed_doc(store, doc_id="doc-inflight", texts=["在飞"], status="indexing")
    await _seed_doc(store, doc_id="doc-empty", texts=[])

    report = await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(), kb_id=KB_ID, **_stores(store))

    assert report.documents_total == 3
    assert report.documents_reindexed == 1
    assert report.documents_skipped == 2
    assert (await store.get_chunk("doc-inflight#0000"))["extract_status"] == "pending", "在飞文档的 chunk 不得被重建动过"


@pytest.mark.asyncio
async def test_reindex_exposes_in_flight_progress_and_last_run(session_factory):
    """可见性：跑的时候 in_progress + 进度可读，跑完置 succeeded（与 wiki 重建同形态）。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["一", "二"])
    await _seed_doc(store, doc_id="doc-2", texts=["三"])

    gate = asyncio.Event()
    started = asyncio.Event()

    class _GatedEmbedder(_DeterministicEmbedder):
        async def embed(self, texts, *, text_type: str = "document"):
            started.set()
            await gate.wait()
            return await super().embed(texts, text_type=text_type)

    assert reindex_in_progress(KB_ID) is False
    assert reindex_last_run_status(KB_ID) is None

    task = asyncio.create_task(reindex_kb(store, _FakeVectorStore(), _GatedEmbedder(), kb_id=KB_ID, **_stores(store)))
    await asyncio.wait_for(started.wait(), timeout=5)

    assert reindex_in_progress(KB_ID) is True
    progress = reindex_progress(KB_ID)
    assert progress["documents_total"] == 2
    assert progress["documents_done"] == 0, "第一个文档还没跑完"

    gate.set()
    await asyncio.wait_for(task, timeout=5)

    assert reindex_in_progress(KB_ID) is False
    assert reindex_last_run_status(KB_ID) == "succeeded"


# ── the three shared-collection passes (spec 2026-09-24 §4.1) ──────────────


@pytest.mark.asyncio
async def test_reindex_rebuilds_entity_vectors_from_the_write_side_text(session_factory):
    """实体遍：重嵌文本与写入侧同源（含原始行 None description 的归一）。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    graph_store = GraphStore(store._sf)
    await _seed_entity(graph_store, "DeerFlow", "超级智能体", type_="系统")
    await _seed_entity(graph_store, "Nulled", None, type_="组件")
    embedder = _DeterministicEmbedder()
    vector_store = _FakeVectorStore()

    report = await reindex_kb(store, vector_store, embedder, kb_id=KB_ID, graph_store=graph_store, wiki_store=WikiStore(store._sf))

    texts = _flatten(embedder.calls)
    assert set(texts) >= {entity_embed_text("DeerFlow", "超级智能体"), entity_embed_text("Nulled", None)}
    assert "Nulled\n" in texts, "原始行的 None description 要按写入侧口径归一成空串"
    by_name = {item.name: item for item in vector_store.entities}
    assert sorted(by_name) == ["DeerFlow", "Nulled"]
    assert by_name["DeerFlow"].kb_id == KB_ID and by_name["DeerFlow"].type == "系统" and by_name["DeerFlow"].description == "超级智能体"
    assert by_name["Nulled"].type == "组件" and by_name["Nulled"].description == ""
    assert report.entities_indexed == 2
    assert report.documents_total == 0 and report.chunks_indexed == 0, "没有文档时也不该碰切片"


@pytest.mark.asyncio
async def test_reindex_rebuilds_every_wiki_entry_regardless_of_status(session_factory):
    """百科遍：全状态重嵌（dirty 与 ready 同等对待）、文本同源、业务行不动。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    wiki_store = WikiStore(store._sf)
    long_content = "长" * 600
    await _seed_entry(wiki_store, "DeerFlow", "超级智能体综述")
    await _seed_entry(wiki_store, "Gateway", long_content, status="dirty")
    embedder = _DeterministicEmbedder()
    vector_store = _FakeVectorStore()

    report = await reindex_kb(store, vector_store, embedder, kb_id=KB_ID, graph_store=GraphStore(store._sf), wiki_store=wiki_store)

    texts = _flatten(embedder.calls)
    assert set(texts) >= {wiki_entry_embed_text("DeerFlow", "超级智能体综述"), wiki_entry_embed_text("Gateway", long_content)}
    assert len(wiki_entry_embed_text("Gateway", long_content).split("\n", 1)[1]) == 500, "条目正文只嵌前 500 字（与写入侧同源）"
    by_title = {item.title: item for item in vector_store.wiki_entries}
    assert sorted(by_title) == ["DeerFlow", "Gateway"]
    assert by_title["Gateway"].entry_id == wiki_entry_id(KB_ID, "Gateway")
    assert report.wiki_entries_indexed == 2
    # 硬约束「不改业务行」：dirty 记号与正文都原样留在业务库里。
    gateway = await wiki_store.get_entry(wiki_entry_id(KB_ID, "Gateway"))
    assert gateway["status"] == "dirty" and gateway["content"] == long_content


@pytest.mark.asyncio
async def test_reindex_rebuilds_only_flagged_cards_and_pages_them(session_factory, monkeypatch):
    """卡片遍：只取 include_in_wiki_search=True、按 offset/limit 游标翻页、关卡不放点。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    for index in range(3):
        await _seed_card(store, f"card-on-{index}", title=f"线上禁令{index}", content="周五不发布", flag=True)
    await _seed_card(store, "card-off", title="草稿", content="还没定", flag=False)

    reads: list[tuple[int, int, bool | None]] = []
    real_read = store.list_manual_cards

    async def _spy(kb_id: str, *, offset: int = 0, limit: int = 50, include_in_wiki_search: bool | None = None):
        reads.append((offset, limit, include_in_wiki_search))
        return await real_read(kb_id, offset=offset, limit=limit, include_in_wiki_search=include_in_wiki_search)

    monkeypatch.setattr(store, "list_manual_cards", _spy)
    embedder = _DeterministicEmbedder()
    vector_store = _FakeVectorStore()

    report = await reindex_kb(store, vector_store, embedder, kb_id=KB_ID, graph_store=GraphStore(store._sf), wiki_store=WikiStore(store._sf), page_size=2)

    assert reads == [(0, 2, True), (2, 2, True)], "卡片是唯一带游标分页的一遍，且必须带开关过滤"
    assert sorted(item.card_id for item in vector_store.manual_cards) == ["card-on-0", "card-on-1", "card-on-2"]
    assert set(_flatten(embedder.calls)) >= {manual_card_embed_text("线上禁令0", "周五不发布")}
    assert report.cards_indexed == 3, "开关关着的卡片一个点都不放"


@pytest.mark.asyncio
async def test_reindex_one_failing_batch_does_not_stop_the_other_passes(session_factory):
    """批级失败：计数只记写成，其余遍照跑，run 判定仍 succeeded。"""

    class _BrokenEntityStore(_FakeVectorStore):
        # 注入点放在写入侧：与实体遍嵌什么文本无关，改文本的 neuter 不会连带打红这里。
        async def upsert_entities(self, items) -> None:
            raise RuntimeError("qdrant 掉线")

    store = KnowledgeStore(session_factory)
    await _kb(store)
    graph_store, wiki_store = GraphStore(store._sf), WikiStore(store._sf)
    await _seed_entity(graph_store, "DeerFlow", "超级智能体")
    await _seed_entry(wiki_store, "DeerFlow", "综述")
    await _seed_card(store, "card-1", title="禁令", content="正文", flag=True)

    report = await reindex_kb(store, _BrokenEntityStore(), _DeterministicEmbedder(), kb_id=KB_ID, graph_store=graph_store, wiki_store=wiki_store)

    assert report.entities_indexed == 0, "失败批一个点都不算写成"
    assert report.wiki_entries_indexed == 1 and report.cards_indexed == 1, "一批失败不得带走其余遍"
    assert reindex_last_run_status(KB_ID) == "succeeded"


@pytest.mark.asyncio
async def test_reindex_one_failing_pass_does_not_stop_the_rest(session_factory, monkeypatch):
    """遍级失败（读那一遍就炸）也只记账：后面的遍照跑。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    graph_store, wiki_store = GraphStore(store._sf), WikiStore(store._sf)
    await _seed_entity(graph_store, "DeerFlow", "超级智能体")
    await _seed_card(store, "card-1", title="禁令", content="正文", flag=True)

    async def _boom(*args, **kwargs):
        raise RuntimeError("业务库掉线")

    monkeypatch.setattr(wiki_store, "list_entries", _boom)
    report = await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(), kb_id=KB_ID, graph_store=graph_store, wiki_store=wiki_store)

    assert report.wiki_entries_indexed == 0
    assert report.entities_indexed == 1 and report.cards_indexed == 1, "一遍炸了，后面的遍照跑"
    assert reindex_last_run_status(KB_ID) == "succeeded"


@pytest.mark.asyncio
async def test_reindex_progress_and_report_carry_the_three_collection_counters(session_factory):
    """报告/进度三键：run 起手即为 0，跑完按实际写成数记账。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    graph_store, wiki_store = GraphStore(store._sf), WikiStore(store._sf)
    await _seed_entity(graph_store, "DeerFlow", "超级智能体")
    await _seed_entry(wiki_store, "DeerFlow", "综述")
    await _seed_card(store, "card-1", title="禁令", content="正文", flag=True)

    gate = asyncio.Event()
    started = asyncio.Event()

    class _GatedEmbedder(_DeterministicEmbedder):
        async def embed(self, texts, *, text_type: str = "document"):
            started.set()
            await gate.wait()
            return await super().embed(texts, text_type=text_type)

    task = asyncio.create_task(reindex_kb(store, _FakeVectorStore(), _GatedEmbedder(), kb_id=KB_ID, graph_store=graph_store, wiki_store=wiki_store))
    await asyncio.wait_for(started.wait(), timeout=5)

    status = reindex_status(KB_ID)
    assert status["in_progress"] is True
    progress = status["progress"]
    assert progress["entities_indexed"] == 0 and progress["wiki_entries_indexed"] == 0 and progress["cards_indexed"] == 0, "run 起手三键置 0"

    gate.set()
    report = await asyncio.wait_for(task, timeout=5)

    assert (report.entities_indexed, report.wiki_entries_indexed, report.cards_indexed) == (1, 1, 1)
    assert reindex_progress(KB_ID) is None


@pytest.mark.asyncio
async def test_reindex_shared_passes_are_idempotent(session_factory):
    """三遍重复跑不新增点：落在同一组确定性 id 上（原位覆盖）。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    graph_store, wiki_store = GraphStore(store._sf), WikiStore(store._sf)
    await _seed_entity(graph_store, "DeerFlow", "超级智能体")
    await _seed_entry(wiki_store, "DeerFlow", "综述")
    await _seed_card(store, "card-1", title="禁令", content="正文", flag=True)
    vector_store = _FakeVectorStore()
    shared = {"graph_store": graph_store, "wiki_store": wiki_store}

    await reindex_kb(store, vector_store, _DeterministicEmbedder(), kb_id=KB_ID, **shared)
    after_first = vector_store.point_ids()
    assert {kind: len(ids) for kind, ids in after_first.items()} == {"chunks": 0, "entities": 1, "wiki": 1, "cards": 1}

    report = await reindex_kb(store, vector_store, _DeterministicEmbedder(), kb_id=KB_ID, **shared)

    assert vector_store.point_ids() == after_first, "第二次跑必须命中同一组点 id，一个新点都不多"
    assert (report.entities_indexed, report.wiki_entries_indexed, report.cards_indexed) == (1, 1, 1)


# ── endpoints ──────────────────────────────────────────────────────────────


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    return KnowledgeService(store=KnowledgeStore(session_factory), vector_store=MagicMock(), worker=None, data_dir=tmp_path)


def _client(service: KnowledgeService):
    from _router_auth_helpers import make_authed_test_app
    from fastapi.testclient import TestClient

    from app.gateway.auth.models import User
    from app.gateway.routers import knowledge_bases

    app = make_authed_test_app(user_factory=lambda: User(email="owner@example.com", password_hash="x", system_role="user", id=uuid.UUID(OWNER_ID)))
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def test_reindex_endpoint_enqueues(service):
    service.reindex_fn = MagicMock(return_value=None)
    client = _client(service)
    kb = client.post("/api/knowledge-bases", json={"name": "库"}).json()

    response = client.post(f"/api/knowledge-bases/{kb['id']}/reindex")

    assert response.status_code == 202
    assert response.json() == {"status": "enqueued"}
    service.reindex_fn.assert_called_once_with(kb["id"])


def test_reindex_endpoint_reports_already_running(service, monkeypatch):
    """在飞时不重复入队（与 wiki 重建同口径）。"""
    monkeypatch.setattr(ks_module, "reindex_in_progress", lambda _kb_id: True)
    service.reindex_fn = MagicMock(return_value=None)
    client = _client(service)
    kb = client.post("/api/knowledge-bases", json={"name": "库"}).json()

    response = client.post(f"/api/knowledge-bases/{kb['id']}/reindex")

    assert response.status_code == 202
    assert response.json() == {"status": "already_running"}
    service.reindex_fn.assert_not_called()


def test_reindex_status_endpoint_reports_idle_state(service):
    client = _client(service)
    kb = client.post("/api/knowledge-bases", json={"name": "库"}).json()

    response = client.get(f"/api/knowledge-bases/{kb['id']}/reindex/status")

    assert response.status_code == 200
    assert response.json() == {"in_progress": False, "last_run": None, "progress": None}


@pytest.mark.asyncio
async def test_run_reindex_hands_the_two_shared_stores_to_the_rebuild(session_factory, tmp_path, monkeypatch):
    """生产调用点的接线钉子：漏传两个 store = 三集合静默不重嵌（本对要修的正是这种缺陷）。"""
    service = KnowledgeService(store=KnowledgeStore(session_factory), vector_store=MagicMock(), worker=None, data_dir=tmp_path)
    spy = AsyncMock()
    monkeypatch.setattr(ks_module, "reindex_kb", spy)
    monkeypatch.setattr(ks_module, "build_embedder", MagicMock)

    await service._run_reindex(KB_ID)

    assert spy.await_args.kwargs["graph_store"] is service.graph_store
    assert spy.await_args.kwargs["wiki_store"] is service.wiki_store


# ── D2 嵌入身份（spec 2026-10-04 §2.2：重建全程成功 ⇒ 库身份=本次 embedder 身份）──


@pytest.mark.asyncio
async def test_reindex_stamps_the_library_identity_after_a_full_rebuild(session_factory):
    """记录=实发：盖章的必须是「真正产出这批向量」的 embedder 身份，不是事后读的配置。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["风急天高", "渚清沙白"])

    embedder = _DeterministicEmbedder()
    await reindex_kb(store, _FakeVectorStore(), embedder, kb_id=KB_ID, **_stores(store))

    assert (await store.get_kb(KB_ID))["embedding_identity"] == embedder.identity


@pytest.mark.asyncio
async def test_an_incomplete_rebuild_never_stamps_the_library_identity(session_factory):
    """有批次软失败 ⇒ 不盖章：库不是均匀空间，宁可保持 NULL（未知）也不做假声明。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["会失败的文本", "风急天高"])

    await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(fail_texts={"会失败的文本"}), kb_id=KB_ID, **_stores(store))

    assert (await store.get_kb(KB_ID))["embedding_identity"] is None


@pytest.mark.asyncio
async def test_a_complete_walk_stamps_only_when_asked_to(session_factory):
    """stamp=False（spec 2026-10-05 D2=乙）：主行走走完不盖章，章留给 delta 完整走完那一刻。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["风急天高", "渚清沙白"])

    await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(), kb_id=KB_ID, stamp=False, **_stores(store))

    assert (await store.get_kb(KB_ID))["embedding_identity"] is None
