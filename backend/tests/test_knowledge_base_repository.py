"""Tests for knowledge base repository layer."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.knowledge_base.document_repository import DocumentRepository
from deerflow.persistence.knowledge_base.index_job_repository import IndexJobRepository
from deerflow.persistence.knowledge_base.model import IndexJobRow, KnowledgeBaseDocumentRow, KnowledgeBaseRow
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield sf
    await engine.dispose()


@pytest_asyncio.fixture
async def kb_repo(session_factory):
    return KnowledgeBaseRepository(session_factory)


@pytest_asyncio.fixture
async def doc_repo(session_factory):
    return DocumentRepository(session_factory)


@pytest_asyncio.fixture
async def job_repo(session_factory):
    return IndexJobRepository(session_factory)


TENANT = "tenant-1"
USER = "user-1"


class TestKnowledgeBaseRepository:
    @pytest.mark.asyncio
    async def test_create_and_get(self, kb_repo: KnowledgeBaseRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="My KB", description="Test")
        assert kb["name"] == "My KB"
        assert kb["description"] == "Test"
        assert kb["collection_name"].startswith("kb_")
        assert kb["status"] == "active"

        fetched = await kb_repo.get(kb["id"], tenant_id=TENANT, owner_user_id=USER)
        assert fetched is not None
        assert fetched["id"] == kb["id"]

    @pytest.mark.asyncio
    async def test_get_returns_none_for_wrong_owner(self, kb_repo: KnowledgeBaseRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="Private")
        result = await kb_repo.get(kb["id"], tenant_id=TENANT, owner_user_id="other-user")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_owner(self, kb_repo: KnowledgeBaseRepository):
        await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="KB1")
        await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="KB2")
        await kb_repo.create(tenant_id=TENANT, owner_user_id="other", name="KB3")

        items = await kb_repo.list_by_owner(tenant_id=TENANT, owner_user_id=USER)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_update(self, kb_repo: KnowledgeBaseRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="Old")
        updated = await kb_repo.update(kb["id"], tenant_id=TENANT, owner_user_id=USER, name="New")
        assert updated is not None
        assert updated["name"] == "New"

    @pytest.mark.asyncio
    async def test_soft_delete(self, kb_repo: KnowledgeBaseRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="ToDelete")
        assert await kb_repo.soft_delete(kb["id"], tenant_id=TENANT, owner_user_id=USER)
        assert await kb_repo.get(kb["id"], tenant_id=TENANT, owner_user_id=USER) is None
    @pytest.mark.asyncio
    async def test_resolve_active_by_ids(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from deerflow.persistence.base import Base
        from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        repo = KnowledgeBaseRepository(sf)
        kb1 = await repo.create(tenant_id="t1", owner_user_id="u1", name="KB1")
        kb2 = await repo.create(tenant_id="t1", owner_user_id="u1", name="KB2")
        kb3 = await repo.create(tenant_id="t1", owner_user_id="u2", name="KB3")

        results = await repo.resolve_active_by_ids(
            [kb1["id"], kb2["id"], kb3["id"]],
            tenant_id="t1",
            owner_user_id="u1",
        )
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert kb1["id"] in ids
        assert kb2["id"] in ids
        assert kb3["id"] not in ids

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_resolve_active_by_collections(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from deerflow.persistence.base import Base
        from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        repo = KnowledgeBaseRepository(sf)
        kb1 = await repo.create(tenant_id="t1", owner_user_id="u1", name="KB1")
        kb2 = await repo.create(tenant_id="t1", owner_user_id="u1", name="KB2")
        kb3 = await repo.create(tenant_id="t1", owner_user_id="u2", name="KB3")

        results = await repo.resolve_active_by_collections(
            [kb1["collection_name"], kb2["collection_name"], kb3["collection_name"]],
            tenant_id="t1",
            owner_user_id="u1",
        )
        assert len(results) == 2
        collections = {r["collection_name"] for r in results}
        assert kb1["collection_name"] in collections
        assert kb2["collection_name"] in collections
        assert kb3["collection_name"] not in collections

        await engine.dispose()


class TestDocumentRepository:
    @pytest.mark.asyncio
    async def test_create_and_get(self, kb_repo: KnowledgeBaseRepository, doc_repo: DocumentRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="KB")
        doc = await doc_repo.create(
            knowledge_base_id=kb["id"],
            tenant_id=TENANT,
            owner_user_id=USER,
            title="Doc 1",
            content="Hello world",
            content_hash="abc123",
        )
        assert doc["title"] == "Doc 1"
        assert doc["content_length"] == 11
        assert doc["index_status"] == "pending"

        fetched = await doc_repo.get(doc["id"], tenant_id=TENANT, owner_user_id=USER)
        assert fetched is not None

    @pytest.mark.asyncio
    async def test_list_by_kb(self, kb_repo: KnowledgeBaseRepository, doc_repo: DocumentRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="KB")
        await doc_repo.create(knowledge_base_id=kb["id"], tenant_id=TENANT, owner_user_id=USER, title="D1", content="a", content_hash="h1")
        await doc_repo.create(knowledge_base_id=kb["id"], tenant_id=TENANT, owner_user_id=USER, title="D2", content="b", content_hash="h2")

        docs = await doc_repo.list_by_kb(kb["id"], tenant_id=TENANT, owner_user_id=USER)
        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_soft_delete(self, kb_repo: KnowledgeBaseRepository, doc_repo: DocumentRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="KB")
        doc = await doc_repo.create(knowledge_base_id=kb["id"], tenant_id=TENANT, owner_user_id=USER, title="D", content="x", content_hash="h")
        assert await doc_repo.soft_delete(doc["id"], tenant_id=TENANT, owner_user_id=USER)
        assert await doc_repo.get(doc["id"], tenant_id=TENANT, owner_user_id=USER) is None

    @pytest.mark.asyncio
    async def test_update_index_status(self, kb_repo: KnowledgeBaseRepository, doc_repo: DocumentRepository):
        kb = await kb_repo.create(tenant_id=TENANT, owner_user_id=USER, name="KB")
        doc = await doc_repo.create(knowledge_base_id=kb["id"], tenant_id=TENANT, owner_user_id=USER, title="D", content="x", content_hash="h")
        await doc_repo.update_index_status(doc["id"], index_status="ready", chunk_ids=["c1", "c2"], chunk_count=2)
        updated = await doc_repo.get(doc["id"], tenant_id=TENANT, owner_user_id=USER)
        assert updated["index_status"] == "ready"
        assert updated["chunk_ids"] == ["c1", "c2"]
        assert updated["chunk_count"] == 2


class TestIndexJobRepository:
    @pytest.mark.asyncio
    async def test_create_and_get(self, job_repo: IndexJobRepository):
        job = await job_repo.create(
            document_id="doc-1",
            knowledge_base_id="kb-1",
            tenant_id=TENANT,
            owner_user_id=USER,
            version=1,
        )
        assert job["status"] == "pending"
        assert job["version"] == 1

        fetched = await job_repo.get(job["id"])
        assert fetched is not None
        assert fetched["document_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_update_status(self, job_repo: IndexJobRepository):
        job = await job_repo.create(document_id="doc-1", knowledge_base_id="kb-1", tenant_id=TENANT, owner_user_id=USER, version=1)
        await job_repo.update_status(job["id"], status="completed", new_chunk_ids=["c1"])
        updated = await job_repo.get(job["id"])
        assert updated["status"] == "completed"
        assert updated["new_chunk_ids"] == ["c1"]

    @pytest.mark.asyncio
    async def test_list_by_document(self, job_repo: IndexJobRepository):
        await job_repo.create(document_id="doc-1", knowledge_base_id="kb-1", tenant_id=TENANT, owner_user_id=USER, version=1)
        await job_repo.create(document_id="doc-1", knowledge_base_id="kb-1", tenant_id=TENANT, owner_user_id=USER, version=2)
        await job_repo.create(document_id="doc-2", knowledge_base_id="kb-1", tenant_id=TENANT, owner_user_id=USER, version=1)

        jobs = await job_repo.list_by_document("doc-1")
        assert len(jobs) == 2
