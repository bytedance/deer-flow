"""Tests for shared assistant payload replay helpers."""

from __future__ import annotations

import copy
import random

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.models.assistant_payload_replay import (
    _ai_signature,
    _assistant_signature,
    _next_unused_index_at_or_after,
    restore_additional_kwargs_field,
    restore_assistant_payloads,
    restore_reasoning_content,
)


def _restore_reasoning(payload_msg: dict, orig_msg: AIMessage) -> None:
    restore_additional_kwargs_field(payload_msg, orig_msg, "reasoning_content")


def test_restore_additional_kwargs_field_copies_present_values_only():
    payload_message = {"role": "assistant"}
    orig_message = AIMessage(
        content="answer",
        additional_kwargs={
            "reasoning_content": "",
            "ignored_none": None,
        },
    )

    restore_additional_kwargs_field(payload_message, orig_message, "reasoning_content")
    restore_additional_kwargs_field(payload_message, orig_message, "ignored_none")
    restore_additional_kwargs_field(payload_message, orig_message, "missing")

    assert payload_message == {"role": "assistant", "reasoning_content": ""}


def test_restore_reasoning_content_copies_reasoning_content():
    payload_message = {"role": "assistant"}
    orig_message = AIMessage(content="answer", additional_kwargs={"reasoning_content": "thought"})

    restore_reasoning_content(payload_message, orig_message)

    assert payload_message["reasoning_content"] == "thought"


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


def test_restore_assistant_payloads_fallback_matches_structured_content_signature():
    original_messages = [
        AIMessage(
            content=[{"type": "text", "text": "first"}],
            additional_kwargs={"reasoning_content": "first-thought"},
        ),
        AIMessage(
            content=[{"type": "text", "text": "second"}],
            additional_kwargs={"reasoning_content": "second-thought"},
        ),
    ]
    payload_messages = [{"role": "assistant", "content": [{"text": "second", "type": "text"}]}]

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


def test_restore_assistant_payloads_fallback_uses_next_unused_when_ordinal_taken():
    # Serialization dropped a leading empty assistant message, so payload ordinals
    # no longer line up with the original AIMessage indices. The first payload
    # uniquely matches a non-ordinal index by signature, which leaves the later
    # ambiguous payload's exact ordinal index already used. It must still fall
    # back to the remaining unused AIMessage (scanning forward from the ordinal)
    # instead of silently dropping the field.
    original_messages = [
        AIMessage(content="", additional_kwargs={"reasoning_content": "dropped-thought"}),
        AIMessage(content="unique", additional_kwargs={"reasoning_content": "unique-thought"}),
        AIMessage(content="", additional_kwargs={"reasoning_content": "trailing-thought"}),
    ]
    payload_messages = [
        {"role": "assistant", "content": "unique"},
        {"role": "assistant", "content": ""},
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "unique-thought"
    # Forward scan from the taken ordinal picks the trailing message, not the
    # dropped leading one (which a naive min-unused scan would wrongly select).
    assert payload_messages[1]["reasoning_content"] == "trailing-thought"


def test_restore_assistant_payloads_does_not_wrap_to_earlier_unused_message():
    original_messages = [
        HumanMessage(content="leading user"),
        AIMessage(content="", additional_kwargs={"reasoning_content": "dropped-leading-thought"}),
        AIMessage(content="unique", additional_kwargs={"reasoning_content": "unique-thought"}),
    ]
    payload_messages = [
        {"role": "assistant", "content": "unique"},
        {"role": "assistant", "content": ""},
    ]

    restore_assistant_payloads(payload_messages, original_messages, _restore_reasoning)

    assert payload_messages[0]["reasoning_content"] == "unique-thought"
    assert "reasoning_content" not in payload_messages[1]


# ---------------------------------------------------------------------------
# Parity: the O(P+A) signature-indexed matcher must behave exactly like the
# original O(P*A) linear-scan implementation across fuzzed inputs.
# ---------------------------------------------------------------------------


def _reference_restore(payload_messages, original_messages, restore):
    """The original O(P*A) implementation, kept as a parity oracle."""
    if len(payload_messages) == len(original_messages):
        for payload_msg, orig_msg in zip(payload_messages, original_messages):
            if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                restore(payload_msg, orig_msg)
        return

    ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
    assistant_payloads = [m for m in payload_messages if m.get("role") == "assistant"]
    used: set[int] = set()
    for ordinal, payload_msg in enumerate(assistant_payloads):
        payload_key = _assistant_signature(payload_msg)
        chosen = None
        if payload_key is not None:
            matches = [i for i, m in enumerate(ai_messages) if i not in used and _ai_signature(m) == payload_key]
            if len(matches) == 1:
                chosen = matches[0]
        if chosen is None:
            chosen = _next_unused_index_at_or_after(len(ai_messages), used, ordinal)
        if chosen is not None:
            used.add(chosen)
            restore(payload_msg, ai_messages[chosen])


def _random_case(rng):
    contents = ["", "a", "b"]
    tool_ids = ["x", "y"]
    originals = []
    marker = 0
    for _ in range(rng.randint(0, 6)):
        if rng.random() < 0.3:
            originals.append(HumanMessage(content="user"))
            continue
        tool_calls = [{"id": f"call_{rng.choice(tool_ids)}", "name": "t", "args": {}}] if rng.random() < 0.35 else []
        # Unique reasoning marker per AI message so the restored value identifies
        # exactly which AI message was matched.
        originals.append(AIMessage(content=rng.choice(contents), additional_kwargs={"reasoning_content": f"r{marker}"}, tool_calls=tool_calls))
        marker += 1

    payloads = []
    for _ in range(rng.randint(0, 6)):
        if rng.random() < 0.3:
            payloads.append({"role": "user", "content": rng.choice(contents)})
            continue
        payload = {"role": "assistant", "content": rng.choice(contents)}
        if rng.random() < 0.35:
            payload["tool_calls"] = [{"id": f"call_{rng.choice(tool_ids)}", "type": "function", "function": {"name": "t", "arguments": "{}"}}]
        payloads.append(payload)
    return payloads, originals


def _restored_markers(impl, payloads, originals):
    local = copy.deepcopy(payloads)
    impl(local, originals, _restore_reasoning)
    return [pm.get("reasoning_content") for pm in local]


def test_restore_assistant_payloads_parity_with_reference():
    rng = random.Random(20260622)
    for _ in range(2000):
        payloads, originals = _random_case(rng)
        assert _restored_markers(restore_assistant_payloads, payloads, originals) == _restored_markers(_reference_restore, payloads, originals)
