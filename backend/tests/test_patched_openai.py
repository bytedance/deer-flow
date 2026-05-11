"""Tests for deerflow.models.patched_openai.PatchedChatOpenAI.

These tests cover:
- Model-level payload behavior via PatchedChatOpenAI._get_request_payload
- tool-call ``thought_signature`` restoration helpers
- Gemini compatibility schema fixes for arrays and integer enums
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.models.patched_openai import (
    PatchedChatOpenAI,
    _fix_array_schemas,
    _fix_integer_enum_schemas,
    _restore_tool_call_signatures,
)

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


def _make_model(**kwargs) -> PatchedChatOpenAI:
    return PatchedChatOpenAI(
        model="gpt-4o-mini",
        api_key="test-key",
        base_url="https://example.com/v1",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Core: model-call integration behavior
# ---------------------------------------------------------------------------


def test_get_request_payload_restores_signature_with_real_model_call():
    """Model payload generation restores thought_signature on assistant tool calls."""
    model = _make_model()

    assistant_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "web_fetch",
                "args": {"url": "http://example.com"},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
        additional_kwargs={"tool_calls": [RAW_TC_SIGNED]},
    )

    payload = model._get_request_payload([HumanMessage(content="hello"), assistant_msg])

    assistant_payload = next(msg for msg in payload["messages"] if msg.get("role") == "assistant")
    assert assistant_payload["tool_calls"][0]["thought_signature"] == "SIG_A=="


def test_get_request_payload_sanitizes_tool_schema_with_real_model_call():
    """Model payload generation fixes array/items and integer enum constraints."""
    model = _make_model()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "calc",
                "description": "demo tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "modes": {"type": "array"},
                        "retry": {"type": "integer", "enum": [1, 2, 4]},
                    },
                },
            },
        }
    ]

    payload = model._get_request_payload([HumanMessage(content="run")], tools=tools)

    params = payload["tools"][0]["function"]["parameters"]
    assert params["properties"]["modes"]["items"] == {"type": "string"}
    assert "enum" not in params["properties"]["retry"]
    assert params["properties"]["retry"]["description"] == "Valid values: 1, 2, 4"


# ---------------------------------------------------------------------------
# Core: signed tool-call restoration helpers
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

# ---------------------------------------------------------------------------
# Schema Fixes (Gemini Compatibility)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "schema, expected",
    [
        (
            {"type": "array"},
            {"type": "array", "items": {"type": "string"}},
        ),
        (
            {"type": ["array", "null"]},
            {"type": ["array", "null"], "items": {"type": "string"}},
        ),
        # Array that already has items (should not be overwritten)
        (
            {"type": "array", "items": {"type": "integer"}},
            {"type": "array", "items": {"type": "integer"}},
        ),
        # Nested structural test (properties)
        (
            {"type": "object", "properties": {"tags": {"type": "array"}}},
            {"type": "object", "properties": {"tags": {"type": "array", "items": {"type": "string"}}}},
        ),
    ],
)
def test_fix_array_schemas(schema, expected):
    """Test that array schemas missing 'items' receive a default string item type."""
    _fix_array_schemas(schema)
    assert schema == expected


@pytest.mark.parametrize(
    "schema, expected",
    [
        # Basic integer enum with existing description
        (
            {"type": "integer", "description": "Retry count", "enum": [1, 2, 3]},
            {"type": "integer", "description": "Retry count (valid values: 1, 2, 3)"},
        ),
        # Pure string enum (should be left alone)
        (
            {"type": "string", "enum": ["a", "b", "c"]},
            {"type": "string", "enum": ["a", "b", "c"]},
        ),
        # Number enum without previous description
        (
            {"type": "number", "enum": [0, 1.5]},
            {"type": "number", "description": "Valid values: 0, 1.5"},
        ),
        # Mixed enum types (contains at least one non-string)
        (
            {"type": "string", "enum": ["a", 2, "c"]},
            {"type": "string", "description": "Valid values: a, 2, c"},
        ),
        # Nested structural test (allOf)
        (
            {"type": "object", "properties": {"nested": {"allOf": [{"type": "integer", "enum": [200, 404]}]}}},
            {"type": "object", "properties": {"nested": {"allOf": [{"type": "integer", "description": "Valid values: 200, 404"}]}}},
        ),
    ],
)
def test_fix_integer_enum_schemas(schema, expected):
    """Test that non-string enums are extracted into descriptions to satisfy Gemini."""
    _fix_integer_enum_schemas(schema)
    assert schema == expected

