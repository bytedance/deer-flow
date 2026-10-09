"""HTTP contract tests for idempotent thread-run creation (issue #5257)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from _router_auth_helpers import call_unwrapped, make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.gateway import services
from app.gateway.auth.models import User
from app.gateway.routers import thread_runs
from app.gateway.run_models import RunCreateRequest
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.runtime import DisconnectMode, RunManager, RunRecord, RunStatus
from deerflow.runtime import serialization as runtime_serialization
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
    assert "event: end" in first.text
    assert "event: gap" not in first.text
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
        services,
        "build_checkpoint_state_accessor",
        lambda *args, **kwargs: (SimpleNamespace(aget=fake_aget), {}),
    )
    monkeypatch.setattr(runtime_serialization, "serialize_channel_values_for_api", lambda values: values)

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


def test_wait_reused_completed_run_does_not_return_later_checkpoint(monkeypatch):
    """A locally cached completed reuse must not serialize a later thread head."""

    async def fake_start_run(body, thread_id, request, *, idempotency_key=None, require_existing_thread=False):
        del body, request, idempotency_key, require_existing_thread
        return RunRecord(
            run_id="run-a",
            thread_id=thread_id,
            assistant_id=None,
            status=RunStatus.success,
            on_disconnect=DisconnectMode.continue_,
            store_only=False,
            idempotency_reused=True,
        )

    async def fake_aget(config):
        del config
        return SimpleNamespace(
            config={"configurable": {"checkpoint_id": "cp-later"}},
            values={"messages": [{"type": "ai", "content": "LATER_RUN_RESULT"}]},
        )

    monkeypatch.setattr(thread_runs, "start_run", fake_start_run)
    monkeypatch.setattr(
        services,
        "build_checkpoint_state_accessor",
        lambda *args, **kwargs: (SimpleNamespace(aget=fake_aget), {}),
    )
    monkeypatch.setattr(runtime_serialization, "serialize_channel_values_for_api", lambda values: values)

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
    assert response.json() == {"status": "success", "error": None}
    assert "LATER_RUN_RESULT" not in response.text


@pytest.mark.anyio
async def test_wait_original_request_keeps_checkpoint_when_retry_overlaps():
    """An overlapping retry must not suppress the original creating /wait result."""
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

    bridge = MemoryStreamBridge()
    record = RunRecord(
        run_id="run-a",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.running,
        on_disconnect=DisconnectMode.continue_,
        store_only=False,
        idempotency_reused=False,
    )
    record.task = asyncio.create_task(asyncio.Event().wait())
    snapshot = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "cp-a"}},
        values={"messages": [{"type": "ai", "content": "FIRST_RUN_RESULT"}]},
    )
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))

    async def fake_start_run(body, thread_id, request, *, idempotency_key=None, require_existing_thread=False):
        del body, thread_id, request, idempotency_key, require_existing_thread
        return record

    async def fake_aget(config):
        del config
        return snapshot

    with (
        patch.object(thread_runs, "start_run", fake_start_run),
        patch.object(thread_runs, "get_stream_bridge", return_value=bridge),
        patch.object(thread_runs, "get_run_manager", return_value=MagicMock()),
        patch.object(
            services,
            "build_checkpoint_state_accessor",
            lambda *args, **kwargs: (SimpleNamespace(aget=fake_aget), {}),
        ),
        patch.object(runtime_serialization, "serialize_channel_values_for_api", lambda values: values),
    ):
        wait_task = asyncio.create_task(
            call_unwrapped(
                thread_runs.wait_run,
                "thread-1",
                RunCreateRequest(input={"messages": []}),
                request,
            )
        )
        await asyncio.sleep(0.05)
        record.idempotency_reused = True
        record.status = RunStatus.success
        await bridge.publish_end(record.run_id)
        result = await asyncio.wait_for(wait_task, timeout=2)

    record.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await record.task

    assert result["messages"][0]["content"] == "FIRST_RUN_RESULT"


@pytest.mark.anyio
async def test_wait_peer_refreshes_status_after_owner_completes():
    """A cross-worker reuse must not keep admission-time running after END."""
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")
    bridge = MemoryStreamBridge()
    bridge.supports_cross_process = True
    input_payload = {"messages": [{"role": "user", "content": "hello"}]}
    first = await owner.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        kwargs={"input": input_payload, "config": None},
    )
    await owner.set_status(first.run_id, RunStatus.running)
    reused = await peer.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        kwargs={"input": input_payload, "config": None},
    )
    assert reused.run_id == first.run_id
    assert reused.store_only is True
    assert reused.idempotency_reused is True
    assert reused.status == RunStatus.running
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))

    async def fake_start_run(body, thread_id, request, *, idempotency_key=None, require_existing_thread=False):
        del body, thread_id, request, idempotency_key, require_existing_thread
        return reused

    with (
        patch.object(thread_runs, "start_run", fake_start_run),
        patch.object(thread_runs, "get_stream_bridge", return_value=bridge),
        patch.object(thread_runs, "get_run_manager", return_value=peer),
        patch.object(
            services,
            "build_checkpoint_state_accessor",
            side_effect=AssertionError("reused wait must not read latest checkpoint"),
        ),
    ):
        wait_task = asyncio.create_task(
            call_unwrapped(
                thread_runs.wait_run,
                "thread-1",
                RunCreateRequest(input=input_payload),
                request,
            )
        )
        await asyncio.sleep(0.05)
        await owner.set_status(first.run_id, RunStatus.success)
        await bridge.publish_end(first.run_id)
        result = await asyncio.wait_for(wait_task, timeout=2)

    assert result == {"status": "success", "error": None}
    assert reused.status == RunStatus.success


def test_scope_http_run_idempotency_key_ignores_header_default():
    """Direct handler calls pass FastAPI's Header() object, not None."""
    from fastapi.params import Header as HeaderParam

    request = SimpleNamespace(state=SimpleNamespace(user=None))
    assert thread_runs._scope_http_run_idempotency_key(request, "thread-1", HeaderParam(default=None)) is None
    assert thread_runs._scope_http_run_idempotency_key(request, "thread-1", None) is None


