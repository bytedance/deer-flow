"""The /events route forwards task_id + after_seq to the store (#3779).

The subtask card pages through one subagent task's persisted steps via these
query params; this locks the wiring so a rename/typo can't silently drop them
(which would make reload backfill fetch the whole run again, or nothing).
"""

import hashlib
from types import SimpleNamespace
from unittest import mock

import pytest
from langchain_core.messages import HumanMessage

from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal


@pytest.mark.anyio
async def test_list_run_events_forwards_task_id_and_after_seq():
    from app.gateway.routers.thread_runs import list_run_events

    calls: dict = {}

    class FakeStore:
        async def list_events(self, thread_id, run_id, *, event_types=None, task_id=None, limit=500, after_seq=None):
            calls.update(thread_id=thread_id, run_id=run_id, event_types=event_types, task_id=task_id, limit=limit, after_seq=after_seq)
            return [{"seq": 1, "event_type": "subagent.step"}]

    class FakeState:
        run_event_store = FakeStore()

    class FakeApp:
        state = FakeState()

    class FakeRequest:
        app = FakeApp()
        _deerflow_test_bypass_auth = True

    result = await list_run_events(
        thread_id="t1",
        run_id="r1",
        request=FakeRequest(),
        event_types="subagent.start,subagent.step,subagent.end",
        task_id="task-A",
        limit=500,
        after_seq=7,
    )

    assert result == [{"seq": 1, "event_type": "subagent.step"}]
    assert calls["task_id"] == "task-A"
    assert calls["after_seq"] == 7
    assert calls["event_types"] == ["subagent.start", "subagent.step", "subagent.end"]


@pytest.mark.anyio
async def test_effective_memory_flows_from_injection_to_the_existing_debug_api():
    """The production run-events route is the field-level consumer for M1."""
    from app.gateway.routers.thread_runs import list_run_events

    store = MemoryRunEventStore()
    journal = RunJournal("r1", "t1", store, flush_threshold=100)
    runtime = SimpleNamespace(context={"__run_journal": journal})
    memory = "<memory>\nUser prefers Python.\n</memory>\n"

    with (
        mock.patch("deerflow.agents.lead_agent.prompt._get_memory_context", return_value=memory),
        mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
        update = DynamicContextMiddleware().before_agent(
            {"messages": [HumanMessage(content="Hi", id="msg-1")]},
            runtime,
        )
    await journal.flush()

    class FakeState:
        run_event_store = store

    class FakeApp:
        state = FakeState()

    class FakeRequest:
        app = FakeApp()
        _deerflow_test_bypass_auth = True

    events = await list_run_events(
        thread_id="t1",
        run_id="r1",
        request=FakeRequest(),
        event_types="context:memory",
        task_id=None,
        limit=500,
        after_seq=None,
    )

    effective_content = update["messages"][1].content
    assert events[0]["content"] == {"content_sha256": hashlib.sha256(effective_content.encode("utf-8")).hexdigest()}
