"""A waited run that parked for approval must not report values-only completion.

Both wait endpoints treat a clean graph exit as completion and return
``snapshot.values``. A real ``interrupt()`` exits the graph normally, so a run
that parked — including a ``Command(resume=...)`` that immediately reached a
second gated call — looks identical to a finished turn from there. The parked
payload lives exclusively on ``snapshot.tasks``, never in channel values, so
without an explicit projection the caller receives neither the new approval
request nor any hint that the turn is unfinished.

``start_run`` deliberately keeps approval enabled for a resume (downgrading it
would discard the posted decisions), which is exactly what makes the second park
reachable over HTTP.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.types import Interrupt

from deerflow.runtime import RunStatus, project_snapshot_for_wait

PAYLOAD = {"action_requests": [{"name": "bash_tool", "args": {"command": "rm -rf /"}}]}


def _snapshot(*, tasks=(), values=None, checkpoint_id="ckpt-1"):
    return SimpleNamespace(
        values=values if values is not None else {"messages": []},
        tasks=tasks,
        config={"configurable": {"checkpoint_id": checkpoint_id}} if checkpoint_id else {},
    )


def _parked_task(*, task_id="task-1", interrupt_id="int-1", value=None):
    return SimpleNamespace(id=task_id, interrupts=(Interrupt(value=value if value is not None else PAYLOAD, id=interrupt_id),))


class TestAParkIsDistinctFromACancellation:
    """The park status must not collide with a durable ``RunStatus`` value.

    The same endpoint's fallback branch returns ``{"status":
    record.status.value, "error": ...}``, and ``RunStatus.interrupted`` is what
    the cancellation path persists. Both branches are reachable from one
    request — the projection only runs when the snapshot has a ``checkpoint_id``
    — so reusing ``"interrupted"`` would leave a client unable to tell a
    resumable park from a terminal cancellation except by probing for keys.
    """

    def test_the_park_status_is_not_a_run_status_value(self):
        result = project_snapshot_for_wait(_snapshot(tasks=(_parked_task(),)))

        assert result["status"] not in {status.value for status in RunStatus}

    def test_the_park_status_is_not_the_cancellation_status(self):
        result = project_snapshot_for_wait(_snapshot(tasks=(_parked_task(),)))

        assert result["status"] != RunStatus.interrupted.value


class TestAParkIsNotCompletion:
    def test_a_parked_snapshot_is_reported_as_awaiting_approval(self):
        result = project_snapshot_for_wait(_snapshot(tasks=(_parked_task(),)))

        assert result["status"] == "interrupted_for_approval"

    def test_the_approval_payload_reaches_the_caller(self):
        result = project_snapshot_for_wait(_snapshot(tasks=(_parked_task(),)))

        interrupts = result["interrupts"]
        assert [entry["id"] for entry in interrupts["task-1"]] == ["int-1"]
        assert interrupts["task-1"][0]["value"] == PAYLOAD

    def test_the_parked_tasks_are_projected_with_the_shared_serializer(self):
        """``tasks`` carries the same interrupts, matching the thread endpoints."""
        result = project_snapshot_for_wait(_snapshot(tasks=(_parked_task(),)))

        assert [entry["id"] for task in result["tasks"] for entry in (task.get("interrupts") or ())] == ["int-1"]

    def test_the_values_gathered_so_far_are_still_returned(self):
        """A park is unfinished, not empty — the caller keeps what exists."""
        result = project_snapshot_for_wait(_snapshot(tasks=(_parked_task(),), values={"messages": [], "title": "T"}))

        assert result["values"]["title"] == "T"

    def test_several_parked_tasks_are_all_surfaced(self):
        snapshot = _snapshot(
            tasks=(
                _parked_task(task_id="task-a", interrupt_id="int-a"),
                _parked_task(task_id="task-b", interrupt_id="int-b"),
            )
        )

        result = project_snapshot_for_wait(snapshot)

        assert sorted(result["interrupts"]) == ["task-a", "task-b"]


class TestAnOrdinaryCompletionIsUnchanged:
    """The values-only contract must survive for every non-parked run."""

    def test_a_finished_run_returns_bare_values(self):
        result = project_snapshot_for_wait(_snapshot(values={"messages": [], "title": "done"}))

        assert result == {"messages": [], "title": "done"}

    def test_a_finished_run_carries_no_status_or_interrupt_keys(self):
        result = project_snapshot_for_wait(_snapshot())

        assert "status" not in result
        assert "interrupts" not in result

    def test_a_task_without_interrupts_is_not_a_park(self):
        """An in-flight task is not an approval request."""
        result = project_snapshot_for_wait(_snapshot(tasks=(SimpleNamespace(id="task-1", interrupts=()),)))

        assert "status" not in result

    @pytest.mark.parametrize("tasks", [None, ()])
    def test_a_snapshot_without_tasks_is_a_completion(self, tasks):
        result = project_snapshot_for_wait(_snapshot(tasks=tasks))

        assert "status" not in result


class TestTheProjectionIsDefensive:
    """A malformed snapshot must not turn a completion into a 500."""

    def test_a_snapshot_with_no_tasks_attribute_still_projects(self):
        snapshot = SimpleNamespace(values={"messages": []}, config={})

        assert project_snapshot_for_wait(snapshot) == {"messages": []}

    def test_non_dict_values_are_passed_through_the_serializer(self):
        result = project_snapshot_for_wait(_snapshot(values={}))

        assert result == {}
