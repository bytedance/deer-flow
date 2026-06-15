"""Router-level integration tests for ``/api/closure``.

These tests drive the real ``ClosureService`` over a per-test SQLite engine
through a stub-authed FastAPI app. The auth boundary is exercised separately
by ``test_auth_middleware``-style tests; here we focus on:

* status-code mapping (201/200, 403, 404, 409, 422)
* idempotency surfaces via the ``X-Closure-Created`` header
* tenant isolation
* permission gating per action (``closure:read|write|verify``)
* status-smuggling rejection on PATCH
* listing pagination + filter parameters
* notifications summary aggregation
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.gateway.authz import AuthContext
from app.gateway.routers import closure_tickets as closure_router
from deerflow.closed_loop.events import ClosureEventPublisher
from deerflow.closed_loop.permissions import (
    CLOSURE_READ,
    CLOSURE_VERIFY,
    CLOSURE_WRITE,
)
from deerflow.closed_loop.repository import ClosureRepository
from deerflow.closed_loop.service import ClosureService

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


class _FakeUser:
    """Minimal user shape consumed by ``_principal()``.

    ``_principal()`` only reads ``id`` and ``tenant_id``. Pinning a stable
    value here keeps tenant-isolation tests deterministic across requests
    (the production-flavored ``_router_auth_helpers`` factory mints a new
    UUID per call which would break our isolation assertions).
    """

    def __init__(self, *, user_id: str, tenant_id: str) -> None:
        self.id = user_id
        self.tenant_id = tenant_id


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Stamp ``request.state.auth`` with a controllable ``AuthContext``.

    We use a callable (rather than a fixed AuthContext) so individual tests
    can mutate the principal between requests — for example, dropping
    ``closure:write`` to verify 403, or switching ``tenant_id`` to verify
    tenant isolation — without rebuilding the app.
    """

    def __init__(self, app: ASGIApp, principal_factory: Callable[[], AuthContext]) -> None:
        super().__init__(app)
        self._factory = principal_factory

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ctx = self._factory()
        request.state.user = ctx.user
        request.state.auth = ctx
        return await call_next(request)


class _Principal:
    """Mutable holder for the active stub principal.

    Tests assign to ``.user`` / ``.permissions`` to control authz between
    requests on the same client. Because TestClient threads requests through
    ASGI, the middleware reads this on every dispatch.
    """

    def __init__(self) -> None:
        self.user = _FakeUser(user_id="alice", tenant_id="tenant-a")
        self.permissions: list[str] = [CLOSURE_READ, CLOSURE_WRITE, CLOSURE_VERIFY]

    def as_context(self) -> AuthContext:
        return AuthContext(user=self.user, permissions=list(self.permissions))


@pytest_asyncio.fixture()
async def app_ctx(tmp_path) -> Iterator[tuple[FastAPI, _Principal]]:
    """Spin up a FastAPI app with the closure router, a real SQLite-backed
    service, and a mutable stub principal.

    Yields ``(app, principal)`` so tests can both make requests and tweak
    the active principal between requests.
    """
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    db_path = tmp_path / f"closure-router-{uuid.uuid4().hex}.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    factory = get_session_factory()
    assert factory is not None

    repository = ClosureRepository(factory)
    publisher = ClosureEventPublisher(None)  # router tests don't assert events
    service = ClosureService(repository=repository, event_publisher=publisher)

    principal = _Principal()
    app = FastAPI()
    app.add_middleware(_StubAuthMiddleware, principal_factory=principal.as_context)
    app.state.closure_service = service
    app.include_router(closure_router.router)

    try:
        yield app, principal
    finally:
        await close_engine()


