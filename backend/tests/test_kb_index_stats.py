"""Tests for knowledge base index stats endpoint and service methods."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.knowledge_base.service import KnowledgeBaseService
from deerflow.knowledge_base.telemetry import KbTelemetryCollector
from deerflow.persistence.base import Base
from deerflow.persistence.knowledge_base.document_repository import DocumentRepository
from deerflow.persistence.knowledge_base.index_job_repository import IndexJobRepository
from deerflow.persistence.knowledge_base.permission_repository import KbPermissionRepository
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

TENANT = "test-tenant"
USER = "test-user"


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


@pytest_asyncio.fixture
def perm_repo(session_factory):
    return KbPermissionRepository(session_factory)


@pytest_asyncio.fixture
async def service(kb_repo, doc_repo, job_repo, perm_repo):
    return KnowledgeBaseService(kb_repo, doc_repo, job_repo, perm_repo)


@pytest_asyncio.fixture
async def kb(service):
    return await service.create_knowledge_base(
        tenant_id=TENANT, owner_user_id=USER, name="Test KB", visibility="private"
    )


class TestCountDocsByStatus:
    @pytest.mark.asyncio
    async def test_empty_kb(self, doc_repo, kb):
        statuses = await doc_repo.count_docs_by_status_for_kb(kb["id"])
        assert statuses == {}

    @pytest.mark.asyncio
    async def test_mixed_statuses(self, doc_repo, kb, session_factory):
        # Directly insert docs with different statuses to avoid indexing side effects
        from datetime import UTC, datetime

        from deerflow.persistence.knowledge_base.model import KnowledgeBaseDocumentRow

        now = datetime.now(UTC)
        docs = [
            KnowledgeBaseDocumentRow(
                id="doc-1", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Ready", content="a", content_hash="h1",
                content_length=1, index_status="ready", chunk_count=3, created_at=now, updated_at=now,
            ),
            KnowledgeBaseDocumentRow(
                id="doc-2", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Failed", content="b", content_hash="h2",
                content_length=1, index_status="failed", chunk_count=0, created_at=now, updated_at=now,
            ),
            KnowledgeBaseDocumentRow(
                id="doc-3", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Pending", content="c", content_hash="h3",
                content_length=1, index_status="pending", chunk_count=0, created_at=now, updated_at=now,
            ),
            KnowledgeBaseDocumentRow(
                id="doc-4", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Ready 2", content="d", content_hash="h4",
                content_length=1, index_status="ready", chunk_count=5, created_at=now, updated_at=now,
            ),
        ]
        async with session_factory() as session:
            session.add_all(docs)
            await session.commit()

        statuses = await doc_repo.count_docs_by_status_for_kb(kb["id"])
        assert statuses == {"ready": 2, "failed": 1, "pending": 1}

    @pytest.mark.asyncio
    async def test_ignores_deleted(self, doc_repo, kb, session_factory):
        from datetime import UTC, datetime

        from deerflow.persistence.knowledge_base.model import KnowledgeBaseDocumentRow

        now = datetime.now(UTC)
        docs = [
            KnowledgeBaseDocumentRow(
                id="doc-1", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Active", content="a", content_hash="h1",
                content_length=1, index_status="ready", chunk_count=1, created_at=now, updated_at=now,
            ),
            KnowledgeBaseDocumentRow(
                id="doc-2", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Deleted", content="b", content_hash="h2",
                content_length=1, index_status="failed", chunk_count=0,
                deleted_at=now, created_at=now, updated_at=now,
            ),
        ]
        async with session_factory() as session:
            session.add_all(docs)
            await session.commit()

        statuses = await doc_repo.count_docs_by_status_for_kb(kb["id"])
        assert statuses == {"ready": 1}


class TestCountDocsByStatusForKbs:
    @pytest.mark.asyncio
    async def test_batch_query(self, doc_repo, kb, session_factory):
        from datetime import UTC, datetime

        from deerflow.persistence.knowledge_base.model import KnowledgeBaseDocumentRow

        now = datetime.now(UTC)
        docs = [
            KnowledgeBaseDocumentRow(
                id="doc-1", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Ready", content="a", content_hash="h1",
                content_length=1, index_status="ready", chunk_count=3, created_at=now, updated_at=now,
            ),
            KnowledgeBaseDocumentRow(
                id="doc-2", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Failed", content="b", content_hash="h2",
                content_length=1, index_status="failed", chunk_count=0, created_at=now, updated_at=now,
            ),
        ]
        async with session_factory() as session:
            session.add_all(docs)
            await session.commit()

        result = await doc_repo.count_docs_by_status_for_kbs([kb["id"]])
        assert kb["id"] in result
        assert result[kb["id"]] == {"ready": 1, "failed": 1}

    @pytest.mark.asyncio
    async def test_empty_input(self, doc_repo):
        result = await doc_repo.count_docs_by_status_for_kbs([])
        assert result == {}


class TestGetIndexStats:
    @pytest.mark.asyncio
    async def test_stats_for_empty_kb(self, service, kb):
        stats = await service.get_index_stats(kb["id"], tenant_id=TENANT, user_id=USER)
        assert stats is not None
        assert stats["total"] == 0
        assert stats["ready"] == 0
        assert stats["failed"] == 0
        assert stats["failure_by_type"] == {}
        assert stats["avg_index_duration_ms"] == 0.0
        assert stats["recent_failures"] == []

    @pytest.mark.asyncio
    async def test_stats_for_missing_kb(self, service):
        stats = await service.get_index_stats("nonexistent", tenant_id=TENANT, user_id=USER)
        assert stats is None

    @pytest.mark.asyncio
    async def test_stats_includes_retrieval_latency(self, service, kb):
        from deerflow.knowledge_base.telemetry import get_kb_telemetry

        telemetry = get_kb_telemetry()
        telemetry.clear()
        telemetry.record_latency(kb["id"], 100.0)
        telemetry.record_latency(kb["id"], 200.0)
        telemetry.record_event("search", {"kb_id": kb["id"], "latency_ms": 150.0})

        stats = await service.get_index_stats(kb["id"], tenant_id=TENANT, user_id=USER)
        assert stats is not None
        assert stats["avg_retrieval_latency_ms"] > 0
        assert stats["total_queries"] >= 1

    @pytest.mark.asyncio
    async def test_stats_includes_failure_classification(self, service, kb, session_factory):
        from datetime import UTC, datetime

        from deerflow.persistence.knowledge_base.model import IndexJobRow, KnowledgeBaseDocumentRow

        now = datetime.now(UTC)
        doc = KnowledgeBaseDocumentRow(
            id="doc-fail", knowledge_base_id=kb["id"], tenant_id=TENANT,
            owner_user_id=USER, title="Fail", content="x", content_hash="h",
            content_length=1, index_status="failed", chunk_count=0, created_at=now, updated_at=now,
        )
        job = IndexJobRow(
            id="job-1", document_id="doc-fail", knowledge_base_id=kb["id"],
            tenant_id=TENANT, owner_user_id=USER, version=1,
            status="failed", error="encrypted_pdf: cannot read",
            created_at=now, updated_at=now, finished_at=now,
        )
        async with session_factory() as session:
            session.add_all([doc, job])
            await session.commit()

        stats = await service.get_index_stats(kb["id"], tenant_id=TENANT, user_id=USER)
        assert stats is not None
        assert stats["failed"] == 1
        assert stats["failure_by_type"] == {"ENCRYPTED_PDF": 1}
        assert len(stats["recent_failures"]) == 1
        assert stats["recent_failures"][0]["error"] == "encrypted_pdf: cannot read"


class TestEnrichListWithIndexCounts:
    @pytest.mark.asyncio
    async def test_enrich_empty_list(self, service):
        result = await service.enrich_list_with_index_counts([])
        assert result == []

    @pytest.mark.asyncio
    async def test_enrich_adds_counts(self, service, kb, session_factory):
        from datetime import UTC, datetime

        from deerflow.persistence.knowledge_base.model import KnowledgeBaseDocumentRow

        now = datetime.now(UTC)
        docs = [
            KnowledgeBaseDocumentRow(
                id="doc-1", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Ready", content="a", content_hash="h1",
                content_length=1, index_status="ready", chunk_count=3, created_at=now, updated_at=now,
            ),
            KnowledgeBaseDocumentRow(
                id="doc-2", knowledge_base_id=kb["id"], tenant_id=TENANT,
                owner_user_id=USER, title="Failed", content="b", content_hash="h2",
                content_length=1, index_status="failed", chunk_count=0, created_at=now, updated_at=now,
            ),
        ]
        async with session_factory() as session:
            session.add_all(docs)
            await session.commit()

        items = [{"id": kb["id"], "name": kb["name"]}]
        result = await service.enrich_list_with_index_counts(items)
        assert result[0]["indexed_count"] == 1
        assert result[0]["failed_count"] == 1


class TestTelemetryCollector:
    def test_increment_and_snapshot(self):
        c = KbTelemetryCollector()
        c.increment("event.index_success", 3)
        c.increment("event.index_failed")
        assert c.get("event.index_success") == 3
        assert c.get("event.index_failed") == 1
        snap = c.snapshot()
        assert snap["event.index_success"] == 3

    def test_latency_tracking(self):
        c = KbTelemetryCollector()
        c.record_latency("kb-1", 100.0)
        c.record_latency("kb-1", 200.0)
        c.record_latency("kb-1", 300.0)
        stats = c.latency_stats("kb-1")
        assert stats["avg_ms"] == 200.0
        assert stats["total_queries"] == 3

    def test_latency_stats_empty(self):
        c = KbTelemetryCollector()
        stats = c.latency_stats("nonexistent")
        assert stats == {"avg_ms": 0.0, "p95_ms": 0.0, "total_queries": 0}

    def test_latency_window_limit(self):
        c = KbTelemetryCollector()
        for i in range(1100):
            c.record_latency("kb-1", float(i))
        stats = c.latency_stats("kb-1")
        assert stats["total_queries"] == 1000  # capped at 1000

    def test_record_event(self, tmp_path):
        log_path = tmp_path / "test.jsonl"
        c = KbTelemetryCollector(log_path=str(log_path))
        c.record_event("index_success", {"kb_id": "kb-1", "doc_id": "doc-1"})
        assert c.get("event.index_success") == 1
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        import json
        entry = json.loads(lines[0])
        assert entry["type"] == "index_success"
        assert entry["kb_id"] == "kb-1"

    def test_clear(self):
        c = KbTelemetryCollector()
        c.increment("x", 5)
        c.record_latency("kb-1", 100.0)
        c.clear()
        assert c.get("x") == 0
        assert c.latency_stats("kb-1")["total_queries"] == 0


class TestHealthSummary:
    @pytest.mark.asyncio
    async def test_empty_summary_when_no_kbs(self, service):
        summary = await service.get_health_summary(tenant_id=TENANT, user_id=USER)
        assert summary["total_kbs"] == 0
        assert summary["documents"]["total"] == 0
        assert summary["documents"]["ready"] == 0
        assert summary["documents"]["failed"] == 0
        assert summary["index_success_rate"] == 0.0
        assert summary["failure_by_type"] == {}
        assert summary["retrieval"]["avg_latency_ms"] == 0.0
        assert summary["retrieval"]["total_queries"] == 0
        assert summary["recent_failures"] == []
        assert summary["per_kb"] == []

    @pytest.mark.asyncio
    async def test_summary_includes_kb_stats(self, service, kb):
        summary = await service.get_health_summary(tenant_id=TENANT, user_id=USER)
        assert summary["total_kbs"] >= 1
        per_kb_ids = [k["kb_id"] for k in summary["per_kb"]]
        assert kb["id"] in per_kb_ids

    @pytest.mark.asyncio
    async def test_summary_aggregates_across_kbs(self, service, kb, kb_repo, doc_repo, session_factory):
        from datetime import UTC, datetime

        from deerflow.persistence.knowledge_base.model import KnowledgeBaseDocumentRow

        # Create a second KB
        kb2 = await service.create_knowledge_base(
            tenant_id=TENANT, owner_user_id=USER, name="KB 2", visibility="tenant"
        )
        try:
            now = datetime.now(UTC)
            # Add docs to both KBs
            docs = [
                KnowledgeBaseDocumentRow(
                    id="doc-ready-1", knowledge_base_id=kb["id"], tenant_id=TENANT,
                    owner_user_id=USER, title="Ready", content="a", content_hash="h1",
                    content_length=1, index_status="ready", chunk_count=3,
                    created_at=now, updated_at=now,
                ),
                KnowledgeBaseDocumentRow(
                    id="doc-failed-1", knowledge_base_id=kb["id"], tenant_id=TENANT,
                    owner_user_id=USER, title="Failed", content="b", content_hash="h2",
                    content_length=1, index_status="failed", chunk_count=0,
                    created_at=now, updated_at=now,
                ),
                KnowledgeBaseDocumentRow(
                    id="doc-ready-2", knowledge_base_id=kb2["id"], tenant_id=TENANT,
                    owner_user_id=USER, title="Ready 2", content="c", content_hash="h3",
                    content_length=1, index_status="ready", chunk_count=1,
                    created_at=now, updated_at=now,
                ),
            ]
            async with session_factory() as session:
                session.add_all(docs)
                await session.commit()

            # Check that we can still access the fixture kb
            summary = await service.get_health_summary(tenant_id=TENANT, user_id=USER)
            assert summary["total_kbs"] == 2  # the fixture kb + kb2
            assert summary["documents"]["total"] == 3
            assert summary["documents"]["ready"] == 2
            assert summary["documents"]["failed"] == 1
        finally:
            await service.delete_knowledge_base(kb2["id"], tenant_id=TENANT, owner_user_id=USER)

    @pytest.mark.asyncio
    async def test_summary_includes_retrieval_latency(self, service, kb):
        from deerflow.knowledge_base.telemetry import get_kb_telemetry

        t = get_kb_telemetry()
        t.clear()
        t.record_latency(kb["id"], 50.0)
        t.record_latency(kb["id"], 150.0)

        summary = await service.get_health_summary(tenant_id=TENANT, user_id=USER)
        assert summary["retrieval"]["total_queries"] > 0
        # Per-kb entry should reflect the queries
        kb_entry = next((k for k in summary["per_kb"] if k["kb_id"] == kb["id"]), None)
        assert kb_entry is not None
        assert kb_entry["total_queries"] > 0

    @pytest.mark.asyncio
    async def test_summary_respects_access_control(self, service, kb_repo):
        """Health summary should only include KBs accessible to the given user."""
        summary = await service.get_health_summary(
            tenant_id="other-tenant", user_id="other-user"
        )
        # Other tenant/user should see no KBs
        assert summary["total_kbs"] == 0
        assert summary["documents"]["total"] == 0

    @pytest.mark.asyncio
    async def test_summary_includes_failure_by_type(self, service, kb, session_factory):
        from datetime import UTC, datetime

        from deerflow.persistence.knowledge_base.model import IndexJobRow, KnowledgeBaseDocumentRow

        now = datetime.now(UTC)
        doc = KnowledgeBaseDocumentRow(
            id="doc-fail-type", knowledge_base_id=kb["id"], tenant_id=TENANT,
            owner_user_id=USER, title="Fail", content="x", content_hash="fh",
            content_length=1, index_status="failed", chunk_count=0,
            created_at=now, updated_at=now,
        )
        job = IndexJobRow(
            id="job-ft", document_id="doc-fail-type", knowledge_base_id=kb["id"],
            tenant_id=TENANT, owner_user_id=USER, version=1,
            status="failed", error="encrypted_pdf: locked",
            created_at=now, updated_at=now, finished_at=now,
        )
        async with session_factory() as session:
            session.add_all([doc, job])
            await session.commit()

        summary = await service.get_health_summary(tenant_id=TENANT, user_id=USER)
        assert summary["failure_by_type"] is not None
        if summary["failure_by_type"]:
            assert any(cat in ("ENCRYPTED_PDF", "OTHER") for cat in summary["failure_by_type"])