def test_stream_reused_store_only_running_run_returns_409(monkeypatch):
    """A reused running record on a process-local bridge must not hang on an empty stream."""

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

    monkeypatch.setattr(thread_runs, "start_run", fake_start_run)

    app = make_authed_test_app(user_factory=lambda: _user("alice@example.com"))
    app.include_router(thread_runs.router)
    app.state.stream_bridge = _LocalBridge()
    app.state.run_manager = MagicMock()

    with TestClient(app) as client:
        response = client.post(
            "/api/threads/thread-1/runs/stream",
            json={"input": {"messages": []}},
            headers={"Idempotency-Key": "send-message-1"},
        )

    assert response.status_code == 409, response.text
    assert "not active on this worker" in response.json()["detail"]


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

    frames = [
        frame
        async for frame in sse_consumer(
            _LocalBridge(),
            record,
            request,
            MagicMock(),
            emit_gap_on_missing_stream=True,
        )
    ]

    assert len(frames) == 1
    assert frames[0].startswith("event: gap\n")
    assert "stream_replay_gap" in frames[0]
    assert "reload_durable_state" in frames[0]
    assert "event: end" not in frames[0]


@pytest.mark.anyio
async def test_sse_consumer_observer_join_keeps_end_after_sticky_reuse_flag():
    """Observer joins must not inherit create_or_reject's sticky reuse flag."""
    from app.gateway.services import sse_consumer

    record = RunRecord(
        run_id="run-done",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        idempotency_reused=True,
    )
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))

    frames = [frame async for frame in sse_consumer(_LocalBridge(), record, request, MagicMock(), apply_on_disconnect=False)]

    assert len(frames) == 1
    assert frames[0].startswith("event: end\n")
    assert "event: gap" not in frames[0]


