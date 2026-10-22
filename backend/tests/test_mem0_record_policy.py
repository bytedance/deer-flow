"""Mem0 record conversion must respect read policies, using real HTTP/client code."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any

import httpx
import pytest

from deerflow.agents.memory.backends.mem0 import mem0_manager
from deerflow.agents.memory.backends.mem0.client import Mem0APIError, Mem0Client
from deerflow.agents.memory.manager import MemoryReadError

OPERATIONS = ["search", "asearch", "get_memory", "export_memory"]
POLICIES = ["fail_open", "fail_closed"]
PRIVATE_CONTENT = "synthetic-memory-content-must-not-appear-in-errors"


def _record(**overrides: Any) -> dict[str, Any]:
    return {"id": "m1", "memory": PRIVATE_CONTENT, "score": 0.8, "categories": ["preference"], "metadata": {"source": "chat"}, **overrides}


@contextmanager
def _manager(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]],
    policy: str,
    *,
    later_page: list[dict[str, Any]] | None = None,
) -> Iterator[tuple[mem0_manager.Mem0Manager, list[httpx.Request]]]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path in {"/v3/memories/search/", "/v3/memories/"}
        if later_page is not None and request.url.params.get("page") == "1":
            return httpx.Response(200, json={"results": records, "next": "page-2"})
        return httpx.Response(200, json={"results": records if later_page is None else later_page})

    monkeypatch.setenv("MEM0_API_KEY", "synthetic-key")
    monkeypatch.setattr(mem0_manager, "Mem0Client", partial(Mem0Client, transport=httpx.MockTransport(handle)))
    manager = mem0_manager.Mem0Manager(backend_config={"failure_policy": {"read": policy}})
    try:
        yield manager, requests
    finally:
        manager.close()


def _read(manager: mem0_manager.Mem0Manager, operation: str) -> list[dict[str, Any]] | dict[str, Any]:
    scope = {"user_id": "synthetic-user", "agent_name": "Research-Agent"}
    if operation == "search":
        return manager.search("preferences", **scope)
    if operation == "asearch":
        return asyncio.run(manager.asearch("preferences", **scope))
    return getattr(manager, operation)(**scope)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("score", "private-invalid-score", id="score-text"),
        pytest.param("score", [0.8], id="score-list"),
        pytest.param("score", "NaN", id="score-nan"),
        pytest.param("score", "Infinity", id="score-infinity"),
        pytest.param("score", 10**400, id="score-overflow"),
        pytest.param("metadata", ["private-invalid-metadata"], id="metadata-list"),
        pytest.param("categories", {"private-category": "value"}, id="categories-object"),
        pytest.param("categories", "private-category", id="categories-text"),
        pytest.param("categories", ["preference", {"private-category": "value"}], id="categories-element"),
    ],
)
def test_invalid_record_fields_follow_read_policy(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, operation: str, policy: str, field: str, value: Any) -> None:
    # A valid earlier record must not escape as partial success when a later one is invalid.
    records = [_record(id="valid"), _record(id="invalid", **{field: value})]
    with _manager(monkeypatch, records, policy) as (manager, requests):
        if policy == "fail_open":
            assert _read(manager, operation) == ([] if operation in {"search", "asearch"} else {"facts": []})
            assert field in caplog.text
        else:
            with pytest.raises(MemoryReadError, match=field) as error:
                _read(manager, operation)
            assert isinstance(error.value.__cause__, Mem0APIError)
            assert PRIVATE_CONTENT not in str(error.value)
            assert "private-" not in str(error.value)
        assert len(requests) == 1  # Read errors do not introduce a retry.
    assert PRIVATE_CONTENT not in caplog.text
    assert "private-" not in caplog.text


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("policy", POLICIES)
def test_valid_records_and_optional_defaults_keep_scope(monkeypatch: pytest.MonkeyPatch, operation: str, policy: str) -> None:
    records = [
        _record(score="0.75"),
        {"id": "missing", "memory": "optional fields missing"},
        _record(id="null", score=None, metadata=None, categories=None),
        _record(id="empty", score="", metadata={}, categories=[]),
    ]
    with _manager(monkeypatch, records, policy) as (manager, requests):
        result = _read(manager, operation)
        facts = result if isinstance(result, list) else result["facts"]
        assert [fact["id"] for fact in facts] == ["m1", "missing", "null", "empty"]
        assert [fact["confidence"] for fact in facts] == [0.75, 0.0, 0.0, 0.0]
        assert [fact["category"] for fact in facts] == ["preference", "context", "context", "context"]
        assert [fact["source"] for fact in facts] == ["chat", "", "", ""]
        assert json.loads(requests[0].content)["filters"] == {"AND": [{"user_id": "synthetic-user"}, {"agent_id": "Research-Agent"}]}


@pytest.mark.parametrize("operation", ["get_memory", "export_memory"])
@pytest.mark.parametrize("policy", POLICIES)
def test_bad_record_on_later_page_cannot_return_partial_memory(monkeypatch: pytest.MonkeyPatch, operation: str, policy: str) -> None:
    with _manager(monkeypatch, [_record()], policy, later_page=[_record(id="later", score="invalid")]) as (manager, requests):
        if policy == "fail_open":
            assert _read(manager, operation) == {"facts": []}
        else:
            with pytest.raises(MemoryReadError, match="score"):
                _read(manager, operation)
        assert [request.url.params["page"] for request in requests] == ["1", "2"]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("policy", POLICIES)
def test_local_conversion_errors_are_not_treated_as_remote_data_errors(monkeypatch: pytest.MonkeyPatch, operation: str, policy: str) -> None:
    def programming_error(record: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("synthetic local programming error")

    monkeypatch.setattr(mem0_manager, "_to_fact", programming_error)
    with _manager(monkeypatch, [_record()], policy) as (manager, _):
        with pytest.raises(ValueError, match="local programming error"):
            _read(manager, operation)
