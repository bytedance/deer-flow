"""Tests for deerflow.models.patched_openai.PatchedChatOpenAI.

These tests verify that _restore_tool_call_signatures correctly re-injects
``thought_signature`` onto tool-call objects stored in
``additional_kwargs["tool_calls"]``, covering id-based matching, positional
fallback, camelCase keys, and several edge-cases.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from deerflow.models.patched_openai import PatchedChatOpenAI, _restore_tool_call_signatures

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RAW_TC_SIGNED = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "web_fetch", "arguments": '{"url":"http://example.com"}'},
    "thought_signature": "SIG_A==",
}

RAW_TC_UNSIGNED = {
    "id": "call_2",
    "type": "function",
    "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
}

PAYLOAD_TC_1 = {
    "type": "function",
    "id": "call_1",
    "function": {"name": "web_fetch", "arguments": '{"url":"http://example.com"}'},
}

PAYLOAD_TC_2 = {
    "type": "function",
    "id": "call_2",
    "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
}


def _ai_msg_with_raw_tool_calls(raw_tool_calls: list[dict]) -> AIMessage:
    return AIMessage(content="", additional_kwargs={"tool_calls": raw_tool_calls})


# ---------------------------------------------------------------------------
# Core: signed tool-call restoration
# ---------------------------------------------------------------------------


def test_tool_call_signature_restored_by_id():
    """thought_signature is copied to the payload tool-call matched by id."""
    payload_msg = {"role": "assistant", "content": None, "tool_calls": [PAYLOAD_TC_1.copy()]}
    orig = _ai_msg_with_raw_tool_calls([RAW_TC_SIGNED])

    _restore_tool_call_signatures(payload_msg, orig)

    assert payload_msg["tool_calls"][0]["thought_signature"] == "SIG_A=="


def test_tool_call_signature_for_parallel_calls():
    """For parallel function calls, only the first has a signature (per Gemini spec)."""
    payload_msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [PAYLOAD_TC_1.copy(), PAYLOAD_TC_2.copy()],
    }
    orig = _ai_msg_with_raw_tool_calls([RAW_TC_SIGNED, RAW_TC_UNSIGNED])

    _restore_tool_call_signatures(payload_msg, orig)

    assert payload_msg["tool_calls"][0]["thought_signature"] == "SIG_A=="
    assert "thought_signature" not in payload_msg["tool_calls"][1]


def test_tool_call_signature_camel_case():
    """thoughtSignature (camelCase) from some gateways is also handled."""
    raw_camel = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "web_fetch", "arguments": "{}"},
        "thoughtSignature": "SIG_CAMEL==",
    }
    payload_msg = {"role": "assistant", "content": None, "tool_calls": [PAYLOAD_TC_1.copy()]}
    orig = _ai_msg_with_raw_tool_calls([raw_camel])

    _restore_tool_call_signatures(payload_msg, orig)

    assert payload_msg["tool_calls"][0]["thought_signature"] == "SIG_CAMEL=="


def test_tool_call_signature_positional_fallback():
    """When ids don't match, falls back to positional matching."""
    raw_no_id = {
        "type": "function",
        "function": {"name": "web_fetch", "arguments": "{}"},
        "thought_signature": "SIG_POS==",
    }
    payload_tc = {
        "type": "function",
        "id": "call_99",
        "function": {"name": "web_fetch", "arguments": "{}"},
    }
    payload_msg = {"role": "assistant", "content": None, "tool_calls": [payload_tc]}
    orig = _ai_msg_with_raw_tool_calls([raw_no_id])

    _restore_tool_call_signatures(payload_msg, orig)

    assert payload_tc["thought_signature"] == "SIG_POS=="


# ---------------------------------------------------------------------------
# Edge cases: no-op scenarios for tool-call signatures
# ---------------------------------------------------------------------------


def test_tool_call_no_raw_tool_calls_is_noop():
    """No change when additional_kwargs has no tool_calls."""
    payload_msg = {"role": "assistant", "content": None, "tool_calls": [PAYLOAD_TC_1.copy()]}
    orig = AIMessage(content="", additional_kwargs={})

    _restore_tool_call_signatures(payload_msg, orig)

    assert "thought_signature" not in payload_msg["tool_calls"][0]


def test_tool_call_no_payload_tool_calls_is_noop():
    """No change when payload has no tool_calls."""
    payload_msg = {"role": "assistant", "content": "just text"}
    orig = _ai_msg_with_raw_tool_calls([RAW_TC_SIGNED])

    _restore_tool_call_signatures(payload_msg, orig)

    assert "tool_calls" not in payload_msg


