import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.gateway.routers import rewind


@dataclass
class _MockResponse:
    status_code: int
    payload: Any = None
    text: str = ""
    json_error: Exception | None = None

    def json(self) -> Any:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class _MockAsyncClient:
    def __init__(self, response_map: dict[tuple[str, str], _MockResponse], calls: list[dict[str, Any]], **kwargs: Any):
        self._response_map = response_map
        self._calls = calls
        self._kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method: str, url: str, json: dict[str, Any] | None = None):
        self._calls.append({"method": method, "url": url, "json": json, "client_kwargs": self._kwargs})
        key = (method, url)
        if key not in self._response_map:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self._response_map[key]


def test_resolve_langgraph_url_prefers_env(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "  http://example.com/  ")
    monkeypatch.setenv("DEERFLOW_LANGGRAPH_URL", "http://ignored:2024")
    assert rewind._resolve_langgraph_url() == "http://example.com"


def test_resolve_langgraph_url_uses_config_channels(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_URL", raising=False)
    monkeypatch.delenv("DEERFLOW_LANGGRAPH_URL", raising=False)

    mock_config = MagicMock()
    mock_config.model_extra = {"channels": {"langgraph_url": " http://cfg:2024/ "}}

    with patch.object(rewind, "get_app_config", return_value=mock_config), patch.object(rewind.Path, "exists", return_value=False):
        assert rewind._resolve_langgraph_url() == "http://cfg:2024"


def test_resolve_langgraph_url_falls_back_to_docker(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_URL", raising=False)
    monkeypatch.delenv("DEERFLOW_LANGGRAPH_URL", raising=False)

    with patch.object(rewind, "get_app_config", side_effect=RuntimeError("boom")), patch.object(rewind.Path, "exists", return_value=True):
        assert rewind._resolve_langgraph_url() == "http://langgraph:2024"


def test_extract_text_from_message_handles_string():
    assert rewind._extract_text_from_message({"content": "  hi  "}) == "hi"


def test_extract_text_from_message_handles_rich_list():
    msg = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "https://example.com"}},
            {"type": "text", "text": "world"},
            {"type": "text", "text": 123},
        ]
    }
    assert rewind._extract_text_from_message(msg) == "hello\nworld"


def test_langgraph_request_success():
    calls: list[dict[str, Any]] = []
    client = _MockAsyncClient(
        response_map={
            ("GET", "/ok"): _MockResponse(status_code=200, payload={"ok": True}),
        },
        calls=calls,
    )

    result = asyncio.run(rewind._langgraph_request(client, "GET", "/ok"))
    assert result == {"ok": True}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "/ok"