@pytest.mark.anyio
async def test_sse_consumer_default_path_keeps_end_after_sticky_reuse_flag():
    """Default sse_consumer, including stateless /api/runs/stream, must not emit gap
    just because create_or_reject left idempotency_reused set, or because
    apply_on_disconnect still defaults to True.
    """
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
    assert frames[0].startswith("event: end\n")
    assert "event: gap" not in frames[0]


@pytest.mark.anyio
async def test_sse_consumer_missing_stream_gap_requires_explicit_flag():
    """apply_on_disconnect must not select gap vs end by itself."""
    from app.gateway.services import sse_consumer

    record = RunRecord(
        run_id="run-done",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        store_only=True,
    )
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))

    default_frames = [frame async for frame in sse_consumer(_LocalBridge(), record, request, MagicMock(), apply_on_disconnect=True)]
    gap_frames = [
        frame
        async for frame in sse_consumer(
            _LocalBridge(),
            record,
            request,
            MagicMock(),
            apply_on_disconnect=False,
            emit_gap_on_missing_stream=True,
        )
    ]

    assert default_frames[0].startswith("event: end\n")
    assert gap_frames[0].startswith("event: gap\n")


@pytest.mark.anyio
async def test_observer_join_stays_end_after_real_manager_reuse():
    """Join of a terminal missing stream stays `end` after a later key reuse.

    ``create_or_reject`` sets ``idempotency_reused`` on the cached record that
    ``RunManager.get()`` returns. Observer joins read that same object; the
    missing-stream branch must still follow ``emit_gap_on_missing_stream``,
    not the sticky flag or ``apply_on_disconnect``.
    """
    from app.gateway.services import sse_consumer

    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="worker-a")
    first = await manager.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
    )
    await manager.set_status(first.run_id, RunStatus.success)
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))

    async def _frames(*, apply_on_disconnect: bool = True, emit_gap_on_missing_stream: bool = False):
        record = await manager.get(first.run_id)
        assert record is not None
        return [
            frame
            async for frame in sse_consumer(
                _LocalBridge(),
                record,
                request,
                manager,
                apply_on_disconnect=apply_on_disconnect,
                emit_gap_on_missing_stream=emit_gap_on_missing_stream,
            )
        ]

    before = await _frames(apply_on_disconnect=False)
    assert before[0].startswith("event: end\n")

    reused = await manager.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
    )
    assert reused.run_id == first.run_id
    assert reused.idempotency_reused is True

    after = await _frames(apply_on_disconnect=False)
    assert after[0].startswith("event: end\n")
    assert "event: gap" not in after[0]

    after_default = await _frames()
    assert after_default[0].startswith("event: end\n")
    assert "event: gap" not in after_default[0]

    creating = await _frames(emit_gap_on_missing_stream=True)
    assert creating[0].startswith("event: gap\n")
    assert "event: end" not in creating[0]


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


def test_resume_idempotency_fingerprint_is_typed_and_order_independent():
    from app.gateway.services import _run_idempotency_request

    first = _run_idempotency_request(RunCreateRequest(command={"resume": {"enabled": True, "count": 1, "ratio": 1.0}}))
    reordered = _run_idempotency_request(RunCreateRequest(command={"resume": {"ratio": 1.0, "count": 1, "enabled": True}}))

    assert first == reordered
    assert first != _run_idempotency_request(RunCreateRequest(command={"resume": {"enabled": 1, "count": 1, "ratio": 1.0}}))
    assert first != _run_idempotency_request(RunCreateRequest(command={"resume": {"enabled": True, "count": 1.0, "ratio": 1.0}}))
    assert first != _run_idempotency_request(RunCreateRequest(input={"command": {"resume": {"enabled": True, "count": 1, "ratio": 1.0}}}))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_resume_idempotency_fingerprint_rejects_non_finite_numbers(value):
    from app.gateway.services import _run_idempotency_request

    with pytest.raises(HTTPException) as excinfo:
        _run_idempotency_request(RunCreateRequest(command={"resume": value}))

    assert excinfo.value.status_code == 422
    assert "strict JSON" in str(excinfo.value.detail)


