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
    assert response.json() == {"status": "success", "error": None}
    assert "LATER_RUN_RESULT" not in response.text


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
        thread_runs,
        "build_checkpoint_state_accessor",
        lambda *args, **kwargs: (SimpleNamespace(aget=fake_aget), {}),
    )
    monkeypatch.setattr(thread_runs, "serialize_channel_values_for_api", lambda values: values)

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
