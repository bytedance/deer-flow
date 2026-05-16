from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from deerflow.models import openai_codex_provider as codex_provider_module
from deerflow.models.claude_provider import ClaudeChatModel
from deerflow.models.credential_loader import CodexCliCredential
from deerflow.models.openai_codex_provider import CodexChatModel


def test_codex_provider_rejects_non_positive_retry_attempts():
    with pytest.raises(ValueError, match="retry_max_attempts must be >= 1"):
        CodexChatModel(retry_max_attempts=0)


def test_codex_provider_requires_credentials(monkeypatch):
    monkeypatch.setattr(CodexChatModel, "_load_codex_auth", lambda self: None)

    with pytest.raises(ValueError, match="Codex CLI credential not found"):
        CodexChatModel()


def test_codex_provider_concatenates_multiple_system_messages(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    model = CodexChatModel()
    instructions, input_items = model._convert_messages(
        [
            SystemMessage(content="First system prompt."),
            SystemMessage(content="Second system prompt."),
            HumanMessage(content="Hello"),
        ]
    )

    assert instructions == "First system prompt.\n\nSecond system prompt."
    assert input_items == [{"role": "user", "content": "Hello"}]


def test_codex_provider_flattens_structured_text_blocks(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    model = CodexChatModel()
    instructions, input_items = model._convert_messages(
        [
            HumanMessage(content=[{"type": "text", "text": "Hello from blocks"}]),
        ]
    )

    assert instructions == "You are a helpful assistant."
    assert input_items == [{"role": "user", "content": "Hello from blocks"}]


def test_claude_provider_rejects_non_positive_retry_attempts():
    with pytest.raises(ValueError, match="retry_max_attempts must be >= 1"):
        ClaudeChatModel(model="claude-sonnet-4-6", retry_max_attempts=0)


def test_codex_provider_skips_terminal_sse_markers(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    model = CodexChatModel()

    assert model._parse_sse_data_line("data: [DONE]") is None
    assert model._parse_sse_data_line("event: response.completed") is None


def test_codex_provider_skips_non_json_sse_frames(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    model = CodexChatModel()

    assert model._parse_sse_data_line("data: not-json") is None


def test_codex_provider_marks_invalid_tool_call_arguments(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    model = CodexChatModel()
    result = model._parse_response(
        {
            "model": "gpt-5.4",
            "output": [
                {
                    "type": "function_call",
                    "name": "bash",
                    "arguments": "{invalid",
                    "call_id": "tc-1",
                }
            ],
            "usage": {},
        }
    )

    message = result.generations[0].message
    assert message.tool_calls == []
    assert len(message.invalid_tool_calls) == 1
    assert message.invalid_tool_calls[0]["type"] == "invalid_tool_call"
    assert message.invalid_tool_calls[0]["name"] == "bash"
    assert message.invalid_tool_calls[0]["args"] == "{invalid"
    assert message.invalid_tool_calls[0]["id"] == "tc-1"
    assert "Failed to parse tool arguments" in message.invalid_tool_calls[0]["error"]


def test_codex_provider_parses_valid_tool_arguments(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    model = CodexChatModel()
    result = model._parse_response(
        {
            "model": "gpt-5.4",
            "output": [
                {
                    "type": "function_call",
                    "name": "bash",
                    "arguments": json.dumps({"cmd": "pwd"}),
                    "call_id": "tc-1",
                }
            ],
            "usage": {},
        }
    )

    assert result.generations[0].message.tool_calls == [{"name": "bash", "args": {"cmd": "pwd"}, "id": "tc-1", "type": "tool_call"}]


class _FakeResponseStream:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield from self._lines


class _FakeHttpxClient:
    def __init__(self, lines: list[str], *_args, **_kwargs):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def stream(self, *_args, **_kwargs):
        return _FakeResponseStream(self._lines)


def test_codex_provider_merges_streamed_output_items_when_completed_output_is_empty(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    lines = [
        'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"message","content":[{"type":"output_text","text":"Hello from stream"}]}}',
        'data: {"type":"response.completed","response":{"model":"gpt-5.4","output":[],"usage":{"input_tokens":1,"output_tokens":2,"total_tokens":3}}}',
    ]

    monkeypatch.setattr(
        codex_provider_module.httpx,
        "Client",
        lambda *args, **kwargs: _FakeHttpxClient(lines, *args, **kwargs),
    )

    model = CodexChatModel()
    response = model._stream_response(headers={}, payload={})
    parsed = model._parse_response(response)

    assert response["output"] == [
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "Hello from stream"}],
        }
    ]
    assert parsed.generations[0].message.content == "Hello from stream"


def test_codex_provider_orders_streamed_output_items_by_output_index(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    lines = [
        'data: {"type":"response.output_item.done","output_index":1,"item":{"type":"message","content":[{"type":"output_text","text":"Second"}]}}',
        'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"message","content":[{"type":"output_text","text":"First"}]}}',
        'data: {"type":"response.completed","response":{"model":"gpt-5.4","output":[],"usage":{}}}',
    ]

    monkeypatch.setattr(
        codex_provider_module.httpx,
        "Client",
        lambda *args, **kwargs: _FakeHttpxClient(lines, *args, **kwargs),
    )

    model = CodexChatModel()
    response = model._stream_response(headers={}, payload={})

    assert [item["content"][0]["text"] for item in response["output"]] == [
        "First",
        "Second",
    ]


def test_codex_provider_preserves_completed_output_when_stream_only_has_placeholder(monkeypatch):
    monkeypatch.setattr(
        CodexChatModel,
        "_load_codex_auth",
        lambda self: CodexCliCredential(access_token="token", account_id="acct"),
    )

    lines = [
        'data: {"type":"response.output_item.added","output_index":0,"item":{"type":"message","status":"in_progress","content":[]}}',
        'data: {"type":"response.completed","response":{"model":"gpt-5.4","output":[{"type":"message","content":[{"type":"output_text","text":"Final from completed"}]}],"usage":{}}}',
    ]

    monkeypatch.setattr(
        codex_provider_module.httpx,
        "Client",
        lambda *args, **kwargs: _FakeHttpxClient(lines, *args, **kwargs),
    )

    model = CodexChatModel()
    response = model._stream_response(headers={}, payload={})
    parsed = model._parse_response(response)

    assert response["output"] == [
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "Final from completed"}],
        }
    ]
    assert parsed.generations[0].message.content == "Final from completed"