@pytest.mark.anyio
@pytest.mark.parametrize("idempotency_key", [None, "http-run:same"])
async def test_start_run_rejects_invalid_resume_before_agent_assembly(_stub_app_config, idempotency_key):
    from app.gateway.services import start_run

    factory = MagicMock(side_effect=AssertionError("agent assembly must not run"))
    with (
        patch("app.gateway.services.resolve_agent_factory", factory),
        pytest.raises(HTTPException) as excinfo,
    ):
        await start_run(
            RunCreateRequest(command={"resume": float("nan")}),
            "thread-1",
            _make_start_run_request(RunManager(store=MemoryRunStore())),
            idempotency_key=idempotency_key,
        )

    assert excinfo.value.status_code == 422
    factory.assert_not_called()


def test_run_response_never_contains_internal_idempotency_fingerprint():
    record = _run("run-1", "thread-1")
    record.kwargs = {"input": None}
    record.idempotency_request = {
        "version": 1,
        "kind": "resume",
        "sha256": "a" * 64,
    }

    response = thread_runs._record_to_response(record)

    assert response.kwargs == {"input": None}


def test_run_response_sanitizes_legacy_resume_idempotency_fence():
    record = _run("run-1", "thread-1")
    record.kwargs = {
        "input": ["deerflow-resume-idempotency", 1, "a" * 64],
        "idempotency_request": {
            "version": 1,
            "kind": "resume",
            "sha256": "a" * 64,
        },
    }

    response = thread_runs._record_to_response(record)

    assert response.kwargs == {"input": None}


@pytest.mark.anyio
async def test_start_run_rejects_legacy_reused_key_for_resume(_stub_app_config):
    from app.gateway.services import start_run

    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")
    await owner.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        kwargs={"input": None, "config": None},
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=AssertionError("worker must not attach")),
        pytest.raises(HTTPException) as excinfo,
    ):
        await start_run(
            RunCreateRequest(command={"resume": {"answer": "approve"}}),
            "thread-1",
            _make_start_run_request(peer),
            idempotency_key="http-run:same",
        )

    assert excinfo.value.status_code == 409
    assert "different request" in str(excinfo.value.detail)


@pytest.mark.anyio
async def test_start_run_reuses_matching_legacy_writer_resume_fingerprint(_stub_app_config):
    from app.gateway.services import _run_idempotency_request, start_run

    approved = RunCreateRequest(command={"resume": {"answer": "approve"}})
    denied = RunCreateRequest(command={"resume": {"answer": "deny"}})
    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")
    first = await owner.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        kwargs={
            "input": ["deerflow-resume-idempotency", 1, "a" * 64],
            "idempotency_request": _run_idempotency_request(approved),
            "config": None,
        },
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=AssertionError("worker must not attach")),
    ):
        reused = await start_run(
            approved,
            "thread-1",
            _make_start_run_request(peer),
            idempotency_key="http-run:same",
        )
        with pytest.raises(HTTPException) as excinfo:
            await start_run(
                denied,
                "thread-1",
                _make_start_run_request(peer),
                idempotency_key="http-run:same",
            )

    assert reused.run_id == first.run_id
    assert reused.idempotency_reused is True
    assert excinfo.value.status_code == 409
    assert "different request" in str(excinfo.value.detail)


