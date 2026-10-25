"""Gateway owns sandbox cleanup even when lazy creation cannot bind signals."""

import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
