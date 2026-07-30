"""Regression tests for extension services owned by the Gateway runtime."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from deerflow.extensions import (
    get_runtime_diagnostics,
    initialize_runtime_diagnostics,
    reset_runtime_diagnostics,
)
from deerflow.extensions.registry import ExtensionRegistry


def _fake_database_config() -> SimpleNamespace:
    """Minimal stand-in for AppConfig.database.

    Mirrors the real field set rather than the subset today's code happens to
    read: langgraph_runtime gained `checkpoint_delta.snapshot_frequency`
    upstream, and a fake that omits a field fails with an AttributeError far
    from the behaviour under test. The frequency comes from the real default so
    this does not pin a magic number.
    """
    from deerflow.config.database_config import DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY

    return SimpleNamespace(
        backend="memory",
        checkpoint_channel_mode="full",
        checkpoint_delta=SimpleNamespace(snapshot_frequency=DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY),
    )


class _RecordingService:
    def __init__(self, events: list[str] | None = None) -> None:
        self.started = False
        self.stopped = False
        self.start_calls = 0
        self.stop_calls = 0
        self._events = events

    async def start(self, _deps) -> None:
        self.start_calls += 1
        self.started = True
        if self._events is not None:
            self._events.append("service_start")

    async def stop(self) -> None:
        self.stop_calls += 1
        self.stopped = True
        if self._events is not None:
            self._events.append("service_stop")


@asynccontextmanager
async def _context(value):
    yield value


@pytest.fixture(autouse=True)
def _isolate_runtime_diagnostics():
    reset_runtime_diagnostics()
    yield
    reset_runtime_diagnostics()


@pytest.mark.asyncio
async def test_runtime_stops_started_extension_services_when_later_startup_fails(monkeypatch) -> None:
    """A failure after service startup must not leak the started service."""
    import deerflow.extensions as extensions_module
    import deerflow.extensions.notify as notify_module
    import deerflow.persistence.engine as engine_module
    import deerflow.persistence.thread_meta as thread_meta_module
    import deerflow.runtime as runtime_module
    import deerflow.runtime.checkpointer.async_provider as checkpointer_module
    from app.gateway.deps import langgraph_runtime

    events: list[str] = []

    class _FailingStartService(_RecordingService):
        async def start(self, _deps) -> None:
            self.start_calls += 1
            events.append("failing_start")
            raise ValueError("start exploded")

        async def stop(self) -> None:
            self.stop_calls += 1
            self.stopped = True
            events.append("failed_start_stop")

    class _FailingStopService(_RecordingService):
        async def start(self, _deps) -> None:
            self.start_calls += 1
            self.started = True
            events.append("failing_stop_start")

        async def stop(self) -> None:
            self.stop_calls += 1
            self.stopped = True
            events.append("failing_stop")
            raise ValueError("stop exploded")

    failing_start = _FailingStartService(events)
    service = _RecordingService(events)
    failing_stop = _FailingStopService(events)
    registry = ExtensionRegistry()
    with registry.attributed_to("failing-start:install"):
        registry.service(failing_start)
    with registry.attributed_to("recording:install"):
        registry.service(service)
    with registry.attributed_to("failing-stop:install"):
        registry.service(failing_stop)
    extensions = registry.build()

    async def init_engine(_database) -> None:
        return None

    async def close_engine() -> None:
        events.append("engine_close")

    def fail_thread_store(_session_factory, _store):
        raise RuntimeError("thread store startup failed")

    monkeypatch.setattr(extensions_module, "get_loaded_extensions", lambda: extensions)
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: _context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: _context(object()))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: _context(object()))
    monkeypatch.setattr(engine_module, "init_engine_from_config", init_engine)
    monkeypatch.setattr(engine_module, "close_engine", close_engine)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    monkeypatch.setattr(thread_meta_module, "make_thread_store", fail_thread_store)
    monkeypatch.setattr(
        notify_module,
        "set_extension_notify_loop",
        lambda _loop: events.append("notify_set"),
    )
    monkeypatch.setattr(
        notify_module,
        "reset_extension_notify_loop",
        lambda: events.append("notify_reset"),
    )

    app = FastAPI()
    live_diagnostics = initialize_runtime_diagnostics([])
    app.state.extension_diagnostics = live_diagnostics
    startup_config = SimpleNamespace(
        database=_fake_database_config(),
        agent_storage=SimpleNamespace(backend="file"),
    )

    with pytest.raises(RuntimeError, match="thread store startup failed"):
        async with langgraph_runtime(app, startup_config):
            pytest.fail("runtime must not yield after startup failure")

    assert service.started is True
    assert service.stopped is True
    assert service.stop_calls == 1
    assert failing_start.start_calls == 1
    assert failing_stop.stop_calls == 1
    assert app.state.extension_diagnostics is live_diagnostics
    assert get_runtime_diagnostics() == app.state.extension_diagnostics
    assert any(diagnostic.source == "failing-start:install" and "start() failed" in diagnostic.message for diagnostic in app.state.extension_diagnostics)
    assert any(diagnostic.source == "failing-stop:install" and "stop() failed" in diagnostic.message for diagnostic in app.state.extension_diagnostics)
    assert events == [
        "notify_set",
        "failing_start",
        "service_start",
        "failing_stop_start",
        "failing_stop",
        "service_stop",
        "failed_start_stop",
        "engine_close",
        "notify_reset",
    ]


@pytest.mark.asyncio
async def test_runtime_closes_engine_when_engine_initialization_fails(monkeypatch) -> None:
    """Cleanup ownership must exist before schema bootstrap can fail."""
    import deerflow.persistence.engine as engine_module
    import deerflow.runtime as runtime_module
    from app.gateway.deps import langgraph_runtime

    events: list[str] = []

    async def fail_engine_init(_database) -> None:
        events.append("engine_init")
        raise RuntimeError("schema bootstrap failed")

    async def close_engine() -> None:
        events.append("engine_close")

    monkeypatch.setattr(
        runtime_module,
        "make_stream_bridge",
        lambda _config: _context(object()),
    )
    monkeypatch.setattr(
        engine_module,
        "init_engine_from_config",
        fail_engine_init,
    )
    monkeypatch.setattr(engine_module, "close_engine", close_engine)

    app = FastAPI()
    startup_config = SimpleNamespace(
        database=_fake_database_config(),
        agent_storage=SimpleNamespace(backend="file"),
    )

    with pytest.raises(RuntimeError, match="schema bootstrap failed"):
        async with langgraph_runtime(app, startup_config):
            pytest.fail("runtime must not yield after engine startup failure")

    assert events == ["engine_init", "engine_close"]


@pytest.mark.asyncio
async def test_runtime_stops_services_when_cancelled_during_service_start(monkeypatch) -> None:
    """Cleanup ownership must exist before the service batch can be cancelled."""
    import deerflow.extensions as extensions_module
    import deerflow.persistence.engine as engine_module
    import deerflow.runtime as runtime_module
    import deerflow.runtime.checkpointer.async_provider as checkpointer_module
    from app.gateway.deps import langgraph_runtime

    events: list[str] = []
    first = _RecordingService(events)
    blocking_start_entered = asyncio.Event()

    class _BlockingStartService(_RecordingService):
        async def start(self, _deps) -> None:
            self.start_calls += 1
            self.started = True
            events.append("blocking_start")
            blocking_start_entered.set()
            await asyncio.Event().wait()

        async def stop(self) -> None:
            self.stop_calls += 1
            self.stopped = True
            events.append("blocking_stop")

    blocking = _BlockingStartService()
    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(first)
    with registry.attributed_to("blocking:install"):
        registry.service(blocking)
    extensions = registry.build()

    async def init_engine(_database) -> None:
        return None

    async def close_engine() -> None:
        events.append("engine_close")

    monkeypatch.setattr(extensions_module, "get_loaded_extensions", lambda: extensions)
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: _context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: _context(object()))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: _context(object()))
    monkeypatch.setattr(engine_module, "init_engine_from_config", init_engine)
    monkeypatch.setattr(engine_module, "close_engine", close_engine)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)

    app = FastAPI()
    startup_config = SimpleNamespace(
        database=_fake_database_config(),
        agent_storage=SimpleNamespace(backend="file"),
    )

    async def start_runtime() -> None:
        async with langgraph_runtime(app, startup_config):
            pytest.fail("runtime must not yield while service startup is blocked")

    startup_task = asyncio.create_task(start_runtime())
    await asyncio.wait_for(blocking_start_entered.wait(), timeout=1.0)
    startup_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup_task

    assert first.stop_calls == 1
    assert blocking.stop_calls == 1
    assert events == [
        "service_start",
        "blocking_start",
        "blocking_stop",
        "service_stop",
        "engine_close",
    ]


@pytest.mark.asyncio
async def test_runtime_stops_started_extension_services_when_later_startup_is_cancelled(monkeypatch) -> None:
    """Cancellation during later bootstrap must unwind the service lifecycle."""
    import app.gateway.deps as gateway_deps
    import deerflow.extensions as extensions_module
    import deerflow.persistence.engine as engine_module
    import deerflow.persistence.thread_meta as thread_meta_module
    import deerflow.runtime as runtime_module
    import deerflow.runtime.checkpointer.async_provider as checkpointer_module
    import deerflow.runtime.events.store as event_store_module

    events: list[str] = []
    service = _RecordingService(events)
    registry = ExtensionRegistry()
    with registry.attributed_to("recording:install"):
        registry.service(service)
    extensions = registry.build()
    reconciliation_started = asyncio.Event()

    class BlockingRunManager:
        def __init__(self, **_kwargs) -> None:
            pass

        async def reconcile_orphaned_inflight_runs(self, **_kwargs):
            reconciliation_started.set()
            await asyncio.Event().wait()

    async def init_engine(_database) -> None:
        return None

    async def close_engine() -> None:
        events.append("engine_close")

    monkeypatch.setattr(extensions_module, "get_loaded_extensions", lambda: extensions)
    monkeypatch.setattr(runtime_module, "make_stream_bridge", lambda _config: _context(object()))
    monkeypatch.setattr(runtime_module, "make_store", lambda _config: _context(object()))
    monkeypatch.setattr(checkpointer_module, "make_checkpointer", lambda _config: _context(object()))
    monkeypatch.setattr(engine_module, "init_engine_from_config", init_engine)
    monkeypatch.setattr(engine_module, "close_engine", close_engine)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    monkeypatch.setattr(thread_meta_module, "make_thread_store", lambda _session_factory, _store: object())
    monkeypatch.setattr(event_store_module, "make_run_event_store", lambda _config: object())
    monkeypatch.setattr(gateway_deps, "RunManager", BlockingRunManager)

    app = FastAPI()
    startup_config = SimpleNamespace(
        database=_fake_database_config(),
        agent_storage=SimpleNamespace(backend="file"),
        run_events=None,
        stream_bridge=None,
    )

    async def start_runtime() -> None:
        async with gateway_deps.langgraph_runtime(app, startup_config):
            pytest.fail("runtime must not yield while reconciliation is blocked")

    startup_task = asyncio.create_task(start_runtime())
    await asyncio.wait_for(reconciliation_started.wait(), timeout=1.0)
    assert service.started is True

    startup_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup_task

    assert service.stopped is True
    assert service.stop_calls == 1
    assert events == ["service_start", "service_stop", "engine_close"]
