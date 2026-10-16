"""Tests for deerflow.models.patched_openai.PatchedChatOpenAI.

These tests verify that _restore_tool_call_signatures correctly re-injects
``thought_signature`` onto tool-call objects stored in
``additional_kwargs["tool_calls"]``, covering id-based matching, positional
fallback, camelCase keys, and several edge-cases. They also check that signed
raw tool calls are captured from streaming and non-streaming responses, and
replayed through the real SDK serialization (only the HTTP boundary is faked).
"""

from __future__ import annotations

import asyncio
import json

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

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


# ---------------------------------------------------------------------------
# Google's OpenAI-compatible endpoint: extra_content.google.thought_signature
# ---------------------------------------------------------------------------

GOOGLE_EXTRA = {"google": {"thought_signature": "SIG_GOOGLE=="}}

RAW_TC_GOOGLE = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "web_fetch", "arguments": '{"url":"http://example.com"}'},
    "extra_content": GOOGLE_EXTRA,
}


def test_tool_call_extra_content_restored():
    """Google returns the signature under extra_content.google; it is echoed back verbatim."""
    payload_msg = {"role": "assistant", "content": None, "tool_calls": [PAYLOAD_TC_1.copy()]}
    orig = _ai_msg_with_raw_tool_calls([RAW_TC_GOOGLE])

    _restore_tool_call_signatures(payload_msg, orig)

    assert payload_msg["tool_calls"][0]["extra_content"] == GOOGLE_EXTRA
    assert payload_msg["tool_calls"][0]["extra_content"] is not GOOGLE_EXTRA
    assert "thought_signature" not in payload_msg["tool_calls"][0]


def _model() -> PatchedChatOpenAI:
    return PatchedChatOpenAI(model="gemini-3.1-pro-preview", api_key="test-key", base_url="https://generativelanguage.googleapis.com/v1beta/openai/")


def _stream_chunk(delta: dict, finish_reason: str | None = None) -> dict:
    return {"id": "chat-1", "object": "chat.completion.chunk", "created": 1, "model": "gemini-3.1-pro-preview", "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}


def test_stream_chunk_captures_signed_raw_tool_calls():
    """langchain-openai 1.x keeps no raw tool calls on stream chunks; the signed ones are captured."""
    delta = {"role": "assistant", "tool_calls": [{"index": None, **RAW_TC_GOOGLE}]}

    generation_chunk = _model()._convert_chunk_to_generation_chunk(_stream_chunk(delta), AIMessageChunk, {})

    raw_tool_calls = generation_chunk.message.additional_kwargs["tool_calls"]
    assert raw_tool_calls == [RAW_TC_GOOGLE]
    assert generation_chunk.message.tool_call_chunks[0]["id"] == "call_1"


def test_stream_chunk_without_signature_is_unchanged():
    delta = {"role": "assistant", "tool_calls": [{"index": 0, **RAW_TC_UNSIGNED}]}

    generation_chunk = _model()._convert_chunk_to_generation_chunk(_stream_chunk(delta), AIMessageChunk, {})

    assert "tool_calls" not in generation_chunk.message.additional_kwargs


def test_chat_result_captures_signed_raw_tool_calls():
    response = {
        "id": "chat-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gemini-3.1-pro-preview",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [RAW_TC_GOOGLE]}}],
    }

    result = _model()._create_chat_result(response)

    message = result.generations[0].message
    assert message.tool_calls[0]["id"] == "call_1"
    assert message.additional_kwargs["tool_calls"] == [RAW_TC_GOOGLE]


def test_signature_survives_streamed_tool_round_trip(monkeypatch):
    """Real SDK serialization: a streamed signed tool call is echoed on the follow-up request."""
    requests: list[dict] = []

    async def send(client, request, **kwargs):
        body = json.loads(request.content)
        requests.append(body)
        if body["messages"][-1]["role"] == "tool":
            deltas = [{"role": "assistant", "content": "Done."}]
            finish = "stop"
        else:
            deltas = [{"role": "assistant", "tool_calls": [{"index": None, **RAW_TC_GOOGLE}]}]
            finish = "tool_calls"
        chunks = [_stream_chunk(delta) for delta in deltas] + [_stream_chunk({}, finish)]
        content = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"}, content=content.encode())

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    model = _model().bind_tools([{"type": "function", "function": {"name": "web_fetch", "description": "Fetch a URL", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}}])

    async def stream(history: list) -> AIMessageChunk:
        merged = None
        async for chunk in model.astream(history):
            merged = chunk if merged is None else merged + chunk
        return merged

    async def run() -> None:
        history = [HumanMessage(content="Fetch example.com")]
        ai_msg = await stream(history)
        history += [ai_msg, ToolMessage(content="<html/>", tool_call_id=ai_msg.tool_calls[0]["id"])]
        await stream(history)

    asyncio.run(run())

    replayed = requests[1]["messages"][1]
    assert replayed["role"] == "assistant"
    assert replayed["tool_calls"][0]["id"] == "call_1"
    assert replayed["tool_calls"][0]["extra_content"] == GOOGLE_EXTRA
