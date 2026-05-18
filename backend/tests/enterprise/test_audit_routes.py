"""Integration test for the audit read API (plan M2-7).

Boots a tiny FastAPI app with the audit router mounted, swaps in an
in-memory ``AuditStorage`` via ``app.dependency_overrides``, and walks
the five routes end-to-end. We bypass the auth/permission decorators by
monkey-patching ``_authenticate`` to return a fully-permissioned context
because the routes themselves are what we want to verify here; the
``@require_auth`` / ``@require_permission`` plumbing has its own coverage
in ``test_authz_permission_provider``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.enterprise.deps import get_audit_config, get_audit_signer, get_audit_storage
from app.enterprise.routers import audit as audit_module
from app.gateway import authz
from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import AuditQueryFilter, AuditStorage
from deerflow.enterprise.config import AuditConfig


class _InMemoryStorage(AuditStorage):
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def query(self, filters: AuditQueryFilter) -> list[AuditEvent]:
        rows = list(reversed(self.events))  # newest first
        if filters.user_id is not None:
            rows = [r for r in rows if r.user_id == filters.user_id]
        if filters.event_type is not None:
            rows = [r for r in rows if r.event_type == filters.event_type]
        return rows[filters.offset : filters.offset + filters.limit]

    async def count(self, filters: AuditQueryFilter) -> int:
        rows = list(self.events)
        if filters.user_id is not None:
            rows = [r for r in rows if r.user_id == filters.user_id]
        if filters.event_type is not None:
            rows = [r for r in rows if r.event_type == filters.event_type]
        return len(rows)

    async def verify_integrity(self, signer, filters=None) -> bool:
        return all(signer.verify(e) for e in self.events if e.signature)


@pytest.fixture
def patched_auth(monkeypatch):
    """Replace ``_authenticate`` with a stub that grants full audit access.

    The decorator chain checks ``request._deerflow_test_bypass_auth`` first
    (via ``getattr``), but that attribute lives on the *original* request
    object and FastAPI rebuilds a fresh ``Request`` per handler — so the
    bypass flag never survives the trip. Patching the one async function
    both decorators ultimately consult is simpler and matches the pattern
    in ``test_authz_permission_provider``.
    """

    async def _fake_authenticate(request):
        user = SimpleNamespace(
            id="test-user",
            username="tester",
            system_role="admin",
            is_active=True,
        )
        return authz.AuthContext(user=user, permissions=["audit:read"])

    monkeypatch.setattr(authz, "_authenticate", _fake_authenticate)
    yield


@pytest.fixture
def client_and_storage(patched_auth) -> tuple[TestClient, _InMemoryStorage]:
    app = FastAPI()
    app.include_router(audit_module.router)

    storage = _InMemoryStorage()
    signer = AuditSigner("test-key")
    cfg = AuditConfig(enabled=True, sign_key="test-key")

    app.dependency_overrides[get_audit_storage] = lambda: storage
    app.dependency_overrides[get_audit_signer] = lambda: signer
    app.dependency_overrides[get_audit_config] = lambda: cfg

    return TestClient(app), storage


def _make_event(**overrides) -> AuditEvent:
    base = {
        "event_type": AuditEventType.AGENT_TASK_STARTED,
        "user_id": "alice",
        "resource": "thread:abc",
        "action": "agent.start",
        "details": {},
        "timestamp": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return AuditEvent(**base)


def test_list_event_types_returns_full_catalog(client_and_storage):
    client, _ = client_and_storage
    resp = client.get("/api/enterprise/audit/event-types")
    assert resp.status_code == 200
    values = {row["value"] for row in resp.json()}
    assert "agent.task_started" in values
    assert "sandbox.command_executed" in values


def test_list_events_returns_pagination_envelope(client_and_storage):
    client, storage = client_and_storage
    for _ in range(3):
        storage.events.append(_make_event())
    resp = client.get("/api/enterprise/audit/events", params={"limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["data"]) == 2
    assert body["has_more"] is True


def test_list_events_filters_by_user(client_and_storage):
    client, storage = client_and_storage
    storage.events.append(_make_event(user_id="alice"))
    storage.events.append(_make_event(user_id="bob"))
    resp = client.get("/api/enterprise/audit/events", params={"user_id": "bob"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["user_id"] == "bob"


def test_list_events_rejects_unknown_event_type(client_and_storage):
    client, _ = client_and_storage
    resp = client.get("/api/enterprise/audit/events", params={"event_type": "not.a.real.type"})
    assert resp.status_code == 400
    assert "Unknown event_type" in resp.json()["detail"]


def test_get_event_by_id_returns_match(client_and_storage):
    client, storage = client_and_storage
    target = _make_event()
    storage.events.append(_make_event())
    storage.events.append(target)
    storage.events.append(_make_event())
    resp = client.get(f"/api/enterprise/audit/events/{target.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == target.id


def test_get_event_by_id_404_on_missing(client_and_storage):
    client, _ = client_and_storage
    resp = client.get("/api/enterprise/audit/events/does-not-exist")
    assert resp.status_code == 404


def test_stats_groups_by_event_type(client_and_storage):
    client, storage = client_and_storage
    storage.events.append(_make_event(event_type=AuditEventType.AGENT_TASK_STARTED))
    storage.events.append(_make_event(event_type=AuditEventType.AGENT_TASK_STARTED))
    storage.events.append(_make_event(event_type=AuditEventType.DATA_EXPORTED))
    resp = client.get("/api/enterprise/audit/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["agent.task_started"] == 2
    assert body["counts"]["data.exported"] == 1


def test_verify_ok_when_signatures_match(client_and_storage):
    client, storage = client_and_storage
    signer = AuditSigner("test-key")
    event = _make_event()
    event.signature = signer.sign(event)
    storage.events.append(event)
    resp = client.post("/api/enterprise/audit/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


def test_verify_503_when_signer_missing(client_and_storage):
    """If no signer is configured the route refuses to lie about integrity."""
    client, _ = client_and_storage
    client.app.dependency_overrides[get_audit_signer] = lambda: None
    resp = client.post("/api/enterprise/audit/verify")
    assert resp.status_code == 503
