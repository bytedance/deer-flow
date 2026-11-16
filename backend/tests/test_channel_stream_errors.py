"""Error SSE frames must enter the IM channel's existing failure cleanup."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from langgraph_sdk.client import LangGraphClient

from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import JsonChannelStore
from app.gateway.routers import thread_runs
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_error, error_payload",
    [
        (False, None),
        (True, {"name": "RuntimeError", "message": "Model failed."}),
        (True, None),
        (True, {"name": "ConflictError", "message": "Thread already running a task."}),
    ],
    ids=["success", "error-event", "empty-error-event", "busy-error-event"],
)
@pytest.mark.parametrize("has_partial", [False, True], ids=["empty", "partial-text"])
@pytest.mark.parametrize("has_values", [False, True], ids=["message-stream", "with-values"])
async def test_channel_consumes_error_sse_and_releases_dedupe_after_final_publish(monkeypatch, tmp_path, caplog, has_error, error_payload, has_partial, has_values):
    caplog.set_level(logging.WARNING, logger="app.channels.manager")
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
            await bridge.publish(record.run_id, "error", error_payload)
        await bridge.publish_end(record.run_id)
        return record

    monkeypatch.setattr(thread_runs, "start_run", start_run)
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.stream_bridge = bridge
    app.state.run_manager = SimpleNamespace(get=AsyncMock(return_value=record))
    bus = MessageBus()
    manager = ChannelManager(bus=bus, store=JsonChannelStore(path=tmp_path / "channels.json"))
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

    error_logs = [record for record in caplog.records if record.name == "app.channels.manager" and "stream error frame:" in record.getMessage()]
    assert len(error_logs) == int(has_error)
    if has_error:
        assert error_logs[0].levelno == logging.WARNING
        logged = error_logs[0].getMessage()
        assert "thread_id=thread-1" in logged
        if isinstance(error_payload, dict):
            assert error_payload["name"] in logged
            assert error_payload["message"] in logged
        else:
            assert "Error" in logged
            assert "unknown" in logged


_STEP_LIMIT_TEXT = "The run stopped at its step limit (recursion_limit=6) before finishing. Created but not presented: /mnt/user-data/outputs/report.md. Send a message to continue."


@pytest.mark.asyncio
@pytest.mark.parametrize("has_partial", [False, True], ids=["empty", "partial-text"])
async def test_channel_reports_a_step_limit_stop_instead_of_a_generic_failure(monkeypatch, tmp_path, has_partial):
    bridge = MemoryStreamBridge()
    record = RunRecord(
        run_id="stream-run",
        thread_id="thread-1",
        assistant_id=None,
        status=RunStatus.error,
        on_disconnect=DisconnectMode.continue_,
        error=_STEP_LIMIT_TEXT,
        stop_reason="recursion_capped",
    )

    async def start_run(*args, **kwargs):
        messages = [{"type": "ai", "content": "Writing the report.", "tool_calls": [{"id": "w-1", "name": "write_file", "args": {}}]}] if has_partial else []
        await bridge.publish(record.run_id, "values", {"messages": messages})
        await bridge.publish(record.run_id, "error", {"name": "GraphRecursionError", "message": _STEP_LIMIT_TEXT})
        await bridge.publish_end(record.run_id)
        return record

    monkeypatch.setattr(thread_runs, "start_run", start_run)
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.stream_bridge = bridge
    app.state.run_manager = SimpleNamespace(get=AsyncMock(return_value=record))
    bus = MessageBus()
    manager = ChannelManager(bus=bus, store=JsonChannelStore(path=tmp_path / "channels.json"))
    inbound = InboundMessage(channel_name="feishu", chat_id="chat-1", user_id="user-1", text="Write the report", metadata={"message_id": "message-1"})
    assert await manager._is_duplicate_inbound(inbound) is False
    outbound = []
    bus.subscribe_outbound(outbound.append)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api") as http:
        await manager._handle_streaming_chat(LangGraphClient(http), inbound, "thread-1", "lead_agent", {}, {}, {"role": "user", "content": "Write the report"})

    final = outbound[-1]
    assert final.is_final
    # The narration stays; the stop replaces the generic failure.
    assert final.text == (f"Writing the report.\n\n{_STEP_LIMIT_TEXT}" if has_partial else _STEP_LIMIT_TEXT)
    # The run ended, so a redelivery may retry it, as after any error frame.
    assert await manager._is_duplicate_inbound(inbound) is False
