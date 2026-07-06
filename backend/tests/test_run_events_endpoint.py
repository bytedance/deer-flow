"""The /events route forwards task_id + after_seq to the store (#3779).

The subtask card pages through one subagent task's persisted steps via these
query params; this locks the wiring so a rename/typo can't silently drop them
(which would make reload backfill fetch the whole run again, or nothing).
"""

import pytest


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