@pytest.fixture()
def client(app_ctx) -> Iterator[tuple[TestClient, _Principal]]:
    app, principal = app_ctx
    with TestClient(app) as c:
        yield c, principal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_payload(**overrides: Any) -> dict[str, Any]:
    body = {
        "title": "fan over-temp",
        "priority": "urgent",
        "device_id": "dev-1",
        "source_type": "diagnosis",
        "source_run_id": "run-1",
        "metadata": {"findings": ["temp_high"], "confidence": 0.9},
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_returns_201_and_idempotent_200(client) -> None:
    c, _principal = client

    first = c.post("/api/closure/tickets", json=_create_payload())
    assert first.status_code == 201, first.text
    assert first.headers.get("X-Closure-Created") == "true"
    body = first.json()
    assert body["status"] == "pending"
    assert body["priority"] == "urgent"
    assert body["tenant_id"] == "tenant-a"

    # Same idempotency key → existing row returned with 200 + header=false.
    second = c.post("/api/closure/tickets", json=_create_payload())
    assert second.status_code == 200, second.text
    assert second.headers.get("X-Closure-Created") == "false"
    assert second.json()["id"] == body["id"]


def test_create_without_write_permission_returns_403(client) -> None:
    c, principal = client
    principal.permissions = [CLOSURE_READ]

    resp = c.post("/api/closure/tickets", json=_create_payload())
    assert resp.status_code == 403, resp.text


def test_create_with_invalid_metadata_returns_422(client) -> None:
    c, _principal = client
    # confidence > 1.0 violates DiagnosisMetadata schema.
    resp = c.post(
        "/api/closure/tickets",
        json=_create_payload(metadata={"confidence": 2.5}),
    )
    assert resp.status_code == 422, resp.text


def test_get_ticket_cross_tenant_returns_404(client) -> None:
    c, principal = client

    created = c.post("/api/closure/tickets", json=_create_payload())
    ticket_id = created.json()["id"]

    # Same tenant: visible.
    same = c.get(f"/api/closure/tickets/{ticket_id}")
    assert same.status_code == 200

    # Switch principal to a different tenant — must not see the row.
    principal.user = _FakeUser(user_id="bob", tenant_id="tenant-b")
    other = c.get(f"/api/closure/tickets/{ticket_id}")
    assert other.status_code == 404


def test_patch_rejects_status_smuggling(client) -> None:
    c, _principal = client

    created = c.post("/api/closure/tickets", json=_create_payload())
    ticket_id = created.json()["id"]

    # ``status`` is forbidden by UpdateTicketRequest (extra="forbid") so the
    # router-level Pydantic parse rejects it with 422 before the service
    # raw-body guard fires. Either path is acceptable as long as it is 422.
    resp = c.patch(
        f"/api/closure/tickets/{ticket_id}",
        json={"status": "closed"},
    )
    assert resp.status_code == 422, resp.text


def test_patch_updates_columns_and_metadata(client) -> None:
    c, _principal = client

    created = c.post("/api/closure/tickets", json=_create_payload())
    ticket_id = created.json()["id"]

    resp = c.patch(
        f"/api/closure/tickets/{ticket_id}",
        json={
            "description": "diagnosis pending",
            "priority": "important",
            "metadata_patch": {"resolution_plan": "replace fan"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["description"] == "diagnosis pending"
    assert body["priority"] == "important"
    assert body["metadata"]["resolution_plan"] == "replace fan"


def test_transition_invalid_returns_409(client) -> None:
    c, _principal = client
    created = c.post("/api/closure/tickets", json=_create_payload())
    ticket_id = created.json()["id"]

    # ``start`` is illegal from ``pending``.
    resp = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "start"},
    )
    assert resp.status_code == 409, resp.text


def test_transition_unknown_action_returns_422(client) -> None:
    c, _principal = client
    created = c.post("/api/closure/tickets", json=_create_payload())
    ticket_id = created.json()["id"]

    resp = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "bogus_action"},
    )
    assert resp.status_code == 422, resp.text


def test_transition_missing_payload_returns_422(client) -> None:
    c, _principal = client
    created = c.post("/api/closure/tickets", json=_create_payload())
    ticket_id = created.json()["id"]

    resp = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "assign", "payload": {}},  # missing assignee_id
    )
    assert resp.status_code == 422, resp.text


def test_transition_walks_state_machine(client) -> None:
    c, principal = client

    created = c.post(
        "/api/closure/tickets",
        json=_create_payload(priority="normal"),
    )
    ticket_id = created.json()["id"]

    assigned = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "assign", "payload": {"assignee_id": "bob"}},
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "assigned"

    started = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "start"},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"

    submitted = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "submit_verification"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_verification"

    # verify_close requires closure:verify — drop it to confirm 403.
    principal.permissions = [CLOSURE_READ, CLOSURE_WRITE]
    forbidden = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "verify_close"},
    )
    assert forbidden.status_code == 403, forbidden.text

    # Restore verify permission and close it.
    principal.permissions = [CLOSURE_READ, CLOSURE_WRITE, CLOSURE_VERIFY]
    closed = c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "verify_close"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


def test_list_tickets_filters_and_paginates(client) -> None:
    c, _principal = client
    for idx in range(5):
        resp = c.post(
            "/api/closure/tickets",
            json=_create_payload(
                title=f"ticket-{idx}",
                source_run_id=f"run-{idx}",
                device_id=f"dev-{idx}",
                priority="urgent" if idx % 2 == 0 else "normal",
            ),
        )
        assert resp.status_code == 201, resp.text

    page = c.get(
        "/api/closure/tickets",
        params={"page": 1, "page_size": 2, "priority": "urgent"},
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["meta"]["total"] == 3
    assert len(body["items"]) == 2
    assert all(t["priority"] == "urgent" for t in body["items"])


def test_list_events_returns_audit_trail(client) -> None:
    c, _principal = client
    created = c.post("/api/closure/tickets", json=_create_payload(priority="normal"))
    ticket_id = created.json()["id"]

    c.post(
        f"/api/closure/tickets/{ticket_id}/transition",
        json={"action": "assign", "payload": {"assignee_id": "bob"}},
    )

    resp = c.get(f"/api/closure/tickets/{ticket_id}/events")
    assert resp.status_code == 200, resp.text
    events = resp.json()
    actions = [e["action"] for e in events]
    assert actions == ["assign"]
    assert events[0]["from_status"] == "pending"
    assert events[0]["to_status"] == "assigned"


def test_notifications_summary_counts(client) -> None:
    c, _principal = client
    for idx in range(2):
        resp = c.post(
            "/api/closure/tickets",
            json=_create_payload(source_run_id=f"open-{idx}", device_id=f"d-{idx}"),
        )
        assert resp.status_code == 201

    closing = c.post(
        "/api/closure/tickets",
        json=_create_payload(source_run_id="to-close", device_id="d-x"),
    )
    closing_id = closing.json()["id"]
    c.post(
        f"/api/closure/tickets/{closing_id}/transition",
        json={"action": "reject"},
    )

    summary = c.get("/api/closure/notifications/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["open_count"] == 2
    assert body["pending_verification_count"] == 0


def test_list_without_read_permission_returns_403(client) -> None:
    c, principal = client
    principal.permissions = []
    resp = c.get("/api/closure/tickets")
    assert resp.status_code == 403, resp.text


def test_get_unknown_ticket_returns_404(client) -> None:
    c, _principal = client
    resp = c.get("/api/closure/tickets/nope-not-a-real-id")
    assert resp.status_code == 404, resp.text
