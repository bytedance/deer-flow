"""Tests for the shared model-bound tool-call argument rewriter (``tool_call_args``)."""

import json

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from deerflow.agents.middlewares.tool_call_args import rewrite_messages_tool_call_args, rewrite_tool_call_args

ARGS = {"path": "/mnt/user-data/outputs/report.md", "content": "x" * 50}
NEW_ARGS = {"path": "/mnt/user-data/outputs/report.md", "content": "[elided]"}


def _full_surface_message(call_id="call-1"):
    """An AIMessage carrying the same call on every surface a provider adapter may read."""
    return AIMessage(
        content=[
            {"type": "text", "text": "writing"},
            {"type": "tool_use", "id": call_id, "name": "write_file", "input": dict(ARGS), "partial_json": json.dumps(ARGS)},
        ],
        tool_calls=[{"name": "write_file", "id": call_id, "args": dict(ARGS)}],
        additional_kwargs={"tool_calls": [{"id": call_id, "type": "function", "function": {"name": "write_file", "arguments": json.dumps(ARGS)}}]},
    )


class TestRewriteToolCallArgs:
    def test_no_matching_id_returns_same_object(self):
        message = _full_surface_message()
        assert rewrite_tool_call_args(message, {"other": NEW_ARGS}) is message
        assert rewrite_tool_call_args(message, {}) is message

    def test_rewrites_every_surface_together(self):
        message = _full_surface_message()

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        assert rewritten is not message
        assert rewritten.tool_calls[0]["args"] == NEW_ARGS
        assert rewritten.tool_calls[0]["name"] == "write_file"
        raw = rewritten.additional_kwargs["tool_calls"][0]
        assert json.loads(raw["function"]["arguments"]) == NEW_ARGS
        assert raw["function"]["name"] == "write_file"
        assert rewritten.content[0] == {"type": "text", "text": "writing"}
        assert rewritten.content[1] == {"type": "tool_use", "id": "call-1", "name": "write_file", "input": NEW_ARGS}
        assert "x" * 50 not in json.dumps(rewritten.model_dump(), ensure_ascii=False)

    def test_original_message_is_never_mutated(self):
        message = _full_surface_message()

        rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        assert message.tool_calls[0]["args"] == ARGS
        assert message.content[1]["input"] == ARGS
        assert "partial_json" in message.content[1]
        assert json.loads(message.additional_kwargs["tool_calls"][0]["function"]["arguments"]) == ARGS

    def test_untouched_sibling_calls_keep_identity(self):
        other = {"name": "bash", "id": "call-2", "args": {"command": "ls"}}
        message = AIMessage(content="", tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}, other])

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        # AIMessage validation copies tool-call dicts at construction, so identity is against the message's own list.
        assert rewritten.tool_calls[1] is message.tool_calls[1]
        assert rewritten.tool_calls[1]["args"] == other["args"]
        assert rewritten.tool_calls[0]["args"] == NEW_ARGS

    def test_rewrites_chunk_surfaces(self):
        chunk = AIMessageChunk(content="", tool_call_chunks=[{"name": "write_file", "args": json.dumps(ARGS), "id": "call-1", "index": 0}])
        assert chunk.tool_calls[0]["args"] == ARGS

        rewritten = rewrite_tool_call_args(chunk, {"call-1": NEW_ARGS})

        assert rewritten.tool_calls[0]["args"] == NEW_ARGS
        assert json.loads(rewritten.tool_call_chunks[0]["args"]) == NEW_ARGS
        assert rewritten.tool_call_chunks[0]["index"] == 0
        assert chunk.tool_call_chunks[0]["args"] == json.dumps(ARGS)

    def test_flattened_raw_provider_variants(self):
        message = AIMessage(
            content="",
            tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}, {"name": "write_file", "id": "call-2", "args": dict(ARGS)}],
            additional_kwargs={
                "tool_calls": [
                    {"id": "call-1", "name": "write_file", "arguments": json.dumps(ARGS)},
                    {"id": "call-2", "name": "write_file", "args": dict(ARGS)},
                    {"id": "call-3", "name": "write_file"},
                    "not-a-dict",
                ]
            },
        )

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS, "call-2": NEW_ARGS, "call-3": NEW_ARGS})

        raw = rewritten.additional_kwargs["tool_calls"]
        assert json.loads(raw[0]["arguments"]) == NEW_ARGS
        assert raw[1]["args"] == NEW_ARGS
        assert raw[2] is message.additional_kwargs["tool_calls"][2]
        assert raw[3] == "not-a-dict"

    def test_non_string_ids_never_match(self):
        message = AIMessage(
            content=[{"type": "tool_use", "id": ["list", "id"], "name": "write_file", "input": dict(ARGS)}],
            tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}],
            additional_kwargs={"tool_calls": [{"id": {"dict": "id"}, "type": "function", "function": {"name": "write_file", "arguments": json.dumps(ARGS)}}]},
        )

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        assert rewritten.tool_calls[0]["args"] == NEW_ARGS
        assert rewritten.content[0]["input"] == ARGS
        assert json.loads(rewritten.additional_kwargs["tool_calls"][0]["function"]["arguments"]) == ARGS

    def test_result_is_deterministic(self):
        message = _full_surface_message()
        first = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})
        second = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})
        assert first.model_dump() == second.model_dump()


class TestRewriteMessagesToolCallArgs:
    def test_returns_none_when_nothing_replaced(self):
        messages = [HumanMessage(content="go"), _full_surface_message(), ToolMessage(content="ok", tool_call_id="call-1", name="write_file")]
        assert rewrite_messages_tool_call_args(messages, lambda _message, _tool_call: None) is None
        assert rewrite_messages_tool_call_args([], lambda _message, _tool_call: NEW_ARGS) is None

    def test_selector_sees_message_and_call_and_untouched_messages_keep_identity(self):
        human = HumanMessage(content="go")
        target = _full_surface_message("call-1")
        other = AIMessage(content="", tool_calls=[{"name": "bash", "id": "call-2", "args": {"command": "ls"}}])
        tool = ToolMessage(content="ok", tool_call_id="call-1", name="write_file")
        seen = []

        def replacement_for(message, tool_call):
            seen.append((message, tool_call["id"]))
            return NEW_ARGS if tool_call["name"] == "write_file" else None

        rewritten = rewrite_messages_tool_call_args([human, target, other, tool], replacement_for)

        assert seen == [(target, "call-1"), (other, "call-2")]
        assert rewritten[0] is human
        assert rewritten[1] is not target
        assert rewritten[1].tool_calls[0]["args"] == NEW_ARGS
        assert rewritten[2] is other
        assert rewritten[3] is tool
        assert target.tool_calls[0]["args"] == ARGS

    def test_calls_without_a_string_id_are_not_offered(self):
        message = AIMessage(content="", tool_calls=[{"name": "write_file", "id": None, "args": dict(ARGS)}])
        offered = []

        assert rewrite_messages_tool_call_args([message], lambda _m, tc: offered.append(tc) or NEW_ARGS) is None
        assert offered == []
