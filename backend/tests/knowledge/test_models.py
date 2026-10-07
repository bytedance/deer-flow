"""Tests for the knowledge-base ORM models and KnowledgeStore CRUD.

Covers the RAG business tables ``knowledge_bases``, ``documents`` and
``chunks``. The sqlite database is bootstrapped through the real persistence
bootstrap, so these tests also prove the table definitions round-trip.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from deerflow.knowledge.models import (
    ChunkRow,
    DocumentRow,
    KnowledgeBaseRow,
)
from deerflow.knowledge.store import KnowledgeStore


@pytest.mark.asyncio
async def test_kb_create_get_list_round_trip(session_factory):
    store = KnowledgeStore(session_factory)

    created = await store.create_kb(kb_id="kb-1", owner_id="user-1", name="产品资料", description="p")
    assert created["id"] == "kb-1"
    assert created["owner_id"] == "user-1"
    assert created["visibility"] == "private"  # Phase-1 scope fence: private KBs only
    assert created["created_at"] is not None

    fetched = await store.get_kb("kb-1")
    assert fetched is not None
    assert fetched["name"] == "产品资料"

    owned = await store.list_kbs("user-1")
    assert [kb["id"] for kb in owned] == ["kb-1"]
    assert await store.list_kbs("user-2") == []
    assert await store.get_kb("kb-missing") is None


@pytest.mark.asyncio
async def test_kb_visibility_explicit_value(session_factory):
    store = KnowledgeStore(session_factory)

    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="a", visibility="private")
    row = await store.get_kb("kb-1")
    assert row["visibility"] == "private"


@pytest.mark.asyncio
async def test_document_defaults_and_fields(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")

    doc = await store.create_document(
        doc_id="doc-1",
        kb_id="kb-1",
        uploader_id="user-1",
        name="产品手册.pdf",
        size_bytes=2_400_000,
        storage_path=".deer-flow/data/uploads/kb-1/doc-1.pdf",
    )

    # Phase-1 must carry uploader_id (spec §3.6: equals kb owner for now,
    # activates real uploader semantics with shared KBs in Phase 2).
    assert doc["uploader_id"] == "user-1"
    assert doc["status"] == "uploaded"
    assert doc["progress_percent"] == 0
    assert doc["chunk_count"] is None  # unfinished docs render "—" in the list
    assert doc["storage_path"].endswith("doc-1.pdf")
    assert doc["error"] is None
    assert doc["size_bytes"] == 2_400_000

    listed = await store.list_documents("kb-1")
    assert [d["id"] for d in listed] == ["doc-1"]
    assert await store.get_document("doc-missing") is None


@pytest.mark.asyncio
async def test_document_status_machine_update(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(
        doc_id="doc-1",
        kb_id="kb-1",
        uploader_id="user-1",
        name="a.pdf",
        size_bytes=10,
        storage_path="p",
    )

    updated = await store.update_document_status("doc-1", "indexing", progress_percent=67)
    assert updated["status"] == "indexing"
    assert updated["progress_percent"] == 67

    ready = await store.update_document_status("doc-1", "ready", progress_percent=100, chunk_count=156)
    assert ready["status"] == "ready"
    assert ready["chunk_count"] == 156

    failed = await store.update_document_status("doc-1", "failed", error="parse timeout")
    assert failed["status"] == "failed"
    assert failed["error"] == "parse timeout"


@pytest.mark.asyncio
async def test_document_path_status_defaults_null(session_factory):
    """spec §5 兼容：新旧行缺省 `path_status` 为 null，前端不展示悬停。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    doc = await store.create_document(
        doc_id="doc-1",
        kb_id="kb-1",
        uploader_id="user-1",
        name="a.md",
        size_bytes=10,
        storage_path="p",
    )
    assert doc["path_status"] is None
    assert (await store.get_document("doc-1"))["path_status"] is None