@pytest.mark.anyio
async def test_start_run_reuses_only_matching_resume_fingerprint(_stub_app_config):
    from app.gateway.services import _run_idempotency_request, start_run

    approved = RunCreateRequest(command={"resume": {"answer": "approve"}})
    denied = RunCreateRequest(command={"resume": {"answer": "deny"}})
    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")
    first = await owner.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        idempotency_request=_run_idempotency_request(approved),
        kwargs={"input": None, "config": None},
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=AssertionError("worker must not attach")),
    ):
        reused = await start_run(
            approved,
            "thread-1",
            _make_start_run_request(peer),
            idempotency_key="http-run:same",
        )
        with pytest.raises(HTTPException) as excinfo:
            await start_run(
                denied,
                "thread-1",
                _make_start_run_request(peer),
                idempotency_key="http-run:same",
            )

    assert reused.run_id == first.run_id
    assert reused.idempotency_reused is True
    assert reused.store_only is True
    assert reused.task is None
    assert excinfo.value.status_code == 409
    assert "different request" in str(excinfo.value.detail)


@pytest.mark.anyio
async def test_start_run_persists_resume_fingerprint_without_payload(_stub_app_config):
    from app.gateway.services import _run_idempotency_request, start_run

    request_body = RunCreateRequest(command={"resume": {"answer": "approve"}})
    manager = RunManager(store=MemoryRunStore(), worker_id="worker-a")

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", new_callable=AsyncMock),
    ):
        record = await start_run(
            request_body,
            "thread-1",
            _make_start_run_request(manager),
            idempotency_key="http-run:same",
        )
        assert record.task is not None
        await record.task

    assert record.idempotency_request == _run_idempotency_request(request_body)
    assert record.idempotency_request["kind"] == "resume"
    assert set(record.idempotency_request) == {"version", "kind", "sha256"}
    assert record.kwargs["input"] is None
    assert "idempotency_request" not in record.kwargs


async def _pre_6499_resume_retry(session_factory, body, idempotency_key):
    """Freeze the null-input resume reuse policy from 02ce9ab2, without mapping the new column.

    This intentionally models only the historical resume case exercised below,
    not an alternative implementation of current Gateway admission.
    """
    import sqlalchemy as sa

    assert body.input is None and body.command.get("resume") is not None
    old_runs = sa.Table(
        "runs",
        sa.MetaData(),
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("assistant_id", sa.String(128)),
        sa.Column("kwargs_json", sa.JSON()),
    )
    async with session_factory() as session:
        row = (await session.execute(sa.select(old_runs).where(old_runs.c.idempotency_key == idempotency_key))).mappings().one()
    stored = row["kwargs_json"]
    # Old start_run compares input, assistant and references, ignoring command.resume.
    if stored.get("input") != body.input or row["assistant_id"] != body.assistant_id or stored.get("conversation_references", []) != list(body.conversation_references or []):
        raise HTTPException(status_code=409, detail="Idempotency-Key already used with a different request")
    return row["run_id"]


