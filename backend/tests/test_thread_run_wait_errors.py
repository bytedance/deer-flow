"""Failed waits must expose the current error instead of historical answers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app
from langgraph_sdk.client import LangGraphClient

from app.gateway.routers import thread_runs
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


@pytest_asyncio.fixture
async def wait_client(monkeypatch):
    bridge = MemoryStreamBridge()
    record = RunRecord(
        run_id="current-run",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
    )
    snapshot = SimpleNamespace(
        config={"configurable": {"checkpoint_id": "old-checkpoint"}},
        values={"messages": [{"type": "ai", "content": "Historical answer."}]},
    )
    accessor = SimpleNamespace(aget=AsyncMock(return_value=snapshot))

    async def start_run(*args, **kwargs):
        # Keep a local task so the real wait helper consumes the bridge's END.
        record.task = asyncio.create_task(asyncio.sleep(0))
        await bridge.publish_end(record.run_id)
        return record

    monkeypatch.setattr(thread_runs, "start_run", start_run)
    monkeypatch.setattr(thread_runs, "abuild_checkpoint_state_accessor", AsyncMock(return_value=(accessor, {})))
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.stream_bridge = bridge
    app.state.run_manager = SimpleNamespace(get=AsyncMock(return_value=record))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api") as http:
        yield SimpleNamespace(client=LangGraphClient(http), http=http, record=record, snapshot=snapshot, accessor=accessor)
    if record.task is not None:
        await record.task


@pytest.mark.asyncio
@pytest.mark.parametrize("reused", [False, True], ids=["created", "reused"])
@pytest.mark.parametrize("has_checkpoint", [False, True], ids=["no-checkpoint", "old-checkpoint"])
async def test_failed_wait_raises_through_real_sdk_without_reading_thread_head(wait_client, reused, has_checkpoint):
    state = wait_client
    state.record.status = RunStatus.error
    state.record.error = "Current model initialization failed."
    state.record.idempotency_reused = reused
    if not has_checkpoint:
        state.snapshot.config = {}

    response = await state.client.runs.wait("thread-1", "lead_agent", input={"messages": []}, raise_error=False)
    assert "messages" not in response
    assert response["status"] == "error"
    assert response["error"] == state.record.error
    assert response["__error__"]["message"] == state.record.error

    # The stock SDK raises only for its __error__ envelope, not flat
    # status/error responses. Drive it through the actual FastAPI wait route.
    with pytest.raises(Exception, match="Current model initialization failed"):
        await state.client.runs.wait("thread-1", "lead_agent", input={"messages": []})
    state.accessor.aget.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reused", [False, True], ids=["created", "reused"])
async def test_successful_wait_preserves_checkpoint_and_reused_status_contract(wait_client, reused):
    state = wait_client
    state.record.idempotency_reused = reused
    state.snapshot.values = {"messages": [{"type": "ai", "content": "Current answer."}]}
    response = await state.client.runs.wait("thread-1", "lead_agent", input={"messages": []})
    if reused:
        assert response == {"status": "success", "error": None}
        state.accessor.aget.assert_not_awaited()
    else:
        assert response["messages"][0]["content"] == "Current answer."
        state.accessor.aget.assert_awaited_once()
