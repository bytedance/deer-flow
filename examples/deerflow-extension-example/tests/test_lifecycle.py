"""Task scope hand-off, and the system-model observer's two paths."""

from __future__ import annotations

from deerflow_extension_api import (
    ExtensionData,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskOutcome,
)

from deerflow_extension_example.lifecycle import SystemCallRecorder, TaskRecorder
from deerflow_extension_example.stats import RunStats, StatsAccess, TaskRecord

ACCESS = StatsAccess(recent_limit=3)


def _info(kind: str = "lead", **overrides: object) -> TaskInfo:
    fields: dict[str, object] = {
        "task_id": "task-1",
        "run_id": "run-1",
        "thread_id": "thread-1",
        "kind": kind,
    }
    fields.update(overrides)
    return TaskInfo(**fields)  # type: ignore[arg-type]


async def test_start_opens_a_task_record_and_stop_hands_it_over() -> None:
    recorder = TaskRecorder(ACCESS)
    app_store, task_store = ExtensionData("app"), ExtensionData("task-1")
    info = _info(agent_name="lead-agent")

    await recorder.on_task_start(app_store, task_store, info)
    task_store.get(TaskRecord).note_physical_model_call(0.5)
    await recorder.on_task_stop(app_store, task_store, info, TaskOutcome.COMPLETED)

    # Taken out, not copied: the store is about to be discarded by the host.
    assert task_store.get(TaskRecord) is None
    snapshot = app_store.get(RunStats).snapshot()
    assert snapshot["tasks"] == {"started": 1, "by_outcome": {"completed": 1}, "by_kind": {"lead": 1}}
    assert snapshot["model_calls"]["physical"] == 1
    assert snapshot["recent_tasks"][0]["agent_name"] == "lead-agent"
    assert snapshot["recent_tasks"][0]["outcome"] == "completed"


async def test_lead_and_subagent_share_one_code_path() -> None:
    recorder = TaskRecorder(ACCESS)
    app_store = ExtensionData("app")

    for kind, task_id in (("lead", "task-1"), ("subagent", "task-2")):
        task_store = ExtensionData(task_id)
        info = _info(kind, task_id=task_id, parent_task_id="task-1" if kind == "subagent" else None)
        await recorder.on_task_start(app_store, task_store, info)
        await recorder.on_task_stop(app_store, task_store, info, TaskOutcome.COMPLETED)

    assert app_store.get(RunStats).snapshot()["tasks"]["by_kind"] == {"lead": 1, "subagent": 1}


async def test_a_stop_without_observations_still_counts_the_outcome() -> None:
    """A run that failed before its first model call must not vanish."""
    recorder = TaskRecorder(ACCESS)
    app_store, task_store = ExtensionData("app"), ExtensionData("task-1")

    await recorder.on_task_stop(app_store, task_store, _info(), TaskOutcome.FAILED)

    snapshot = app_store.get(RunStats).snapshot()
    assert snapshot["tasks"]["by_outcome"] == {"failed": 1}
    assert snapshot["recent_tasks"] == []


async def test_every_outcome_is_recorded_under_its_own_name() -> None:
    recorder = TaskRecorder(ACCESS)
    app_store = ExtensionData("app")

    for outcome in (TaskOutcome.COMPLETED, TaskOutcome.ABORTED, TaskOutcome.FAILED):
        await recorder.on_task_stop(app_store, ExtensionData("task"), _info(), outcome)

    assert app_store.get(RunStats).snapshot()["tasks"]["by_outcome"] == {
        "completed": 1,
        "aborted": 1,
        "failed": 1,
    }


async def test_recent_tasks_stays_bounded_by_the_configured_limit() -> None:
    recorder = TaskRecorder(ACCESS)  # recent_limit=3
    app_store = ExtensionData("app")

    for index in range(5):
        task_store = ExtensionData(f"task-{index}")
        info = _info(task_id=f"task-{index}")
        await recorder.on_task_start(app_store, task_store, info)
        await recorder.on_task_stop(app_store, task_store, info, TaskOutcome.COMPLETED)

    recent = app_store.get(RunStats).snapshot()["recent_tasks"]
    assert [entry["task_id"] for entry in recent] == ["task-2", "task-3", "task-4"]


async def test_system_model_calls_are_counted_per_kind() -> None:
    observer = SystemCallRecorder(ACCESS)
    app_store, task_store = ExtensionData("app"), ExtensionData("task-1")

    await observer.on_system_model_call(
        app_store,
        task_store,
        SystemOperationKind.TITLE,
        SystemModelRequest(model_name="fast-model"),
        SystemModelResult(response="A title", duration_ms=250.0),
    )
    await observer.on_system_model_call(
        app_store,
        task_store,
        SystemOperationKind.MEMORY,
        SystemModelRequest(),
        SystemModelResult(response="ok", duration_ms=1000.0),
    )

    assert app_store.get(RunStats).snapshot()["system_model_calls"] == {
        "title": {"calls": 1, "errors": 0, "seconds": 0.25},
        "memory": {"calls": 1, "errors": 0, "seconds": 1.0},
    }


async def test_a_failed_system_call_is_not_silently_missed() -> None:
    """The host notifies on both paths; keying off `response` would lose this."""
    observer = SystemCallRecorder(ACCESS)
    app_store = ExtensionData("app")

    await observer.on_system_model_call(
        app_store,
        ExtensionData("task-1"),
        SystemOperationKind.SUMMARIZATION,
        SystemModelRequest(),
        SystemModelResult(response=None, error=RuntimeError("rate limited"), duration_ms=None),
    )

    assert app_store.get(RunStats).snapshot()["system_model_calls"] == {"summarization": {"calls": 1, "errors": 1, "seconds": 0.0}}
