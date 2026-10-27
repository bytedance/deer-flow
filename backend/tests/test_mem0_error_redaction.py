"""Remote Mem0 failures retain diagnostics without rendering private payloads."""

import logging
import traceback
from contextlib import closing
from functools import partial

import httpx
import pytest
from langchain_core.messages import HumanMessage

from deerflow.agents.memory.backends.mem0 import mem0_manager
from deerflow.agents.memory.backends.mem0.client import Mem0APIError, Mem0AuthError, Mem0Client
from deerflow.agents.memory.manager import MemoryManagerError, MemoryReadError

PRIVATE = "synthetic-private-memory-and-credential"


def _handler(failure):
    def handle(request):
        if failure == "transport":
            raise httpx.ReadTimeout(PRIVATE, request=request)
        if failure == "encoding":
            return httpx.Response(200, content=PRIVATE.encode() + b"\xff")
        if failure == "json":
            return httpx.Response(200, content=(PRIVATE + "{").encode())
        return httpx.Response(failure, text=PRIVATE)

    return handle


def _operation(client, operation):
    if operation == "search":
        return client.search_memories(query="q", filters={"user_id": "u"}, top_k=5, threshold=0)
    if operation == "list":
        return client.list_memories(filters={"user_id": "u"})
    if operation == "add":
        return client.add_memories(messages=[{"role": "user", "content": "test"}], user_id="u")
    if operation == "delete":
        return client.delete_all_memories(user_id="u")
    return client.ping()


@pytest.mark.parametrize("operation", ["search", "list", "add", "delete", "ping"])
@pytest.mark.parametrize("failure", [401, 403, 429, 500, "transport", "encoding", "json"])
def test_client_errors_do_not_render_private_provider_data(operation, failure):
    with closing(Mem0Client(base_url="https://mem0.invalid", api_key=PRIVATE, transport=httpx.MockTransport(_handler(failure)))) as client:
        with pytest.raises(Mem0APIError) as caught:
            _operation(client, operation)
    error = caught.value
    assert PRIVATE not in "".join(traceback.format_exception(error))
    assert error.__cause__ is None
    if failure == 401:
        assert isinstance(error, Mem0AuthError)
    elif isinstance(failure, int):
        assert str(failure) in str(error)
    elif failure == "transport":
        assert "ReadTimeout" in str(error)
    else:
        assert "malformed JSON" in str(error)


@pytest.mark.parametrize("policy", ["fail_open", "fail_closed"])
@pytest.mark.parametrize("operation", ["get_context", "search", "get_memory", "export_memory"])
@pytest.mark.parametrize("failure", [500, "transport", "encoding"])
def test_read_policy_logs_and_errors_are_redacted(monkeypatch, caplog, policy, operation, failure):
    monkeypatch.setenv("MEM0_API_KEY", PRIVATE)
    monkeypatch.setattr(mem0_manager, "Mem0Client", partial(Mem0Client, transport=httpx.MockTransport(_handler(failure))))
    caplog.set_level(logging.WARNING)
    with closing(mem0_manager.Mem0Manager(backend_config={"failure_policy": {"read": policy}})) as manager:

        def read():
            if operation == "get_context":
                return manager.get_context("u")
            if operation == "search":
                return manager.search("q", user_id="u")
            return getattr(manager, operation)(user_id="u")

        if policy == "fail_closed":
            with pytest.raises(MemoryReadError) as caught:
                read()
            assert PRIVATE not in "".join(traceback.format_exception(caught.value))
            assert isinstance(caught.value.__cause__, Mem0APIError)
        else:
            assert read() == {"get_context": "", "search": [], "get_memory": {"facts": []}, "export_memory": {"facts": []}}[operation]
            assert "mem0 read failed" in caplog.text
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize("policy", ["log_and_drop", "raise"])
@pytest.mark.parametrize("operation", ["add", "clear_memory", "delete_memory"])
@pytest.mark.parametrize("failure", [500, "transport"])
def test_write_policy_logs_and_errors_are_redacted(monkeypatch, caplog, policy, operation, failure):
    monkeypatch.setenv("MEM0_API_KEY", PRIVATE)
    monkeypatch.setattr(mem0_manager, "Mem0Client", partial(Mem0Client, transport=httpx.MockTransport(_handler(failure))))
    with closing(mem0_manager.Mem0Manager(backend_config={"failure_policy": {"write": policy}})) as manager:

        def write():
            if operation == "add":
                return manager.add("t", [HumanMessage(content="test")], user_id="u")
            return getattr(manager, operation)(user_id="u")

        if policy == "raise":
            with pytest.raises(MemoryManagerError) as caught:
                write()
            assert PRIVATE not in "".join(traceback.format_exception(caught.value))
        else:
            write()
            assert "mem0 write failed" in caplog.text
    assert PRIVATE not in caplog.text
