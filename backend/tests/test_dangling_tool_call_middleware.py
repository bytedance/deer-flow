"""Tests for DanglingToolCallMiddleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.dangling_tool_call_middleware import (
    DanglingToolCallMiddleware,
)


def _ai_with_tool_calls(tool_calls):
    return AIMessage(content="", tool_calls=tool_calls)


def _ai_with_invalid_tool_calls(invalid_tool_calls):
    return AIMessage(content="", tool_calls=[], invalid_tool_calls=invalid_tool_calls)


def _tool_msg(tool_call_id, name="test_tool"):
    return ToolMessage(content="result", tool_call_id=tool_call_id, name=name)


def _tc(name="bash", tc_id="call_1"):
    return {"name": name, "id": tc_id, "args": {}}


def _invalid_tc(name="write_file", tc_id="write_file:36", error="Failed to parse tool arguments: malformed JSON"):
    return {
        "type": "invalid_tool_call",
        "name": name,
        "id": tc_id,
        "args": '{"description":"write report","path":"/mnt/user-data/outputs/report.md","content":"bad {"json"}"}',
        "error": error,
    }


class TestBuildPatchedMessagesNoPatch:
    def test_empty_messages(self):
        mw = DanglingToolCallMiddleware()
        assert mw._build_patched_messages([]) is None

    def test_no_ai_messages(self):
        mw = DanglingToolCallMiddleware()
        msgs = [HumanMessage(content="hello")]
        assert mw._build_patched_messages(msgs) is None

    def test_ai_without_tool_calls(self):
        mw = DanglingToolCallMiddleware()
        msgs = [AIMessage(content="hello")]
        assert mw._build_patched_messages(msgs) is None

    def test_all_tool_calls_responded(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            _tool_msg("call_1", "bash"),
        ]
        assert mw._build_patched_messages(msgs) is None


class TestBuildPatchedMessagesPatching:
    def test_single_dangling_call(self):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_tool_calls([_tc("bash", "call_1")])]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        assert len(patched) == 2
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call_1"
        assert patched[1].status == "error"

    def test_multiple_dangling_calls_same_message(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1"), _tc("read", "call_2")]),
        ]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        # Original AI + 2 synthetic ToolMessages
        assert len(patched) == 3
        tool_msgs = [m for m in patched if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 2
        assert {tm.tool_call_id for tm in tool_msgs} == {"call_1", "call_2"}

    def test_patch_inserted_after_offending_ai_message(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            HumanMessage(content="hi"),
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            HumanMessage(content="still here"),
        ]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        # HumanMessage, AIMessage, synthetic ToolMessage, HumanMessage
        assert len(patched) == 4
        assert isinstance(patched[0], HumanMessage)
        assert isinstance(patched[1], AIMessage)
        assert isinstance(patched[2], ToolMessage)
        assert patched[2].tool_call_id == "call_1"
        assert isinstance(patched[3], HumanMessage)

    def test_mixed_responded_and_dangling(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1"), _tc("read", "call_2")]),
            _tool_msg("call_1", "bash"),
        ]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        synthetic = [m for m in patched if isinstance(m, ToolMessage) and m.status == "error"]
        assert len(synthetic) == 1
        assert synthetic[0].tool_call_id == "call_2"

    def test_multiple_ai_messages_each_patched(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            HumanMessage(content="next turn"),
            _ai_with_tool_calls([_tc("read", "call_2")]),
        ]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        synthetic = [m for m in patched if isinstance(m, ToolMessage)]
        assert len(synthetic) == 2

    def test_synthetic_message_content(self):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_tool_calls([_tc("bash", "call_1")])]
        patched = mw._build_patched_messages(msgs)
        tool_msg = patched[1]
        assert "interrupted" in tool_msg.content.lower()
        assert tool_msg.name == "bash"

    def test_raw_provider_tool_calls_are_patched(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage(
                content="",
                tool_calls=[],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "bash", "arguments": '{"command":"ls"}'},
                        }
                    ]
                },
            )
        ]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        assert len(patched) == 2
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call_1"
        assert patched[1].name == "bash"
        assert patched[1].status == "error"

    def test_invalid_tool_call_is_patched(self):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_invalid_tool_calls([_invalid_tc()])]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        assert len(patched) == 2
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "write_file:36"
        assert patched[1].name == "write_file"
        assert patched[1].status == "error"
        assert "arguments were invalid" in patched[1].content
        assert "Failed to parse tool arguments" in patched[1].content

    def test_valid_and_invalid_tool_calls_are_both_patched(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage(
                content="",
                tool_calls=[_tc("bash", "call_1")],
                invalid_tool_calls=[_invalid_tc()],
            )
        ]
        patched = mw._build_patched_messages(msgs)
        assert patched is not None
        tool_msgs = [m for m in patched if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 2
        assert {tm.tool_call_id for tm in tool_msgs} == {"call_1", "write_file:36"}

    def test_invalid_tool_call_already_responded_is_not_patched(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_invalid_tool_calls([_invalid_tc()]),
            _tool_msg("write_file:36", "write_file"),
        ]
        assert mw._build_patched_messages(msgs) is None


class TestWrapModelCall:
    def test_no_patch_passthrough(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [AIMessage(content="hello")]
        handler = MagicMock(return_value="response")

        result = mw.wrap_model_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "response"

    def test_patched_request_forwarded(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [_ai_with_tool_calls([_tc("bash", "call_1")])]
        patched_request = MagicMock()
        request.override.return_value = patched_request
        handler = MagicMock(return_value="response")

        result = mw.wrap_model_call(request, handler)

        # Verify override was called with the patched messages
        request.override.assert_called_once()
        call_kwargs = request.override.call_args
        passed_messages = call_kwargs.kwargs["messages"]
        assert len(passed_messages) == 2
        assert isinstance(passed_messages[1], ToolMessage)
        assert passed_messages[1].tool_call_id == "call_1"

        handler.assert_called_once_with(patched_request)
        assert result == "response"


class TestAwrapModelCall:
    @pytest.mark.anyio
    async def test_async_no_patch(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [AIMessage(content="hello")]
        handler = AsyncMock(return_value="response")

        result = await mw.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "response"

    @pytest.mark.anyio
    async def test_async_patched(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [_ai_with_tool_calls([_tc("bash", "call_1")])]
        patched_request = MagicMock()
        request.override.return_value = patched_request
        handler = AsyncMock(return_value="response")

        result = await mw.awrap_model_call(request, handler)

        # Verify override was called with the patched messages
        request.override.assert_called_once()
        call_kwargs = request.override.call_args
        passed_messages = call_kwargs.kwargs["messages"]
        assert len(passed_messages) == 2
        assert isinstance(passed_messages[1], ToolMessage)
        assert passed_messages[1].tool_call_id == "call_1"

        handler.assert_called_once_with(patched_request)
        assert result == "response"
