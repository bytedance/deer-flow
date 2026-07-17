"""Tests for DanglingToolCallMiddleware."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# Intentional private import: these tests lock the OpenAI serialization boundary
# that strict providers reject when assistant tool-call names or arguments are malformed.
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

    def test_issue_4172_mixed_tool_calls_serialize_with_valid_names_and_arguments(self):
        mw = DanglingToolCallMiddleware()
        invalid_args = '{"description": "读取CSV数据文件前部内容", "path": "/mnt/user-data/uploads/test2.csv"}}'
        ai_message = AIMessage(
            content="",
            tool_calls=[
                _tc("read_file", "valid_call"),
                _tc("", "empty_name_call"),
            ],
            invalid_tool_calls=[
                {
                    "type": "invalid_tool_call",
                    "id": "invalid_args_call",
                    "name": "read_file",
                    "args": invalid_args,
                    "error": None,
                }
            ],
        )
        msgs = [
            ai_message,
            _tool_msg("valid_call", "read_file"),
            ToolMessage(
                content="Error: invalid tool",
                tool_call_id="empty_name_call",
                name="",
                status="error",
            ),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        payload = _convert_message_to_dict(patched[0])
        assert all(call["function"]["name"] for call in payload["tool_calls"])
        assert [json.loads(call["function"]["arguments"]) for call in payload["tool_calls"]] == [
            {},
            {},
            {},
        ]
        assert ai_message.invalid_tool_calls[0]["args"] == invalid_args
        tool_messages = [message for message in patched if isinstance(message, ToolMessage)]
        assert [message.tool_call_id for message in tool_messages] == [
            "valid_call",
            "empty_name_call",
            "invalid_args_call",
        ]
        assert tool_messages[1].name == "unknown_tool"
        assert tool_messages[2].status == "error"

    def test_empty_name_and_malformed_arguments_in_invalid_tool_call_are_sanitized(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_invalid_tool_calls(
                [
                    _invalid_tc(
                        name="",
                        tc_id="empty_invalid_call",
                        error="Failed to parse tool arguments: malformed JSON",
                    )
                ]
            )
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        payload_call = _convert_message_to_dict(patched[0])["tool_calls"][0]
        assert payload_call["function"]["name"] == "unknown_tool"
        assert json.loads(payload_call["function"]["arguments"]) == {}

    @pytest.mark.parametrize(
        "arguments",
        [
            '{"path":"/tmp/data.csv"}}',
            None,
            '["not", "an", "object"]',
            {"path": "/tmp/data.csv"},
        ],
    )
    def test_raw_provider_tool_call_arguments_are_sanitized(self, arguments):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage.model_construct(
                content="",
                type="ai",
                tool_calls=[],
                invalid_tool_calls=[],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "raw_invalid_args_call",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": arguments},
                        }
                    ]
                },
                response_metadata={},
            )
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        raw_arguments = patched[0].additional_kwargs["tool_calls"][0]["function"]["arguments"]
        assert json.loads(raw_arguments) == (arguments if isinstance(arguments, dict) else {})

    def test_valid_invalid_tool_call_arguments_are_sanitization_noop(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_invalid_tool_calls(
                [
                    {
                        "type": "invalid_tool_call",
                        "id": "valid_args_call",
                        "name": "read_file",
                        "args": '{"path": "/tmp/data.csv"}',
                        "error": "schema validation failed",
                    }
                ]
            ),
            _tool_msg("valid_args_call", "read_file"),
        ]

        assert mw._build_patched_messages(msgs) is None

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

    def test_invalid_tool_call_already_responded_is_sanitized_without_placeholder(self):
        mw = DanglingToolCallMiddleware()
        ai_message = _ai_with_invalid_tool_calls([_invalid_tc()])
        tool_message = _tool_msg("write_file:36", "write_file")
        msgs = [
            ai_message,
            tool_message,
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert patched[1] is tool_message
        assert json.loads(_convert_message_to_dict(patched[0])["tool_calls"][0]["function"]["arguments"]) == {}
        assert ai_message.invalid_tool_calls[0]["args"] == _invalid_tc()["args"]


class TestMalformedToolCallIdRecovery:
    """Empty/missing tool-call ids get the same recovery as empty names (#4008).

    A provider that omits the id parses into a well-formed ``tool_calls`` entry with
    ``id=""``/``None``, so these reach the middleware through the normal path.
    """

    @pytest.mark.parametrize("tc_id", ["", "   ", None])
    def test_malformed_structured_tool_call_id_is_normalized(self, tc_id):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_tool_calls([_tc("bash", tc_id)])]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        normalized_id = patched[0].tool_calls[0]["id"]
        assert normalized_id
        assert normalized_id.strip()
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["id"] == normalized_id
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].tool_call_id == normalized_id
        assert patched[1].status == "error"

    def test_empty_tool_call_id_keeps_its_paired_tool_result(self):
        """The destructive case: the result exists, so it must survive and stay paired.

        Without id normalization the empty id never enters the pairing set, so the
        real result is dropped as an orphan while the AIMessage keeps ``id=""``.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "")]),
            ToolMessage(content="REAL RESULT", tool_call_id="", name="bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert len(patched) == 2
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].content == "REAL RESULT"
        assert patched[1].tool_call_id == patched[0].tool_calls[0]["id"]
        assert patched[1].status != "error"

    def test_multiple_empty_ids_get_distinct_ids_and_pair_in_order(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", ""), _tc("ls", "")]),
            ToolMessage(content="first", tool_call_id="", name="bash"),
            ToolMessage(content="second", tool_call_id="", name="ls"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        first_id, second_id = (tc["id"] for tc in patched[0].tool_calls)
        assert first_id != second_id
        assert [m.content for m in patched[1:]] == ["first", "second"]
        assert [m.tool_call_id for m in patched[1:]] == [first_id, second_id]

    def test_empty_id_invalid_tool_call_is_normalized(self):
        mw = DanglingToolCallMiddleware()
        msgs = [_ai_with_invalid_tool_calls([_invalid_tc(tc_id="")])]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        normalized_id = patched[0].invalid_tool_calls[0]["id"]
        assert normalized_id
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["id"] == normalized_id
        assert patched[1].tool_call_id == normalized_id

    def test_empty_id_raw_provider_tool_call_is_normalized(self):
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage.model_construct(
                content="",
                type="ai",
                tool_calls=[],
                invalid_tool_calls=[],
                additional_kwargs={"tool_calls": [{"id": "", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
                response_metadata={},
            )
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        normalized_id = patched[0].additional_kwargs["tool_calls"][0]["id"]
        assert normalized_id
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["id"] == normalized_id
        assert patched[1].tool_call_id == normalized_id

    def test_only_the_serialized_view_of_a_call_gets_a_recovered_id(self):
        """When both views of one call are present, only the read one is relabelled.

        ``_message_tool_calls`` and the OpenAI serializer both prefer structured
        tool_calls and ignore the raw payload while they coexist. Relabelling raw here
        would invent a *second* id for a call that already got one, so the two views of
        the same call would disagree; the raw ids cannot simply be copied from
        structured either, since a partially-parsed turn splits calls across
        ``invalid_tool_calls`` and breaks positional alignment.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            AIMessage.model_construct(
                content="",
                type="ai",
                tool_calls=[_tc("bash", "")],
                invalid_tool_calls=[],
                additional_kwargs={"tool_calls": [{"id": "", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
                response_metadata={},
            )
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        recovered_id = patched[0].tool_calls[0]["id"]
        assert recovered_id
        payload = _convert_message_to_dict(patched[0])
        assert payload["tool_calls"][0]["id"] == recovered_id
        assert patched[1].tool_call_id == recovered_id
        # The unread view keeps the provider's value rather than a second invented id.
        assert patched[0].additional_kwargs["tool_calls"][0]["id"] == ""
        # ...which is only safe while the serializer ignores raw once structured exists.
        # If that ever changes, the id="" above would ride onto the wire as a second
        # tool_calls entry and cause the 400 this recovery exists to prevent.
        assert len(payload["tool_calls"]) == 1

    def test_raw_view_shadowed_by_invalid_calls_gets_no_placeholder(self):
        """A shadowed raw payload is not a call of its own, so it is owed no placeholder.

        ``_convert_message_to_dict`` serializes ``tool_calls + invalid_tool_calls`` and
        reaches for the raw ``additional_kwargs`` view only in its ``elif`` — i.e. never
        while *either* structured view is non-empty. Relabelling raw here would mint a
        second id for a call the provider never sees, and that id's placeholder would
        reach the wire as a tool result with no matching tool_call: the exact HTTP 400
        this middleware exists to prevent. Sibling of
        ``test_only_the_serialized_view_of_a_call_gets_a_recovered_id`` — there the
        shadowing view is ``tool_calls``, here it is ``invalid_tool_calls``.

        This is the realistic malformed-``write_file`` shape (#2894): LangChain parks the
        parse failure in ``invalid_tool_calls`` while the raw payload stays in
        ``additional_kwargs``, so both views describe one call.
        """
        mw = DanglingToolCallMiddleware()
        bad_args = '{"path": "/mnt/user-data/outputs/report.md", "content": "## Report {"'
        msgs = [
            AIMessage.model_construct(
                content="",
                type="ai",
                tool_calls=[],
                invalid_tool_calls=[{"name": "write_file", "args": bad_args, "id": "", "error": "Unterminated string"}],
                additional_kwargs={"tool_calls": [{"id": "", "type": "function", "function": {"name": "write_file", "arguments": bad_args}}]},
                response_metadata={},
            ),
            ToolMessage(content="REAL RESULT", tool_call_id="", name="write_file"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        # Assert on the serialized request, because that is where a strict provider rejects.
        wire = [_convert_message_to_dict(m) for m in patched]
        call_ids = [tc["id"] for m in wire if m["role"] == "assistant" for tc in m.get("tool_calls", [])]
        result_ids = [m["tool_call_id"] for m in wire if m["role"] == "tool"]
        assert [i for i in result_ids if i not in call_ids] == []
        assert len(call_ids) == 1
        assert result_ids == call_ids
        assert patched[1].content == "REAL RESULT"

    def test_none_id_call_reclaims_its_own_none_id_result(self):
        """A ``None``-id result is an orphan only when no call used ``None`` as its id.

        Sibling of ``test_tool_call_id_none_orphan_is_dropped``: there the call's id is
        valid, so the result stays an orphan. Here the call itself carries the ``None``
        id, so the result is its own and must follow the call to its recovered id
        instead of being dropped. Both are reachable only from a corrupt serialized
        payload, which is why the ToolMessage is built with ``model_construct``.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", None)]),
            ToolMessage.model_construct(content="REAL RESULT", tool_call_id=None),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert len(patched) == 2
        assert isinstance(patched[1], ToolMessage)
        assert patched[1].content == "REAL RESULT"
        assert patched[1].tool_call_id == patched[0].tool_calls[0]["id"]

    def test_dangling_call_does_not_consume_a_later_turns_result(self):
        """A result answers the turn that issued it, never an earlier dangling call.

        Malformed originals are all equally empty, so pairing on the original id alone
        lets the first empty-id call claim a later turn's result: the real result is
        served to the wrong call while the call that actually ran gets the placeholder.
        The retried tool shares the interrupted one's name — the realistic shape, and
        the one where nothing but document order can tell the two turns apart.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", "")]),  # interrupted: never produced a result
            _ai_with_tool_calls([_tc("bash", "")]),  # retried, and this one ran
            ToolMessage(content="REAL RESULT", tool_call_id="", name="bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        interrupted_call, interrupted_result, retried_call, retried_result = patched
        assert interrupted_result.tool_call_id == interrupted_call.tool_calls[0]["id"]
        assert interrupted_result.status == "error"
        assert retried_result.tool_call_id == retried_call.tool_calls[0]["id"]
        assert retried_result.content == "REAL RESULT"

    def test_orphan_result_is_not_adopted_by_a_later_malformed_call(self):
        """An orphan malformed result stays an orphan and is dropped.

        A result whose originating AIMessage is gone (e.g. dropped by summarization)
        has no call to return to. Pairing on the original id alone lets a *later*
        malformed call adopt it, resurrecting a stale result as the answer to a call
        that never produced it — and swallowing the placeholder that call is owed.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            ToolMessage(content="STALE ORPHAN", tool_call_id="", name="search"),
            HumanMessage(content="continue"),
            _ai_with_tool_calls([_tc("write_file", "")]),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert all(getattr(m, "content", None) != "STALE ORPHAN" for m in patched)
        human, write_call, write_result = patched
        assert isinstance(human, HumanMessage)
        assert write_result.tool_call_id == write_call.tool_calls[0]["id"]
        assert write_result.status == "error"

    def test_sibling_call_does_not_consume_its_neighbours_result(self):
        """Parallel calls in one turn: the result goes to the sibling that ran.

        Interrupting one of several parallel calls is this middleware's own trigger,
        and within a turn the empty originals cannot tell the siblings apart either.
        The result's name can, so it must not be handed to whichever sibling is first.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("search", ""), _tc("write_file", "")]),
            ToolMessage(content="REAL RESULT", tool_call_id="", name="write_file"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        search_id, write_id = (tc["id"] for tc in patched[0].tool_calls)
        results = {m.tool_call_id: m for m in patched[1:]}
        assert results[write_id].content == "REAL RESULT"
        assert results[search_id].status == "error"

    def test_nameless_result_is_dropped_when_several_siblings_are_eligible(self):
        """With nothing to tell two malformed siblings apart, the result names neither.

        ``ToolMessage.name`` is optional, and a missing name cannot contradict any call,
        so every open call in the turn stays eligible. Handing the result to whichever
        sibling comes first is a guess: the interrupted call may be the first one, which
        would serve a real result to the wrong call and give the one that actually ran a
        placeholder — the same corruption as the cross-turn case, inside one turn.
        Position cannot break the tie here either: one call has no result at all, so the
        two no longer line up.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("search", ""), _tc("write_file", "")]),
            ToolMessage.model_construct(content="REAL RESULT", tool_call_id="", name=None),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert all(getattr(m, "content", None) != "REAL RESULT" for m in patched)
        assert [m.status for m in patched[1:]] == ["error", "error"]

    def test_identical_parallel_calls_pair_with_their_results_in_order(self):
        """Indistinguishable siblings that all answered are paired by position.

        Two ``bash`` calls cannot be told apart by name, so a per-result "claim only a
        unique candidate" rule would drop *both* real results and report two interrupted
        calls. Position is real evidence precisely because nothing is missing: LangGraph's
        ``ToolNode`` builds these results with ``asyncio.gather`` / ``executor.map`` over
        ``tool_calls``, which yield in input order regardless of completion order, so a
        fully answered turn lines up by construction. Contrast the test above, where one
        call is unanswered and that alignment is gone.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", ""), _tc("bash", "")]),
            ToolMessage(content="RESULT A", tool_call_id="", name="bash"),
            ToolMessage(content="RESULT B", tool_call_id="", name="bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        first_id, second_id = (tc["id"] for tc in patched[0].tool_calls)
        assert [m.tool_call_id for m in patched[1:]] == [first_id, second_id]
        assert [m.content for m in patched[1:]] == ["RESULT A", "RESULT B"]

    def test_identical_parallel_calls_drop_a_lone_ambiguous_result(self):
        """Position is only evidence while the turn is fully answered.

        Same two indistinguishable ``bash`` calls, but one result: the alignment that
        justifies pairing by position no longer holds, and the name cannot narrow the
        pair either, so there is no evidence tying the result to a call. Guards against
        the positional tie-break widening into a first-sibling default.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", ""), _tc("bash", "")]),
            ToolMessage(content="LONE RESULT", tool_call_id="", name="bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert all(getattr(m, "content", None) != "LONE RESULT" for m in patched)
        assert [m.status for m in patched[1:]] == ["error", "error"]

    def test_result_naming_no_call_is_dropped_rather_than_misattributed(self):
        """An unattributable result is dropped, not repurposed.

        When the name matches no open call there is no evidence tying the result to
        any of them. Dropping it is what it already gets today; handing it to an
        arbitrary call would invent a pairing and corrupt the transcript instead.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("search", ""), _tc("write_file", "")]),
            ToolMessage(content="RESULT OF NEITHER", tool_call_id="", name="grep"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        assert all(getattr(m, "content", None) != "RESULT OF NEITHER" for m in patched)
        assert [m.status for m in patched[1:]] == ["error", "error"]

    def test_valid_ids_are_left_byte_for_byte_unchanged(self):
        """Delta-set guard: normalization must only fire on malformed ids.

        A valid id is matched against ``ToolMessage.tool_call_id`` verbatim, so
        rewriting (e.g. stripping) one would break pairing that works today. The
        malformed sibling is what makes this assert on the patched output rather than
        on the no-op path: with only the whitespace id present the transcript is fully
        responded, ``_build_patched_messages`` returns ``None``, and the guarantee is
        never actually exercised through the rewriting code.
        """
        mw = DanglingToolCallMiddleware()
        msgs = [
            _ai_with_tool_calls([_tc("bash", " call_1 "), _tc("ls", "")]),
            ToolMessage(content="result", tool_call_id=" call_1 ", name="bash"),
        ]

        patched = mw._build_patched_messages(msgs)

        assert patched is not None
        kept_id, recovered_id = (tc["id"] for tc in patched[0].tool_calls)
        assert kept_id == " call_1 "
        assert recovered_id and recovered_id != " call_1 "
        results = {m.tool_call_id: m for m in patched[1:]}
        assert results[" call_1 "].content == "result"
        assert results[recovered_id].status == "error"


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
