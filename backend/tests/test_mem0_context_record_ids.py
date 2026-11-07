"""Mem0 context deduplication failures must obey the configured read policy."""

from __future__ import annotations

import asyncio
import copy
import json
from functools import partial
from types import SimpleNamespace

import httpx
import pytest

from deerflow.agents.memory.backends.mem0 import mem0_manager
from deerflow.agents.memory.backends.mem0.client import Mem0APIError, Mem0Client
from deerflow.agents.memory.manager import MemoryReadError

PRIVATE = "synthetic-private-value"


def _read(manager, asynchronous):
    scope = {"agent_name": "Research-Agent", "thread_id": "thread-1"}
    if asynchronous:
        return asyncio.run(manager.aget_context("user-1", **scope))
    return manager.get_context("user-1", **scope)


def _manager(monkeypatch, handler, policy="fail_open", *, budget=12000):
    monkeypatch.setenv("MEM0_API_KEY", "synthetic-key")
    monkeypatch.setattr(mem0_manager, "Mem0Client", partial(Mem0Client, transport=httpx.MockTransport(handler)))
    return mem0_manager.Mem0Manager(backend_config={"failure_policy": {"read": policy}, "max_injection_chars": budget})


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("record_id", [[PRIVATE], {"private": PRIVATE}], ids=["list-id", "object-id"])
@pytest.mark.parametrize("later_page", [False, True], ids=["same-page", "later-page"])
def test_context_id_failure_obeys_read_policy(monkeypatch, caplog, asynchronous, policy, record_id, later_page):
    requests = []
    good = {"id": "valid", "memory": PRIVATE}
    bad = {"id": record_id, "memory": PRIVATE}

    def handle(request):
        requests.append(request)
        assert request.url.path == "/v3/memories/"
        assert json.loads(request.content) == {"filters": {"AND": [{"user_id": "user-1"}, {"agent_id": "Research-Agent"}, {"run_id": "thread-1"}]}}
        assert request.url.params["page_size"] == "8"
        if later_page and request.url.params["page"] == "1":
            return httpx.Response(200, json={"results": [good], "next": "page-2"})
        return httpx.Response(200, json={"results": [bad] if later_page else [good, bad]})

    manager = _manager(monkeypatch, handle, policy)
    try:
        if policy == "fail_open":
            assert _read(manager, asynchronous) == ""
            assert "mem0 read failed" in caplog.text
            assert "field id" in caplog.text
        else:
            with pytest.raises(MemoryReadError, match="field id") as error:
                _read(manager, asynchronous)
            assert isinstance(error.value.__cause__, Mem0APIError)
            assert PRIVATE not in str(error.value)
            assert error.value.__cause__.__cause__ is None
        assert len(requests) == (2 if later_page else 1)
        assert PRIVATE not in caplog.text
    finally:
        manager.close()


@pytest.mark.parametrize("record_id", ["m1", 17, 1.25, True, None, "missing"], ids=["string", "integer", "float", "boolean", "null", "missing"])
def test_context_preserves_legacy_scalar_ids_and_entry_budget(monkeypatch, record_id):
    first = {"id": record_id, "memory": "short"}
    if record_id == "missing":
        first.pop("id")
    records = [first, dict(first, memory="duplicate"), {"id": "big", "memory": "x" * 30}, {"id": "last", "memory": "end"}]
    before = copy.deepcopy(records)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"results": records})

    manager = _manager(monkeypatch, handle, budget=15)
    try:
        assert _read(manager, False) == "- short\n- end"
        assert len(requests) == 1
        assert records == before
    finally:
        manager.close()


def test_context_does_not_swallow_unrelated_programming_errors(monkeypatch):
    manager = _manager(monkeypatch, lambda request: httpx.Response(200, json={"results": []}))

    def broken_list(**kwargs):
        raise TypeError("local programming error")

    monkeypatch.setattr(manager._client, "list_memories", broken_list)
    try:
        with pytest.raises(TypeError, match="local programming error"):
            _read(manager, False)
    finally:
        manager.close()


@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("record_id", [[PRIVATE], {"private": PRIVATE}], ids=["list-id", "object-id"])
def test_prompt_loader_preserves_read_policy_for_unusable_ids(monkeypatch, policy, record_id):
    from deerflow.agents.lead_agent.prompt import _get_memory_context

    manager = _manager(monkeypatch, lambda request: httpx.Response(200, json={"results": [{"id": record_id, "memory": PRIVATE}]}), policy)
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True, backend_config={"failure_policy": {"read": policy}}))
    try:
        if policy == "fail_open":
            assert _get_memory_context("Research-Agent", app_config=config, user_id="user-1") == ""
        else:
            with pytest.raises(MemoryReadError, match="field id"):
                _get_memory_context("Research-Agent", app_config=config, user_id="user-1")
    finally:
        manager.close()


@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
def test_prompt_loader_keeps_valid_memory_context(monkeypatch, policy):
    from deerflow.agents.lead_agent.prompt import _get_memory_context

    manager = _manager(monkeypatch, lambda request: httpx.Response(200, json={"results": [{"id": "valid", "memory": "a valid fact"}]}), policy)
    monkeypatch.setattr("deerflow.agents.memory.get_memory_manager", lambda: manager)
    config = SimpleNamespace(memory=SimpleNamespace(enabled=True, injection_enabled=True, backend_config={"failure_policy": {"read": policy}}))
    try:
        assert _get_memory_context("Research-Agent", app_config=config, user_id="user-1") == "<memory>\n- a valid fact\n</memory>\n"
    finally:
        manager.close()
