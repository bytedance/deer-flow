"""Unit tests for ModelLengthFinishReasonMiddleware."""

import logging
from unittest.mock import MagicMock

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from deerflow.agents.middlewares.model_length_finish_reason_middleware import (
    MODEL_LENGTH_CAPPED_STOP_REASON,
    ModelLengthFinishReasonMiddleware,
)

_MW_LOGGER = "deerflow.agents.middlewares.model_length_finish_reason_middleware"


def _runtime(run_id: str = "run-1"):
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread-1", "run_id": run_id}
    return runtime


def test_finish_reason_length_records_stop_reason_without_rewriting_textual_tool_call():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content=('<tool_call><invoke name="write_file"><path>/mnt/user-data/outputs/report.md</path><content># partial'),
        tool_calls=[],
        invalid_tool_calls=[],
        response_metadata={"finish_reason": "length"},
    )

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is None
    assert runtime.context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON
    assert msg.content.startswith('<tool_call><invoke name="write_file">')
    assert msg.tool_calls == []
    assert msg.invalid_tool_calls == []


def test_finish_reason_stop_with_tool_call_example_in_prose_passes_through():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content=('Here is an example, not a real tool call:\n\n```xml\n<tool_call><invoke name="write_file"></invoke></tool_call>\n```'),
        response_metadata={"finish_reason": "stop"},
    )

    assert mw._apply({"messages": [msg]}, runtime) is None
    assert "stop_reason" not in runtime.context


def test_additional_kwargs_finish_reason_length_records_stop_reason():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content="partial",
        additional_kwargs={"finish_reason": "length"},
    )

    assert mw._apply({"messages": [msg]}, runtime) is None
    assert runtime.context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON


def test_gemini_max_tokens_finish_reason_records_stop_reason():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content="partial",
        response_metadata={"finish_reason": "MAX_TOKENS"},
    )

    assert mw._apply({"messages": [msg]}, runtime) is None
    assert runtime.context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON


def test_anthropic_max_tokens_stop_reason_records_stop_reason():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content="partial",
        response_metadata={"stop_reason": "max_tokens"},
    )

    assert mw._apply({"messages": [msg]}, runtime) is None
    assert runtime.context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON


def test_length_cap_detection_logs_observability_fields(caplog):
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime(run_id="run-observe")
    msg = AIMessage(
        id="msg-1",
        content="partial",
        response_metadata={"finish_reason": "length"},
    )

    with caplog.at_level(logging.INFO, logger=_MW_LOGGER):
        assert mw._apply({"messages": [msg]}, runtime) is None

    records = [record for record in caplog.records if record.message == "Provider model length cap detected"]
    assert len(records) == 1
    record = records[0]
    assert record.thread_id == "thread-1"
    assert record.run_id == "run-observe"
    assert record.message_id == "msg-1"
    assert record.detector == "openai_compatible_length"
    assert record.reason_field == "finish_reason"
    assert record.reason_value == "length"
    assert record.stamped_stop_reason is True


def test_finish_reason_length_drops_potentially_truncated_tool_calls():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content=[
            {"type": "text", "text": "partial answer"},
            {
                "type": "tool_use",
                "id": "call_write_1",
                "name": "write_file",
                "input": {"path": "/mnt/user-data/outputs/report.md"},
            },
        ],
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "call_write_1",
                    "type": "function",
                    "function": {"name": "write_file", "arguments": '{"path":"/tmp/report.md"'},
                }
            ]
        },
        tool_calls=[
            {
                "id": "call_write_1",
                "name": "write_file",
                "args": {"path": "/mnt/user-data/outputs/report.md", "content": "# partial"},
            }
        ],
        response_metadata={"finish_reason": "length"},
    )

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    replacement = result["messages"][0]
    assert replacement.tool_calls == []
    assert replacement.invalid_tool_calls == []
    assert replacement.content[0] == {"type": "text", "text": "partial answer"}
    assert "output limit" in replacement.content[-1]["text"]
    assert "tool_calls" not in replacement.additional_kwargs
    assert replacement.additional_kwargs["model_length_termination"]["suppressed_tool_call_count"] == 1
    assert replacement.additional_kwargs["model_length_termination"]["suppressed_tool_call_names"] == ["write_file"]
    assert runtime.context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON


