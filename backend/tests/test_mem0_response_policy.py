"""Malformed remote recall payloads must honor Mem0's configured read policy."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import ExitStack, closing
from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage

from deerflow.agents.memory.backends.mem0 import mem0_manager
from deerflow.agents.memory.backends.mem0.client import Mem0APIError, Mem0Client
from deerflow.agents.memory.manager import MemoryManagerError, MemoryReadError


def _manager(monkeypatch: pytest.MonkeyPatch, policy: str, handler: Callable[[httpx.Request], httpx.Response], *, write_policy: str = "log_and_drop") -> mem0_manager.Mem0Manager:
    monkeypatch.setenv("MEM0_API_KEY", "synthetic-key")
    monkeypatch.setattr(mem0_manager, "Mem0Client", lambda **kwargs: Mem0Client(**kwargs, transport=httpx.MockTransport(handler)))
    return mem0_manager.Mem0Manager(backend_config={"failure_policy": {"read": policy, "write": write_policy}})


def _read(manager: mem0_manager.Mem0Manager, operation: str) -> Any:
    if operation == "get_context":
        return manager.get_context("u1")
    if operation == "search":
        return manager.search("preference", user_id="u1")
    return getattr(manager, operation)(user_id="u1")


def _empty(operation: str) -> Any:
    if operation in {"get_context", "aget_context"}:
        return ""
    if operation in {"search", "asearch"}:
        return []
    return {"facts": []}


@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("operation", ["get_context", "search", "get_memory", "export_memory"])
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="array-envelope"),
        pytest.param(None, id="null-envelope"),
        pytest.param("unexpected", id="string-envelope"),
        pytest.param({"results": None}, id="null-results"),
        pytest.param({"results": {}}, id="object-results"),
        pytest.param({"results": [None]}, id="null-record"),
        pytest.param({"results": [{"id": "valid", "memory": "Python"}, "invalid"]}, id="mixed-records"),
        pytest.param(b'{"results": ["\xff"]}', id="invalid-utf8"),
    ],
)
def test_malformed_recall_honors_read_policy(monkeypatch: pytest.MonkeyPatch, policy: str, operation: str, payload: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload if isinstance(payload, bytes) else json.dumps(payload), headers={"Content-Type": "application/json"})

    with closing(_manager(monkeypatch, policy, handler)) as manager:
        if policy == "fail_closed":
            with pytest.raises(MemoryReadError) as caught:
                _read(manager, operation)
            assert isinstance(caught.value.__cause__, Mem0APIError)
            if isinstance(payload, bytes):
                assert isinstance(caught.value.__cause__.__cause__, UnicodeDecodeError)
        else:
            assert _read(manager, operation) == _empty(operation)


@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("operation", ["get_context", "search", "get_memory", "export_memory"])
@pytest.mark.parametrize("payload", [{}, {"results": []}])
def test_empty_recall_remains_valid(monkeypatch: pytest.MonkeyPatch, policy: str, operation: str, payload: dict) -> None:
    with closing(_manager(monkeypatch, policy, lambda request: httpx.Response(200, json=payload))) as manager:
        assert _read(manager, operation) == _empty(operation)


@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("operation", ["aget_context", "asearch"])
@pytest.mark.parametrize("body", [b'{"results": [null]}', b'{"results": ["\xff"]}'], ids=["null-record", "invalid-utf8"])
def test_async_recall_honors_read_policy(monkeypatch: pytest.MonkeyPatch, policy: str, operation: str, body: bytes) -> None:
    with closing(_manager(monkeypatch, policy, lambda request: httpx.Response(200, content=body))) as manager:
        coroutine = manager.aget_context("u1") if operation == "aget_context" else manager.asearch("preference", user_id="u1")
        if policy == "fail_closed":
            with pytest.raises(MemoryReadError) as caught:
                asyncio.run(coroutine)
            assert isinstance(caught.value.__cause__, Mem0APIError)
            if b"\xff" in body:
                assert isinstance(caught.value.__cause__.__cause__, UnicodeDecodeError)
        else:
            assert asyncio.run(coroutine) == _empty(operation)


@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("body", [b'{"results": [null]}', b'{"results": ["\xff"]}'], ids=["null-record", "invalid-utf8"])
def test_malformed_later_page_does_not_return_partial_memories(monkeypatch: pytest.MonkeyPatch, policy: str, body: bytes) -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages.append(page)
        if page == 1:
            return httpx.Response(200, json={"results": [{"id": "m1", "memory": "Python"}], "next": "page-2"})
        return httpx.Response(200, content=body)

    with closing(_manager(monkeypatch, policy, handler)) as manager:
        if policy == "fail_closed":
            with pytest.raises(MemoryReadError) as caught:
                manager.get_memory(user_id="u1")
            assert isinstance(caught.value.__cause__, Mem0APIError)
            if b"\xff" in body:
                assert isinstance(caught.value.__cause__.__cause__, UnicodeDecodeError)
        else:
            assert manager.get_memory(user_id="u1") == {"facts": []}
    assert pages == [1, 2]


def _client_operation(client: Mem0Client, operation: str) -> Any:
    if operation == "add":
        return client.add_memories(messages=[{"role": "user", "content": "synthetic memory"}], user_id="u1")
    if operation == "delete":
        return client.delete_all_memories(user_id="u1")
    return client.ping()


@pytest.mark.parametrize("operation", ["add", "delete", "ping"])
@pytest.mark.parametrize("empty_body", [False, True], ids=["object", "empty-body"])
def test_shared_request_preserves_valid_write_and_probe_responses(operation: str, empty_body: bool) -> None:
    payload = {"add": {"event_id": "synthetic-event"}, "delete": {"message": "Memories deleted successfully!"}, "ping": {"results": []}}[operation]
    body = b"" if empty_body else json.dumps(payload).encode("utf-8")
    status_code = 204 if operation == "delete" and empty_body else 200
    with closing(Mem0Client(base_url="https://mem0.invalid", api_key="synthetic-key", transport=httpx.MockTransport(lambda request: httpx.Response(status_code, content=body)))) as client:
        result = _client_operation(client, operation)
    if operation == "add":
        assert result == (json.loads(body) if body else {})
    else:
        assert result is None


@pytest.mark.parametrize("operation", ["add", "delete", "ping"])
@pytest.mark.parametrize("body", [b'{"results": ["\xff"]}', b"{", b"[]"], ids=["invalid-utf8", "invalid-json", "array-envelope"])
def test_shared_request_normalizes_invalid_write_and_probe_responses(operation: str, body: bytes) -> None:
    with closing(Mem0Client(base_url="https://mem0.invalid", api_key="synthetic-key", transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)))) as client:
        with pytest.raises(Mem0APIError) as caught:
            _client_operation(client, operation)
    if b"\xff" in body:
        assert isinstance(caught.value.__cause__, UnicodeDecodeError)


@pytest.mark.parametrize("operation", ["add", "clear_memory"])
@pytest.mark.parametrize("write_policy", ["log_and_drop", "raise"])
def test_invalid_encoding_honors_write_policy(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, operation: str, write_policy: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b'{"results": ["\xff"]}')

    with closing(_manager(monkeypatch, "fail_open", handler, write_policy=write_policy)) as manager:

        def write() -> Any:
            if operation == "add":
                return manager.add("thread-1", [HumanMessage(content="synthetic memory")], user_id="u1")
            return manager.clear_memory(user_id="u1")

        if write_policy == "raise":
            with pytest.raises(MemoryManagerError) as caught:
                write()
            assert isinstance(caught.value.__cause__, Mem0APIError)
            assert isinstance(caught.value.__cause__.__cause__, UnicodeDecodeError)
        else:
            assert write() == (None if operation == "add" else {"facts": []})
            assert "dropping update" in caplog.text
    assert len(requests) == 1
    assert requests[0].method == ("POST" if operation == "add" else "DELETE")


@pytest.mark.parametrize("startup_policy", ["fail_fast", "tolerate"])
def test_invalid_encoding_probe_honors_startup_policy(monkeypatch: pytest.MonkeyPatch, startup_policy: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b'{"results": ["\xff"]}')

    monkeypatch.setenv("MEM0_API_KEY", "synthetic-key")
    with ExitStack() as stack:

        def client_factory(**kwargs: Any) -> Mem0Client:
            return stack.enter_context(closing(Mem0Client(**kwargs, transport=httpx.MockTransport(handler))))

        monkeypatch.setattr(mem0_manager, "Mem0Client", client_factory)
        config = {"startup_policy": startup_policy, "failure_policy": {"read": "fail_open"}}
        if startup_policy == "fail_fast":
            with pytest.raises(Mem0APIError) as caught:
                mem0_manager.Mem0Manager.from_config(config)
            assert isinstance(caught.value.__cause__, UnicodeDecodeError)
            assert len(requests) == 1
            assert json.loads(requests[0].content) == {"filters": {"user_id": "__deerflow_startup_check__"}}
        else:
            with closing(mem0_manager.Mem0Manager.from_config(config)):
                assert requests == []


def test_unrelated_client_bug_is_not_silently_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    with closing(_manager(monkeypatch, "fail_open", lambda request: httpx.Response(200, json={}))) as manager:

        def broken_search(**kwargs: Any) -> Any:
            raise RuntimeError("local programming error")

        monkeypatch.setattr(manager._client, "search_memories", broken_search)
        with pytest.raises(RuntimeError, match="local programming error"):
            manager.search("preference", user_id="u1")
