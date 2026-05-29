"""Tests for shared assistant payload replay helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.models.assistant_payload_replay import restore_additional_kwargs_field, restore_assistant_payloads


def _restore_reasoning(payload_msg: dict, orig_msg: AIMessage) -> None:
    restore_additional_kwargs_field(payload_msg, orig_msg, "reasoning_content")


def test_restore_assistant_payloads_matches_by_position_when_lengths_match():
    original_messages = [
        HumanMessage(content="question"),
        AIMessage(content="answer", additional_kwargs={"reasoning_content": "thought"}),
    ]
    payload_messages = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[1]["reasoning_content"] == "thought"


def test_restore_assistant_payloads_fallback_matches_unique_content_signature():
    original_messages = [
        AIMessage(content="first", additional_kwargs={"reasoning_content": "first-thought"}),
        AIMessage(content="second", additional_kwargs={"reasoning_content": "second-thought"}),
    ]
    payload_messages = [{"role": "assistant", "content": "second"}]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "second-thought"


def test_restore_assistant_payloads_fallback_matches_unique_tool_call_signature():
    original_messages = [
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "first-thought"},
            tool_calls=[{"id": "call_first", "name": "tool", "args": {}}],
        ),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "second-thought"},
            tool_calls=[{"id": "call_second", "name": "tool", "args": {}}],
        ),
    ]
    payload_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_second", "type": "function", "function": {"name": "tool", "arguments": "{}"}}],
        }
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "second-thought"


def test_restore_assistant_payloads_fallback_uses_order_when_signature_is_ambiguous():
    original_messages = [
        AIMessage(content="", additional_kwargs={"reasoning_content": "first-thought"}),
        AIMessage(content="", additional_kwargs={"reasoning_content": "second-thought"}),
    ]
    payload_messages = [{"role": "assistant", "content": ""}]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "first-thought"