def test_anthropic_content_only_tool_use_is_removed_before_next_request():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content=[
            {
                "type": "tool_use",
                "id": "call_write_1",
                "name": "write_file",
                "input": {"path": "/mnt/user-data/outputs/report.md"},
            }
        ],
        response_metadata={"stop_reason": "max_tokens"},
    )

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    replacement = result["messages"][0]
    assert all(block.get("type") != "tool_use" for block in replacement.content)
    metadata = replacement.additional_kwargs["model_length_termination"]
    assert metadata["suppressed_tool_call_count"] == 1
    assert metadata["suppressed_tool_call_names"] == ["write_file"]
    assert msg.content[0]["type"] == "tool_use"

    messages = [HumanMessage("write a report"), replacement, HumanMessage("continue")]
    repaired = DanglingToolCallMiddleware()._build_patched_messages(messages) or messages
    payload = ChatAnthropic(model="claude-sonnet-4-5", api_key="test")._get_request_payload(repaired)
    assistant_message = next(item for item in payload["messages"] if item["role"] == "assistant")
    assert all(block.get("type") != "tool_use" for block in assistant_message["content"])


def test_anthropic_thinking_is_preserved_when_native_tool_use_is_removed():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    thinking_block = {
        "type": "thinking",
        "thinking": "Need to write the file.",
        "signature": "signed",
    }
    msg = AIMessage(
        content=[
            thinking_block,
            {
                "type": "tool_use",
                "id": "call_write_1",
                "name": "write_file",
                "input": {"path": "/mnt/user-data/outputs/report.md"},
            },
        ],
        response_metadata={"stop_reason": "max_tokens"},
    )

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    content = result["messages"][0].content
    assert thinking_block in content
    assert all(block.get("type") != "tool_use" for block in content)
    assert content[-1]["type"] == "text"
    assert "output limit" in content[-1]["text"]


def test_suppressed_tool_call_with_string_fragment_appends_notice():
    """Reproduces the incident: string content fragment + suppressed tool call
    at length cap -> notice is appended alongside the fragment."""
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content="nit",
        tool_calls=[
            {
                "name": "write_file",
                "id": "call_truncated",
                "args": {"path": "/mnt/user-data/outputs/report.md", "content": "# Deep Research\n| ext4 | jbd2 | Every 5s |"},
            }
        ],
        response_metadata={"finish_reason": "length", "model_name": "deepseek-v4-pro"},
    )

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    replacement = result["messages"][0]
    assert replacement.tool_calls == []
    assert "output limit" in replacement.content
    assert "nit" in replacement.content
    assert replacement.additional_kwargs["model_length_termination"]["suppressed_tool_call_names"] == ["write_file"]
    assert runtime.context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON


def test_finish_reason_length_suppresses_complete_tool_call_as_safety_policy():
    """Even parsed arguments cannot be proven complete after a length cap."""
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_write_complete",
                "name": "write_file",
                "args": {"path": "/mnt/user-data/outputs/report.md", "content": "complete"},
            }
        ],
        response_metadata={"finish_reason": "length"},
    )

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    replacement = result["messages"][0]
    assert replacement.tool_calls == []
    assert replacement.additional_kwargs["model_length_termination"]["suppressed_tool_call_names"] == ["write_file"]
    assert "output limit" in str(replacement.content)


def test_empty_finish_reason_length_gets_visible_capped_message():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(content="", response_metadata={"finish_reason": "length"})

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    replacement = result["messages"][0]
    assert "output limit" in replacement.content
    assert replacement.response_metadata["finish_reason"] == "length"
    assert runtime.context["stop_reason"] == MODEL_LENGTH_CAPPED_STOP_REASON


def test_reasoning_only_length_preserves_reasoning_when_adding_visible_message():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "internal reasoning"},
        response_metadata={"finish_reason": "length"},
    )

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    replacement = result["messages"][0]
    assert replacement.additional_kwargs["reasoning_content"] == "internal reasoning"
    assert "output limit" in replacement.content


def test_thinking_blocks_are_preserved_when_length_notice_is_appended():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    thinking_block = {"type": "thinking", "thinking": "internal reasoning"}
    msg = AIMessage(content=[thinking_block], response_metadata={"finish_reason": "length"})

    result = mw._apply({"messages": [msg]}, runtime)

    assert result is not None
    content = result["messages"][0].content
    assert content[0] == thinking_block
    assert content[-1]["type"] == "text"
    assert "output limit" in content[-1]["text"]


def test_existing_stop_reason_is_not_overwritten(caplog):
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()
    runtime.context["stop_reason"] = "token_capped"
    msg = AIMessage(content="partial", response_metadata={"finish_reason": "length"})

    with caplog.at_level(logging.INFO, logger=_MW_LOGGER):
        assert mw._apply({"messages": [msg]}, runtime) is None

    assert runtime.context["stop_reason"] == "token_capped"
    records = [record for record in caplog.records if record.message == "Provider model length cap detected"]
    assert len(records) == 1
    assert records[0].stamped_stop_reason is False


def test_non_ai_last_message_passes_through():
    mw = ModelLengthFinishReasonMiddleware()
    runtime = _runtime()

    assert mw._apply({"messages": [HumanMessage(content="hello")]}, runtime) is None
    assert "stop_reason" not in runtime.context
