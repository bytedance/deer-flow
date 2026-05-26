"""Integration tests for the insights dashboard API endpoints."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.gateway.authz import AuthContext
from app.gateway.routers import insights as insights_router
from deerflow.insights.cache import JsonFileInsightsCache
from deerflow.insights.models import (
    ImprovementEvidence,
    ImprovementSuggestion,
    KBCandidate,
)
from deerflow.insights.permissions import INSIGHTS_READ, INSIGHTS_WRITE


class _FakeUser:
    def __init__(self, *, user_id: str = "test-user", tenant_id: str = "default") -> None:
        self.id = user_id
        self.tenant_id = tenant_id


class _StubAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, principal_factory: Callable[[], AuthContext]) -> None:
        super().__init__(app)
        self._factory = principal_factory

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ctx = self._factory()
        request.state.user = ctx.user
        request.state.auth = ctx
        return await call_next(request)


class _Principal:
    def __init__(self) -> None:
        self.user = _FakeUser()
        self.permissions: list[str] = [INSIGHTS_READ, INSIGHTS_WRITE]

    def as_context(self) -> AuthContext:
        return AuthContext(user=self.user, permissions=list(self.permissions))


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def client_and_principal(temp_dir) -> Iterator[tuple[TestClient, _Principal]]:
    cache = JsonFileInsightsCache(base_dir=temp_dir)
    principal = _Principal()

    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, principal_factory=principal.as_context)
    app.state.insights_cache = cache
    app.include_router(insights_router.router)

    with TestClient(app) as c:
        yield c, principal


class TestFeedbackTrends:
    def test_requires_read_permission(self, client_and_principal):
        client, principal = client_and_principal
        principal.permissions = []
        response = client.get("/api/insights/feedback-trends")
        assert response.status_code == 403

    def test_returns_empty_when_no_data(self, client_and_principal):
        client, _ = client_and_principal
        response = client.get("/api/insights/feedback-trends")
        assert response.status_code == 200
        data = response.json()
        assert data["trends"] == []
        assert data["metadata"]["skill_correlation_available"] is False

    def test_returns_cached_trends(self, client_and_principal, temp_dir):
        client, _ = client_and_principal
        cache = JsonFileInsightsCache(base_dir=temp_dir)
        trend_data = [{
            "agent_name": "test-agent",
            "positive_count": 10,
            "negative_count": 2,
            "positive_ratio": 0.83,
            "trend_direction": "improving",
            "window_days": 30,
            "top_complaints": [["slow", 3]],
            "computed_at": datetime.now(UTC).isoformat(),
        }]
        cache.set("default", "feedback_trends_30d", trend_data)

        response = client.get("/api/insights/feedback-trends")
        assert response.status_code == 200
        data = response.json()
        assert len(data["trends"]) == 1
        assert data["trends"][0]["agent_name"] == "test-agent"


class TestImprovements:
    def test_requires_read_permission(self, client_and_principal):
        client, principal = client_and_principal
        principal.permissions = [INSIGHTS_WRITE]
        response = client.get("/api/insights/improvements")
        assert response.status_code == 403

    def test_returns_empty_when_no_suggestions(self, client_and_principal):
        client, _ = client_and_principal
        response = client.get("/api/insights/improvements")
        assert response.status_code == 200
        assert response.json()["suggestions"] == []

    def test_apply_requires_write_permission(self, client_and_principal):
        client, principal = client_and_principal
        principal.permissions = [INSIGHTS_READ]
        response = client.post("/api/insights/improvements/fake-id/apply")
        assert response.status_code == 403

    def test_apply_not_found(self, client_and_principal):
        client, _ = client_and_principal
        response = client.post(
            "/api/insights/improvements/nonexistent/apply",
            json={"note": "test"},
        )
        assert response.status_code == 404

    def test_apply_success(self, client_and_principal, temp_dir):
        client, _ = client_and_principal
        cache = JsonFileInsightsCache(base_dir=temp_dir)

        suggestion = ImprovementSuggestion(
            id="sug-1",
            target="agent:test-agent",
            issue_pattern="declining_feedback",
            suggestion="Review agent configuration",
            confidence=0.7,
            evidence=ImprovementEvidence(
                feedback_ids=["f1"],
                metrics={"negative_count": 5},
            ),
            status="pending",
            created_at=datetime.now(UTC),
        )
        cache.set(
            "default",
            "improvement_suggestions",
            [suggestion.model_dump(mode="json")],
        )

        response = client.post(
            "/api/insights/improvements/sug-1/apply",
            json={"note": "Applied in sprint 5"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["suggestion"]["status"] == "applied"
        assert data["suggestion"]["applied_note"] == "Applied in sprint 5"

    def test_dismiss_requires_reason(self, client_and_principal):
        client, _ = client_and_principal
        response = client.post(
            "/api/insights/improvements/fake-id/dismiss",
            json={},
        )
        assert response.status_code == 422

    def test_dismiss_success(self, client_and_principal, temp_dir):
        client, _ = client_and_principal
        cache = JsonFileInsightsCache(base_dir=temp_dir)

        suggestion = ImprovementSuggestion(
            id="sug-2",
            target="agent:test-agent",
            issue_pattern="complaint:slow",
            suggestion="Optimize response times",
            confidence=0.5,
            status="pending",
            created_at=datetime.now(UTC),
        )
        cache.set(
            "default",
            "improvement_suggestions",
            [suggestion.model_dump(mode="json")],
        )

        response = client.post(
            "/api/insights/improvements/sug-2/dismiss",
            json={"reason": "Not relevant anymore"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["suggestion"]["status"] == "dismissed"
        assert data["suggestion"]["dismiss_reason"] == "Not relevant anymore"


class TestClosureKnowledge:
    def test_requires_read_permission(self, client_and_principal):
        client, principal = client_and_principal
        principal.permissions = [INSIGHTS_WRITE]
        response = client.get("/api/insights/closure-knowledge")
        assert response.status_code == 403

    def test_returns_empty_when_no_candidates(self, client_and_principal):
        client, _ = client_and_principal
        response = client.get("/api/insights/closure-knowledge")
        assert response.status_code == 200
        assert response.json()["candidates"] == []

    def test_promote_not_found(self, client_and_principal):
        client, _ = client_and_principal
        response = client.post(
            "/api/insights/closure-knowledge/nonexistent/promote",
            json={"target_kb_id": "kb-1"},
        )
        assert response.status_code == 404

    def test_promote_success(self, client_and_principal, temp_dir):
        client, _ = client_and_principal

        from deerflow.insights.kb_candidate_store import KBCandidateStore

        store = KBCandidateStore(base_dir=temp_dir)
        candidate = KBCandidate(
            ticket_id="ticket-promote",
            tenant_id="default",
            title="Test Resolution",
            body="Resolved by restarting service",
            status="pending_review",
        )
        store.save(candidate)

        # Patch the store used by the router
        import app.gateway.routers.insights as insights_mod

        original_store = insights_mod.KBCandidateStore

        def patched_store(*args, **kwargs):
            kwargs["base_dir"] = temp_dir
            return original_store(**kwargs)

        insights_mod.KBCandidateStore = patched_store
        try:
            response = client.post(
                "/api/insights/closure-knowledge/ticket-promote/promote",
                json={"target_kb_id": "kb-123"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["candidate"]["status"] == "approved"
        finally:
            insights_mod.KBCandidateStore = original_store

    def test_dismiss_success(self, client_and_principal, temp_dir):
        client, _ = client_and_principal

        from deerflow.insights.kb_candidate_store import KBCandidateStore

        store = KBCandidateStore(base_dir=temp_dir)
        candidate = KBCandidate(
            ticket_id="ticket-dismiss",
            tenant_id="default",
            title="Test Resolution",
            body="Resolved by updating config",
            status="pending_review",
        )
        store.save(candidate)

        import app.gateway.routers.insights as insights_mod

        original_store = insights_mod.KBCandidateStore

        def patched_store(*args, **kwargs):
            kwargs["base_dir"] = temp_dir
            return original_store(**kwargs)

        insights_mod.KBCandidateStore = patched_store
        try:
            response = client.post(
                "/api/insights/closure-knowledge/ticket-dismiss/dismiss",
                json={"reason": "Duplicate"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["candidate"]["status"] == "dismissed"
        finally:
            insights_mod.KBCandidateStore = original_store


class TestInsightsNotInitialized:
    def test_returns_503_when_cache_missing(self, temp_dir):
        principal = _Principal()
        app = FastAPI()
        app.add_middleware(_StubAuthMiddleware, principal_factory=principal.as_context)
        # Don't set app.state.insights_cache
        app.include_router(insights_router.router)

        with TestClient(app) as c:
            response = c.get("/api/insights/feedback-trends")
            assert response.status_code == 503
            assert "not initialized" in response.json()["detail"]
