"""HTTP contract tests for idempotent thread-run creation (issue #5257)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import thread_runs
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus


def _user(email: str) -> User:
    return User(email=email, password_hash="x", system_role="user", id=uuid4())


def _run(run_id: str, thread_id: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        thread_id=thread_id,
        assistant_id=None,
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        error=run_id,
    )


def _make_client(monkeypatch, user: User, admissions: dict[str, RunRecord]) -> TestClient:
    async def fake_start_run(body, thread_id, request, *, idempotency_key=None, require_existing_thread=False):
        del body, request, require_existing_thread
        if idempotency_key is not None and idempotency_key in admissions:
            return admissions[idempotency_key]
        record = _run(f"run-{len(admissions) + 1}", thread_id)
        admissions[idempotency_key or f"unkeyed-{record.run_id}"] = record
        return record

    monkeypatch.setattr(thread_runs, "start_run", fake_start_run)
    app = make_authed_test_app(user_factory=lambda: user)
    app.include_router(thread_runs.router)
    app.state.stream_bridge = MagicMock(stream_exists=AsyncMock(return_value=False))
    app.state.run_manager = MagicMock()
    return TestClient(app)


def test_same_idempotency_key_reuses_thread_run(monkeypatch):
    admissions: dict[str, RunRecord] = {}
    client = _make_client(monkeypatch, _user("alice@example.com"), admissions)
    url = "/api/threads/thread-1/runs"
    headers = {"Idempotency-Key": "send-message-1"}

    first = client.post(url, json={"input": {"messages": []}}, headers=headers)
    retry = client.post(url, json={"input": {"messages": []}}, headers=headers)

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["run_id"] == first.json()["run_id"]


def test_same_idempotency_key_reuses_stream_run(monkeypatch):
    admissions: dict[str, RunRecord] = {}
    client = _make_client(monkeypatch, _user("alice@example.com"), admissions)
    url = "/api/threads/thread-1/runs/stream"
    headers = {"Idempotency-Key": "send-message-1"}

    first = client.post(url, json={"input": {"messages": []}}, headers=headers)
    retry = client.post(url, json={"input": {"messages": []}}, headers=headers)

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.headers["Content-Location"] == first.headers["Content-Location"]


def test_same_idempotency_key_reuses_wait_run(monkeypatch):
    admissions: dict[str, RunRecord] = {}
    client = _make_client(monkeypatch, _user("alice@example.com"), admissions)
    url = "/api/threads/thread-1/runs/wait"
    headers = {"Idempotency-Key": "send-message-1"}

    first = client.post(url, json={"input": {"messages": []}}, headers=headers)
    retry = client.post(url, json={"input": {"messages": []}}, headers=headers)

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["error"] == first.json()["error"]


def test_idempotency_key_is_scoped_to_thread(monkeypatch):
    admissions: dict[str, RunRecord] = {}
    client = _make_client(monkeypatch, _user("alice@example.com"), admissions)
    headers = {"Idempotency-Key": "send-message-1"}

    first = client.post("/api/threads/thread-1/runs", json={}, headers=headers)
    second = client.post("/api/threads/thread-2/runs", json={}, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["run_id"] != first.json()["run_id"]


def test_idempotency_key_is_scoped_to_authenticated_user(monkeypatch):
    admissions: dict[str, RunRecord] = {}
    alice = _make_client(monkeypatch, _user("alice@example.com"), admissions)
    bob = _make_client(monkeypatch, _user("bob@example.com"), admissions)
    url = "/api/threads/thread-1/runs"
    headers = {"Idempotency-Key": "send-message-1"}

    first = alice.post(url, json={}, headers=headers)
    second = bob.post(url, json={}, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["run_id"] != first.json()["run_id"]


def test_missing_idempotency_key_keeps_creating_runs(monkeypatch):
    admissions: dict[str, RunRecord] = {}
    client = _make_client(monkeypatch, _user("alice@example.com"), admissions)
    url = "/api/threads/thread-1/runs"

    first = client.post(url, json={})
    second = client.post(url, json={})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["run_id"] != first.json()["run_id"]


def test_different_idempotency_keys_create_different_runs(monkeypatch):
    admissions: dict[str, RunRecord] = {}
    client = _make_client(monkeypatch, _user("alice@example.com"), admissions)
    url = "/api/threads/thread-1/runs"

    first = client.post(url, json={}, headers={"Idempotency-Key": "send-message-1"})
    second = client.post(url, json={}, headers={"Idempotency-Key": "send-message-2"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["run_id"] != first.json()["run_id"]


def test_blank_idempotency_key_is_rejected(monkeypatch):
    client = _make_client(monkeypatch, _user("alice@example.com"), {})

    response = client.post(
        "/api/threads/thread-1/runs",
        json={},
        headers={"Idempotency-Key": "   "},
    )

    assert response.status_code == 422


def test_oversized_idempotency_key_is_rejected(monkeypatch):
    client = _make_client(monkeypatch, _user("alice@example.com"), {})

    response = client.post(
        "/api/threads/thread-1/runs",
        json={},
        headers={"Idempotency-Key": "x" * 256},
    )

    assert response.status_code == 422
