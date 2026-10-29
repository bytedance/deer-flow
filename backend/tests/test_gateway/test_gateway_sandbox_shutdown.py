"""Gateway owns sandbox cleanup even when lazy creation cannot bind signals."""

import asyncio
import importlib
import signal
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest


def _runtime(monkeypatch, events):
    @asynccontextmanager
    async def runtime(_app, _config):
        try:
            yield
        finally:
            events.append("runtime_drained")

    monkeypatch.setattr("app.gateway.app.langgraph_runtime", runtime)
    pool = SimpleNamespace(close_all=AsyncMock(side_effect=lambda: events.append("mcp_closed")))
    monkeypatch.setattr("deerflow.mcp.session_pool.get_session_pool", lambda: pool)
    return pool


def test_shutdown_closes_provider_created_by_lazy_first_write_after_run_drain(monkeypatch):
    from app.gateway.app import _runtime_with_mcp_pool_shutdown
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
    from deerflow.runtime import RunManager, RunStatus
    from deerflow.sandbox import sandbox_provider as registry

    async def scenario():
        events = []
        loop_thread = threading.get_ident()

        class Provider:
            def __init__(self):
                self.created_thread = threading.get_ident()
                self.closed = False

            def shutdown(self):
                assert threading.get_ident() != loop_thread
                events.append("sandbox_closed")
                self.closed = True

        monkeypatch.setattr(registry, "_default_sandbox_provider", None)
        monkeypatch.setattr(registry, "get_app_config", lambda: SimpleNamespace(sandbox=SimpleNamespace(use="fixture:Provider")))
        monkeypatch.setattr(registry, "resolve_class", lambda *_args: Provider)
        pool = _runtime(monkeypatch, events)
        manager = RunManager()
        record = await manager.create("lazy-first-write")
        await manager.set_status(record.run_id, RunStatus.running)
        resume = asyncio.Event()
        first_write_finished = asyncio.Event()
        created = []

        def read_new_file(_runtime, _path):
            created.append(registry.get_sandbox_provider())
            raise FileNotFoundError("new output")

        middleware = ReadBeforeWriteMiddleware(content_reader=read_new_file)
        state = {"messages": []}
        runtime = SimpleNamespace(state=state, context={"thread_id": "lazy-first-write"})
        call = ToolCallRequest(tool_call={"name": "write_file", "args": {"path": "/mnt/user-data/outputs/new.txt", "content": "new"}, "id": "write"}, tool=None, state=state, runtime=runtime)

        async def write(_request):
            return ToolMessage(content="OK", tool_call_id="write", name="write_file")

        async def active_run():
            await resume.wait()
            await middleware.awrap_tool_call(call, write)
            first_write_finished.set()
            await asyncio.Event().wait()

        @asynccontextmanager
        async def draining_runtime(_app, _config):
            record.task = asyncio.create_task(active_run())
            try:
                yield
            finally:
                resume.set()
                await asyncio.wait_for(first_write_finished.wait(), timeout=1)
                await manager.shutdown(timeout=1.0)
                events.append("runtime_drained")

        monkeypatch.setattr("app.gateway.app.langgraph_runtime", draining_runtime)
        try:
            async with _runtime_with_mcp_pool_shutdown(FastAPI(), SimpleNamespace()):
                assert registry.get_initialized_sandbox_provider() is None
            assert record.task.done()
            assert len(created) == 1 and created[0].created_thread != loop_thread
            assert created[0].closed
            assert registry.get_initialized_sandbox_provider() is None
            assert events == ["runtime_drained", "mcp_closed", "sandbox_closed"]
            pool.close_all.assert_awaited_once()
        finally:
            resume.set()
            if record.task is not None and not record.task.done():
                record.task.cancel()
                await asyncio.gather(record.task, return_exceptions=True)

    asyncio.run(scenario())


def test_shutdown_without_provider_does_not_allocate_one(monkeypatch):
    from app.gateway.app import _runtime_with_mcp_pool_shutdown
    from deerflow.sandbox import sandbox_provider as registry

    async def scenario():
        events = []
        monkeypatch.setattr(registry, "_default_sandbox_provider", None)
        monkeypatch.setattr(registry, "resolve_class", lambda *_args: pytest.fail("shutdown allocated a sandbox provider"))
        _runtime(monkeypatch, events)
        async with _runtime_with_mcp_pool_shutdown(FastAPI(), SimpleNamespace()):
            assert registry.get_initialized_sandbox_provider() is None
        assert registry.get_initialized_sandbox_provider() is None
        assert events == ["runtime_drained", "mcp_closed"]

    asyncio.run(scenario())


def test_sandbox_shutdown_failure_is_logged_and_remains_retryable(monkeypatch, caplog):
    from app.gateway.app import _runtime_with_mcp_pool_shutdown
    from deerflow.sandbox import sandbox_provider as registry

    async def scenario():
        events = []
        pool = _runtime(monkeypatch, events)

        def fail_close():
            raise RuntimeError("sandbox close failed")

        provider = SimpleNamespace(shutdown=fail_close)
        monkeypatch.setattr(registry, "_default_sandbox_provider", provider)
        async with _runtime_with_mcp_pool_shutdown(FastAPI(), SimpleNamespace()):
            pass
        assert registry.get_initialized_sandbox_provider() is provider
        assert "Failed to shut down sandbox provider" in caplog.text
        pool.close_all.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_during", ["mcp", "sandbox"])