def test_tool_call_unsigned_raw_entries_is_noop():
    """No signature added when raw tool-calls have no thought_signature."""
    payload_msg = {"role": "assistant", "content": None, "tool_calls": [PAYLOAD_TC_2.copy()]}
    orig = _ai_msg_with_raw_tool_calls([RAW_TC_UNSIGNED])

    _restore_tool_call_signatures(payload_msg, orig)

    assert "thought_signature" not in payload_msg["tool_calls"][0]


def test_tool_call_multiple_sequential_signatures():
    """Sequential tool calls each carry their own signature."""
    raw_tc_a = {
        "id": "call_a",
        "type": "function",
        "function": {"name": "check_flight", "arguments": "{}"},
        "thought_signature": "SIG_STEP1==",
    }
    raw_tc_b = {
        "id": "call_b",
        "type": "function",
        "function": {"name": "book_taxi", "arguments": "{}"},
        "thought_signature": "SIG_STEP2==",
    }
    payload_tc_a = {"type": "function", "id": "call_a", "function": {"name": "check_flight", "arguments": "{}"}}
    payload_tc_b = {"type": "function", "id": "call_b", "function": {"name": "book_taxi", "arguments": "{}"}}
    payload_msg = {"role": "assistant", "content": None, "tool_calls": [payload_tc_a, payload_tc_b]}
    orig = _ai_msg_with_raw_tool_calls([raw_tc_a, raw_tc_b])

    _restore_tool_call_signatures(payload_msg, orig)

    assert payload_tc_a["thought_signature"] == "SIG_STEP1=="
    assert payload_tc_b["thought_signature"] == "SIG_STEP2=="


def test_create_chat_result_preserves_raw_tool_calls():
    """Raw tool_calls stay attached to the parsed AIMessage for later replay."""
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [RAW_TC_SIGNED],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "model": "gpt-4o-mini",
    }

    result = model._create_chat_result(response)
    message = result.generations[0].message

    assert isinstance(message, AIMessage)
    assert message.additional_kwargs["tool_calls"][0]["thought_signature"] == "SIG_A=="


def test_final_stream_chunk_keeps_raw_tool_calls():
    """Final streaming chunk should not drop raw signed tool_calls."""
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    completion = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [RAW_TC_SIGNED],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "model": "gpt-4o-mini",
    }

    chunk = model._get_generation_chunk_from_completion(completion)

    assert chunk.message.additional_kwargs["tool_calls"][0]["thought_signature"] == "SIG_A=="


# ---------------------------------------------------------------------------
# Additional coverage: edge cases for the new overrides
# ---------------------------------------------------------------------------


def _make_response(tool_calls: list[dict] | None = None, content: str | None = None) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "model": "gpt-4o-mini",
    }


def test_create_chat_result_no_tool_calls_does_not_crash():
    """Text-only response should not raise even though there are no tool calls."""
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    result = model._create_chat_result(_make_response(content="Hello!"))
    message = result.generations[0].message
    assert isinstance(message, AIMessage)


def test_create_chat_result_empty_tool_calls_list_does_not_crash():
    """Empty tool_calls list should not raise."""
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    result = model._create_chat_result(_make_response(tool_calls=[]))
    assert result.generations[0].message is not None


def test_create_chat_result_preserves_multiple_signed_tool_calls():
    """All tool calls in a multi-call response should retain their signatures."""
    raw_tc_b = {
        "id": "call_2",
        "type": "function",
        "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
        "thought_signature": "SIG_B==",
    }
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    result = model._create_chat_result(_make_response(tool_calls=[RAW_TC_SIGNED, raw_tc_b]))
    raw = result.generations[0].message.additional_kwargs["tool_calls"]
    assert raw[0]["thought_signature"] == "SIG_A=="
    assert raw[1]["thought_signature"] == "SIG_B=="


def test_create_chat_result_unsigned_tool_calls_have_no_signature():
    """Tool calls without thought_signature should not have one added."""
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    result = model._create_chat_result(_make_response(tool_calls=[RAW_TC_UNSIGNED]))
    raw = result.generations[0].message.additional_kwargs["tool_calls"]
    assert "thought_signature" not in raw[0]


def test_final_stream_chunk_no_tool_calls_does_not_crash():
    """Streaming chunk for a text-only completion should not raise."""
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    chunk = model._get_generation_chunk_from_completion(_make_response(content="Done"))
    assert chunk is not None


def test_final_stream_chunk_preserves_usage_metadata():
    """The usage_metadata field should survive the chunk reconstruction."""
    model = PatchedChatOpenAI(model="gpt-4o-mini", api_key="test", base_url="https://example.com/v1")
    chunk = model._get_generation_chunk_from_completion(_make_response(tool_calls=[RAW_TC_SIGNED]))
    # usage_metadata may be None for some responses but must not raise
    assert hasattr(chunk.message, "usage_metadata")
