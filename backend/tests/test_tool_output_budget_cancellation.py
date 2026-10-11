from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares import tool_output_budget_middleware as module
from deerflow.config.tool_output_config import ToolOutputConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellations", [1, 3])
@pytest.mark.parametrize("command_result", [False, True])
async def test_cancelled_tool_output_externalization_finishes_before_owner_exits(monkeypatch, cancellations, command_result):
    loop = asyncio.get_running_loop()
    writing = asyncio.Event()
    finished = asyncio.Event()
    allow_write = threading.Event()
    owner_released = asyncio.Event()
    late_operations = []

    class Sandbox:
        def execute_command(self, command):
            late_operations.append(owner_released.is_set())
            return "OK"

        def write_file(self, path, content):
            loop.call_soon_threadsafe(writing.set)
            assert allow_write.wait(timeout=5), "test did not release sandbox write"
            late_operations.append(owner_released.is_set())
            loop.call_soon_threadsafe(finished.set)

    sandbox = Sandbox()
    provider = SimpleNamespace(uses_thread_data_mounts=False, get=lambda _: sandbox)
    monkeypatch.setattr(module, "get_sandbox_provider", lambda: provider)
    middleware = module.ToolOutputBudgetMiddleware(ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10))
    request = SimpleNamespace(tool_call={"name": "bash", "id": "call-1"}, runtime=SimpleNamespace(state={"sandbox": {"sandbox_id": "sandbox-1"}}))
    message = ToolMessage(content="x" * 500, name="bash", tool_call_id="call-1")

    async def handler(_request):
        return Command(update={"messages": [message]}) if command_result else message

    async def execution_owner():
        try:
            await middleware.awrap_tool_call(request, handler)
        finally:
            # Mirrors the enclosing execution lease's finally boundary.
            owner_released.set()

    task = asyncio.create_task(execution_owner())
    try:
        await asyncio.wait_for(writing.wait(), timeout=2)
        task.cancel("first cancellation")
        await asyncio.sleep(0)
        for _ in range(cancellations - 1):
            task.cancel("repeated cancellation")
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done(), "tool hook abandoned its persistence worker"
        assert not owner_released.is_set(), "execution owner exited while sandbox I/O was active"
        allow_write.set()
        with pytest.raises(asyncio.CancelledError, match="first cancellation"):
            await task
        assert finished.is_set()
        assert owner_released.is_set()
        assert late_operations == [False, False, False]
    finally:
        allow_write.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(finished.wait(), timeout=2)
