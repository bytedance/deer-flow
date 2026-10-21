"""Stateless waits must expose the current run error, not an earlier checkpoint."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app
from langgraph_sdk.client import LangGraphClient

from app.gateway.routers import runs
from deerflow.runtime import DisconnectMode, RunStatus
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


@pytest_asyncio.fixture
async def stateless_wait_client(monkeypatch):
    bridge = MemoryStreamBridge()
    run_manager = RunManager()
    record = await run_manager.create(
        "thread-1",
        "lead_agent",
        on_disconnect=DisconnectMode.continue_,
    )
    snapshot = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "old-checkpoint"}},
        values={"messages": [{"type": "ai", "content": "Historical answer."}]},
    )
    accessor = SimpleNamespace(aget=AsyncMock(return_value=snapshot))
    state = SimpleNamespace(
        terminal_status=RunStatus.success,
        terminal_error=None,
    )

    async def start_run(*args, **kwargs):
        async def finish_run():
            await run_manager.try_start(record.run_id)
            await run_manager.set_status(
                record.run_id,
                state.terminal_status,
                error=state.terminal_error,
                persist=False,
            )
            await bridge.publish_end(record.run_id)

        record.task = asyncio.create_task(finish_run())
        return record

    monkeypatch.setattr(runs, "start_run", start_run)
    monkeypatch.setattr(runs, "abuild_checkpoint_state_accessor", AsyncMock(return_value=(accessor, {})))
    app = make_authed_test_app()
    app.include_router(runs.router)
    app.state.stream_bridge = bridge
    app.state.run_manager = run_manager

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api") as http:
        state.client = LangGraphClient(http)
        state.record = record
        state.run_manager = run_manager
        state.snapshot = snapshot
        state.accessor = accessor
        yield state

    if record.task is not None:
        await record.task


@pytest.mark.asyncio
@pytest.mark.parametrize("has_checkpoint", [False, True], ids=["no-checkpoint", "old-checkpoint"])
async def test_failed_stateless_wait_raises_through_real_sdk_and_skips_checkpoint(stateless_wait_client, has_checkpoint):
    state = stateless_wait_client
    state.terminal_status = RunStatus.error
    state.terminal_error = "Current model initialization failed."
    if not has_checkpoint:
        state.snapshot.config = {}

    response = await state.client.runs.wait(
        None,
        "lead_agent",
        input={"messages": []},
        config={"configurable": {"thread_id": "thread-1"}},
        raise_error=False,
    )

    assert "messages" not in response
    assert response["status"] == "error"
    assert response["error"] == state.terminal_error
    assert response["__error__"]["message"] == state.terminal_error
    manager_record = await state.run_manager.get(state.record.run_id)
    assert manager_record is state.record
    assert manager_record.status == RunStatus.error
    assert manager_record.error == state.terminal_error

    # The SDK only raises for its __error__ envelope, so check the stock path too.
    with pytest.raises(Exception, match="Current model initialization failed"):
        await state.client.runs.wait(
            None,
            "lead_agent",
            input={"messages": []},
            config={"configurable": {"thread_id": "thread-1"}},
        )
    state.accessor.aget.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_stateless_wait_preserves_final_checkpoint_state(stateless_wait_client):
    state = stateless_wait_client
    state.snapshot.values = {"messages": [{"type": "ai", "content": "Current answer."}]}

    response = await state.client.runs.wait(
        None,
        "lead_agent",
        input={"messages": []},
        config={"configurable": {"thread_id": "thread-1"}},
    )

    assert response["messages"][0]["content"] == "Current answer."
    assert state.record.status == RunStatus.success
    state.accessor.aget.assert_awaited_once()
