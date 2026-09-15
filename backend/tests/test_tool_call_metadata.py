"""Tests for keeping AIMessage tool-call surfaces consistent when calls are removed.

Provider adapters re-serialize tool calls from ``AIMessage.content`` blocks, not
only from ``tool_calls``. A guard that strips a call from ``tool_calls`` but
leaves its content block behind sends the provider a tool call with no matching
tool result, which Anthropic and the OpenAI Responses API reject on every later
request for that thread.
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.models.claude_provider import ClaudeChatModel

# DeerFlow deployments use ClaudeChatModel, which post-processes the payload
# built by the upstream ChatAnthropic formatter; pin both.
_ANTHROPIC_MODEL_CLASSES = pytest.mark.parametrize("model_class", [ChatAnthropic, ClaudeChatModel], ids=["ChatAnthropic", "ClaudeChatModel"])


def _call(call_id: str, name: str = "bash") -> dict:
    return {"id": call_id, "name": name, "args": {}}


def _tool_use(call_id: str, name: str = "bash") -> dict:
    return {"type": "tool_use", "id": call_id, "name": name, "input": {}}


class TestContentToolCallBlockSync:
    def test_drops_anthropic_tool_use_blocks_for_removed_calls(self):
        message = AIMessage(
            content=[{"type": "text", "text": "running"}, _tool_use("a"), _tool_use("b")],
            tool_calls=[_call("a"), _call("b")],
        )

        cloned = clone_ai_message_with_tool_calls(message, [_call("a")])

        assert cloned.content == [{"type": "text", "text": "running"}, _tool_use("a")]
        assert [tc["id"] for tc in cloned.tool_calls] == ["a"]

    def test_clearing_every_call_keeps_non_tool_call_blocks(self):
        thinking = {"type": "thinking", "thinking": "hmm", "signature": "sig"}
        server_tool = {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {}}
        message = AIMessage(content=[thinking, server_tool, _tool_use("a")], tool_calls=[_call("a")])

        cloned = clone_ai_message_with_tool_calls(message, [])

        assert cloned.content == [thinking, server_tool]

    def test_filters_caller_supplied_content(self):
        message = AIMessage(content=[_tool_use("a")], tool_calls=[_call("a")])
        stop_note = {"type": "text", "text": "stopped"}

        cloned = clone_ai_message_with_tool_calls(message, [], content=[*message.content, stop_note])

        assert cloned.content == [stop_note]

    def test_openai_responses_blocks_match_by_call_id_not_item_id(self):
        kept = {"type": "function_call", "id": "fc_1", "call_id": "a", "name": "bash", "arguments": "{}"}
        dropped = {"type": "function_call", "id": "fc_2", "call_id": "b", "name": "bash", "arguments": "{}"}
        dropped_custom = {"type": "custom_tool_call", "id": "ctc_3", "call_id": "c", "name": "patch", "input": "x"}
        message = AIMessage(
            content=[kept, dropped, dropped_custom],
            tool_calls=[_call("a"), _call("b"), _call("c", "patch")],
        )

        cloned = clone_ai_message_with_tool_calls(message, [_call("a")])

        assert cloned.content == [kept]

    def test_langchain_standard_tool_call_blocks_match_by_id(self):
        kept = {"type": "tool_call", "id": "a", "name": "bash", "args": {}}
        dropped = {"type": "tool_call", "id": "b", "name": "bash", "args": {}}
        dropped_chunk = {"type": "tool_call_chunk", "id": "c", "name": "bash", "args": "{}", "index": 2}
        message = AIMessage(content=[kept, dropped, dropped_chunk], tool_calls=[_call("a"), _call("b"), _call("c")])

        cloned = clone_ai_message_with_tool_calls(message, [_call("a")])

        assert cloned.content == [kept]

    def test_google_genai_function_call_blocks_match_by_id(self):
        # Keep the second of two same-named calls: an id match keeps its own
        # block, where falling back to name order would keep the first one.
        dropped = {"type": "function_call", "id": "a", "name": "bash", "args": {}}
        kept = {"type": "function_call", "id": "b", "name": "bash", "args": {}}
        message = AIMessage(content=[dropped, kept], tool_calls=[_call("a"), _call("b")])

        cloned = clone_ai_message_with_tool_calls(message, [_call("b")])

        assert cloned.content == [kept]

    def test_idless_blocks_keep_only_as_many_per_name_as_retained_calls(self):
        # Gemini-style blocks carry no id, so they pair with retained calls by
        # name, in order: truncating four same-named calls to three keeps three.
        blocks = [{"type": "function_call", "name": "task", "args": {"n": n}} for n in range(4)]
        calls = [_call(f"t{n}", "task") for n in range(4)]
        message = AIMessage(content=list(blocks), tool_calls=calls)

        cloned = clone_ai_message_with_tool_calls(message, calls[:3])

        assert cloned.content == blocks[:3]

    def test_keeps_blocks_for_calls_that_remain_invalid_tool_calls(self):
        # DanglingToolCallMiddleware answers invalid_tool_calls with a placeholder
        # ToolMessage, so their content block must stay to pair with it.
        message = AIMessage(
            content=[_tool_use("bad"), _tool_use("a")],
            tool_calls=[_call("a")],
            invalid_tool_calls=[{"type": "invalid_tool_call", "id": "bad", "name": "bash", "args": "{", "error": "parse"}],
        )

        cloned = clone_ai_message_with_tool_calls(message, [])

        assert cloned.content == [_tool_use("bad")]
        assert [tc["id"] for tc in cloned.invalid_tool_calls] == ["bad"]

    def test_leaves_content_untouched_when_every_block_is_still_paired(self):
        content = [{"type": "text", "text": "hi"}, _tool_use("a")]
        message = AIMessage(content=content, tool_calls=[_call("a")])

        cloned = clone_ai_message_with_tool_calls(message, [_call("a")])

        assert cloned.content is message.content

    def test_string_content_is_unchanged(self):
        message = AIMessage(content="plain", tool_calls=[_call("a")])

        assert clone_ai_message_with_tool_calls(message, []).content == "plain"


def _anthropic_payload_turns(model_class: type[ChatAnthropic], messages: list) -> list[tuple[str, list[str]]]:
    payload = model_class(model="claude-sonnet-4-5", anthropic_api_key="sk-ant-offline")._get_request_payload(messages)
    turns = []
    for turn in payload["messages"]:
        blocks = turn["content"] if isinstance(turn["content"], list) else [{"type": "text"}]
        turns.append((turn["role"], [block.get("id") or block.get("tool_use_id") or block["type"] for block in blocks if block["type"] in ("tool_use", "tool_result")]))
    return turns


class TestProviderRequestContract:
    """Drive the real provider request builders offline; no network is used."""

    @_ANTHROPIC_MODEL_CLASSES
    def test_anthropic_request_pairs_every_tool_use_after_calls_are_cleared(self, model_class):
        message = AIMessage(
            content=[{"type": "text", "text": "reading"}, _tool_use("toolu_a")],
            tool_calls=[_call("toolu_a")],
            response_metadata={"model_provider": "anthropic"},
        )
        stopped = clone_ai_message_with_tool_calls(message, [], content=[*message.content, {"type": "text", "text": "stopped"}])

        turns = _anthropic_payload_turns(model_class, [HumanMessage("hi"), stopped, HumanMessage("continue")])

        assert turns == [("user", []), ("assistant", []), ("user", [])]

    @_ANTHROPIC_MODEL_CLASSES
    def test_anthropic_request_pairs_every_tool_use_after_calls_are_truncated(self, model_class):
        calls = [_call(f"toolu_{n}", "task") for n in range(3)]
        message = AIMessage(
            content=[_tool_use(call["id"], "task") for call in calls],
            tool_calls=calls,
            response_metadata={"model_provider": "anthropic"},
        )
        truncated = clone_ai_message_with_tool_calls(message, calls[:2])
        results = [ToolMessage(content="ok", tool_call_id=call["id"]) for call in truncated.tool_calls]

        turns = _anthropic_payload_turns(model_class, [HumanMessage("go"), truncated, *results])

        assert turns == [("user", []), ("assistant", ["toolu_0", "toolu_1"]), ("user", ["toolu_0", "toolu_1"])]

    def test_openai_responses_request_drops_function_call_after_calls_are_cleared(self):
        message = AIMessage(
            content=[{"type": "function_call", "id": "fc_1", "call_id": "call_a", "name": "bash", "arguments": "{}"}],
            tool_calls=[_call("call_a")],
            response_metadata={"model_provider": "openai"},
        )
        stopped = clone_ai_message_with_tool_calls(message, [], content=[*message.content, {"type": "text", "text": "stopped"}])
        llm = ChatOpenAI(model="gpt-5", api_key="sk-offline", use_responses_api=True, output_version="responses/v1")

        payload = llm._get_request_payload([HumanMessage("hi"), stopped, HumanMessage("continue")])

        assert [item for item in payload["input"] if item.get("type") == "function_call"] == []