def test_langgraph_request_raises_on_request_error():
    class _BoomClient:
        async def request(self, method: str, url: str, json: dict[str, Any] | None = None):
            raise RuntimeError("network down")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind._langgraph_request(_BoomClient(), "GET", "/x"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "LangGraph request failed"


def test_langgraph_request_raises_on_http_error_status():
    calls: list[dict[str, Any]] = []
    client = _MockAsyncClient(
        response_map={
            ("GET", "/bad"): _MockResponse(status_code=500, payload={"err": True}, text="server error"),
        },
        calls=calls,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind._langgraph_request(client, "GET", "/bad"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "LangGraph response error (status=500)"


def test_langgraph_request_raises_on_invalid_json():
    calls: list[dict[str, Any]] = []
    client = _MockAsyncClient(
        response_map={
            ("GET", "/badjson"): _MockResponse(status_code=200, json_error=ValueError("nope")),
        },
        calls=calls,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind._langgraph_request(client, "GET", "/badjson"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "LangGraph response invalid JSON"


def test_langgraph_request_raises_on_invalid_format():
    calls: list[dict[str, Any]] = []
    client = _MockAsyncClient(
        response_map={
            ("GET", "/scalar"): _MockResponse(status_code=200, payload="not a dict or list"),
        },
        calls=calls,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind._langgraph_request(client, "GET", "/scalar"))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "LangGraph response invalid format"


def test_rewind_thread_success_history_newest_to_oldest(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.test")

    thread_id = "t-1"
    anchor_id = "m-2"

    calls: list[dict[str, Any]] = []
    response_map = {
        ("GET", f"/threads/{thread_id}/runs"): _MockResponse(status_code=200, payload=[]),
        ("GET", f"/threads/{thread_id}/state"): _MockResponse(
            status_code=200,
            payload={
                "values": {
                    "title": "My Thread",
                    "todos": [{"t": 1}],
                    "messages": [
                        {"type": "human", "id": "m-1", "content": "before"},
                        {"type": "human", "id": anchor_id, "content": [{"type": "text", "text": "anchor text"}]},
                        {"type": "ai", "id": "a-1", "content": "after"},
                    ],
                }
            },
        ),
        ("POST", f"/threads/{thread_id}/history"): _MockResponse(
            status_code=200,
            payload=[
                {"values": {"messages": [{"type": "human", "id": anchor_id}]}},
                {"checkpoint": {"checkpoint_id": "cp-1"}, "values": {"messages": [{"type": "human", "id": "m-1"}]}},
                {"checkpoint": {"checkpoint_id": "cp-0"}, "values": {"messages": []}},
            ],
        ),
        ("POST", f"/threads/{thread_id}/state"): _MockResponse(status_code=200, payload={"ok": True}),
    }

    def _client_factory(*args: Any, **kwargs: Any):
        return _MockAsyncClient(response_map=response_map, calls=calls, **kwargs)

    monkeypatch.setattr(rewind.httpx, "AsyncClient", _client_factory)

    result = asyncio.run(rewind.rewind_thread(thread_id, rewind.RewindRequest(anchor_user_message_id=anchor_id)))

    assert result.thread_id == thread_id
    assert result.backup_thread_id is None
    assert result.filled_text == "anchor text"
    assert result.rewound_to_message_count == 1

    state_call = next(c for c in calls if c["method"] == "POST" and c["url"] == f"/threads/{thread_id}/state")
    assert state_call["json"]["checkpoint_id"] == "cp-1"
    assert state_call["json"]["values"]["title"] == "My Thread"
    assert state_call["json"]["values"]["todos"] == []


def test_rewind_thread_success_history_oldest_to_newest(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.test")

    thread_id = "t-2"
    anchor_id = "m-20"

    calls: list[dict[str, Any]] = []
    response_map = {
        ("GET", f"/threads/{thread_id}/runs"): _MockResponse(status_code=200, payload={"runs": []}),
        ("GET", f"/threads/{thread_id}/state"): _MockResponse(
            status_code=200,
            payload={
                "values": {
                    "title": "Title",
                    "todos": [],
                    "messages": [
                        {"type": "human", "id": anchor_id, "content": " anchor "},
                    ],
                }
            },
        ),
        ("POST", f"/threads/{thread_id}/history"): _MockResponse(
            status_code=200,
            payload=[
                {"checkpoint": {"checkpoint_id": "cp-base"}, "values": {"messages": [{"type": "human", "id": "m-1"}]}},
                {"values": {"messages": [{"type": "human", "id": anchor_id}]}},
                {"values": {"messages": [{"type": "human", "id": anchor_id}, {"type": "ai", "id": "a"}]}},
            ],
        ),
        ("POST", f"/threads/{thread_id}/state"): _MockResponse(status_code=200, payload={"ok": True}),
    }

    def _client_factory(*args: Any, **kwargs: Any):
        return _MockAsyncClient(response_map=response_map, calls=calls, **kwargs)

    monkeypatch.setattr(rewind.httpx, "AsyncClient", _client_factory)

    result = asyncio.run(rewind.rewind_thread(thread_id, rewind.RewindRequest(anchor_user_message_id=anchor_id)))

    assert result.filled_text == "anchor"
    assert result.rewound_to_message_count == 1

    state_call = next(c for c in calls if c["method"] == "POST" and c["url"] == f"/threads/{thread_id}/state")
    assert state_call["json"]["checkpoint_id"] == "cp-base"


def test_rewind_thread_raises_when_thread_running(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.test")

    thread_id = "t-running"
    anchor_id = "m-1"

    calls: list[dict[str, Any]] = []
    response_map = {
        ("GET", f"/threads/{thread_id}/runs"): _MockResponse(status_code=200, payload=[{"status": "running"}]),
    }

    def _client_factory(*args: Any, **kwargs: Any):
        return _MockAsyncClient(response_map=response_map, calls=calls, **kwargs)

    monkeypatch.setattr(rewind.httpx, "AsyncClient", _client_factory)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind.rewind_thread(thread_id, rewind.RewindRequest(anchor_user_message_id=anchor_id)))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Thread is running"


def test_rewind_thread_raises_when_anchor_not_in_current_state(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.test")

    thread_id = "t-miss"

    calls: list[dict[str, Any]] = []
    response_map = {
        ("GET", f"/threads/{thread_id}/runs"): _MockResponse(status_code=200, payload=[]),
        ("GET", f"/threads/{thread_id}/state"): _MockResponse(
            status_code=200,
            payload={"values": {"messages": [{"type": "human", "id": "other", "content": "x"}]}},
        ),
    }

    def _client_factory(*args: Any, **kwargs: Any):
        return _MockAsyncClient(response_map=response_map, calls=calls, **kwargs)

    monkeypatch.setattr(rewind.httpx, "AsyncClient", _client_factory)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind.rewind_thread(thread_id, rewind.RewindRequest(anchor_user_message_id="missing")))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Anchor message not found"


def test_rewind_thread_raises_when_history_missing_pre_anchor_checkpoint(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.test")

    thread_id = "t-window"
    anchor_id = "m-anchor"

    calls: list[dict[str, Any]] = []
    response_map = {
        ("GET", f"/threads/{thread_id}/runs"): _MockResponse(status_code=200, payload=[]),
        ("GET", f"/threads/{thread_id}/state"): _MockResponse(
            status_code=200,
            payload={"values": {"messages": [{"type": "human", "id": anchor_id, "content": "a"}]}},
        ),
        ("POST", f"/threads/{thread_id}/history"): _MockResponse(
            status_code=200,
            payload=[
                {"values": {"messages": [{"type": "human", "id": anchor_id}]}},
                {"values": {"messages": [{"type": "human", "id": anchor_id}, {"type": "ai", "id": "a"}]}},
            ],
        ),
    }

    def _client_factory(*args: Any, **kwargs: Any):
        return _MockAsyncClient(response_map=response_map, calls=calls, **kwargs)

    monkeypatch.setattr(rewind.httpx, "AsyncClient", _client_factory)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind.rewind_thread(thread_id, rewind.RewindRequest(anchor_user_message_id=anchor_id)))

    assert exc_info.value.status_code == 400
    assert "pre-anchor checkpoint" in exc_info.value.detail


def test_rewind_thread_raises_when_history_invalid_type(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.test")

    thread_id = "t-badhistory"
    anchor_id = "m-anchor"

    calls: list[dict[str, Any]] = []
    response_map = {
        ("GET", f"/threads/{thread_id}/runs"): _MockResponse(status_code=200, payload=[]),
        ("GET", f"/threads/{thread_id}/state"): _MockResponse(
            status_code=200,
            payload={"values": {"messages": [{"type": "human", "id": anchor_id, "content": "a"}]}},
        ),
        ("POST", f"/threads/{thread_id}/history"): _MockResponse(
            status_code=200,
            payload={"history": []},
        ),
    }

    def _client_factory(*args: Any, **kwargs: Any):
        return _MockAsyncClient(response_map=response_map, calls=calls, **kwargs)

    monkeypatch.setattr(rewind.httpx, "AsyncClient", _client_factory)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind.rewind_thread(thread_id, rewind.RewindRequest(anchor_user_message_id=anchor_id)))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Invalid thread history"


def test_rewind_thread_raises_when_checkpoint_invalid(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://langgraph.test")

    thread_id = "t-nocp"
    anchor_id = "m-anchor"

    calls: list[dict[str, Any]] = []
    response_map = {
        ("GET", f"/threads/{thread_id}/runs"): _MockResponse(status_code=200, payload=[]),
        ("GET", f"/threads/{thread_id}/state"): _MockResponse(
            status_code=200,
            payload={"values": {"messages": [{"type": "human", "id": anchor_id, "content": "a"}]}},
        ),
        ("POST", f"/threads/{thread_id}/history"): _MockResponse(
            status_code=200,
            payload=[
                {"values": {"messages": [{"type": "human", "id": anchor_id}]}},
                {"checkpoint": {"checkpoint_id": "  "}, "values": {"messages": []}},
            ],
        ),
    }

    def _client_factory(*args: Any, **kwargs: Any):
        return _MockAsyncClient(response_map=response_map, calls=calls, **kwargs)

    monkeypatch.setattr(rewind.httpx, "AsyncClient", _client_factory)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rewind.rewind_thread(thread_id, rewind.RewindRequest(anchor_user_message_id=anchor_id)))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Invalid checkpoint"
