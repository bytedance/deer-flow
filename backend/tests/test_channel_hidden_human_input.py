"""Hidden user answers form turn boundaries; internal control messages do not."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.manager import ChannelManager, _extract_artifacts, _extract_response_text
from app.channels.message_bus import HUMAN_INPUT_RESPONSE_METADATA_KEY, InboundMessage, MessageBus
from app.channels.store import JsonChannelStore


def _hidden_answer() -> dict:
    return {
        "type": "human",
        "content": "Alpha",
        "additional_kwargs": {
            "hide_from_ui": True,
            "human_input_response": {
                "version": 1,
                "kind": "human_input_response",
                "source": "ask_clarification",
                "request_id": "clarification:call-1",
                "response_kind": "option",
                "option_id": "alpha",
                "value": "Alpha",
            },
        },
    }


def test_hidden_answer_stops_previous_clarification_text():
    result = {
        "messages": [
            {"type": "human", "content": "Original question"},
            {"type": "tool", "name": "ask_clarification", "content": "Pick one"},
            _hidden_answer(),
        ]
    }

    assert _extract_response_text(result) == ""


def _file_response(content: str, path: str) -> dict:
    return {"type": "ai", "content": content, "tool_calls": [{"name": "present_files", "args": {"filepaths": [path]}}]}


@pytest.mark.parametrize("response_kind", ["option", "text"])
def test_hidden_answer_stops_previous_response_and_artifacts(response_kind):
    answer = _hidden_answer()
    response = answer["additional_kwargs"][HUMAN_INPUT_RESPONSE_METADATA_KEY]
    response["response_kind"] = response_kind
    if response_kind == "text":
        response.pop("option_id")
    result = {"messages": [{"type": "human", "content": "Original question"}, _file_response("Previous answer", "/old.txt"), answer], "artifacts": ["/old.txt"]}

    assert _extract_response_text(result) == ""
    assert _extract_artifacts(result) == []


def test_hidden_answer_keeps_current_response_and_artifacts():
    result = {
        "messages": [
            {"type": "human", "content": "Original question"},
            _file_response("Previous answer", "/old.txt"),
            _hidden_answer(),
            _file_response("Current answer", "/new.txt"),
            {"type": "human", "content": "Internal context", "additional_kwargs": {"hide_from_ui": True}},
        ]
    }

    assert _extract_response_text(result) == "Current answer"
    assert _extract_artifacts(result) == ["/new.txt"]


@pytest.mark.parametrize("invalid_response", [None, {}, "invalid", {"version": 2}, {"option_id": ""}, {"value": " "}])
def test_invalid_hidden_answer_remains_a_control_message(invalid_response):
    hidden = _hidden_answer()
    if invalid_response is None:
        hidden["additional_kwargs"].pop(HUMAN_INPUT_RESPONSE_METADATA_KEY)
    elif isinstance(invalid_response, dict):
        hidden["additional_kwargs"][HUMAN_INPUT_RESPONSE_METADATA_KEY].update(invalid_response)
        if not invalid_response:
            hidden["additional_kwargs"][HUMAN_INPUT_RESPONSE_METADATA_KEY] = {}
    else:
        hidden["additional_kwargs"][HUMAN_INPUT_RESPONSE_METADATA_KEY] = invalid_response
    result = {"messages": [{"type": "human", "content": "Current question"}, _file_response("Current answer", "/current.txt"), hidden]}

    assert _extract_response_text(result) == "Current answer"
    assert _extract_artifacts(result) == ["/current.txt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_card_answer_without_fresh_ai_preserves_terminal_result(tmp_path, monkeypatch, failed):
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    bus = MessageBus()
    store = JsonChannelStore(path=tmp_path / "routing.json")
    await store.set_thread_id("feishu", "chat-1", "thread-1", topic_id="topic-1")
    manager = ChannelManager(bus=bus, store=store)
    inbound = InboundMessage(
        channel_name="feishu", chat_id="chat-1", user_id="ou-originator", topic_id="topic-1", text="Alpha", metadata={HUMAN_INPUT_RESPONSE_METADATA_KEY: _hidden_answer()["additional_kwargs"][HUMAN_INPUT_RESPONSE_METADATA_KEY]}
    )
    client = MagicMock()
    client.threads.get = AsyncMock(return_value={"thread_id": "thread-1"})
    client.threads.update = AsyncMock(return_value={"thread_id": "thread-1"})

    async def stream(*args, **kwargs):
        answer = dict(kwargs["input"]["messages"][0], type="human")
        yield SimpleNamespace(
            event="values",
            data={"messages": [{"type": "human", "content": "Original question"}, _file_response("Previous answer", "/old.txt"), {"type": "tool", "name": "ask_clarification", "content": "Pick one"}, answer], "artifacts": ["/old.txt"]},
        )
        if failed:
            yield SimpleNamespace(event="error", data={"name": "ModelError", "message": "offline failure"})

    client.runs.stream = MagicMock(side_effect=stream)
    manager._client = client
    outbound = []

    async def capture(message):
        outbound.append(message)

    bus.subscribe_outbound(capture)
    await manager._handle_chat(inbound)

    assert len(outbound) == 1
    assert outbound[0].is_final is True
    assert outbound[0].text == ("An error occurred while processing your request. Please try again." if failed else "(No response from agent)")
    assert outbound[0].artifacts == []
    assert outbound[0].attachments == []
