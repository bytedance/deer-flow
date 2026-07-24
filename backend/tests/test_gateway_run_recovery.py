"""Gateway startup recovery for stale persisted runs."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI

import deerflow.runtime as runtime_module
from app.gateway import deps as gateway_deps
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence import engine as engine_module
from deerflow.persistence import thread_meta as thread_meta_module
from deerflow.runtime import END_SENTINEL, MemoryStreamBridge, RunManager
from deerflow.runtime.checkpointer import async_provider as checkpointer_module
from deerflow.runtime.events import store as event_store_module
from deerflow.runtime.runs.store.memory import MemoryRunStore


@asynccontextmanager
async def _fake_context(value):
    yield value


class _FakeRunManager:
    """RunManager double that records startup reconciliation calls."""

    instances: list[_FakeRunManager] = []
    recovered_runs = [SimpleNamespace(run_id="run-1", thread_id="thread-1")]
    latest_by_thread: dict[str, list[SimpleNamespace]] = {}

    def __init__(self, *, store, run_ownership_config=None, on_orphans_recovered=None):
        self.store = store
        self.run_ownership_config = run_ownership_config
        self.on_orphans_recovered = on_orphans_recovered
        self.reconcile_calls: list[dict] = []
        self.list_by_thread_calls: list[dict] = []
        self.shutdown_calls: int = 0
        _FakeRunManager.instances.append(self)

    async def reconcile_orphaned_inflight_runs(
        self,
        *,
        error: str,
        before: str | None = None,
        stop_reason: str | None = None,
    ):
        self.reconcile_calls.append({"error": error, "before": before, "stop_reason": stop_reason})
        return self.recovered_runs

    async def list_by_thread(self, thread_id: str, *, user_id=None, limit: int = 100):
        self.list_by_thread_calls.append({"thread_id": thread_id, "user_id": user_id, "limit": limit})
        return self.latest_by_thread.get(thread_id, self.recovered_runs[:limit])

    async def start_heartbeat(self) -> None:
        pass

    async def stop_heartbeat(self) -> None:
        pass

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        # No in-flight tasks in these startup-recovery tests; langgraph_runtime
        # drains the manager on teardown, so the double must accept the call.
        self.shutdown_calls += 1


class _FakeThreadStore:
    def __init__(self) -> None:
        self.status_updates: list[tuple[str, str, str | None]] = []

    async def update_status(self, thread_id: str, status: str, *, user_id=None) -> None:
        self.status_updates.append((thread_id, status, user_id))


class _FakeStreamBridge:
    def __init__(self, *, existing_streams: set[str] | None = None) -> None:
        self.publish_end_calls: list[str] = []
        self.cleanup_calls: list[tuple[str, float]] = []
        self._existing_streams: set[str] = existing_streams if existing_streams is not None else set()

    async def stream_exists(self, run_id: str) -> bool:
        return run_id in self._existing_streams

    async def publish_end(self, run_id: str) -> None:
        self.publish_end_calls.append(run_id)

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        self.cleanup_calls.append((run_id, delay))


class _RetainedMemoryStreamBridge(MemoryStreamBridge):
    """Memory bridge that records cleanup without deleting test history."""

    def __init__(self) -> None:
        super().__init__()
        self.cleanup_calls: list[tuple[str, float]] = []

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        self.cleanup_calls.append((run_id, delay))


class _DelayedCleanupStreamBridge(_FakeStreamBridge):
    def __init__(self) -> None:
        super().__init__(existing_streams={"run-1"})
        self.delayed_cleanup_started = asyncio.Event()
        self.delayed_cleanup_cancelled = asyncio.Event()

    async def cleanup(self, run_id: str, *, delay: float = 0) -> None:
        self.cleanup_calls.append((run_id, delay))
        if delay <= 0:
            return
        self.delayed_cleanup_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.delayed_cleanup_cancelled.set()
            raise


@pytest.mark.anyio
async def test_recovered_run_stream_end_skips_expired_stream():
    """Startup recovery should not recreate an already-expired retained stream."""
    stream_bridge = _FakeStreamBridge(existing_streams=set())

    await gateway_deps._publish_recovered_run_stream_end(
        stream_bridge,
        [SimpleNamespace(run_id="expired-run", thread_id="thread-1")],
    )

    assert stream_bridge.publish_end_calls == []
    assert stream_bridge.cleanup_calls == []


@pytest.mark.anyio
async def test_shutdown_flushes_delayed_recovered_stream_cleanup_immediately():
    """Bridge shutdown must not abandon a delayed cleanup until the stream TTL."""
    stream_bridge = _DelayedCleanupStreamBridge()
    cleanups = await gateway_deps._publish_recovered_run_stream_end(
        stream_bridge,
        [SimpleNamespace(run_id="run-1", thread_id="thread-1")],
        cleanup_delay=60.0,
    )
    cleanup_tasks = {task: run_id for run_id, task in cleanups}
    await asyncio.wait_for(stream_bridge.delayed_cleanup_started.wait(), timeout=0.5)

    await gateway_deps._flush_recovered_stream_cleanups(
        stream_bridge,
        cleanup_tasks,
    )

    assert stream_bridge.delayed_cleanup_cancelled.is_set()
    assert stream_bridge.cleanup_calls == [("run-1", 60.0), ("run-1", 0)]


@pytest.mark.anyio
async def test_periodic_recovery_terminalizes_stream_without_thread_projection():
    """Periodic recovery must close streams without racing thread projection."""
    store = MemoryRunStore()
    stream_bridge = _RetainedMemoryStreamBridge()
    thread_store = _FakeThreadStore()
    expired = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    await store.put(
        "periodic-orphan",
        thread_id="thread-1",
        status="running",
        owner_worker_id="dead-worker",
        lease_expires_at=expired,
        created_at=expired,
    )
    await stream_bridge.publish("periodic-orphan", "values", {"step": 1})

    async def terminalize(recovered_runs):
        await gateway_deps._terminalize_recovered_runs(
            stream_bridge,
            recovered_runs,
            cleanup_delay=60.0,
        )

    manager = RunManager(
        store=store,
        worker_id="live-worker",
        run_ownership_config=RunOwnershipConfig(
            heartbeat_enabled=True,
            lease_seconds=30,
            grace_seconds=10,
        ),
        on_orphans_recovered=terminalize,
    )

    await manager._reconcile_orphans_periodic()
    await anyio.sleep(0)
    received = [
        entry
        async for entry in stream_bridge.subscribe(
            "periodic-orphan",
            heartbeat_interval=0.01,
        )
    ]
    await anyio.sleep(0)

    assert received[-1] is END_SENTINEL
    assert stream_bridge.cleanup_calls == [("periodic-orphan", 60.0)]
    assert thread_store.status_updates == []


@pytest.mark.anyio
async def test_sqlite_runtime_reconciles_orphaned_runs_on_startup(monkeypatch):
    """SQLite startup should recover stale active runs before serving requests."""
    app = FastAPI()
    config = SimpleNamespace(
        database=SimpleNamespace(backend="sqlite", checkpoint_channel_mode="full"),
        run_events=SimpleNamespace(backend="memory"),
        stream_bridge=SimpleNamespace(recovered_stream_cleanup_delay_seconds=60.0),
    )
    thread_store = _FakeThreadStore()
    stream_bridge = _FakeStreamBridge(existing_streams={"run-1"})
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
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: _fake_context(stream_bridge))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: _fake_context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: _fake_context(object()))
    monkeypatch.setattr(thread_meta_module, "make_thread_store", lambda _sf, _store: thread_store)
    monkeypatch.setattr(event_store_module, "make_run_event_store", lambda _config: object())
    monkeypatch.setattr(gateway_deps, "RunManager", _FakeRunManager)

    async with gateway_deps.langgraph_runtime(app, config):
        pass
    await anyio.sleep(0)

    assert len(_FakeRunManager.instances) == 1
    assert _FakeRunManager.instances[0].reconcile_calls
    assert _FakeRunManager.instances[0].reconcile_calls[0]["error"]
    assert _FakeRunManager.instances[0].reconcile_calls[0]["stop_reason"] == runtime_module.ORPHAN_RECOVERY_STOP_REASON
    assert _FakeRunManager.instances[0].list_by_thread_calls == [{"thread_id": "thread-1", "user_id": None, "limit": 1}]
    assert thread_store.status_updates == [("thread-1", "error", None)]
    assert stream_bridge.publish_end_calls == ["run-1"]
    assert stream_bridge.cleanup_calls == [("run-1", 60.0)]


@pytest.mark.anyio
async def test_sqlite_runtime_does_not_mark_thread_error_when_newer_run_is_success(monkeypatch):
    """Startup recovery should not let an old orphaned run overwrite a newer terminal thread state."""
    app = FastAPI()
    config = SimpleNamespace(
        database=SimpleNamespace(backend="sqlite", checkpoint_channel_mode="full"),
        run_events=SimpleNamespace(backend="memory"),
        stream_bridge=SimpleNamespace(recovered_stream_cleanup_delay_seconds=60.0),
    )
    thread_store = _FakeThreadStore()
    stream_bridge = _FakeStreamBridge(existing_streams={"old-running"})
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
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: _fake_context(stream_bridge))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: _fake_context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: _fake_context(object()))
    monkeypatch.setattr(thread_meta_module, "make_thread_store", lambda _sf, _store: thread_store)
    monkeypatch.setattr(event_store_module, "make_run_event_store", lambda _config: object())
    monkeypatch.setattr(gateway_deps, "RunManager", _FakeRunManager)

    async with gateway_deps.langgraph_runtime(app, config):
        pass
    await anyio.sleep(0)

    assert len(_FakeRunManager.instances) == 1
    assert _FakeRunManager.instances[0].list_by_thread_calls == [{"thread_id": "thread-1", "user_id": None, "limit": 1}]
    assert thread_store.status_updates == []
    assert stream_bridge.publish_end_calls == ["old-running"]
    assert stream_bridge.cleanup_calls == [("old-running", 60.0)]
