"""Tests for deerflow.models.openai_codex_provider.CodexChatModel.

Covers:
- LangChain serialization: is_lc_serializable, to_json kwargs, no token leakage
- _parse_response: text content, tool calls, reasoning_content
- _convert_messages: SystemMessage, HumanMessage, AIMessage, ToolMessage
- _parse_sse_data_line: valid data, [DONE], non-JSON, non-data lines
- _parse_tool_call_arguments: valid JSON, invalid JSON, non-dict JSON
"""

from __future__ import annotations

import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.models.credential_loader import CodexCliCredential


def _make_model(**kwargs):
    from deerflow.models.openai_codex_provider import CodexChatModel

    cred = CodexCliCredential(access_token="tok-test", account_id="acc-test")
    with patch("deerflow.models.openai_codex_provider.load_codex_cli_credential", return_value=cred):
        return CodexChatModel(model="gpt-5.4", reasoning_effort="medium", **kwargs)


# ---------------------------------------------------------------------------
# Serialization protocol
# ---------------------------------------------------------------------------


def test_is_lc_serializable_returns_true():
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel.is_lc_serializable() is True


def test_to_json_produces_constructor_type():
    model = _make_model()
    result = model.to_json()
    assert result["type"] == "constructor"
    assert "kwargs" in result


def test_to_json_contains_model_and_reasoning_effort():
    model = _make_model()
    result = model.to_json()
    assert result["kwargs"]["model"] == "gpt-5.4"
    assert result["kwargs"]["reasoning_effort"] == "medium"


def test_to_json_does_not_leak_access_token():
    """_access_token is not a Pydantic field and must not appear in serialized kwargs."""
    model = _make_model()
    result = model.to_json()
    kwargs_str = json.dumps(result["kwargs"])
    assert "tok-test" not in kwargs_str
    assert "_access_token" not in kwargs_str
    assert "_account_id" not in kwargs_str


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_text_content():
    model = _make_model()
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello world"}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "model": "gpt-5.4",
    }
    result = model._parse_response(response)
    assert result.generations[0].message.content == "Hello world"


def test_parse_response_populates_usage_metadata():
    model = _make_model()
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello world"}],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
        "model": "gpt-5.4",
    }

    result = model._parse_response(response)

    meta = result.generations[0].message.usage_metadata
    assert meta is not None
    assert meta["input_tokens"] == 10
    assert meta["output_tokens"] == 5
    assert meta["total_tokens"] == 15
    assert meta["input_token_details"]["cache_read"] == 3
    assert meta["output_token_details"]["reasoning"] == 2


def test_parse_response_reasoning_content():
    model = _make_model()
    response = {
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "I reasoned about this."}],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Answer"}],
            },
        ],
        "usage": {},
    }
    result = model._parse_response(response)
    msg = result.generations[0].message
    assert msg.content == "Answer"
    assert msg.additional_kwargs["reasoning_content"] == "I reasoned about this."


def test_parse_response_tool_call():
    model = _make_model()
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "web_search",
                "arguments": '{"query": "test"}',
                "call_id": "call_abc",
            }
        ],
        "usage": {},
    }
    result = model._parse_response(response)
    tool_calls = result.generations[0].message.tool_calls
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "web_search"
    assert tool_calls[0]["args"] == {"query": "test"}
    assert tool_calls[0]["id"] == "call_abc"


def test_parse_response_invalid_tool_call_arguments():
    model = _make_model()
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "bad_tool",
                "arguments": "not-json",
                "call_id": "call_bad",
            }
        ],
        "usage": {},
    }
    result = model._parse_response(response)
    msg = result.generations[0].message
    assert len(msg.tool_calls) == 0
    assert len(msg.invalid_tool_calls) == 1
    assert msg.invalid_tool_calls[0]["name"] == "bad_tool"


# ---------------------------------------------------------------------------
# _convert_messages
# ---------------------------------------------------------------------------


def test_convert_messages_human():
    model = _make_model()
    _, items = model._convert_messages([HumanMessage(content="Hello")])
    assert items == [{"role": "user", "content": "Hello"}]


def test_convert_messages_system_becomes_instructions():
    model = _make_model()
    instructions, items = model._convert_messages([SystemMessage(content="You are helpful.")])
    assert "You are helpful." in instructions
    assert items == []


def test_convert_messages_ai_with_tool_calls():
    model = _make_model()
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "search", "args": {"q": "foo"}, "id": "tc1", "type": "tool_call"}],
    )
    _, items = model._convert_messages([ai])
    assert any(item.get("type") == "function_call" and item["name"] == "search" for item in items)


def test_convert_messages_tool_message():
    model = _make_model()
    tool_msg = ToolMessage(content="result data", tool_call_id="tc1")
    _, items = model._convert_messages([tool_msg])
    assert items[0]["type"] == "function_call_output"
    assert items[0]["call_id"] == "tc1"
    assert items[0]["output"] == "result data"


