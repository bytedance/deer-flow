"""Tests for LangChain-to-OpenAI message format converters."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from deerflow.runtime.converters import (
    langchain_messages_to_openai,
    langchain_to_openai_completion,
    langchain_to_openai_message,
)


def _make_ai_message(content="", tool_calls=None, id="msg-123", usage_metadata=None, response_metadata=None):
    msg = MagicMock()
    msg.type = "ai"
    msg.content = content
    msg.tool_calls = tool_calls or []
    msg.id = id
    msg.usage_metadata = usage_metadata
    msg.response_metadata = response_metadata or {}
    return msg


def _make_human_message(content="Hello"):
    msg = MagicMock()
    msg.type = "human"
    msg.content = content
    return msg


def _make_system_message(content="You are an assistant."):
    msg = MagicMock()
    msg.type = "system"
    msg.content = content
    return msg


def _make_tool_message(content="result", tool_call_id="call-abc"):
    msg = MagicMock()
    msg.type = "tool"
    msg.content = content
    msg.tool_call_id = tool_call_id
    return msg


class TestLangchainToOpenaiMessage:
    def test_ai_message_text_only(self):
        msg = _make_ai_message(content="Hello world")
        result = langchain_to_openai_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] == "Hello world"
        assert "tool_calls" not in result

    def test_ai_message_with_tool_calls(self):
        tool_calls = [
            {"id": "call-1", "name": "bash", "args": {"command": "ls"}},
        ]
        msg = _make_ai_message(content="", tool_calls=tool_calls)
        result = langchain_to_openai_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] is None
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call-1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "bash"
        # arguments must be a JSON string
        args = json.loads(tc["function"]["arguments"])
        assert args == {"command": "ls"}

    def test_ai_message_text_and_tool_calls(self):
        tool_calls = [
            {"id": "call-2", "name": "read_file", "args": {"path": "/tmp/x"}},
        ]
        msg = _make_ai_message(content="Reading the file", tool_calls=tool_calls)
        result = langchain_to_openai_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] == "Reading the file"
        assert len(result["tool_calls"]) == 1

    def test_ai_message_empty_content_no_tools(self):
        msg = _make_ai_message(content="")
        result = langchain_to_openai_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] == ""
        assert "tool_calls" not in result

    def test_ai_message_list_content(self):
        # Multimodal content is preserved as-is
        list_content = [
            {"type": "text", "text": "Here is an image"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        msg = _make_ai_message(content=list_content)
        result = langchain_to_openai_message(msg)
        assert result["role"] == "assistant"
        assert result["content"] == list_content

    def test_human_message(self):
        msg = _make_human_message("Tell me a joke")
        result = langchain_to_openai_message(msg)
        assert result["role"] == "user"
        assert result["content"] == "Tell me a joke"

    def test_tool_message(self):
        msg = _make_tool_message(content="file contents here", tool_call_id="call-xyz")
        result = langchain_to_openai_message(msg)
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call-xyz"
        assert result["content"] == "file contents here"

    def test_system_message(self):
        msg = _make_system_message("You are a helpful assistant.")
        result = langchain_to_openai_message(msg)
        assert result["role"] == "system"
        assert result["content"] == "You are a helpful assistant."


class TestLangchainToOpenaiCompletion:
    def test_basic_completion(self):
        usage_metadata = {"input_tokens": 10, "output_tokens": 20}
        msg = _make_ai_message(
            content="Hello",
            id="msg-abc",
            usage_metadata=usage_metadata,
            response_metadata={"model_name": "gpt-4o", "finish_reason": "stop"},
        )
        result = langchain_to_openai_completion(msg)
        assert result["id"] == "msg-abc"
        assert result["model"] == "gpt-4o"
        assert len(result["choices"]) == 1
        choice = result["choices"][0]
        assert choice["index"] == 0
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["content"] == "Hello"
        assert result["usage"] is not None
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20
        assert result["usage"]["total_tokens"] == 30

    def test_completion_with_tool_calls(self):
        tool_calls = [{"id": "call-1", "name": "bash", "args": {}}]
        msg = _make_ai_message(
            content="",
            tool_calls=tool_calls,
            id="msg-tc",
            response_metadata={"model_name": "gpt-4o"},
        )
        result = langchain_to_openai_completion(msg)
        assert result["choices"][0]["finish_reason"] == "tool_calls"

    def test_completion_no_usage(self):
        msg = _make_ai_message(content="Hi", id="msg-nousage", usage_metadata=None)
        result = langchain_to_openai_completion(msg)
        assert result["usage"] is None

    def test_finish_reason_from_response_metadata(self):
        msg = _make_ai_message(
            content="Done",
            id="msg-fr",
            response_metadata={"model_name": "claude-3", "finish_reason": "end_turn"},
        )
        result = langchain_to_openai_completion(msg)
        assert result["choices"][0]["finish_reason"] == "end_turn"

    def test_finish_reason_default_stop(self):
        msg = _make_ai_message(content="Done", id="msg-defstop", response_metadata={})
        result = langchain_to_openai_completion(msg)
        assert result["choices"][0]["finish_reason"] == "stop"


class TestMessagesToOpenai:
    def test_convert_message_list(self):
        human = _make_human_message("Hi")
        ai = _make_ai_message(content="Hello!")
        tool_msg = _make_tool_message("result", "call-1")
        messages = [human, ai, tool_msg]
        result = langchain_messages_to_openai(messages)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "tool"

    def test_empty_list(self):
        assert langchain_messages_to_openai([]) == []
