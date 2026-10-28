"""Broken Mem0 continuation pages fail without looping or returning partial data."""

import asyncio
from contextlib import closing
from functools import partial

import httpx
import pytest

from deerflow.agents.memory.backends.mem0 import mem0_manager
from deerflow.agents.memory.backends.mem0.client import Mem0APIError, Mem0Client
from deerflow.agents.memory.manager import MemoryReadError


def _pages(kind, calls):
    def handle(request):
        page = int(request.url.params["page"])
        calls.append(page)
        # An assertion rather than a timeout makes the unfixed regression bounded.
        assert page <= 4, "Client continued requesting broken pagination"
        records = [] if kind == "empty" and page > 1 else [{"id": f"m{page}", "memory": f"fact {page}"}]
        next_page = "synthetic-private-continuation" if kind == "cycle" else f"page-{page + 1}"
        return httpx.Response(200, json={"results": records, "next": next_page})

    return handle


@pytest.mark.parametrize("kind", ["empty", "cycle"])
@pytest.mark.parametrize("max_items", [None, 8])
def test_nonprogressing_pages_raise_a_redacted_api_error(kind, max_items):
    calls = []
    with closing(Mem0Client(base_url="https://mem0.invalid", api_key="synthetic", transport=httpx.MockTransport(_pages(kind, calls)))) as client:
        with pytest.raises(Mem0APIError, match="page=4" if kind == "empty" else "page=2") as caught:
            client.list_memories(filters={"user_id": "u"}, max_items=max_items)
    assert "synthetic-private-continuation" not in str(caught.value)
    assert calls == ([1, 2, 3, 4] if kind == "empty" else [1, 2])


@pytest.mark.parametrize("kind", ["empty", "cycle"])
@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("operation", ["get_context", "aget_context", "get_memory", "export_memory"])
def test_pagination_failures_obey_policy_without_partial_results(monkeypatch, kind, policy, operation):
    calls = []
    monkeypatch.setenv("MEM0_API_KEY", "synthetic")
    monkeypatch.setattr(mem0_manager, "Mem0Client", partial(Mem0Client, transport=httpx.MockTransport(_pages(kind, calls))))
    with closing(mem0_manager.Mem0Manager(backend_config={"failure_policy": {"read": policy}})) as manager:

        def read():
            if operation == "aget_context":
                return asyncio.run(manager.aget_context("u"))
            if operation == "get_context":
                return manager.get_context("u")
            return getattr(manager, operation)(user_id="u")

        if policy == "fail_closed":
            with pytest.raises(MemoryReadError):
                read()
        else:
            assert read() == ("" if operation.endswith("context") else {"facts": []})
    assert calls == ([1, 2, 3, 4] if kind == "empty" else [1, 2])


@pytest.mark.parametrize("max_items,expected", [(None, ["a", "b", "c"]), (1, ["a"]), (2, ["a", "b"])])
def test_normal_pages_and_item_limit_keep_order(max_items, expected):
    calls = []

    def handle(request):
        page = int(request.url.params["page"])
        calls.append(page)
        assert request.url.host == "mem0.invalid"
        assert request.url.params["page_size"] == "2"
        payload = {1: {"results": [{"id": "a"}, {"id": "b"}], "next": "https://untrusted.invalid/?page=2"}, 2: {"results": [{"id": "c"}], "next": None}}[page]
        return httpx.Response(200, json=payload)

    with closing(Mem0Client(base_url="https://mem0.invalid", api_key="synthetic", transport=httpx.MockTransport(handle))) as client:
        assert [r["id"] for r in client.list_memories(filters={"user_id": "u"}, page_size=2, max_items=max_items)] == expected
    assert calls == ([1, 2] if max_items is None else [1])


def test_empty_terminal_page_is_valid():
    with closing(Mem0Client(base_url="https://mem0.invalid", api_key="synthetic", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": [], "next": None})))) as client:
        assert client.list_memories(filters={"user_id": "u"}) == []


@pytest.mark.parametrize("next_page", [True, False, 1, 0, 1.5, {"private": "synthetic-private-continuation"}, ["synthetic-private-continuation"]])
@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("operation", ["get_context", "aget_context", "get_memory", "export_memory"])
def test_invalid_continuation_type_obeys_policy(monkeypatch, caplog, next_page, policy, operation):
    calls = []

    def handle(request):
        calls.append(request)
        assert len(calls) == 1
        return httpx.Response(200, json={"results": [{"id": "m", "memory": "partial"}], "next": next_page})

    monkeypatch.setenv("MEM0_API_KEY", "synthetic")
    monkeypatch.setattr(mem0_manager, "Mem0Client", partial(Mem0Client, transport=httpx.MockTransport(handle)))
    with closing(mem0_manager.Mem0Manager(backend_config={"top_k": 1, "failure_policy": {"read": policy}})) as manager:

        def read():
            if operation == "aget_context":
                return asyncio.run(manager.aget_context("u"))
            if operation == "get_context":
                return manager.get_context("u")
            return getattr(manager, operation)(user_id="u")

        if policy == "fail_closed":
            with pytest.raises(MemoryReadError, match="next must be a string or null") as caught:
                read()
            assert "synthetic-private-continuation" not in str(caught.value)
        else:
            assert read() == ("" if operation.endswith("context") else {"facts": []})
            assert "next must be a string or null" in caplog.text
        assert len(calls) == 1
        assert "synthetic-private-continuation" not in caplog.text


@pytest.mark.parametrize("empty_counts", [[1], [2], [2, 2]])
def test_transient_empty_pages_can_recover_and_reset_the_counter(empty_counts):
    rows = [[{"id": "first"}]]
    for i, count in enumerate(empty_counts):
        rows.extend([[] for _ in range(count)])
        rows.append([{"id": f"after-{i}"}])
    calls = []

    def handle(request):
        page = int(request.url.params["page"])
        calls.append(page)
        return httpx.Response(200, json={"results": rows[page - 1], "next": f"page-{page + 1}" if page < len(rows) else None})

    with closing(Mem0Client(base_url="https://mem0.invalid", api_key="synthetic", transport=httpx.MockTransport(handle))) as client:
        assert [r["id"] for r in client.list_memories(filters={"user_id": "u"})] == ["first", *[f"after-{i}" for i in range(len(empty_counts))]]
    assert calls == list(range(1, len(rows) + 1))