@pytest.mark.asyncio
async def test_document_path_status_partial_merge(session_factory):
    """spec §5：path_status 写入语义为局部合并——只更新当次阶段对应的 key，
    不覆盖其他路。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(
        doc_id="doc-1",
        kb_id="kb-1",
        uploader_id="user-1",
        name="a.md",
        size_bytes=10,
        storage_path="p",
    )

    entered = await store.update_document_status("doc-1", "indexing", path_status={"vector": "pending", "caption": "pending"})
    assert entered["path_status"] == {"vector": "pending", "caption": "pending"}

    # 只写 vector=done，caption 必须保持 pending（整体覆盖即违反契约）
    merged = await store.update_document_status("doc-1", "indexing", path_status={"vector": "done"})
    assert merged["path_status"] == {"vector": "done", "caption": "pending"}

    # 独立读取与列表序列化同样携带合并结果（持久化而非内存态）
    assert (await store.get_document("doc-1"))["path_status"] == {"vector": "done", "caption": "pending"}
    listed = await store.list_documents("kb-1")
    assert listed[0]["path_status"] == {"vector": "done", "caption": "pending"}


@pytest.mark.asyncio
async def test_reset_document_for_retry_clears_path_status(session_factory):
    """retry 重置：path_status 与 progress/error 一起清空（worker 重跑时重建）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(
        doc_id="doc-1",
        kb_id="kb-1",
        uploader_id="user-1",
        name="a.md",
        size_bytes=10,
        storage_path="p",
    )
    await store.update_document_status("doc-1", "failed", error="boom", path_status={"vector": "done", "caption": "failed"})

    reset = await store.reset_document_for_retry("doc-1")
    assert reset is not None
    assert reset["status"] == "uploaded"
    assert reset["path_status"] is None


