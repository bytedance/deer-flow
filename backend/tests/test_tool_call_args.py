"""Tests for the shared model-bound tool-call argument rewriter (``tool_call_args``)."""

import json

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from deerflow.agents.middlewares.tool_call_args import pair_tool_call_results, rewrite_messages_tool_call_args, rewrite_tool_call_args

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


RESPONSES_V1_BLOCK = {"type": "function_call", "id": "fc_1", "call_id": "call-1", "name": "write_file", "arguments": json.dumps(ARGS), "status": "completed"}
V1_BLOCK = {"type": "tool_call", "id": "call-1", "name": "write_file", "args": dict(ARGS), "extras": {"item_id": "fc_1", "arguments": json.dumps(ARGS), "status": "completed"}}
V1_CHUNK_BLOCK = {"type": "tool_call_chunk", "id": "call-1", "name": "write_file", "args": json.dumps(ARGS), "index": 0, "extras": {"item_id": "fc_1"}}


def _responses_v1_message():
    return AIMessage(content=[{"type": "text", "text": "writing"}, dict(RESPONSES_V1_BLOCK)], tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}], response_metadata={"output_version": "responses/v1"})


def _v1_message():
    return AIMessage(content=[{"type": "text", "text": "writing"}, {**V1_BLOCK, "extras": dict(V1_BLOCK["extras"])}], tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}], response_metadata={"output_version": "v1"})


class TestContentBlockVariants:
    """Every content-block dialect that carries its own copy of the arguments is rewritten, ids preserved."""

    def test_responses_function_call_block_matched_by_call_id_keeps_item_id(self):
        message = _responses_v1_message()

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        block = rewritten.content[1]
        assert json.loads(block["arguments"]) == NEW_ARGS
        assert block["id"] == "fc_1"
        assert block["call_id"] == "call-1"
        assert block["status"] == "completed"
        assert rewritten.content[0] is message.content[0]
        assert json.loads(message.content[1]["arguments"]) == ARGS

    def test_responses_function_call_block_ignores_item_id_as_match_key(self):
        message = _responses_v1_message()
        assert rewrite_tool_call_args(message, {"fc_1": NEW_ARGS}) is message

    def test_v1_tool_call_block_rewrites_args_and_extras_arguments(self):
        message = _v1_message()

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        block = rewritten.content[1]
        assert block["args"] == NEW_ARGS
        assert json.loads(block["extras"]["arguments"]) == NEW_ARGS
        assert block["extras"]["item_id"] == "fc_1"
        assert block["extras"]["status"] == "completed"
        assert message.content[1]["args"] == ARGS
        assert json.loads(message.content[1]["extras"]["arguments"]) == ARGS

    def test_v1_tool_call_block_without_extras_arguments_gets_no_extras_entry(self):
        block = {"type": "tool_call", "id": "call-1", "name": "write_file", "args": dict(ARGS), "extras": {"item_id": "fc_1"}}
        message = AIMessage(content=[block], tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}])

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        assert rewritten.content[0]["args"] == NEW_ARGS
        assert rewritten.content[0]["extras"] == {"item_id": "fc_1"}

    def test_v1_tool_call_chunk_block_rewrites_serialized_args(self):
        chunk = AIMessageChunk(content=[dict(V1_CHUNK_BLOCK)], tool_call_chunks=[{"name": "write_file", "args": json.dumps(ARGS), "id": "call-1", "index": 0}])

        rewritten = rewrite_tool_call_args(chunk, {"call-1": NEW_ARGS})

        assert json.loads(rewritten.content[0]["args"]) == NEW_ARGS
        assert rewritten.content[0]["extras"] == {"item_id": "fc_1"}
        assert rewritten.content[0]["index"] == 0
        assert json.loads(rewritten.tool_call_chunks[0]["args"]) == NEW_ARGS
        assert json.loads(chunk.content[0]["args"]) == ARGS

    def test_unrelated_block_types_pass_through_by_identity(self):
        reasoning = {"type": "reasoning", "id": "rs_1", "summary": []}
        message = AIMessage(content=[reasoning, dict(RESPONSES_V1_BLOCK)], tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}])

        rewritten = rewrite_tool_call_args(message, {"call-1": NEW_ARGS})

        assert rewritten.content[0] is message.content[0]


