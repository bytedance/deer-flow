"""Tests for deferred-tool promotion audit events."""

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_promotion_audit_middleware import DeferredToolPromotionAuditMiddleware
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


class _Recorder:
    def __init__(self):
        self.calls: list[dict] = []
        self.claimed: set[str] = set()

    def claim_tool_promotions(self, tool_names):
        names = sorted(set(tool_names) - self.claimed)
        self.claimed.update(names)
        return names

    def record_middleware(self, **kwargs):
        self.calls.append(kwargs)


class _ToolRequest:
    def __init__(self, *, name="tool_search", state=None, context=None, query="private query"):
        self.tool_call = {"name": name, "id": "tc1", "args": {"query": query}}
        self.state = state or {}
        self.runtime = SimpleNamespace(context=context or {})


def _middleware():
    return DeferredToolPromotionAuditMiddleware(frozenset({"mcp_a", "mcp_b"}), "h1")


def test_records_only_new_names_from_the_final_current_catalog_command():
    recorder = _Recorder()
    request = _ToolRequest(
        state={"promoted": {"catalog_hash": "h1", "names": ["mcp_b"]}},
        context={"__run_journal": recorder},
        query="credential-adjacent query",
    )
    result = Command(
        update={
            "promoted": {"catalog_hash": "h1", "names": ["not_deferred", "mcp_b", "mcp_a", "mcp_a"]},
            "messages": [ToolMessage(content="private schema", tool_call_id="tc1", name="tool_search")],
        }
    )

    assert _middleware().wrap_tool_call(request, lambda _: result) is result

    assert recorder.calls == [
        {
            "tag": "tool_promotion",
            "name": "DeferredToolPromotionAuditMiddleware",
            "hook": "wrap_tool_call",
            "action": "promote",
            "changes": {
                "source": "tool_search",
                "tool_names": ["mcp_a"],
                "count": 1,
                "is_subagent": False,
                "agent_id": None,
            },
        }
    ]
    persisted = repr(recorder.calls)
    assert "credential-adjacent query" not in persisted
    assert "private schema" not in persisted
    assert "h1" not in persisted


@pytest.mark.asyncio
async def test_async_records_promotion_but_repeated_stale_and_non_search_results_do_not():
    recorder = _Recorder()
    middleware = _middleware()
    request = _ToolRequest(context={"__run_journal": recorder})
    promoted = Command(update={"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})

    async def handle_promoted(_):
        return promoted

    assert await middleware.awrap_tool_call(request, handle_promoted) is promoted
    assert recorder.calls[0]["changes"]["tool_names"] == ["mcp_a"]

    request.state = {"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}}

    async def handle_stale(_):
        return Command(update={"promoted": {"catalog_hash": "stale", "names": ["mcp_b"]}})

    assert await middleware.awrap_tool_call(request, handle_promoted) is promoted
    assert await middleware.awrap_tool_call(request, handle_stale)
    request.tool_call["name"] = "another_tool"
    assert await middleware.awrap_tool_call(request, handle_promoted) is promoted
    assert len(recorder.calls) == 1


def test_final_handler_result_is_observed_without_rebuilding_it():
    """An outer audit wrapper must see names after inner policy filtering."""
    recorder = _Recorder()
    request = _ToolRequest(context={"__run_journal": recorder})
    policy_filtered = Command(update={"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})

    observed = _middleware().wrap_tool_call(request, lambda _: policy_filtered)

    assert observed is policy_filtered
    assert recorder.calls[0]["changes"]["tool_names"] == ["mcp_a"]


@pytest.mark.parametrize(
    "result",
    [
        ToolMessage(content="no match", tool_call_id="tc1", name="tool_search"),
        Command(update={}),
        Command(update={"promoted": {"catalog_hash": "h1", "names": []}}),
        Command(update={"promoted": {"catalog_hash": "h1", "names": ["mcp_a", 7]}}),
    ],
)
def test_non_promotion_and_malformed_results_emit_nothing(result):
    recorder = _Recorder()
    request = _ToolRequest(context={"__run_journal": recorder})

    assert _middleware().wrap_tool_call(request, lambda _: result) is result
    assert recorder.calls == []


def test_recorder_failure_does_not_replace_the_tool_result(caplog):
    class BrokenRecorder:
        def record_middleware(self, **kwargs):
            raise RuntimeError("event store unavailable")

    request = _ToolRequest(context={"__run_journal": BrokenRecorder()})
    result = Command(update={"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})

    with caplog.at_level("WARNING"):
        assert _middleware().wrap_tool_call(request, lambda _: result) is result

    assert "Failed to record middleware:tool_promotion event" in caplog.text


@pytest.mark.anyio
async def test_event_round_trips_through_run_journal_and_store():
    store = MemoryRunEventStore()
    journal = RunJournal("run-1", "thread-1", store, flush_threshold=100)
    request = _ToolRequest(context={"__run_journal": journal})
    result = Command(update={"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})

    assert _middleware().wrap_tool_call(request, lambda _: result) is result
    await journal.flush()

    events = await store.list_events("thread-1", "run-1")
    assert len(events) == 1
    assert events[0]["event_type"] == "middleware:tool_promotion"
    assert events[0]["category"] == "middleware"
    assert events[0]["content"]["changes"] == {
        "source": "tool_search",
        "tool_names": ["mcp_a"],
        "count": 1,
        "is_subagent": False,
        "agent_id": None,
    }


@pytest.mark.anyio
async def test_parallel_searches_claim_the_same_new_name_only_once():
    """Parallel tool Sends share pre-step state but must not duplicate events."""
    store = MemoryRunEventStore()
    journal = RunJournal("run-parallel", "thread-1", store, flush_threshold=100)
    middleware = _middleware()
    result = Command(update={"promoted": {"catalog_hash": "h1", "names": ["mcp_a"]}})
    requests = [
        _ToolRequest(context={"__run_journal": journal}),
        _ToolRequest(context={"__run_journal": journal}),
    ]

    async def handler(_):
        await asyncio.sleep(0)
        return result

    observed = await asyncio.gather(*(middleware.awrap_tool_call(request, handler) for request in requests))
    await journal.flush()

    assert observed == [result, result]
    events = await store.list_events("thread-1", "run-parallel")
    assert [event["event_type"] for event in events] == ["middleware:tool_promotion"]