@pytest.mark.asyncio
async def test_chunks_insert_list_and_extract_status(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(
        doc_id="doc-1",
        kb_id="kb-1",
        uploader_id="user-1",
        name="a.pdf",
        size_bytes=10,
        storage_path="p",
    )

    inserted = await store.insert_chunks(
        [
            {
                "chunk_id": "doc-1#0000",
                "doc_id": "doc-1",
                "kb_id": "kb-1",
                "chunk_index": 0,
                "text": "第一章正文……",
                "heading_path": ["第1章"],
                "page": 1,
                "token_count": 486,
            },
            {
                "chunk_id": "doc-1#0001",
                "doc_id": "doc-1",
                "kb_id": "kb-1",
                "chunk_index": 1,
                "text": "第二节正文……",
                "heading_path": ["第1章", "1.2节"],
                "page": 2,
                "token_count": 512,
            },
        ]
    )
    assert inserted == 2
    assert await store.count_chunks("doc-1") == 2

    page = await store.list_chunks("doc-1", offset=0, limit=10)
    assert [c["chunk_id"] for c in page] == ["doc-1#0000", "doc-1#0001"]
    # Chunk text lives in the business DB (spec §3.2 切片存储归属).
    assert page[0]["text"] == "第一章正文……"
    assert page[0]["heading_path"] == ["第1章"]
    assert page[0]["page"] == 1
    assert page[0]["token_count"] == 486
    # Extract state machine defaults to pending for resume support (spec §3.4).
    assert page[0]["extract_status"] == "pending"
    assert page[0]["extract_error"] is None


@pytest.mark.asyncio
async def test_chunk_extract_status_transitions_persist_for_resume(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=10, storage_path="p")
    await store.insert_chunks(
        [
            {"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "t0", "heading_path": [], "page": None, "token_count": 1},
            {"chunk_id": "doc-1#0001", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 1, "text": "t1", "heading_path": [], "page": None, "token_count": 1},
            {"chunk_id": "doc-1#0002", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 2, "text": "t2", "heading_path": [], "page": None, "token_count": 1},
        ]
    )

    # pending → done (with normalized entity backfill), empty, failed.
    await store.update_chunk_extract("doc-1#0000", "done", entities=["广义相对论", "GPS"])
    await store.update_chunk_extract("doc-1#0001", "empty")
    await store.update_chunk_extract("doc-1#0002", "failed", error="llm timeout")

    chunks = {c["chunk_id"]: c for c in await store.list_chunks("doc-1")}
    assert chunks["doc-1#0000"]["extract_status"] == "done"
    assert chunks["doc-1#0000"]["entities"] == ["广义相对论", "GPS"]
    assert chunks["doc-1#0001"]["extract_status"] == "empty"
    assert chunks["doc-1#0002"]["extract_status"] == "failed"
    assert chunks["doc-1#0002"]["extract_error"] == "llm timeout"


@pytest.mark.asyncio
async def test_chunk_pagination(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=10, storage_path="p")
    await store.insert_chunks([{"chunk_id": f"doc-1#{i:04d}", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": i, "text": f"t{i}", "heading_path": [], "page": None, "token_count": 1} for i in range(5)])

    first = await store.list_chunks("doc-1", offset=0, limit=2)
    rest = await store.list_chunks("doc-1", offset=2, limit=10)
    assert [c["chunk_index"] for c in first] == [0, 1]
    assert [c["chunk_index"] for c in rest] == [2, 3, 4]


@pytest.mark.asyncio
async def test_delete_document_cascades_chunks(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=10, storage_path="p")
    await store.insert_chunks([{"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "t", "heading_path": [], "page": None, "token_count": 1}])

    assert await store.delete_document("doc-1") is True
    assert await store.get_document("doc-1") is None
    assert await store.count_chunks("doc-1") == 0
    assert await store.delete_document("doc-1") is False


@pytest.mark.asyncio
async def test_delete_kb_cascades_all_tables(session_factory):
    """Deleting a KB must clear business rows across its tables; the
    Qdrant-side cleanup is layered on top by the API/worker (spec §3.7)."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="kb")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=10, storage_path="p")
    await store.insert_chunks([{"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "t", "heading_path": [], "page": None, "token_count": 1}])

    assert await store.delete_kb("kb-1") is True
    assert await store.get_kb("kb-1") is None
    assert await store.list_documents("kb-1") == []
    async with session_factory() as session:
        for row_cls in (ChunkRow, DocumentRow):
            remaining = (await session.execute(select(row_cls).where(row_cls.kb_id == "kb-1"))).scalars().all()
            assert remaining == [], f"{row_cls.__tablename__} rows left after delete_kb"
        assert (await session.execute(select(KnowledgeBaseRow).where(KnowledgeBaseRow.id == "kb-1"))).scalars().all() == []


@pytest.mark.asyncio
async def test_update_kb_renames_and_descriptions(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="旧名", description="旧描述")

    updated = await store.update_kb("kb-1", name="新名", description="新描述")

    assert updated is not None
    assert updated["name"] == "新名"
    assert updated["description"] == "新描述"
    assert (await store.get_kb("kb-1"))["name"] == "新名"


@pytest.mark.asyncio
async def test_update_kb_partial_and_missing(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="名", description="述")

    updated = await store.update_kb("kb-1", name="只改名")
    assert updated is not None
    assert updated["name"] == "只改名"
    assert updated["description"] == "述"  # untouched

    assert await store.update_kb("kb-nope", name="x") is None


@pytest.mark.asyncio
async def test_list_non_terminal_documents_for_startup_recovery(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    for doc_id, status in [("d-uploaded", "uploaded"), ("d-parsing", "parsing"), ("d-indexing", "indexing"), ("d-ready", "ready"), ("d-failed", "failed")]:
        await store.create_document(doc_id=doc_id, kb_id="kb-1", uploader_id="user-1", name=f"{doc_id}.pdf", size_bytes=1, storage_path="p")
        if status != "uploaded":
            await store.update_document_status(doc_id, status)

    recovered = await store.list_non_terminal_documents()

    assert sorted(d["id"] for d in recovered) == ["d-indexing", "d-parsing", "d-uploaded"]


@pytest.mark.asyncio
async def test_delete_chunks_by_doc_only_that_document(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=1, storage_path="p")
    await store.create_document(doc_id="doc-2", kb_id="kb-1", uploader_id="user-1", name="b.pdf", size_bytes=1, storage_path="p")
    await store.insert_chunks(
        [
            {"chunk_id": "doc-1#0000", "doc_id": "doc-1", "kb_id": "kb-1", "chunk_index": 0, "text": "t1", "heading_path": [], "page": None, "token_count": 1},
            {"chunk_id": "doc-2#0000", "doc_id": "doc-2", "kb_id": "kb-1", "chunk_index": 0, "text": "t2", "heading_path": [], "page": None, "token_count": 1},
        ]
    )

    assert await store.delete_chunks_by_doc("doc-1") == 1
    assert await store.count_chunks("doc-1") == 0
    assert await store.count_chunks("doc-2") == 1


@pytest.mark.asyncio
async def test_reset_document_for_retry_clears_failure_state(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-1", kb_id="kb-1", uploader_id="user-1", name="a.pdf", size_bytes=1, storage_path="p")
    await store.update_document_status("doc-1", "failed", progress_percent=40, chunk_count=3, error="boom")

    reset = await store.reset_document_for_retry("doc-1")

    assert reset is not None
    assert reset["status"] == "uploaded"
    assert reset["progress_percent"] == 0
    assert reset["chunk_count"] is None
    assert reset["error"] is None
    assert await store.reset_document_for_retry("doc-nope") is None
