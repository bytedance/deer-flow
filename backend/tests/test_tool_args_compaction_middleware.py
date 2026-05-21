"""Tests for ToolArgsCompactionMiddleware."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.tool_args_compaction_middleware import (
    ToolArgsCompactionMiddleware,
)


def _tool_msg(tool_call_id: str, *, name: str = "write_file") -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id=tool_call_id, name=name)


def _write_file_tool_call(
    *,
    tc_id: str = "call_write",
    content: str = "x" * 3000,
    path: str = "/mnt/user-data/report.html",
) -> dict:
    return {
        "name": "write_file",
        "id": tc_id,
        "args": {
            "path": path,
            "content": content,
            "append": False,
        },
    }


def _ai_with_tool_calls(tool_calls: list[dict], *, additional_kwargs: dict | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=tool_calls, additional_kwargs=additional_kwargs or {})


class TestBuildCompactedMessages:
    def test_compacts_completed_large_write_file_call(self):
        mw = ToolArgsCompactionMiddleware()
        large_content = "x" * 3000
        msgs = [
            HumanMessage(content="hi"),
            _ai_with_tool_calls([_write_file_tool_call(content=large_content)]),
            _tool_msg("call_write"),
        ]

        patched = mw._build_compacted_messages(msgs)

        assert patched is not None
        ai_msg = patched[1]
        assert isinstance(ai_msg, AIMessage)
        assert ai_msg.tool_calls[0]["args"]["path"] == "/mnt/user-data/report.html"
        assert ai_msg.tool_calls[0]["args"]["content"] == "[write_file content omitted in model context: 3000 chars]"
        assert large_content not in ai_msg.tool_calls[0]["args"]["content"]

    def test_compacts_recent_completed_pair_at_end_of_messages(self):
        mw = ToolArgsCompactionMiddleware()
        large_content = "x" * 3000
        msgs = [
            HumanMessage(content="hi"),
            _ai_with_tool_calls([_write_file_tool_call(content=large_content)]),
            _tool_msg("call_write"),
        ]

        patched = mw._build_compacted_messages(msgs)

        assert patched is not None
        assert patched[1].tool_calls[0]["args"]["content"] == "[write_file content omitted in model context: 3000 chars]"

    def test_does_not_compact_unpaired_active_write_file_call(self):
        mw = ToolArgsCompactionMiddleware()
        msgs = [_ai_with_tool_calls([_write_file_tool_call(content="x" * 3000)])]

        assert mw._build_compacted_messages(msgs) is None

    def test_marker_omits_original_content_preview(self):
        mw = ToolArgsCompactionMiddleware(write_file_max_chars=20)
        large_content = "HEAD_CONTENT_SHOULD_NOT_APPEAR" + ("x" * 100) + "TAIL_CONTENT_SHOULD_NOT_APPEAR"
        msgs = [
            _ai_with_tool_calls([_write_file_tool_call(content=large_content)]),
            _tool_msg("call_write"),
        ]

        patched = mw._build_compacted_messages(msgs)

        assert patched is not None
        compacted_content = patched[0].tool_calls[0]["args"]["content"]
        assert "HEAD_CONTENT_SHOULD_NOT_APPEAR" not in compacted_content
        assert "TAIL_CONTENT_SHOULD_NOT_APPEAR" not in compacted_content
        assert compacted_content == f"[write_file content omitted in model context: {len(large_content)} chars]"

    def test_does_not_mutate_original_messages(self):
        mw = ToolArgsCompactionMiddleware()
        large_content = "x" * 3000
        original_ai = _ai_with_tool_calls([_write_file_tool_call(content=large_content)])
        msgs = [original_ai, _tool_msg("call_write")]

        patched = mw._build_compacted_messages(msgs)

        assert patched is not None
        assert original_ai.tool_calls[0]["args"]["content"] == large_content
        assert patched[0].tool_calls[0]["args"]["content"] != large_content

    def test_zero_budget_disables_compaction(self):
        mw = ToolArgsCompactionMiddleware(write_file_max_chars=0)
        msgs = [
            _ai_with_tool_calls([_write_file_tool_call(content="x" * 3000)]),
            _tool_msg("call_write"),
        ]

        assert mw._build_compacted_messages(msgs) is None

    def test_does_not_compact_non_write_file_call(self):
        mw = ToolArgsCompactionMiddleware()
        msgs = [
            _ai_with_tool_calls([{"name": "bash", "id": "call_1", "args": {"command": "echo hi" * 1000}}]),
            _tool_msg("call_1", name="bash"),
        ]

        assert mw._build_compacted_messages(msgs) is None

    def test_only_completed_write_file_calls_are_compacted_in_mixed_tool_call_message(self):
        mw = ToolArgsCompactionMiddleware()
        completed = _write_file_tool_call(tc_id="call_done", content="x" * 3000)
        active = _write_file_tool_call(tc_id="call_active", content="y" * 3000, path="/mnt/user-data/active.html")
        msgs = [
            _ai_with_tool_calls([completed, active]),
            _tool_msg("call_done"),
        ]

        patched = mw._build_compacted_messages(msgs)

        assert patched is not None
        tool_calls = patched[0].tool_calls
        assert tool_calls[0]["args"]["content"] == "[write_file content omitted in model context: 3000 chars]"
        assert tool_calls[1]["args"]["content"] == "y" * 3000

    def test_does_not_compact_short_write_file_call(self):
        mw = ToolArgsCompactionMiddleware()
        msgs = [
            _ai_with_tool_calls([_write_file_tool_call(content="small")]),
            _tool_msg("call_write"),
        ]

        assert mw._build_compacted_messages(msgs) is None

    def test_preserves_and_updates_raw_provider_tool_call_metadata(self):
        mw = ToolArgsCompactionMiddleware()
        large_content = "x" * 2500
        tool_call = _write_file_tool_call(content=large_content)
        raw_tool_call = {
            "id": "call_write",
            "type": "function",
            "thought_signature": "sig-123",
            "function": {"name": "write_file", "arguments": json.dumps(tool_call["args"])},
        }
        msgs = [
            _ai_with_tool_calls([tool_call], additional_kwargs={"tool_calls": [raw_tool_call]}),
            _tool_msg("call_write"),
        ]

        patched = mw._build_compacted_messages(msgs)

        assert patched is not None
        ai_msg = patched[0]
        raw_patched = ai_msg.additional_kwargs["tool_calls"][0]
        assert raw_patched["thought_signature"] == "sig-123"
        assert large_content not in raw_patched["function"]["arguments"]
        assert "2500 chars" in raw_patched["function"]["arguments"]


class TestWrapModelCall:
    def test_wrap_model_call_overrides_messages_when_compaction_applies(self):
        mw = ToolArgsCompactionMiddleware()
        request = MagicMock()
        request.messages = [
            _ai_with_tool_calls([_write_file_tool_call(content="x" * 3000)]),
            _tool_msg("call_write"),
        ]
        request.override.return_value = "patched-request"
        handler = MagicMock(return_value="response")

        result = mw.wrap_model_call(request, handler)

        assert result == "response"
        request.override.assert_called_once()
        handler.assert_called_once_with("patched-request")

    @pytest.mark.anyio
    async def test_awrap_model_call_overrides_messages_when_compaction_applies(self):
        mw = ToolArgsCompactionMiddleware()
        request = MagicMock()
        request.messages = [
            _ai_with_tool_calls([_write_file_tool_call(content="x" * 3000)]),
            _tool_msg("call_write"),
        ]
        request.override.return_value = "patched-request"
        handler = AsyncMock(return_value="response")

        result = await mw.awrap_model_call(request, handler)

        assert result == "response"
        request.override.assert_called_once()
        handler.assert_awaited_once_with("patched-request")
