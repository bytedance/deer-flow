"""Regression tests for Gateway ownership of extension services."""

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


@pytest.fixture(autouse=True)
def _isolate_runtime_diagnostics():
    reset_runtime_diagnostics()
    yield
    reset_runtime_diagnostics()


def _database_config() -> SimpleNamespace:
    return SimpleNamespace(
        backend="memory",
        checkpoint_channel_mode="full",
        checkpoint_delta=SimpleNamespace(snapshot_frequency=10),
    )


@asynccontextmanager
async def _resource(value):
    yield value


def _patch_runtime_resources(monkeypatch, events: list[str]) -> None:
    async def init_engine(_database) -> None:
        return None

    async def close_engine() -> None:
        events.append("engine_close")

    monkeypatch.setattr("deerflow.runtime.make_stream_bridge", lambda _config: _resource(object()))
    monkeypatch.setattr("deerflow.runtime.make_store", lambda _config: _resource(object()))
    monkeypatch.setattr("deerflow.runtime.checkpointer.async_provider.make_checkpointer", lambda _config: _resource(object()))
    monkeypatch.setattr("deerflow.persistence.engine.init_engine_from_config", init_engine)
    monkeypatch.setattr("deerflow.persistence.engine.close_engine", close_engine)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: None)


@pytest.mark.asyncio
async def test_runtime_owns_engine_cleanup_before_initialization(monkeypatch):
    from app.gateway.deps import langgraph_runtime

    events: list[str] = []

    async def fail_engine_init(_database) -> None:
        events.append("engine_init")
        raise RuntimeError("schema bootstrap failed")

    async def close_engine() -> None:
        events.append("engine_close")

    monkeypatch.setattr("deerflow.runtime.make_stream_bridge", lambda _config: _resource(object()))
    monkeypatch.setattr("deerflow.persistence.engine.init_engine_from_config", fail_engine_init)
    monkeypatch.setattr("deerflow.persistence.engine.close_engine", close_engine)

    with pytest.raises(RuntimeError, match="schema bootstrap failed"):
        async with langgraph_runtime(
            FastAPI(),
            SimpleNamespace(database=_database_config()),
        ):
            pytest.fail("runtime must not yield")

    assert events == ["engine_init", "engine_close"]


@pytest.mark.asyncio
async def test_later_startup_failure_stops_same_snapshot_and_appends_diagnostics(monkeypatch):
    import deerflow.extensions as extensions_module
    from app.gateway.deps import langgraph_runtime

    events: list[str] = []

    class _Service:
        def __init__(self, name: str, *, fail_start: bool = False, fail_stop: bool = False) -> None:
            self.name = name
            self.fail_start = fail_start
            self.fail_stop = fail_stop

        async def start(self, _deps) -> None:
            events.append(f"start:{self.name}")
            if self.fail_start:
                raise RuntimeError("start exploded")

        async def stop(self) -> None:
            events.append(f"stop:{self.name}")
            if self.fail_stop:
                raise RuntimeError("stop exploded")

    registry = ExtensionRegistry()
    with registry.attributed_to("bad-start:install"):
        registry.service(_Service("bad-start", fail_start=True))
    with registry.attributed_to("bad-stop:install"):
        registry.service(_Service("bad-stop", fail_stop=True))
    snapshot = registry.build()

    other_registry = ExtensionRegistry()
    with other_registry.attributed_to("other:install"):
        other_registry.service(_Service("other"))
    monkeypatch.setattr(extensions_module, "_loaded", other_registry.build())

    _patch_runtime_resources(monkeypatch, events)
    monkeypatch.setattr(
        "deerflow.persistence.thread_meta.make_thread_store",
        lambda _sf, _store: (_ for _ in ()).throw(RuntimeError("thread store failed")),
    )

    app = FastAPI()
    app.state.extensions = snapshot
    live_diagnostics = initialize_runtime_diagnostics([])
    app.state.extension_diagnostics = live_diagnostics

    with pytest.raises(RuntimeError, match="thread store failed"):
        async with langgraph_runtime(
            app,
            SimpleNamespace(database=_database_config()),
        ):
            pytest.fail("runtime must not yield")

    assert events == [
        "start:bad-start",
        "start:bad-stop",
        "stop:bad-stop",
        "stop:bad-start",
        "engine_close",
    ]
    assert all("other" not in event for event in events)
    assert app.state.extension_diagnostics is live_diagnostics
    assert app.state.extension_diagnostics == get_runtime_diagnostics()
    assert [diagnostic.source for diagnostic in live_diagnostics] == [
        "bad-start:install",
        "bad-stop:install",
    ]


@pytest.mark.asyncio
async def test_cancellation_during_service_start_propagates_after_cleanup(monkeypatch):
    from app.gateway.deps import langgraph_runtime

    events: list[str] = []
    blocking_start_entered = asyncio.Event()

    class _Service:
        def __init__(self, name: str, *, block: bool = False) -> None:
            self.name = name
            self.block = block

        async def start(self, _deps) -> None:
            events.append(f"start:{self.name}")
            if self.block:
                blocking_start_entered.set()
                await asyncio.Event().wait()

        async def stop(self) -> None:
            events.append(f"stop:{self.name}")

    registry = ExtensionRegistry()
    with registry.attributed_to("first:install"):
        registry.service(_Service("first"))
    with registry.attributed_to("blocking:install"):
        registry.service(_Service("blocking", block=True))
    with registry.attributed_to("never-started:install"):
        registry.service(_Service("never-started"))

    _patch_runtime_resources(monkeypatch, events)
    app = FastAPI()
    app.state.extensions = registry.build()

    async def run_runtime() -> None:
        async with langgraph_runtime(
            app,
            SimpleNamespace(database=_database_config()),
        ):
            pytest.fail("runtime must not yield while service start is blocked")

    task = asyncio.create_task(run_runtime())
    await asyncio.wait_for(blocking_start_entered.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == [
        "start:first",
        "start:blocking",
        "stop:blocking",
        "stop:first",
        "engine_close",
    ]
