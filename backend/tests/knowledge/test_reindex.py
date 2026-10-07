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
from unittest.mock import MagicMock

import pytest
from deerflow_knowledge import parser as parser_mod
from deerflow_knowledge import reindex as reindex_mod
from deerflow_knowledge.embedder import EmbedderError, EmbeddingResult
from deerflow_knowledge.indexer import index_chunks
from deerflow_knowledge.reindex import reindex_in_progress, reindex_kb, reindex_last_run_status, reindex_progress
from deerflow_knowledge.services import knowledge_service as ks_module
from deerflow_knowledge.services.knowledge_service import KnowledgeService
from deerflow_knowledge.store import KnowledgeStore
from deerflow_knowledge.vector_store import ChunkUpsert
from qdrant_client.models import SparseVector

OWNER_ID = str(uuid.UUID(int=1234567890))
KB_ID = "kb-1"


class _FakeVectorStore:
    """Records the upserts instead of talking to Qdrant (no service needed in CI)."""

    def __init__(self) -> None:
        self.upserts: list[ChunkUpsert] = []

    async def upsert_chunks(self, items) -> None:
        self.upserts.extend(items)

    def points(self) -> dict[str, tuple[tuple[float, ...], tuple[int, ...]]]:
        """The observable point set: id → (dense, sparse indices)."""
        return {item.chunk_id: (tuple(item.dense), tuple(item.sparse.indices)) for item in self.upserts}


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
    report = await reindex_kb(store, vector_store, _DeterministicEmbedder(), kb_id=KB_ID)

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
    report = await reindex_kb(store, _FakeVectorStore(), embedder, kb_id=KB_ID)

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
    report = await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(), kb_id=KB_ID, page_size=2)

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

    report = await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(fail_texts={"会失败的文本"}), kb_id=KB_ID)

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
    report = await reindex_kb(store, vector_store, _DeterministicEmbedder(), kb_id=KB_ID)

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

    report = await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(), kb_id=KB_ID)

    assert report.documents_total == 3
    assert report.documents_reindexed == 1
    assert report.documents_skipped == 2
    assert (await store.get_chunk("doc-inflight#0000"))["extract_status"] == "pending", "在飞文档的 chunk 不得被重建动过"


@pytest.mark.asyncio
async def test_reindex_exposes_in_flight_progress_and_last_run(session_factory):
    """可见性：跑的时候 in_progress + 进度可读，跑完置 succeeded。"""
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

    task = asyncio.create_task(reindex_kb(store, _FakeVectorStore(), _GatedEmbedder(), kb_id=KB_ID))
    await asyncio.wait_for(started.wait(), timeout=5)

    assert reindex_in_progress(KB_ID) is True
    progress = reindex_progress(KB_ID)
    assert progress["documents_total"] == 2
    assert progress["documents_done"] == 0, "第一个文档还没跑完"

    gate.set()
    await asyncio.wait_for(task, timeout=5)

    assert reindex_in_progress(KB_ID) is False
    assert reindex_last_run_status(KB_ID) == "succeeded"


# ── endpoints ──────────────────────────────────────────────────────────────


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    return KnowledgeService(store=KnowledgeStore(session_factory), vector_store=MagicMock(), worker=None, data_dir=tmp_path)


def _client(service: KnowledgeService):
    from _router_auth_helpers import make_authed_test_app
    from deerflow_knowledge.routers import knowledge_bases
    from deerflow_knowledge.service import KnowledgeExtensionService
    from fastapi.testclient import TestClient

    from app.gateway.auth.models import User

    app = make_authed_test_app(user_factory=lambda: User(email="owner@example.com", password_hash="x", system_role="user", id=uuid.UUID(OWNER_ID)))
    extension = KnowledgeExtensionService()
    extension.knowledge = service
    app.include_router(knowledge_bases.build_router(extension))
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
    """在飞时不重复入队。"""
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


# ── D2 嵌入身份（spec 2026-10-04 §2.2：重建全程成功 ⇒ 库身份=本次 embedder 身份）──


@pytest.mark.asyncio
async def test_reindex_stamps_the_library_identity_after_a_full_rebuild(session_factory):
    """记录=实发：盖章的必须是「真正产出这批向量」的 embedder 身份，不是事后读的配置。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["风急天高", "渚清沙白"])

    embedder = _DeterministicEmbedder()
    await reindex_kb(store, _FakeVectorStore(), embedder, kb_id=KB_ID)

    assert (await store.get_kb(KB_ID))["embedding_identity"] == embedder.identity


@pytest.mark.asyncio
async def test_an_incomplete_rebuild_never_stamps_the_library_identity(session_factory):
    """有批次软失败 ⇒ 不盖章：库不是均匀空间，宁可保持 NULL（未知）也不做假声明。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["会失败的文本", "风急天高"])

    await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(fail_texts={"会失败的文本"}), kb_id=KB_ID)

    assert (await store.get_kb(KB_ID))["embedding_identity"] is None


@pytest.mark.asyncio
async def test_a_complete_walk_stamps_only_when_asked_to(session_factory):
    """stamp=False（spec 2026-10-05 D2=乙）：主行走走完不盖章，章留给 delta 完整走完那一刻。"""
    store = KnowledgeStore(session_factory)
    await _kb(store)
    await _seed_doc(store, doc_id="doc-1", texts=["风急天高", "渚清沙白"])

    await reindex_kb(store, _FakeVectorStore(), _DeterministicEmbedder(), kb_id=KB_ID, stamp=False)

    assert (await store.get_kb(KB_ID))["embedding_identity"] is None
