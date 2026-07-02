"""Gateway startup recovery for stale persisted runs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

import deerflow.runtime as runtime_module
from app.gateway import deps as gateway_deps
from deerflow.persistence import engine as engine_module
from deerflow.persistence import thread_meta as thread_meta_module
from deerflow.runtime.checkpointer import async_provider as checkpointer_module
from deerflow.runtime.events import store as event_store_module


@asynccontextmanager
async def _fake_context(value):
    yield value


class _FakeRunManager:
    """RunManager double that records startup reconciliation calls."""

    instances: list[_FakeRunManager] = []
    recovered_runs = [SimpleNamespace(run_id="run-1", thread_id="thread-1")]
    latest_by_thread: dict[str, list[SimpleNamespace]] = {}

    def __init__(self, *, store):
        self.store = store
        self.reconcile_calls: list[dict] = []
        self.list_by_thread_calls: list[dict] = []
        self.shutdown_calls: int = 0
        _FakeRunManager.instances.append(self)

    async def reconcile_orphaned_inflight_runs(self, *, error: str, before: str | None = None):
        self.reconcile_calls.append({"error": error, "before": before})
        return self.recovered_runs

    async def list_by_thread(self, thread_id: str, *, user_id=None, limit: int = 100):
        self.list_by_thread_calls.append({"thread_id": thread_id, "user_id": user_id, "limit": limit})
        return self.latest_by_thread.get(thread_id, self.recovered_runs[:limit])

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        # No in-flight tasks in these startup-recovery tests; langgraph_runtime
        # drains the manager on teardown, so the double must accept the call.
        self.shutdown_calls += 1


class _FakeThreadStore:
    def __init__(self) -> None:
        self.status_updates: list[tuple[str, str, str | None]] = []

    async def update_status(self, thread_id: str, status: str, *, user_id=None) -> None:
        self.status_updates.append((thread_id, status, user_id))


class _FakeWorkflowStore:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.mark_calls: list[dict] = []
        self.events: list[dict] = []

    async def list(self, *, thread_id=None, run_id=None, limit=100, **_kwargs):
        return [
            row
            for row in self.rows[:limit]
            if (thread_id is None or row.get("thread_id") == thread_id)
            and (run_id is None or row.get("run_id") == run_id)
        ]

    async def mark_orphaned(self, workflow_id: str, *, error: str, metadata=None):
        self.mark_calls.append({"workflow_id": workflow_id, "error": error, "metadata": metadata})
        for row in self.rows:
            if row.get("workflow_id") == workflow_id:
                row["status"] = "orphaned"
                row["error"] = error
                row["lease_owner"] = None
                row["lease_expires_at"] = None
                row["metadata"] = {**(row.get("metadata") or {}), **(metadata or {})}
                return True
        return False

    async def append_event(self, workflow_id: str, **kwargs):
        event = {"workflow_id": workflow_id, **kwargs}
        self.events.append(event)
        return event


@pytest.mark.anyio
async def test_sqlite_runtime_reconciles_orphaned_runs_on_startup(monkeypatch):
    """SQLite startup should recover stale active runs before serving requests."""
    app = FastAPI()
    config = SimpleNamespace(
        database=SimpleNamespace(backend="sqlite"),
        run_events=SimpleNamespace(backend="memory"),
    )
    thread_store = _FakeThreadStore()
    _FakeRunManager.instances.clear()
    _FakeRunManager.recovered_runs = [SimpleNamespace(run_id="run-1", thread_id="thread-1")]
    _FakeRunManager.latest_by_thread = {}

    async def fake_init_engine_from_config(_database):
        return None

    async def fake_close_engine():
        return None

    monkeypatch.setattr(engine_module, "init_engine_from_config", fake_init_engine_from_config)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    monkeypatch.setattr(engine_module, "close_engine", fake_close_engine)
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: _fake_context(object()))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: _fake_context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: _fake_context(object()))
    monkeypatch.setattr(thread_meta_module, "make_thread_store", lambda _sf, _store: thread_store)
    monkeypatch.setattr(event_store_module, "make_run_event_store", lambda _config: object())
    monkeypatch.setattr(gateway_deps, "RunManager", _FakeRunManager)

    async with gateway_deps.langgraph_runtime(app, config):
        pass

    assert len(_FakeRunManager.instances) == 1
    assert _FakeRunManager.instances[0].reconcile_calls
    assert _FakeRunManager.instances[0].reconcile_calls[0]["error"]
    assert _FakeRunManager.instances[0].list_by_thread_calls == [{"thread_id": "thread-1", "user_id": None, "limit": 1}]
    assert thread_store.status_updates == [("thread-1", "error", None)]


@pytest.mark.anyio
async def test_sqlite_runtime_does_not_mark_thread_error_when_newer_run_is_success(monkeypatch):
    """Startup recovery should not let an old orphaned run overwrite a newer terminal thread state."""
    app = FastAPI()
    config = SimpleNamespace(
        database=SimpleNamespace(backend="sqlite"),
        run_events=SimpleNamespace(backend="memory"),
    )
    thread_store = _FakeThreadStore()
    _FakeRunManager.instances.clear()
    _FakeRunManager.recovered_runs = [SimpleNamespace(run_id="old-running", thread_id="thread-1")]
    _FakeRunManager.latest_by_thread = {"thread-1": [SimpleNamespace(run_id="newer-success", thread_id="thread-1", status="success")]}

    async def fake_init_engine_from_config(_database):
        return None

    async def fake_close_engine():
        return None

    monkeypatch.setattr(engine_module, "init_engine_from_config", fake_init_engine_from_config)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    monkeypatch.setattr(engine_module, "close_engine", fake_close_engine)
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: _fake_context(object()))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: _fake_context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: _fake_context(object()))
    monkeypatch.setattr(thread_meta_module, "make_thread_store", lambda _sf, _store: thread_store)
    monkeypatch.setattr(event_store_module, "make_run_event_store", lambda _config: object())
    monkeypatch.setattr(gateway_deps, "RunManager", _FakeRunManager)

    async with gateway_deps.langgraph_runtime(app, config):
        pass

    assert len(_FakeRunManager.instances) == 1
    assert _FakeRunManager.instances[0].list_by_thread_calls == [{"thread_id": "thread-1", "user_id": None, "limit": 1}]
    assert thread_store.status_updates == []


@pytest.mark.anyio
async def test_recovered_run_marks_active_workflows_orphaned():
    workflow_store = _FakeWorkflowStore(
        [
            {
                "workflow_id": "wf-running",
                "thread_id": "thread-1",
                "run_id": "run-1",
                "status": "running",
                "lease_owner": "worker-old",
                "lease_expires_at": "2099-01-01T00:00:00+00:00",
            },
            {
                "workflow_id": "wf-terminal",
                "thread_id": "thread-1",
                "run_id": "run-1",
                "status": "succeeded",
            },
        ]
    )
    recovered_runs = [SimpleNamespace(run_id="run-1", thread_id="thread-1")]

    marked = await gateway_deps._mark_recovered_workflows_orphaned(
        workflow_store,
        recovered_runs,
        error="gateway restarted",
    )

    assert marked == 1
    assert workflow_store.mark_calls == [
        {
            "workflow_id": "wf-running",
            "error": "gateway restarted",
            "metadata": {
                "recovery": "gateway_restart_orphan",
                "run_id": "run-1",
                "run_status": "error",
            },
        }
    ]
    assert workflow_store.rows[0]["status"] == "orphaned"
    assert workflow_store.rows[0]["lease_owner"] is None
    assert [event["event_type"] for event in workflow_store.events] == ["workflow.orphaned"]
    assert workflow_store.events[0]["category"] == "recovery"