def test_convert_messages_keeps_placeholder_result_paired_with_invalid_tool_call():
    """A malformed call stays on invalid_tool_calls but is answered by a placeholder
    ToolMessage, so it must still serialize as a function_call item.

    Responses rejects a function_call_output whose call_id has no matching
    function_call item, so dropping the invalid call turns the placeholder the
    middleware injected for recovery into the provider error it exists to prevent.
    """
    from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware

    model = _make_model()
    response = {
        "output": [
            {
                "type": "function_call",
                "name": "write_file",
                "arguments": '{"path": "report.md", "content": "unterminated',
                "call_id": "call_bad",
            }
        ],
        "usage": {},
    }
    ai_msg = model._parse_response(response).generations[0].message
    assert [tc["id"] for tc in ai_msg.invalid_tool_calls] == ["call_bad"]

    patched = DanglingToolCallMiddleware()._build_patched_messages([HumanMessage(content="write it"), ai_msg])
    assert isinstance(patched[-1], ToolMessage)
    assert patched[-1].tool_call_id == "call_bad"

    _, items = model._convert_messages(patched)
    call_ids = {item["call_id"] for item in items if item.get("type") == "function_call"}
    output_ids = {item["call_id"] for item in items if item.get("type") == "function_call_output"}
    assert output_ids == {"call_bad"}
    assert output_ids <= call_ids


def test_convert_messages_drops_invalid_calls_missing_a_name_or_call_id():
    """A call the middleware has not repaired must not serialize as null fields.

    InvalidToolCall fields are nullable, and a ``function_call`` item carrying a
    null ``name`` or ``call_id`` is schema-invalid, so serializing one turns a
    case the old serializer dropped into a rejected request. The middleware
    repairs exactly these calls (see the test below), so dropping them here
    cannot leave a placeholder ToolMessage without its call.
    """
    model = _make_model()

    for output_item in (
        {"type": "function_call", "name": "write_file", "arguments": '{"a":'},
        {"type": "function_call", "call_id": "call_x", "arguments": '{"a":'},
        {"type": "function_call", "arguments": '{"a":'},
    ):
        ai_msg = model._parse_response({"output": [output_item], "usage": {}}).generations[0].message
        assert ai_msg.invalid_tool_calls, output_item

        _, items = model._convert_messages([HumanMessage(content="hi"), ai_msg])
        assert [i for i in items if i.get("type") == "function_call"] == []


def test_convert_messages_serializes_invalid_calls_the_middleware_repaired():
    """A repaired invalid call is still sent, and still paired with its result."""
    from deerflow.agents.middlewares.dangling_tool_call_middleware import (
        DanglingToolCallMiddleware,
    )

    model = _make_model()

    for output_item in (
        {"type": "function_call", "name": "write_file", "arguments": '{"a":'},
        {"type": "function_call", "call_id": "call_x", "arguments": '{"a":'},
        {"type": "function_call", "arguments": '{"a":'},
    ):
        ai_msg = model._parse_response({"output": [output_item], "usage": {}}).generations[0].message
        patched = DanglingToolCallMiddleware()._build_patched_messages([HumanMessage(content="hi"), ai_msg])

        _, items = model._convert_messages(patched)
        call_ids = {i["call_id"] for i in items if i.get("type") == "function_call"}
        output_ids = {i["call_id"] for i in items if i.get("type") == "function_call_output"}
        assert output_ids == call_ids
        assert call_ids
        assert all(cid for cid in call_ids)
        for item in items:
            if item.get("type") == "function_call":
                assert item["name"]
                assert item["arguments"]


# ---------------------------------------------------------------------------
# _parse_sse_data_line
# ---------------------------------------------------------------------------


def test_parse_sse_data_line_valid():
    from deerflow.models.openai_codex_provider import CodexChatModel

    data = {"type": "response.completed", "response": {}}
    line = "data: " + json.dumps(data)
    assert CodexChatModel._parse_sse_data_line(line) == data


def test_parse_sse_data_line_done_returns_none():
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel._parse_sse_data_line("data: [DONE]") is None


def test_parse_sse_data_line_non_data_returns_none():
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel._parse_sse_data_line("event: ping") is None


def test_parse_sse_data_line_invalid_json_returns_none():
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel._parse_sse_data_line("data: {bad json}") is None


# ---------------------------------------------------------------------------
# _parse_tool_call_arguments
# ---------------------------------------------------------------------------


def test_parse_tool_call_arguments_valid_string():
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": '{"key": "val"}', "name": "t", "call_id": "c"})
    assert parsed == {"key": "val"}
    assert err is None


def test_parse_tool_call_arguments_already_dict():
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": {"key": "val"}, "name": "t", "call_id": "c"})
    assert parsed == {"key": "val"}
    assert err is None


def test_parse_tool_call_arguments_invalid_json():
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": "not-json", "name": "t", "call_id": "c"})
    assert parsed is None
    assert err is not None
    assert "Failed to parse" in err["error"]


def test_parse_tool_call_arguments_non_dict_json():
    model = _make_model()
    parsed, err = model._parse_tool_call_arguments({"arguments": '["list", "not", "dict"]', "name": "t", "call_id": "c"})
    assert parsed is None
    assert err is not None


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------


def test_model_post_init_accepts_null_account_id(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"tokens": {"access_token": "tok-test", "account_id": None}}))
    monkeypatch.setenv("CODEX_AUTH_PATH", str(auth_path))

    from deerflow.models.openai_codex_provider import CodexChatModel

    model = CodexChatModel(model="gpt-5.4", reasoning_effort="medium")

    assert model._account_id == ""
