"""Tests for DanglingToolCallMiddleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.dangling_tool_call_middleware import (
    DanglingToolCallMiddleware,
)


def _ai_with_tool_calls(tool_calls):
    return AIMessage(content="", tool_calls=tool_calls)


def _tool_msg(tool_call_id, name="test_tool"):
    return ToolMessage(content="result", tool_call_id=tool_call_id, name=name)


def _tc(name="bash", tc_id="call_1"):
    return {"name": name, "id": tc_id, "args": {}}


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

    def test_normalizes_missing_tool_call_ids_in_model_response(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [HumanMessage(content="find cars")]
        message = AIMessage(
            content="",
            id="run-123",
            tool_calls=[
                {
                    "name": "vector_search",
                    "args": {"keyword": "汽车"},
                    "id": None,
                    "type": "tool_call",
                }
            ],
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": "vector_search", "arguments": '{"keyword":"汽车"}'},
                    }
                ]
            },
            response_metadata={"finish_reason": "tool_calls"},
        )
        response = ModelResponse(result=[message])
        handler = MagicMock(return_value=response)

        result = mw.wrap_model_call(request, handler)

        normalized = result.result[0]
        assert isinstance(normalized, AIMessage)
        tool_call_id = normalized.tool_calls[0]["id"]
        assert isinstance(tool_call_id, str)
        assert tool_call_id.startswith("call_")
        assert normalized.additional_kwargs["tool_calls"][0]["id"] == tool_call_id
        assert normalized.response_metadata["finish_reason"] == "tool_calls"

    def test_keeps_existing_tool_call_ids_in_model_response(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [HumanMessage(content="find cars")]
        message = AIMessage(
            content="",
            id="run-123",
            tool_calls=[_tc("vector_search", "call_existing")],
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": "call_existing",
                        "type": "function",
                        "function": {"name": "vector_search", "arguments": '{"keyword":"汽车"}'},
                    }
                ]
            },
        )
        response = ModelResponse(result=[message])
        handler = MagicMock(return_value=response)

        result = mw.wrap_model_call(request, handler)

        assert result is response
        assert result.result[0].tool_calls[0]["id"] == "call_existing"
        assert result.result[0].additional_kwargs["tool_calls"][0]["id"] == "call_existing"

    def test_normalizes_direct_ai_message_model_response(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [HumanMessage(content="find cars")]
        message = AIMessage(
            content="",
            id="run-direct-123",
            tool_calls=[{"name": "vector_search", "args": {"keyword": "汽车"}, "id": None}],
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": "vector_search", "arguments": '{"keyword":"汽车"}'},
                    }
                ]
            },
        )
        handler = MagicMock(return_value=message)

        result = mw.wrap_model_call(request, handler)

        assert isinstance(result.tool_calls[0]["id"], str)
        assert result.additional_kwargs["tool_calls"][0]["id"] == result.tool_calls[0]["id"]


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

    @pytest.mark.anyio
    async def test_async_normalizes_missing_tool_call_ids_in_model_response(self):
        mw = DanglingToolCallMiddleware()
        request = MagicMock()
        request.messages = [HumanMessage(content="find cars")]
        message = AIMessage(
            content="",
            id="run-async-123",
            tool_calls=[{"name": "vector_search", "args": {"keyword": "汽车"}, "id": None}],
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": "vector_search", "arguments": '{"keyword":"汽车"}'},
                    }
                ]
            },
        )
        handler = AsyncMock(return_value=ModelResponse(result=[message]))

        result = await mw.awrap_model_call(request, handler)

        normalized = result.result[0]
        assert isinstance(normalized.tool_calls[0]["id"], str)
        assert normalized.additional_kwargs["tool_calls"][0]["id"] == normalized.tool_calls[0]["id"]