class TestProviderSerializers:
    """Lock the rewrite against the real adapter request builders: the payload must not reach the wire."""

    PAYLOAD = ARGS["content"]

    @staticmethod
    def _responses_input(message):
        from langchain_openai.chat_models.base import _construct_responses_api_input

        return _construct_responses_api_input([message])

    def _function_calls(self, message):
        items = self._responses_input(message)
        assert self.PAYLOAD not in json.dumps(items, ensure_ascii=False)
        return [item for item in items if item.get("type") == "function_call"]

    def test_responses_v1_content_sends_rewritten_arguments_once(self):
        calls = self._function_calls(rewrite_tool_call_args(_responses_v1_message(), {"call-1": NEW_ARGS}))

        assert len(calls) == 1
        assert json.loads(calls[0]["arguments"]) == NEW_ARGS
        assert calls[0]["call_id"] == "call-1"
        assert calls[0]["id"] == "fc_1"

    def test_v1_content_sends_rewritten_arguments_once(self):
        calls = self._function_calls(rewrite_tool_call_args(_v1_message(), {"call-1": NEW_ARGS}))

        assert len(calls) == 1
        assert json.loads(calls[0]["arguments"]) == NEW_ARGS
        assert calls[0]["call_id"] == "call-1"
        assert calls[0]["id"] == "fc_1"

    def test_v0_responses_message_sends_rewritten_arguments_with_item_id(self):
        message = AIMessage(
            content=[{"type": "text", "text": "writing"}],
            tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(ARGS)}],
            additional_kwargs={"__openai_function_call_ids__": {"call-1": "fc_1"}},
        )

        calls = self._function_calls(rewrite_tool_call_args(message, {"call-1": NEW_ARGS}))

        assert len(calls) == 1
        assert json.loads(calls[0]["arguments"]) == NEW_ARGS
        assert calls[0]["id"] == "fc_1"

    def test_unrewritten_responses_message_still_carries_payload(self):
        """Sanity check that the probe can see the payload at all."""
        items = self._responses_input(_responses_v1_message())
        assert self.PAYLOAD in json.dumps(items, ensure_ascii=False)

    def test_chat_completions_payload_uses_rewritten_arguments(self):
        from langchain_openai.chat_models.base import _convert_message_to_dict

        payload = _convert_message_to_dict(rewrite_tool_call_args(_full_surface_message(), {"call-1": NEW_ARGS}))

        assert json.loads(payload["tool_calls"][0]["function"]["arguments"]) == NEW_ARGS
        assert self.PAYLOAD not in json.dumps(payload, ensure_ascii=False)

    def test_anthropic_native_tool_use_payload_uses_rewritten_input(self):
        from langchain_anthropic.chat_models import _format_messages

        _system, formatted = _format_messages([rewrite_tool_call_args(_full_surface_message(), {"call-1": NEW_ARGS})])

        tool_use = [block for block in formatted[0]["content"] if block["type"] == "tool_use"]
        assert len(tool_use) == 1
        assert tool_use[0]["input"] == NEW_ARGS
        assert self.PAYLOAD not in json.dumps(formatted, ensure_ascii=False)

    def test_anthropic_v1_content_payload_uses_rewritten_input(self):
        from langchain_anthropic._compat import _convert_from_v1_to_anthropic
        from langchain_anthropic.chat_models import _format_messages

        rewritten = rewrite_tool_call_args(_v1_message(), {"call-1": NEW_ARGS})
        # Mirrors ChatAnthropic._get_request_payload's v1 translation step.
        tcs = [{"type": "tool_call", "name": tc["name"], "args": tc["args"], "id": tc.get("id")} for tc in rewritten.tool_calls]
        translated = rewritten.model_copy(update={"content": _convert_from_v1_to_anthropic(rewritten.content, tcs, "anthropic")})

        _system, formatted = _format_messages([translated])

        tool_use = [block for block in formatted[0]["content"] if block["type"] == "tool_use"]
        assert len(tool_use) == 1
        assert tool_use[0]["input"] == NEW_ARGS
        assert self.PAYLOAD not in json.dumps(formatted, ensure_ascii=False)


