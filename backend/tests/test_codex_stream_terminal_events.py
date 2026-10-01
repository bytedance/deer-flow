"""Offline HTTP-stream regressions for Codex terminal response events."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from langchain_core.messages import HumanMessage

from deerflow.models import openai_codex_provider as provider
from deerflow.models.credential_loader import CodexCliCredential


class EventStream(httpx.SyncByteStream):
    def __init__(self, events: list[dict], tail_error: Exception | None = None):
        self.events = events
        self.tail_error = tail_error
        self.closed = False
        self.read_past_events = False

    def __iter__(self) -> Iterator[bytes]:
        for event in self.events:
            yield f"data: {json.dumps(event)}\n\n".encode()
        self.read_past_events = True
        if self.tail_error is not None:
            raise self.tail_error

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("fake-token", "fake-account"))
    return provider.CodexChatModel(retry_max_attempts=3)


@pytest.fixture
def serve_events(monkeypatch):
    client_class = httpx.Client

    def install(events: list[dict], *, tail_error: Exception | None = None, status_code: int = 200):
        stream = EventStream(events, tail_error)
        requests = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(status_code, headers={"content-type": "text/event-stream"}, stream=stream)

        transport = httpx.MockTransport(handle)
        monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: client_class(transport=transport, **kwargs))
        return stream, requests

    return install


def message_item(text: str) -> dict:
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


@pytest.mark.parametrize("recover_streamed_output", [False, True])
def test_completed_response_does_not_wait_for_transport_eof(model, serve_events, recover_streamed_output):
    item = message_item("Report ready")
    response = {
        "id": "resp-complete",
        "status": "completed",
        "output": [] if recover_streamed_output else [item],
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }
    events = [
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": response},
    ]
    stream, requests = serve_events(events, tail_error=httpx.ReadTimeout("Connection stayed open after completion"))

    result = model.invoke([HumanMessage(content="Prepare a report")])

    assert result.content == "Report ready"
    assert result.usage_metadata == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    assert len(requests) == 1
    assert stream.closed
    assert not stream.read_past_events


@pytest.mark.parametrize(
    ("event", "diagnostics"),
    [
        ({"type": "error", "code": "invalid_request", "message": "Unsupported model"}, ["error", "invalid_request", "Unsupported model"]),
        (
            {"type": "error", "error": {"code": "flex_unavailable", "message": "Service tier unavailable"}},
            ["error", "flex_unavailable", "Service tier unavailable"],
        ),
        (
            {"type": "response.failed", "response": {"status": "failed", "error": {"code": "server_error", "message": "Generation failed"}}},
            ["response.failed", "server_error", "Generation failed"],
        ),
        (
            {"type": "response.incomplete", "response": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}},
            ["response.incomplete", "max_output_tokens"],
        ),
    ],
)
def test_terminal_failure_keeps_diagnostics_and_closes_without_retry(model, serve_events, monkeypatch, event, diagnostics):
    events = [{"type": "response.output_item.done", "output_index": 0, "item": message_item("Partial answer")}, event]
    stream, requests = serve_events(events, tail_error=httpx.ReadTimeout("Connection stayed open after failure"))
    monkeypatch.setattr(provider.time, "sleep", lambda _: pytest.fail("SSE terminal errors must not trigger an HTTP retry"))

    with pytest.raises(RuntimeError) as caught:
        model.invoke([HumanMessage(content="Prepare a report")])

    for diagnostic in diagnostics:
        assert diagnostic in str(caught.value)
    assert "Partial answer" not in str(caught.value)
    assert len(requests) == 1
    assert stream.closed
    assert not stream.read_past_events


@pytest.mark.parametrize(
    "event",
    [
        {"type": "error", "code": None, "message": "Request rejected"},
        {"type": "response.failed", "response": {"error": None}},
        {"type": "response.incomplete", "response": {"incomplete_details": None}},
    ],
)
def test_terminal_failure_with_unavailable_details_still_names_event(model, serve_events, event):
    stream, _ = serve_events([event])

    with pytest.raises(RuntimeError, match=event["type"].replace(".", r"\.")):
        model.invoke([HumanMessage(content="Hello")])

    assert stream.closed
    assert not stream.read_past_events


def test_transport_eof_without_terminal_event_remains_an_error(model, serve_events):
    stream, _ = serve_events([{"type": "response.output_item.done", "output_index": 0, "item": message_item("Partial")}])

    with pytest.raises(RuntimeError, match="without response.completed"):
        model.invoke([HumanMessage(content="Hello")])

    assert stream.closed
    assert stream.read_past_events


def test_http_status_failure_is_not_replaced_by_sse_error(model, serve_events):
    stream, requests = serve_events([], status_code=400)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        model.invoke([HumanMessage(content="Hello")])

    assert caught.value.response.status_code == 400
    assert len(requests) == 1
    assert stream.closed


def test_completed_response_recovers_tool_calls_and_reasoning_before_closing(model, serve_events):
    tool_call = {"type": "function_call", "name": "save_report", "call_id": "call-report", "arguments": '{"name": "report.md"}'}
    reasoning = {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Save the completed report"}]}
    stream, _ = serve_events(
        [
            {"type": "response.output_item.done", "output_index": 1, "item": tool_call},
            {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
            {"type": "response.completed", "response": {"status": "completed", "output": [], "usage": {}}},
        ],
        tail_error=httpx.ReadTimeout("Connection stayed open after tool-call completion"),
    )

    result = model.invoke([HumanMessage(content="Save the report")])

    assert result.tool_calls == [{"type": "tool_call", "name": "save_report", "id": "call-report", "args": {"name": "report.md"}}]
    assert result.additional_kwargs["reasoning_content"] == "Save the completed report"
    assert stream.closed
    assert not stream.read_past_events