def test_shutdown_drains_sandbox_worker_across_cancellation(monkeypatch, cancel_during):
    from app.gateway.app import _runtime_with_mcp_pool_shutdown
    from deerflow.sandbox import sandbox_provider as registry

    async def scenario():
        events = []
        _runtime(monkeypatch, events)
        pool_started = asyncio.Event()
        worker_started = threading.Event()
        release_worker = threading.Event()
        worker_finished = threading.Event()
        loop_thread = threading.get_ident()

        async def close_pool():
            events.append("mcp_close_started")
            pool_started.set()
            if cancel_during == "mcp":
                await asyncio.Event().wait()

        def close_sandbox():
            assert threading.get_ident() != loop_thread
            worker_started.set()
            assert release_worker.wait(5.0)
            worker_finished.set()

        monkeypatch.setattr("deerflow.mcp.session_pool.get_session_pool", lambda: SimpleNamespace(close_all=close_pool))
        monkeypatch.setattr(registry, "_default_sandbox_provider", SimpleNamespace(shutdown=close_sandbox))
        context = _runtime_with_mcp_pool_shutdown(FastAPI(), SimpleNamespace())
        await context.__aenter__()
        task = asyncio.create_task(context.__aexit__(None, None, None))
        try:
            await asyncio.wait_for(pool_started.wait(), timeout=1)
            if cancel_during == "mcp":
                task.cancel()
            assert await asyncio.to_thread(worker_started.wait, 1.0)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done(), "shutdown abandoned the sandbox worker"
            release_worker.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert worker_finished.is_set()
            assert registry.get_initialized_sandbox_provider() is None
        finally:
            release_worker.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.fixture
def restore_signal_handlers():
    signums = [signal.SIGTERM, signal.SIGINT] + ([signal.SIGHUP] if hasattr(signal, "SIGHUP") else [])
    saved = {signum: signal.getsignal(signum) for signum in signums}
    try:
        yield
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, handler)


def _build_aio_provider(monkeypatch, backend, sandbox_ids):
    """Run the real AIO constructor (signal registration included) over a fake backend."""
    from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    config = {"replicas": 10, "idle_timeout": 0, "ownership": None, "stream_bridge": None, "command_timeout": 600.0}
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_load_config", lambda _self: config)
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_create_backend", lambda _self: backend)
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_reconcile_orphans", lambda _self: None)
    provider = aio_mod.AioSandboxProvider()
    for sandbox_id in sandbox_ids:
        sandbox = MagicMock(id=sandbox_id, requires_container_recycle=False, has_pending_session_creates=False)
        with provider._lock:
            provider._sandbox_infos[sandbox_id] = SandboxInfo(sandbox_id=sandbox_id, sandbox_url=f"http://fake/{sandbox_id}")
            provider._sandboxes[sandbox_id] = sandbox
            provider._last_activity[sandbox_id] = time.monotonic()
    return provider


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_stop_signal_with_main_thread_provider_destroys_sandboxes_only_after_run_drain(monkeypatch, restore_signal_handlers, signum):
    """G6/S0: a provider built on the event-loop thread must not tear down from its signal handler."""
    from app.gateway.app import _runtime_with_mcp_pool_shutdown
    from deerflow.sandbox import sandbox_provider as registry

    sandbox_ids = ["sbx-0", "sbx-1", "sbx-2"]
    events = []

    class Backend:
        def destroy(self, info):
            events.append(f"destroy:{info.sandbox_id}")

        def list_running(self):
            return []

    def uvicorn_handle_exit(received, _frame):
        events.append(f"handle_exit:{signal.Signals(received).name}")

    # uvicorn installs its handlers before lifespan startup builds anything.
    signal.signal(signal.SIGTERM, uvicorn_handle_exit)
    signal.signal(signal.SIGINT, uvicorn_handle_exit)
    monkeypatch.setattr(registry, "_default_sandbox_provider", None)
    pool = _runtime(monkeypatch, events)

    async def scenario():
        provider = None
        with registry.hold_sandbox_shutdown_ownership():
            try:
                provider = _build_aio_provider(monkeypatch, Backend(), sandbox_ids)
                assert threading.current_thread() is threading.main_thread()
                registry.set_sandbox_provider(provider)

                @asynccontextmanager
                async def draining_runtime(_app, _config):
                    try:
                        yield
                    finally:
                        # The in-flight run still reaches its sandbox while it drains.
                        events.append("runtime_drained" if provider.get("sbx-0") is not None else "runtime_drained_without_sandbox")

                monkeypatch.setattr("app.gateway.app.langgraph_runtime", draining_runtime)
                async with _runtime_with_mcp_pool_shutdown(FastAPI(), SimpleNamespace()):
                    signal.raise_signal(signum)
                    await asyncio.sleep(0)
                    assert events == [f"handle_exit:{signal.Signals(signum).name}"]
            finally:
                if provider is not None:
                    provider.shutdown()

        assert events[:3] == [f"handle_exit:{signal.Signals(signum).name}", "runtime_drained", "mcp_closed"]
        assert sorted(events[3:]) == [f"destroy:{sandbox_id}" for sandbox_id in sandbox_ids]
        assert registry.get_initialized_sandbox_provider() is None
        pool.close_all.assert_awaited_once()

    asyncio.run(scenario())


def test_gateway_lifespan_owns_sandbox_shutdown_from_its_first_step(monkeypatch):
    """The declaration must precede every startup step that can build a provider."""
    from app.gateway import app as gateway_app
    from deerflow.sandbox import sandbox_provider as registry

    observed = []

    def failing_config():
        observed.append(registry.host_owns_sandbox_shutdown())
        raise RuntimeError("stop startup here")

    monkeypatch.setattr(gateway_app, "get_app_config", failing_config)

    async def scenario():
        assert registry.host_owns_sandbox_shutdown() is False
        with pytest.raises(RuntimeError, match="stop startup here"):
            async with gateway_app.lifespan(FastAPI()):
                pytest.fail("startup should have failed")
        assert observed == [True]
        assert registry.host_owns_sandbox_shutdown() is False

    asyncio.run(scenario())