class TestResponseChainInvalidation:
    """A rewritten history must be replayed, never chained to the original server-side copy."""

    PAYLOAD = ARGS["content"]

    @staticmethod
    def _chained_history(rewritten_call=True):
        first = AIMessage(content=[{"type": "text", "text": "earlier"}], response_metadata={"id": "resp_a", "model_name": "gpt-x"})
        call = _responses_v1_message()
        call = call.model_copy(update={"response_metadata": {**call.response_metadata, "id": "resp_b", "model_name": "gpt-x"}})
        tool = ToolMessage(content="Error: blocked", tool_call_id="call-1", name="write_file", status="error")
        later = AIMessage(content=[{"type": "text", "text": "later"}], response_metadata={"id": "resp_c"})
        return [HumanMessage(content="go"), first, call, tool, later]

    def test_rewrite_drops_resp_ids_from_every_ai_message(self):
        messages = self._chained_history()

        rewritten = rewrite_messages_tool_call_args(messages, lambda _m, tc: NEW_ARGS if tc["id"] == "call-1" else None)

        assert [type(m) for m in rewritten] == [type(m) for m in messages]
        for index in (1, 2, 4):
            assert "id" not in rewritten[index].response_metadata
            assert rewritten[index] is not messages[index]
        assert rewritten[1].response_metadata == {"model_name": "gpt-x"}
        assert rewritten[2].tool_calls[0]["args"] == NEW_ARGS
        assert rewritten[0] is messages[0]
        assert rewritten[3] is messages[3]
        # Stored history keeps its chain ids and arguments.
        assert messages[1].response_metadata["id"] == "resp_a"
        assert messages[2].response_metadata["id"] == "resp_b"
        assert messages[4].response_metadata["id"] == "resp_c"
        assert messages[2].tool_calls[0]["args"] == ARGS

    def test_non_resp_ids_are_left_alone(self):
        anthropic_style = AIMessage(content="earlier", response_metadata={"id": "msg_01", "model": "claude"})
        messages = [anthropic_style, _full_surface_message(), ToolMessage(content="ok", tool_call_id="call-1", name="write_file")]

        rewritten = rewrite_messages_tool_call_args(messages, lambda _m, tc: NEW_ARGS)

        assert rewritten[0] is anthropic_style
        assert rewritten[0].response_metadata["id"] == "msg_01"

    def test_no_rewrite_keeps_chain_ids(self):
        messages = self._chained_history()
        assert rewrite_messages_tool_call_args(messages, lambda _m, _tc: None) is None
        assert messages[2].response_metadata["id"] == "resp_b"

    @staticmethod
    def _chained_model():
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model="gpt-4.1", api_key="test-key", use_responses_api=True, use_previous_response_id=True)

    def test_unrewritten_history_chains_and_never_sends_the_call(self):
        """Documents the leak: with chaining on, the adapter sends only the tail after the last resp_ id."""
        payload = self._chained_model()._get_request_payload(self._chained_history()[:4])

        assert payload["previous_response_id"] == "resp_b"
        assert [item["type"] for item in payload["input"]] == ["function_call_output"]

    def test_rewritten_history_is_replayed_with_rewritten_arguments(self):
        messages = self._chained_history()[:4]
        rewritten = rewrite_messages_tool_call_args(messages, lambda _m, tc: NEW_ARGS if tc["id"] == "call-1" else None)

        payload = self._chained_model()._get_request_payload(rewritten)

        assert "previous_response_id" not in payload
        calls = [item for item in payload["input"] if item.get("type") == "function_call"]
        assert len(calls) == 1
        assert json.loads(calls[0]["arguments"]) == NEW_ARGS
        assert calls[0]["id"] == "fc_1"
        assert any(item.get("type") == "function_call_output" for item in payload["input"])
        assert self.PAYLOAD not in json.dumps(payload, ensure_ascii=False)


