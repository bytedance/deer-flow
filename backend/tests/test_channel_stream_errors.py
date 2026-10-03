"""Error SSE frames must enter the IM channel's existing failure cleanup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from langgraph_sdk.client import LangGraphClient

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import ChannelStore
from app.gateway.routers import thread_runs
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


@pytest.mark.asyncio
@pytest.mark.parametrize("has_error", [False, True], ids=["success", "error-event"])
@pytest.mark.parametrize("has_partial", [False, True], ids=["empty", "partial-text"])
@pytest.mark.parametrize("has_values", [False, True], ids=["message-stream", "with-values"])
async def test_channel_consumes_error_sse_and_releases_dedupe_after_final_publish(monkeypatch, tmp_path, has_error, has_partial, has_values):
    bridge = MemoryStreamBridge()
    record = RunRecord(
        run_id="stream-run",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.error if has_error else RunStatus.success,
        on_disconnect=DisconnectMode.continue_,
        error="Model failed." if has_error else None,
    )

    async def start_run(*args, **kwargs):
        if has_partial:
            await bridge.publish(record.run_id, "messages-tuple", [{"type": "AIMessageChunk", "id": "answer", "content": "Partial"}, {"langgraph_node": "agent"}])
        if has_values:
            await bridge.publish(record.run_id, "values", {"messages": [{"type": "ai", "content": "Partial"}] if has_partial else []})
        if has_error:
            await bridge.publish(record.run_id, "error", {"error": "RuntimeError", "message": "Model failed."})
        await bridge.publish_end(record.run_id)
        return record

    monkeypatch.setattr(thread_runs, "start_run", start_run)
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.stream_bridge = bridge
    app.state.run_manager = SimpleNamespace(get=AsyncMock(return_value=record))
    bus = MessageBus()
    manager = ChannelManager(bus=bus, store=ChannelStore(path=tmp_path / "channels.json"))
    inbound = InboundMessage(channel_name="feishu", chat_id="chat-1", user_id="user-1", text="Hello", metadata={"message_id": "message-1"})
    assert await manager._is_duplicate_inbound(inbound) is False
    outbound = []
    deduped_during_final = []

    async def capture(message):
        outbound.append(message)
        if message.is_final:
            deduped_during_final.append(await manager._is_duplicate_inbound(inbound))

    bus.subscribe_outbound(capture)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api") as http:
        await manager._handle_streaming_chat(
            LangGraphClient(http),
            inbound,
            "thread-1",
            "lead_agent",
            {},
            {},
            {"role": "user", "content": "Hello"},
        )

    final = outbound[-1]
    assert final.is_final
    if has_partial:
        # Preserve the same partial-text behavior as a transport exception.
        assert final.text == "Partial"
    elif has_error:
        assert final.text == "An error occurred while processing your request. Please try again."
    else:
        assert final.text == "(No response from agent)"
    assert deduped_during_final == [True]
    assert await manager._is_duplicate_inbound(inbound) is (not has_error)
