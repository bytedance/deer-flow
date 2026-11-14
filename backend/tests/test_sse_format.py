"""Tests for SSE frame formatting utilities."""

import json


def _format_sse(event: str, data, *, event_id: str | None = None) -> str:
    from app.gateway.services import format_sse

    return format_sse(event, data, event_id=event_id)


def test_sse_end_event_data_null():
    """End event should have data: null."""
    frame = _format_sse("end", None)
    assert "data: null" in frame


def test_sse_metadata_event():
    """Metadata event should include run_id and attempt."""
    frame = _format_sse("metadata", {"run_id": "abc", "attempt": 1}, event_id="123-0")
    assert "event: metadata" in frame
    assert "id: 123-0" in frame


def test_sse_error_format():
    """Error event should use message/name format."""
    frame = _format_sse("error", {"message": "boom", "name": "ValueError"})
    parsed = json.loads(frame.split("data: ")[1].split("\n")[0])
    assert parsed["message"] == "boom"
    assert parsed["name"] == "ValueError"


def test_sse_frame_rejects_non_finite_floats():
    """A non-finite float must not reach the wire as a bare NaN/Infinity token.

    The canonical serializer normalizes non-finite floats before they reach
    ``format_sse``; this guards the wire boundary directly so a regression in
    either layer is caught. A strict ``parse_constant`` mirrors the JS
    ``useStream`` / ``langgraph-sdk`` SSE decoder, which rejects such tokens.
    """
    from deerflow.runtime.serialization import serialize

    payload = serialize({"messages": [], "metric": float("inf")}, mode="values")
    frame = _format_sse("values", payload)
    data_line = frame.split("data: ")[1].split("\n")[0]

    def _reject_constant(token):
        raise ValueError(f"non-finite JSON token: {token}")

    json.loads(data_line, parse_constant=_reject_constant)


def test_sse_messages_frame_rejects_non_finite_floats_in_metadata():
    """A non-finite float inside messages-mode metadata must not reach the
    wire as a bare NaN/Infinity token either (#7669)."""
    from deerflow.runtime.serialization import serialize

    payload = serialize(
        (
            {"type": "AIMessageChunk", "content": "hi"},
            {"langgraph_node": "model", "score": float("inf")},
        ),
        mode="messages",
    )
    frame = _format_sse("messages", payload)
    data_line = frame.split("data: ")[1].split("\n")[0]

    def _reject_constant(token):
        raise ValueError(f"non-finite JSON token: {token}")

    json.loads(data_line, parse_constant=_reject_constant)