class TestPairToolCallResults:
    """Per-occurrence pairing of AIMessage tool calls with the ToolMessage that answered them."""

    @staticmethod
    def _call(call_id, name="bash", args=None):
        return {"name": name, "id": call_id, "args": {"command": "ls"} if args is None else args}

    def test_pairs_each_call_with_the_result_that_answered_it(self):
        ai = AIMessage(content="", tool_calls=[self._call("call-1"), self._call("call-2")])
        first = ToolMessage(content="1", tool_call_id="call-1")
        second = ToolMessage(content="2", tool_call_id="call-2")

        occurrences = pair_tool_call_results([HumanMessage(content="go"), ai, second, first])

        assert [(o.index, o.message is ai, o.call_id, o.result) for o in occurrences] == [(1, True, "call-1", first), (1, True, "call-2", second)]
        assert occurrences[0].name == "bash"
        assert occurrences[0].args == {"command": "ls"}

    def test_unanswered_call_gets_no_result(self):
        ai = AIMessage(content="", tool_calls=[self._call("call-1")])

        occurrences = pair_tool_call_results([ai])

        assert len(occurrences) == 1
        assert occurrences[0].result is None

    def test_reused_ids_pair_per_occurrence_in_history_order(self):
        first_ai = AIMessage(content="", tool_calls=[self._call("call-1")])
        first_result = ToolMessage(content="first", tool_call_id="call-1")
        second_ai = AIMessage(content="", tool_calls=[self._call("call-1")])
        second_result = ToolMessage(content="second", tool_call_id="call-1")

        occurrences = pair_tool_call_results([first_ai, first_result, second_ai, second_result])

        assert [(o.index, o.result) for o in occurrences] == [(0, first_result), (2, second_result)]

    def test_calls_without_a_string_id_are_skipped(self):
        ai = AIMessage(content="", tool_calls=[self._call("call-1"), {"name": "bash", "id": None, "args": {}}, {"name": "bash", "id": "", "args": {}}])
        ai.tool_calls.append({"name": "bash", "id": ["not", "a", "string"], "args": {}})

        occurrences = pair_tool_call_results([ai, ToolMessage(content="1", tool_call_id="call-1")])

        assert [o.call_id for o in occurrences] == ["call-1"]

    def test_non_ai_messages_and_non_dict_calls_are_ignored(self):
        ai = AIMessage(content="", tool_calls=[self._call("call-1")])
        ai.tool_calls.append("not-a-dict")  # malformed provider payload

        occurrences = pair_tool_call_results([HumanMessage(content="go"), ToolMessage(content="stray", tool_call_id="call-9"), ai])

        assert [o.call_id for o in occurrences] == ["call-1"]

    def test_accessors_tolerate_malformed_calls(self):
        ai = AIMessage(content="", tool_calls=[self._call("call-1")])
        # Malformed provider payloads can only get here past construction-time validation.
        ai.tool_calls[0]["args"] = "not-a-dict"
        del ai.tool_calls[0]["name"]

        (occurrence,) = pair_tool_call_results([ai])

        assert occurrence.name == ""
        assert occurrence.args == {}
        assert occurrence.call_id == "call-1"

    def test_empty_history_pairs_nothing(self):
        assert pair_tool_call_results([]) == []
