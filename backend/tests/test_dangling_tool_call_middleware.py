"""Tests for DanglingToolCallMiddleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# Intentional private import: these tests lock the OpenAI serialization boundary
# that strict providers reject when assistant tool-call names are empty.
from langchain_openai.chat_models.base import _convert_message_to_dict

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

    def test_valid_tool_call_names_are_sanitization_noop(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage(
                content="",
                tool_calls=[_tc("bash", "call_1")],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{}"},
                        }
                    ]
                },
            ),
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

    def test_empty_structured_tool_call_name_is_sanitized(self):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_tool_calls([_tc("", "empty_name_call")])]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[0].tool_calls[0]["name"] == "unknown_tool"
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["function"]["name"] == "unknown_tool"
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "empty_name_call"
        assert patched[1].name == "unknown_tool"
        assert patched[1].status == "error"
        assert "name was missing or empty" in patched[1].content

    @pytest.mark.parametrize(
        "raw_tool_call",
        [
            {"id": "missing_name_call", "type": "function", "function": {"arguments": "{}"}},
            {"id": "non_string_name_call", "type": "function", "function": {"name": 42, "arguments": "{}"}},
        ],
    )
    def test_malformed_raw_provider_tool_call_name_is_sanitized(self, raw_tool_call):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage.model_construct(
                content="",
                type="ai",
                tool_calls=[],
                invalid_tool_calls=[],
                additional_kwargs={"tool_calls": [raw_tool_call]},
                response_metadata={},
            )
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[0].additional_kwargs["tool_calls"][0]["function"]["name"] == "unknown_tool"
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["function"]["name"] == "unknown_tool"
        assert patched[1].name == "unknown_tool"
        assert patched[1].status == "error"

    def test_existing_tool_result_still_sanitizes_empty_structured_tool_call_name(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc(" ", "empty_name_call")]),
            ToolMessage(content="Error: invalid tool", tool_call_id="empty_name_call", name=""),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[0].tool_calls[0]["name"] == "unknown_tool"
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["function"]["name"] == "unknown_tool"
        assert patched[1].tool_call_id == "empty_name_call"
        assert patched[1].name == "unknown_tool"

    def test_raw_provider_tool_call_empty_function_name_is_sanitized(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage(
                content="",
                tool_calls=[],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "raw_empty_name_call",
                            "type": "function",
                            "function": {"name": "", "arguments": "{}"},
                        }
                    ]
                },
            )
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        raw_tool_call = patched[0].additional_kwargs["tool_calls"][0]
        assert raw_tool_call["function"]["name"] == "unknown_tool"
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["function"]["name"] == "unknown_tool"
        assert patched[1].tool_call_id == "raw_empty_name_call"
        assert patched[1].name == "unknown_tool"
        assert patched[1].status == "error"
        assert "name was missing or empty" in patched[1].content

    def test_valid_structured_call_with_empty_raw_provider_name_is_sanitized(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage.model_construct(
                content="",
                type="ai",
                tool_calls=[_tc("bash", "call_1")],
                invalid_tool_calls=[],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "", "arguments": "{}"},
                        }
                    ]
                },
                response_metadata={},
            ),
            _tool_msg("call_1", "bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[0].tool_calls[0]["name"] == "bash"
        raw_tool_call = patched[0].additional_kwargs["tool_calls"][0]
        assert raw_tool_call["function"]["name"] == "unknown_tool"
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["function"]["name"] == "bash"
        assert patched[1].tool_call_id == "call_1"
        assert patched[1].name == "bash"

    def test_empty_name_invalid_tool_call_uses_name_recovery_message(self):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_invalid_tool_calls([_invalid_tc(name="", tc_id="empty_invalid_call")])]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[1].tool_call_id == "empty_invalid_call"
        assert patched[1].name == "unknown_tool"
        assert "name was missing or empty" in patched[1].content
        assert "arguments were invalid" not in patched[1].content

    def test_non_adjacent_tool_result_is_moved_next_to_tool_call(self):
        middleware = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            HumanMessage(content="interruption"),
            _tool_msg("call_1", "bash"),
        ]
        patched = middleware._build_patched_messages(msgs)
        assert patched is not None
        assert isinstance(patched[0], AIMessage)
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call_1"
        assert isinstance(patched[2], HumanMessage)

    def test_multiple_tool_results_stay_grouped_after_ai_tool_call(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1"), _tc("read", "call_2")]),
            HumanMessage(content="interruption"),
            _tool_msg("call_2", "read"),
            _tool_msg("call_1", "bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert isinstance(patched[0], AIMessage)
        assert isinstance(patched[1], ToolMessage)
        assert isinstance(patched[2], ToolMessage)
        assert [patched[1].tool_call_id, patched[2].tool_call_id] == ["call_1", "call_2"]
        assert isinstance(patched[3], HumanMessage)

    def test_non_tool_message_inserted_between_partial_tool_results_is_regrouped(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1"), _tc("read", "call_2")]),
            _tool_msg("call_1", "bash"),
            HumanMessage(content="interruption"),
            _tool_msg("call_2", "read"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert isinstance(patched[0], AIMessage)
        assert isinstance(patched[1], ToolMessage)
        assert isinstance(patched[2], ToolMessage)
        assert [patched[1].tool_call_id, patched[2].tool_call_id] == ["call_1", "call_2"]
        assert isinstance(patched[3], HumanMessage)

    def test_valid_adjacent_tool_results_are_unchanged(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            _tool_msg("call_1", "bash"),
            HumanMessage(content="next"),
        ]

        assert mw._build_patched_messages(msgs) is None

    def test_reused_tool_call_ids_across_ai_turns_keep_their_own_tool_results(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            HumanMessage(content="summary", name="summary", additional_kwargs={"hide_from_ui": True}),
            _ai_with_tool_calls(
                [
                    _tc("web_search", "web_search:11"),
                    _tc("web_search", "web_search:12"),
                    _tc("web_search", "web_search:13"),
                ]
            ),
            _tool_msg("web_search:11", "web_search"),
            _tool_msg("web_search:12", "web_search"),
            _tool_msg("web_search:13", "web_search"),
            _ai_with_tool_calls(
                [
                    _tc("web_search", "web_search:9"),
                    _tc("web_search", "web_search:10"),
                    _tc("web_search", "web_search:11"),
                ]
            ),
            _tool_msg("web_search:9", "web_search"),
            _tool_msg("web_search:10", "web_search"),
            _tool_msg("web_search:11", "web_search"),
        ]

        assert mw._build_patched_messages(msgs) is None

    def test_reused_tool_call_id_patches_second_dangling_occurrence(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("web_search", "web_search:11")]),
            _tool_msg("web_search:11", "web_search"),
            _ai_with_tool_calls([_tc("web_search", "web_search:11")]),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "web_search:11"
        assert patched[1].status == "success"
        assert isinstance(patched[3], ToolMessage)
        assert patched[3].tool_call_id == "web_search:11"
        assert patched[3].status == "error"

    def test_reused_tool_call_id_consumes_later_result_for_first_dangling_occurrence(self):
        mw = DanglingToolCallMiddleware()
        result = _tool_msg("web_search:11", "web_search")
        msgs = [
            _ai_with_tool_calls([_tc("web_search", "web_search:11")]),
            _ai_with_tool_calls([_tc("web_search", "web_search:11")]),
            result,
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[1] is result
        assert patched[1].status == "success"
        assert isinstance(patched[3], ToolMessage)
        assert patched[3].tool_call_id == "web_search:11"
        assert patched[3].status == "error"

    def test_tool_results_are_grouped_with_their_own_ai_turn_across_multiple_ai_messages(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            HumanMessage(content="interruption"),
            _ai_with_tool_calls([_tc("read", "call_2")]),
            _tool_msg("call_1", "bash"),
            _tool_msg("call_2", "read"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert isinstance(patched[0], AIMessage)
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call_1"
        assert isinstance(patched[2], HumanMessage)
        assert isinstance(patched[3], AIMessage)
        assert isinstance(patched[4], ToolMessage)
        assert patched[4].tool_call_id == "call_2"

    def test_orphan_tool_message_is_dropped_during_grouping(self):
        """An orphan ToolMessage — one whose tool_call_id has no matching AIMessage
        tool_call — is dropped from the patched output.

        Behavior intentionally changed: strict OpenAI-compatible providers reject a
        ToolMessage that does not follow an assistant tool_call, so an orphan left
        over from interruption/compaction must not be forwarded.
        """
        mw = DanglingToolCallMiddleware()
        orphan = _tool_msg("orphan_call", "orphan")
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            orphan,
            HumanMessage(content="interruption"),
            _tool_msg("call_1", "bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        # The orphan is dropped; call_1's result is regrouped right after its AIMessage.
        assert isinstance(patched[0], AIMessage)
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call_1"
        assert isinstance(patched[2], HumanMessage)
        assert orphan not in patched
        assert patched.count(orphan) == 0
        assert len(patched) == 3

    def test_leading_orphan_tool_message_is_dropped(self):
        """A ToolMessage that leads the transcript with no preceding tool_call is an
        orphan and must be dropped (leaving a valid grouped transcript)."""
        mw = DanglingToolCallMiddleware()
        leading_orphan = _tool_msg("stale_call", "stale")
        msgs = [
            leading_orphan,
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            _tool_msg("call_1", "bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert leading_orphan not in patched
        assert isinstance(patched[0], AIMessage)
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call_1"
        assert len(patched) == 2

    def test_tool_call_id_none_orphan_is_dropped(self):
        """A ToolMessage whose tool_call_id is None is always an orphan —
        no valid tool call uses ``None`` as its id — and must be dropped."""
        mw = DanglingToolCallMiddleware()
        # Use model_construct to bypass pydantic validation (ToolMessage requires
        # a string tool_call_id at construction, but a corrupt serialized payload
        # or edge-case provider could still produce None at runtime).
        none_id_orphan = ToolMessage.model_construct(content="ghost", tool_call_id=None)
        msgs = [
            _ai_with_tool_calls([_tc("bash", "call_1")]),
            none_id_orphan,
            _tool_msg("call_1", "bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert none_id_orphan not in patched
        assert len(patched) == 2
        assert isinstance(patched[0], AIMessage)
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == "call_1"

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
        assert "write_file failed before execution" in patched[1].content
        assert "no file was written" in patched[1].content
        assert "very large Markdown file in a single tool call" in patched[1].content
        assert "Do not retry the same large `write_file` payload" in patched[1].content
        assert "split the file into smaller sections" in patched[1].content
        assert "normal assistant text" in patched[1].content
        assert "Failed to parse tool arguments" in patched[1].content
        assert 'bad {"json"}' not in patched[1].content

    def test_non_write_file_invalid_tool_call_uses_generic_recovery_message(self):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_invalid_tool_calls([_invalid_tc(name="search", tc_id="search:1")])]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[1].tool_call_id == "search:1"
        assert patched[1].name == "search"
        assert "arguments were invalid" in patched[1].content
        assert "Failed to parse tool arguments" in patched[1].content
        assert "write_file failed before execution" not in patched[1].content

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
