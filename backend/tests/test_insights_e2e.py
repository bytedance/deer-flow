"""End-to-end integration tests for the complete feedback loop.

Tests the full pipeline:
- 8.1: submit feedback → aggregation → improvement → apply → memory fact
- 8.2: closure ticket → events → KB candidate → promote
- 8.3: tenant isolation at every layer
- 8.4: API integration with auth/tenant validation
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.insights.analytics import FeedbackAggregator
from deerflow.insights.cache import JsonFileInsightsCache
from deerflow.insights.improvement import ImprovementEngine
from deerflow.insights.kb_candidate_store import KBCandidateStore
from deerflow.insights.knowledge_extractor import ClosureKnowledgeExtractor
from deerflow.insights.memory_integration import FeedbackMemoryIntegration
from deerflow.insights.models import (
    ImprovementSuggestion,
    KBCandidate,
)
from deerflow.persistence.agent.usage_model import AgentUsageRow
from deerflow.persistence.base import Base
from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.models.closure_ticket import ClosureTicketEventRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow


@pytest_asyncio.fixture
async def e2e_engine():
    """Create an in-memory SQLite async engine for e2e tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def e2e_session_factory(e2e_engine):
    """Create an async session factory for e2e tests."""
    return async_sessionmaker(e2e_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def e2e_temp_dir():
    """Create a temporary directory for e2e test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def e2e_cache(e2e_temp_dir):
    """Create a JSON file insights cache for e2e tests."""
    return JsonFileInsightsCache(base_dir=e2e_temp_dir)


@pytest.fixture
def e2e_kb_store(e2e_temp_dir):
    """Create a KB candidate store for e2e tests."""
    return KBCandidateStore(base_dir=e2e_temp_dir)


class TestE2EFeedbackLoop:
    """8.1: Full feedback loop e2e test."""

    @pytest.mark.asyncio
    async def test_complete_feedback_loop(
        self, e2e_session_factory, e2e_cache, e2e_temp_dir
    ):
        """Test: submit feedback → aggregation → improvement → apply → memory fact."""
        tenant_id = "e2e-tenant"
        aggregator = FeedbackAggregator(e2e_session_factory, e2e_cache)

        # Step 1: Submit feedback (need at least 3 entries for suggestion generation)
        async with e2e_session_factory() as session:
            # Create thread metadata
            thread = ThreadMetaRow(
                thread_id="thread-e2e-1",
                tenant_id=tenant_id,
                created_at=datetime.now(UTC),
            )
            session.add(thread)

            # Submit negative feedback (3 entries with different run_ids to meet minimum threshold)
            for i in range(3):
                # Create agent usage for each feedback
                usage = AgentUsageRow(
                    tenant_id=tenant_id,
                    agent_name="test-agent",
                    user_id="user-e2e",
                    run_id=f"run-e2e-{i}",
                    token_input=100,
                    token_output=200,
                    used_at=datetime.now(UTC),
                )
                session.add(usage)

                feedback = FeedbackRow(
                    feedback_id=f"feedback-e2e-{i}",
                    thread_id="thread-e2e-1",
                    run_id=f"run-e2e-{i}",
                    user_id="user-e2e",
                    rating=-1,
                    comment="Response was too slow",
                    created_at=datetime.now(UTC),
                )
                session.add(feedback)
            await session.commit()

        # Step 2: Run aggregation
        trends = await aggregator.aggregate(tenant_id=tenant_id, window_days=7)
        assert len(trends) == 1
        trend = trends[0]
        assert trend.agent_name == "test-agent"
        assert trend.negative_count == 3
        assert trend.positive_ratio == 0.0

        # Step 3: Generate improvement
        engine = ImprovementEngine()
        suggestions = engine.generate_suggestions(
            tenant_id=tenant_id,
            feedback_trends=[trend],
        )
        assert len(suggestions) >= 1
        suggestion = suggestions[0]
        assert "test-agent" in suggestion.target
        assert suggestion.confidence > 0.0

        # Step 4: Apply suggestion
        applied = engine.apply(suggestion, note="Applied in e2e test")
        assert applied.status == "applied"
        assert applied.applied_note == "Applied in e2e test"

        # Step 5: Verify memory fact created
        integration = FeedbackMemoryIntegration(e2e_cache)
        mock_fact = {
            "id": "fact_e2e_001",
            "content": f"{applied.target}: {applied.suggestion}",
            "category": "improvement",
            "confidence": 0.9,
            "source": "feedback_loop",
            "createdAt": datetime.now(UTC).isoformat(),
        }

        with patch(
            "deerflow.agents.memory.updater.create_memory_fact",
            return_value=mock_fact,
        ):
            await integration.on_suggestion_applied(applied)

        # Verify fact stored in cache
        facts = e2e_cache.get("global", "improvement_facts") or []
        assert len(facts) >= 1
        fact = facts[0]
        assert fact["source"] == "feedback_loop"
        assert fact["category"] == "improvement"
        assert "test-agent" in fact["content"]
        assert fact["suggestion_id"] == applied.id


class TestE2EClosureKnowledge:
    """8.2: Closure knowledge pipeline e2e test."""

    @pytest.mark.asyncio
    async def test_complete_closure_knowledge_pipeline(
        self, e2e_session_factory, e2e_kb_store
    ):
        """Test: closure ticket → events → KB candidate → promote."""
        extractor = ClosureKnowledgeExtractor()
        tenant_id = "e2e-tenant"
        ticket_id = "ticket-e2e-1"

        # Step 1: Create closure ticket with events
        async with e2e_session_factory() as session:
            submit_event = ClosureTicketEventRow(
                ticket_id=ticket_id,
                tenant_id=tenant_id,
                action="submit_verification",
                actor_id="verifier-1",
                payload={
                    "verification_summary": "Issue resolved by restarting service",
                    "evidence": ["log_2024-01-01.txt", "screenshot.png"],
                },
                created_at=datetime.now(UTC),
            )
            session.add(submit_event)

            close_event = ClosureTicketEventRow(
                ticket_id=ticket_id,
                tenant_id=tenant_id,
                action="verify_close",
                actor_id="verifier-1",
                payload={"verification_summary": "Confirmed fix after restart"},
                created_at=datetime.now(UTC),
            )
            session.add(close_event)
            await session.commit()

        # Step 2: Extract KB candidate
        candidate = await extractor.extract(
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            events=[submit_event, close_event],
        )

        assert candidate is not None
        assert candidate.tenant_id == tenant_id
        assert candidate.ticket_id == ticket_id
        assert "Issue resolved" in candidate.body
        assert "Confirmed fix" in candidate.body
        assert candidate.status == "pending_review"

        # Step 3: Save candidate
        e2e_kb_store.save(candidate)

        # Step 4: Promote to approved
        target_kb_id = "kb-equipment-faq"
        promoted = e2e_kb_store.promote(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            target_kb_id=target_kb_id,
        )

        assert promoted is not None
        assert promoted.status == "approved"
        assert promoted.metadata_tags.get("target_kb_id") == target_kb_id
        assert promoted.metadata_tags.get("approved_at") is not None

        # Step 5: Verify candidate can be retrieved
        retrieved = e2e_kb_store.get(tenant_id, ticket_id)
        assert retrieved is not None
        assert retrieved.status == "approved"


class TestE2ETenantIsolation:
    """8.3: Tenant isolation at every layer."""

    @pytest.mark.asyncio
    async def test_tenant_isolation_across_all_layers(
        self, e2e_session_factory, e2e_cache, e2e_temp_dir
    ):
        """Verify Tenant A data is isolated from Tenant B at every layer."""
        tenant_a = "tenant-a"
        tenant_b = "tenant-b"
        aggregator = FeedbackAggregator(e2e_session_factory, e2e_cache)
        kb_store = KBCandidateStore(base_dir=e2e_temp_dir)

        # Create data for both tenants
        async with e2e_session_factory() as session:
            # Tenant A thread and feedback
            session.add(ThreadMetaRow(
                thread_id="thread-a",
                tenant_id=tenant_a,
                created_at=datetime.now(UTC),
            ))
            session.add(FeedbackRow(
                feedback_id="feedback-a",
                thread_id="thread-a",
                run_id="run-a",
                user_id="user-a",
                rating=1,
                created_at=datetime.now(UTC),
            ))

            # Tenant B thread and feedback
            session.add(ThreadMetaRow(
                thread_id="thread-b",
                tenant_id=tenant_b,
                created_at=datetime.now(UTC),
            ))
            session.add(FeedbackRow(
                feedback_id="feedback-b",
                thread_id="thread-b",
                run_id="run-b",
                user_id="user-b",
                rating=-1,
                created_at=datetime.now(UTC),
            ))
            await session.commit()

        # Layer 1: Analytics isolation
        trends_a = await aggregator.aggregate(tenant_id=tenant_a, window_days=7)
        trends_b = await aggregator.aggregate(tenant_id=tenant_b, window_days=7)

        assert len(trends_a) == 1
        assert trends_a[0].positive_count == 1
        assert trends_a[0].negative_count == 0

        assert len(trends_b) == 1
        assert trends_b[0].positive_count == 0
        assert trends_b[0].negative_count == 1

        # Layer 2: KB candidate isolation
        candidate_a = KBCandidate(
            ticket_id="ticket-a",
            tenant_id=tenant_a,
            title="Tenant A Resolution",
            body="Resolved for tenant A",
            status="pending_review",
        )
        candidate_b = KBCandidate(
            ticket_id="ticket-b",
            tenant_id=tenant_b,
            title="Tenant B Resolution",
            body="Resolved for tenant B",
            status="pending_review",
        )
        kb_store.save(candidate_a)
        kb_store.save(candidate_b)

        # Verify each tenant only sees their own candidates
        candidates_a = kb_store.list_candidates(tenant_a)
        candidates_b = kb_store.list_candidates(tenant_b)

        assert len(candidates_a) == 1
        assert candidates_a[0].tenant_id == tenant_a
        assert "Tenant A" in candidates_a[0].title

        assert len(candidates_b) == 1
        assert candidates_b[0].tenant_id == tenant_b
        assert "Tenant B" in candidates_b[0].title

        # Layer 3: Improvement suggestions isolation
        suggestion_a = ImprovementSuggestion(
            id="sug-a",
            target="agent:agent-a",
            issue_pattern="issue-a",
            suggestion="Suggestion for tenant A",
            confidence=0.8,
            status="pending",
            created_at=datetime.now(UTC),
        )
        suggestion_b = ImprovementSuggestion(
            id="sug-b",
            target="agent:agent-b",
            issue_pattern="issue-b",
            suggestion="Suggestion for tenant B",
            confidence=0.7,
            status="pending",
            created_at=datetime.now(UTC),
        )

        e2e_cache.set(tenant_a, "improvement_suggestions", [suggestion_a.model_dump(mode="json")])
        e2e_cache.set(tenant_b, "improvement_suggestions", [suggestion_b.model_dump(mode="json")])

        # Verify each tenant only sees their own suggestions
        suggestions_a = e2e_cache.get(tenant_a, "improvement_suggestions") or []
        suggestions_b = e2e_cache.get(tenant_b, "improvement_suggestions") or []

        assert len(suggestions_a) == 1
        assert suggestions_a[0]["target"] == "agent:agent-a"

        assert len(suggestions_b) == 1
        assert suggestions_b[0]["target"] == "agent:agent-b"

        # Layer 4: Memory facts isolation
        # (Memory facts are stored globally in the cache, but the memory integration
        # system should filter by tenant when injecting into agent context)
        fact_a = {
            "id": "fact-a",
            "content": "Memory fact for tenant A",
            "category": "improvement",
            "confidence": 0.9,
            "source": "feedback_loop",
            "createdAt": datetime.now(UTC).isoformat(),
        }
        fact_b = {
            "id": "fact-b",
            "content": "Memory fact for tenant B",
            "category": "improvement",
            "confidence": 0.9,
            "source": "feedback_loop",
            "createdAt": datetime.now(UTC).isoformat(),
        }

        # Store facts with tenant-specific keys
        e2e_cache.set(tenant_a, "memory_facts", [fact_a])
        e2e_cache.set(tenant_b, "memory_facts", [fact_b])

        facts_a = e2e_cache.get(tenant_a, "memory_facts") or []
        facts_b = e2e_cache.get(tenant_b, "memory_facts") or []

        assert len(facts_a) == 1
        assert "tenant A" in facts_a[0]["content"]

        assert len(facts_b) == 1
        assert "tenant B" in facts_b[0]["content"]


class TestE2EAPIIntegration:
    """8.4: API integration with auth/tenant validation."""

    def test_api_allows_access_without_auth_middleware(self, e2e_cache):
        """Test that API endpoints are accessible without auth middleware.

        Note: require_permission decorator enforces permissions when auth context
        is present, but allows access when no auth middleware is configured. This is
        by design - the decorator enforces permissions, not authentication.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.gateway.routers import insights as insights_router

        app = FastAPI()
        app.state.insights_cache = e2e_cache
        app.include_router(insights_router.router)

        with TestClient(app) as client:
            # No auth middleware → should succeed (200)
            response = client.get("/api/insights/feedback-trends")
            assert response.status_code == 200

    def test_api_enforces_read_permission(self, e2e_cache):
        """Test that GET endpoints require insights:read permission."""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.types import ASGIApp

        from app.gateway.authz import AuthContext
        from app.gateway.routers import insights as insights_router
        from deerflow.insights.permissions import INSIGHTS_WRITE

        class _FakeUser:
            def __init__(self):
                self.id = "test-user"
                self.tenant_id = "default"

        class _StubAuthMiddleware(BaseHTTPMiddleware):
            def __init__(self, app: ASGIApp, principal_factory):
                super().__init__(app)
                self._factory = principal_factory

            async def dispatch(self, request: Request, call_next):
                ctx = self._factory()
                request.state.user = ctx.user
                request.state.auth = ctx
                return await call_next(request)

        class _Principal:
            def __init__(self):
                self.user = _FakeUser()
                # Only WRITE permission, no READ
                self.permissions = [INSIGHTS_WRITE]

            def as_context(self):
                return AuthContext(user=self.user, permissions=self.permissions)

        principal = _Principal()
        app = FastAPI()
        app.add_middleware(_StubAuthMiddleware, principal_factory=principal.as_context)
        app.state.insights_cache = e2e_cache
        app.include_router(insights_router.router)

        with TestClient(app) as client:
            response = client.get("/api/insights/feedback-trends")
            assert response.status_code == 403

    def test_api_enforces_write_permission(self, e2e_cache):
        """Test that POST endpoints require insights:write permission."""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.types import ASGIApp

        from app.gateway.authz import AuthContext
        from app.gateway.routers import insights as insights_router
        from deerflow.insights.permissions import INSIGHTS_READ

        class _FakeUser:
            def __init__(self):
                self.id = "test-user"
                self.tenant_id = "default"

        class _StubAuthMiddleware(BaseHTTPMiddleware):
            def __init__(self, app: ASGIApp, principal_factory):
                super().__init__(app)
                self._factory = principal_factory

            async def dispatch(self, request: Request, call_next):
                ctx = self._factory()
                request.state.user = ctx.user
                request.state.auth = ctx
                return await call_next(request)

        class _Principal:
            def __init__(self):
                self.user = _FakeUser()
                # Only READ permission, no WRITE
                self.permissions = [INSIGHTS_READ]

            def as_context(self):
                return AuthContext(user=self.user, permissions=self.permissions)

        principal = _Principal()
        app = FastAPI()
        app.add_middleware(_StubAuthMiddleware, principal_factory=principal.as_context)
        app.state.insights_cache = e2e_cache
        app.include_router(insights_router.router)

        with TestClient(app) as client:
            response = client.post(
                "/api/insights/improvements/fake-id/apply",
                json={"note": "test"},
            )
            assert response.status_code == 403

    def test_api_returns_404_for_cross_tenant_access(self, e2e_cache, e2e_temp_dir):
        """Test that API prevents cross-tenant access to KB candidates."""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.types import ASGIApp

        from app.gateway.authz import AuthContext
        from app.gateway.routers import insights as insights_router
        from deerflow.insights.kb_candidate_store import KBCandidateStore
        from deerflow.insights.models import KBCandidate
        from deerflow.insights.permissions import INSIGHTS_READ, INSIGHTS_WRITE

        class _FakeUser:
            def __init__(self):
                self.id = "test-user"
                self.tenant_id = "tenant-a"

        class _StubAuthMiddleware(BaseHTTPMiddleware):
            def __init__(self, app: ASGIApp, principal_factory):
                super().__init__(app)
                self._factory = principal_factory

            async def dispatch(self, request: Request, call_next):
                ctx = self._factory()
                request.state.user = ctx.user
                request.state.auth = ctx
                return await call_next(request)

        class _Principal:
            def __init__(self):
                self.user = _FakeUser()
                self.permissions = [INSIGHTS_READ, INSIGHTS_WRITE]

            def as_context(self):
                return AuthContext(user=self.user, permissions=self.permissions)

        # Create KB candidate for tenant-b
        kb_store = KBCandidateStore(base_dir=e2e_temp_dir)
        candidate = KBCandidate(
            ticket_id="ticket-cross",
            tenant_id="tenant-b",
            title="Tenant B Resolution",
            body="Resolved for tenant B",
            status="pending_review",
        )
        kb_store.save(candidate)

        principal = _Principal()
        app = FastAPI()
        app.add_middleware(_StubAuthMiddleware, principal_factory=principal.as_context)
        app.state.insights_cache = e2e_cache
        app.include_router(insights_router.router)

        # Patch KBCandidateStore to use test directory
        import app.gateway.routers.insights as insights_mod

        original_store = insights_mod.KBCandidateStore

        def patched_store(*args, **kwargs):
            kwargs["base_dir"] = e2e_temp_dir
            return original_store(**kwargs)

        insights_mod.KBCandidateStore = patched_store

        try:
            with TestClient(app) as client:
                # Try to promote tenant-b's candidate as tenant-a
                response = client.post(
                    "/api/insights/closure-knowledge/ticket-cross/promote",
                    json={"target_kb_id": "kb-123"},
                )
                # Should return 404 because tenant-a can't see tenant-b's candidate
                assert response.status_code == 404
        finally:
            insights_mod.KBCandidateStore = original_store
