"""HTTP contract tests for idempotent thread-run creation (issue #5257)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import thread_runs
from app.gateway.run_models import RunCreateRequest
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.runtime import DisconnectMode, RunManager, RunRecord, RunStatus
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore


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
            record = admissions[idempotency_key]
            record.idempotency_reused = True
            return record
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
    assert "event: gap" in retry.text
    assert "stream_replay_gap" in retry.text
    assert "reload_durable_state" in retry.text
    assert "event: end" not in retry.text


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


class _LocalBridge:
    supports_cross_process = False

    async def stream_exists(self, run_id):
        del run_id
        return False


class _StaleSnapshot:
    config = {"configurable": {"checkpoint_id": "cp-previous"}}
    values = {"messages": [{"type": "ai", "content": "PREVIOUS_TURN"}]}


def test_wait_reused_store_only_run_does_not_return_stale_checkpoint(monkeypatch):
    """A reused running record has no local task; /wait must not serialize the current checkpoint."""

    async def fake_start_run(body, thread_id, request, *, idempotency_key=None, require_existing_thread=False):
        del body, request, idempotency_key, require_existing_thread
        return RunRecord(
            run_id="run-live",
            thread_id=thread_id,
            assistant_id=None,
            status=RunStatus.running,
            on_disconnect=DisconnectMode.continue_,
            store_only=True,
            idempotency_reused=True,
        )

    async def fake_aget(config):
        del config
        return _StaleSnapshot()

    monkeypatch.setattr(thread_runs, "start_run", fake_start_run)
    monkeypatch.setattr(
        thread_runs,
        "build_checkpoint_state_accessor",
        lambda *args, **kwargs: (SimpleNamespace(aget=fake_aget), {}),
    )
    monkeypatch.setattr(thread_runs, "serialize_channel_values_for_api", lambda values: values)

    app = make_authed_test_app(user_factory=lambda: _user("alice@example.com"))
    app.include_router(thread_runs.router)
    app.state.stream_bridge = _LocalBridge()
    app.state.run_manager = MagicMock()

    with TestClient(app) as client:
        response = client.post(
            "/api/threads/thread-1/runs/wait",
            json={"input": {"messages": []}},
            headers={"Idempotency-Key": "send-message-1"},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "running", "error": None}
    assert "PREVIOUS_TURN" not in response.text


@pytest.mark.anyio
async def test_sse_consumer_reused_terminal_missing_stream_yields_gap():
    from app.gateway.services import sse_consumer

    record = RunRecord(
        run_id="run-done",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        store_only=True,
        idempotency_reused=True,
    )
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))

    frames = [frame async for frame in sse_consumer(_LocalBridge(), record, request, MagicMock())]

    assert len(frames) == 1
    assert frames[0].startswith("event: gap\n")
    assert "stream_replay_gap" in frames[0]
    assert "reload_durable_state" in frames[0]
    assert "event: end" not in frames[0]


def _make_start_run_request(run_manager):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore

    store = InMemoryStore()
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=None, user=None),
        app=SimpleNamespace(
            state=SimpleNamespace(
                stream_bridge=SimpleNamespace(),
                run_manager=run_manager,
                checkpointer=InMemorySaver(),
                store=store,
                run_event_store=MemoryRunEventStore(),
                run_events_config=None,
                thread_store=MemoryThreadMetaStore(store),
            )
        ),
    )


@pytest.fixture
def _stub_app_config():
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


@pytest.mark.anyio
async def test_start_run_reuses_store_backed_running_row_without_attaching_worker(_stub_app_config):
    from app.gateway.services import start_run

    input_payload = {"messages": [{"role": "user", "content": "hello"}]}
    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")
    first = await owner.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        kwargs={"input": input_payload, "config": None},
    )

    attached = False

    async def fake_run_agent(*args, **kwargs):
        del args, kwargs
        nonlocal attached
        attached = True

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
    ):
        record = await start_run(
            RunCreateRequest(input=input_payload),
            "thread-1",
            _make_start_run_request(peer),
            idempotency_key="http-run:same",
        )

    assert record.run_id == first.run_id
    assert record.idempotency_reused is True
    assert record.store_only is True
    assert record.task is None
    assert attached is False


@pytest.mark.anyio
async def test_start_run_rejects_reused_key_with_different_input(_stub_app_config):
    from app.gateway.services import start_run

    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")
    await owner.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        kwargs={"input": {"messages": [{"role": "user", "content": "summarize"}]}, "config": None},
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=AssertionError("worker must not attach")),
        pytest.raises(HTTPException) as excinfo,
    ):
        await start_run(
            RunCreateRequest(input={"messages": [{"role": "user", "content": "translate"}]}),
            "thread-1",
            _make_start_run_request(peer),
            idempotency_key="http-run:same",
        )

    assert excinfo.value.status_code == 409
    assert "different request" in str(excinfo.value.detail)