@pytest.mark.anyio
@pytest.mark.parametrize("writer_version", ["pre-6499", "current"])
async def test_mixed_version_resume_admission_requires_upgraded_routing(tmp_path, _stub_app_config, writer_version):
    """Read compatibility does not make old workers safe keyed-resume retry targets."""
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'mixed-resume.db'}", sqlite_dir=str(tmp_path))
    try:
        session_factory = get_session_factory()
        repo = RunRepository(session_factory)
        owner = RunManager(store=repo, worker_id="writer")
        peer = RunManager(store=repo, worker_id="upgraded-reader")
        approved = RunCreateRequest(command={"resume": {"answer": "approve"}})
        denied = RunCreateRequest(command={"resume": {"answer": "deny"}})
        key = "http-run:mixed-resume"
        with (
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", new_callable=AsyncMock) as run_agent,
        ):
            if writer_version == "current":
                first = await services.start_run(approved, "thread-1", _make_start_run_request(owner), idempotency_key=key)
                assert first.task is not None
                await first.task
                assert run_agent.await_args.kwargs["graph_input"].resume == {"answer": "approve"}
            else:
                # Pre-6499 writers admit null input and persist no resume identity.
                first = await owner.create_or_reject("thread-1", approved.assistant_id, user_id=None, idempotency_key=key, kwargs={"input": None, "config": None})

            persisted = await repo.get(first.run_id, user_id=None)
            assert persisted is not None
            assert bool(persisted["idempotency_request"]) is (writer_version == "current")
            assert persisted["kwargs"]["input"] is None
            assert "idempotency_request" not in persisted["kwargs"]

            # The genuine old-column SQL projection cannot see the private identity:
            # both decisions reuse the same row under the historical input-only policy.
            assert await _pre_6499_resume_retry(session_factory, approved, key) == first.run_id
            assert await _pre_6499_resume_retry(session_factory, denied, key) == first.run_id

            if writer_version == "current":
                retry = await services.start_run(approved, "thread-1", _make_start_run_request(peer), idempotency_key=key)
                assert retry.run_id == first.run_id and retry.idempotency_reused
            else:
                # Even an identical retry is unverifiable for an identity-less legacy row.
                with pytest.raises(HTTPException) as error:
                    await services.start_run(approved, "thread-1", _make_start_run_request(peer), idempotency_key=key)
                assert error.value.status_code == 409

            with pytest.raises(HTTPException) as error:
                await services.start_run(denied, "thread-1", _make_start_run_request(peer), idempotency_key=key)
            assert error.value.status_code == 409
            assert run_agent.await_count == (1 if writer_version == "current" else 0)
            assert len(await repo.list_by_thread("thread-1", user_id=None)) == 1
            assert (await repo.get(first.run_id, user_id=None))["idempotency_request"] == persisted["idempotency_request"]
    finally:
        await close_engine()


@pytest.mark.anyio
@pytest.mark.parametrize("stored_kind", ["input", "resume"])
async def test_start_run_rejects_input_resume_kind_collision(_stub_app_config, stored_kind):
    from app.gateway.services import _run_idempotency_request, start_run

    collision = {"command": {"resume": {"answer": "approve"}}}
    input_request = RunCreateRequest(input=collision)
    resume_request = RunCreateRequest(input=collision, command={"resume": {"answer": "approve"}})
    stored_request, retry_request = (input_request, resume_request) if stored_kind == "input" else (resume_request, input_request)
    store = MemoryRunStore()
    owner = RunManager(store=store, worker_id="worker-a")
    peer = RunManager(store=store, worker_id="worker-b")
    await owner.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:same",
        idempotency_request=_run_idempotency_request(stored_request),
        kwargs={"input": collision, "config": None},
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=AssertionError("worker must not attach")),
        pytest.raises(HTTPException) as excinfo,
    ):
        await start_run(
            retry_request,
            "thread-1",
            _make_start_run_request(peer),
            idempotency_key="http-run:same",
        )

    assert excinfo.value.status_code == 409
    assert "different request" in str(excinfo.value.detail)


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ["interrupt", "rollback"])
async def test_memory_store_reuses_live_idempotency_key_before_foreign_lease_conflict(strategy):
    from deerflow.config.run_ownership_config import RunOwnershipConfig

    store = MemoryRunStore()
    ownership = RunOwnershipConfig(
        lease_seconds=30,
        grace_seconds=10,
        heartbeat_enabled=True,
    )
    owner = RunManager(
        store=store,
        worker_id="worker-a",
        run_ownership_config=ownership,
    )
    peer = RunManager(
        store=store,
        worker_id="worker-b",
        run_ownership_config=ownership,
    )
    first = await owner.create_or_reject(
        "thread-1",
        multitask_strategy=strategy,
        idempotency_key="http-run:same",
    )

    reused = await peer.create_or_reject(
        "thread-1",
        multitask_strategy=strategy,
        idempotency_key="http-run:same",
    )

    assert reused.run_id == first.run_id
    assert reused.idempotency_reused is True
    assert reused.store_only is True
    stored = await store.get(first.run_id)
    assert stored is not None
    assert stored["status"] == "pending"
    assert stored["owner_worker_id"] == "worker-a"


