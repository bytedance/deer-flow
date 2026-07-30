"""Task lifecycle and out-of-graph system model calls.

These two contributors are where the scope discipline lives. The host creates a
task-scoped store when the task starts and drops it when the task returns, so
``on_task_stop`` is the last moment anything accumulated during the run can be
saved. ``remove()`` rather than ``get()``: the record is being handed over, and
leaving a copy behind in a store that is about to be discarded reads as if it
still mattered.
"""

from __future__ import annotations

from dataclasses import dataclass

from deerflow_extension_api import (
    ExtensionData,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskOutcome,
)

from deerflow_extension_example.stats import StatsAccess, TaskRecord


@dataclass(frozen=True)
class TaskRecorder:
    """Implements ``TaskLifecycleContributor`` structurally -- no base class.

    The contract is a Protocol, so conformance is a matter of shape. That is
    also what lets the tests in this package verify it against a fake host.
    """

    access: StatsAccess

    async def on_task_start(self, app_store: ExtensionData, task_store: ExtensionData, info: TaskInfo) -> None:
        # Lead and subagent executions are the same type here on purpose: one
        # code path serves both, and `info.kind` is the only thing that differs.
        task_store.set(
            TaskRecord(
                task_id=info.task_id,
                kind=info.kind,
                thread_id=info.thread_id,
                resumed=info.resumed,
                agent_name=info.agent_name,
            )
        )
        self.access.of(app_store).note_task_start(info.kind)

    async def on_task_stop(self, app_store: ExtensionData, task_store: ExtensionData, info: TaskInfo, outcome: TaskOutcome) -> None:
        record = task_store.remove(TaskRecord)
        # A run that failed before its first model call has no record. The
        # outcome is still folded in: dropping the task would hide the failure.
        self.access.of(app_store).absorb(record, outcome.value)


@dataclass(frozen=True)
class SystemCallRecorder:
    """Implements ``SystemModelCallObserver`` structurally.

    These are the host's own model calls -- title generation, memory extraction,
    goal evaluation, summarization -- which happen outside the agent graph and
    are therefore invisible to middleware.
    """

    access: StatsAccess

    async def on_system_model_call(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        kind: SystemOperationKind,
        request: SystemModelRequest,
        result: SystemModelResult,
    ) -> None:
        # The host notifies on both the success and the failure path, so an
        # observer that only looked at `result.response` would silently miss
        # every failed system call. Key off `result.error` instead.
        self.access.of(app_store).note_system_call(
            kind.value,
            seconds=(result.duration_ms / 1000.0) if result.duration_ms is not None else None,
            failed=result.error is not None,
        )