@pytest.mark.anyio
async def test_keyed_input_remains_compatible_with_legacy_explicit_atomic_signature():
    from deerflow.runtime import RunIdempotencyUnsupported

    class LegacyAtomicMemoryStore(MemoryRunStore):
        async def create_thread_operation_atomic(
            self,
            run_id,
            *,
            thread_id,
            owner_worker_id,
            lease_expires_at,
            operation_kind="run",
            multitask_strategy="reject",
            assistant_id=None,
            user_id=None,
            model_name=None,
            metadata=None,
            kwargs=None,
            created_at=None,
            grace_seconds=10,
            idempotency_key=None,
        ):
            return await super().create_thread_operation_atomic(
                run_id,
                thread_id=thread_id,
                owner_worker_id=owner_worker_id,
                lease_expires_at=lease_expires_at,
                operation_kind=operation_kind,
                multitask_strategy=multitask_strategy,
                assistant_id=assistant_id,
                user_id=user_id,
                model_name=model_name,
                metadata=metadata,
                kwargs=kwargs,
                created_at=created_at,
                grace_seconds=grace_seconds,
                idempotency_key=idempotency_key,
            )

    manager = RunManager(store=LegacyAtomicMemoryStore())

    record = await manager.create_or_reject(
        "thread-1",
        idempotency_key="http-run:key",
    )

    assert record.idempotency_key == "http-run:key"

    with pytest.raises(RunIdempotencyUnsupported, match="does not support keyed resume"):
        await manager.create_or_reject(
            "thread-2",
            idempotency_key="http-run:resume",
            idempotency_request={
                "version": 1,
                "kind": "resume",
                "sha256": "a" * 64,
            },
        )


@pytest.mark.anyio
async def test_wait_retry_after_later_run_does_not_return_later_checkpoint(monkeypatch):
    """Complete two runs, then retry the first key: /wait must not return run B."""
    first_input = {"messages": [{"role": "user", "content": "one"}]}
    later_input = {"messages": [{"role": "user", "content": "two"}]}
    store = MemoryRunStore()
    manager = RunManager(store=store, worker_id="worker-a")
    first = await manager.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:first",
        kwargs={"input": first_input, "config": None},
    )
    await manager.set_status(first.run_id, RunStatus.success)
    later = await manager.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:later",
        kwargs={"input": later_input, "config": None},
    )
    await manager.set_status(later.run_id, RunStatus.success)
    reused = await manager.create_or_reject(
        "thread-1",
        user_id=None,
        idempotency_key="http-run:first",
        kwargs={"input": first_input, "config": None},
    )
    assert reused.run_id == first.run_id
    assert reused.idempotency_reused is True
    assert reused.store_only is False
    assert reused.status == RunStatus.success

    async def fake_start_run(body, thread_id, request, *, idempotency_key=None, require_existing_thread=False):
        del body, thread_id, request, idempotency_key, require_existing_thread
        return reused

    async def fake_aget(config):
        del config
        return SimpleNamespace(
            config={"configurable": {"checkpoint_id": "cp-later"}},
            values={"messages": [{"type": "ai", "content": "LATER_RUN_RESULT"}]},
        )

    monkeypatch.setattr(thread_runs, "start_run", fake_start_run)
    monkeypatch.setattr(
        services,
        "build_checkpoint_state_accessor",
        lambda *args, **kwargs: (SimpleNamespace(aget=fake_aget), {}),
    )
    monkeypatch.setattr(runtime_serialization, "serialize_channel_values_for_api", lambda values: values)

    app = make_authed_test_app(user_factory=lambda: _user("alice@example.com"))
    app.include_router(thread_runs.router)
    app.state.stream_bridge = _LocalBridge()
    app.state.run_manager = manager

    with TestClient(app) as client:
        response = client.post(
            "/api/threads/thread-1/runs/wait",
            json={"input": first_input},
            headers={"Idempotency-Key": "first"},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "success", "error": None}
    assert "LATER_RUN_RESULT" not in response.text
