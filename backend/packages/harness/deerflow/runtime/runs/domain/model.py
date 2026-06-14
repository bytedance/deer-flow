"""Run aggregate root and lifecycle invariants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deerflow.utils.time import now_iso

from .errors import InvalidRunTransition
from .events import RunCancelled, RunCompleted, RunCreated, RunEvent, RunFailed, RunStarted
from .identifiers import AssistantId, RunId, ThreadId, require_non_empty
from .value_objects import CancelAction, MultitaskStrategy, RunScope, RunStatus

# Keep lifecycle transitions explicit so later application code cannot invent
# ad hoc status moves outside the aggregate.
_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.pending: frozenset(
        {
            RunStatus.running,
            RunStatus.error,
            RunStatus.timeout,
            RunStatus.interrupted,
        }
    ),
    RunStatus.running: frozenset(
        {
            RunStatus.success,
            RunStatus.error,
            RunStatus.timeout,
            RunStatus.interrupted,
        }
    ),
    RunStatus.success: frozenset(),
    RunStatus.error: frozenset(),
    RunStatus.timeout: frozenset(),
    RunStatus.interrupted: frozenset(),
}


@dataclass
class Run:
    """Run aggregate root.

    The aggregate owns lifecycle invariants only. Infrastructure concerns such
    as SQL sessions, SSE frames, Redis clients, and FastAPI requests stay out of
    this model.
    """

    run_id: RunId
    thread_id: ThreadId
    status: RunStatus
    assistant_id: AssistantId | None = None
    scope: RunScope = RunScope.stateful
    multitask_strategy: MultitaskStrategy = MultitaskStrategy.reject
    metadata: dict[str, Any] = field(default_factory=dict)
    kwargs: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    error: str | None = None
    model_name: str | None = None
    _pending_events: list[RunEvent] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.run_id = RunId(require_non_empty(str(self.run_id), field_name="run_id"))
        self.thread_id = ThreadId(require_non_empty(str(self.thread_id), field_name="thread_id"))
        if self.assistant_id is not None:
            self.assistant_id = AssistantId(require_non_empty(str(self.assistant_id), field_name="assistant_id"))

    @classmethod
    def create(
        cls,
        *,
        run_id: RunId,
        thread_id: ThreadId,
        assistant_id: AssistantId | None = None,
        scope: RunScope = RunScope.stateful,
        multitask_strategy: MultitaskStrategy = MultitaskStrategy.reject,
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        model_name: str | None = None,
        created_at: str | None = None,
    ) -> Run:
        timestamp = created_at or now_iso()
        run = cls(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            status=RunStatus.pending,
            scope=scope,
            multitask_strategy=multitask_strategy,
            metadata=metadata or {},
            kwargs=kwargs or {},
            created_at=timestamp,
            updated_at=timestamp,
            model_name=model_name,
        )
        run._record_event(
            RunCreated(
                run_id=run.run_id,
                thread_id=run.thread_id,
                occurred_at=timestamp,
                assistant_id=run.assistant_id,
                metadata=dict(run.metadata),
            )
        )
        return run

    @property
    def is_terminal(self) -> bool:
        return not _ALLOWED_TRANSITIONS[self.status]

    def pull_events(self) -> tuple[RunEvent, ...]:
        # Domain events are drained by the application layer after the aggregate
        # has accepted a state change.
        events = tuple(self._pending_events)
        self._pending_events.clear()
        return events

    def mark_started(self, *, at: str | None = None) -> None:
        self._transition_to(RunStatus.running, at=at)

    def mark_completed(self, *, at: str | None = None) -> None:
        self._transition_to(RunStatus.success, at=at)

    def mark_failed(self, error: str | None = None, *, at: str | None = None) -> None:
        self._transition_to(RunStatus.error, error=error, at=at)

    def mark_timed_out(self, error: str | None = None, *, at: str | None = None) -> None:
        self._transition_to(RunStatus.timeout, error=error, at=at)

    def mark_cancelled(self, *, action: CancelAction = CancelAction.interrupt, at: str | None = None) -> None:
        self._transition_to(RunStatus.interrupted, action=action, at=at)

    def _transition_to(
        self,
        target: RunStatus,
        *,
        error: str | None = None,
        action: CancelAction = CancelAction.interrupt,
        at: str | None = None,
    ) -> None:
        if target == self.status:
            return
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidRunTransition(self.status, target)

        timestamp = at or now_iso()
        self.status = target
        self.updated_at = timestamp
        if error is not None:
            self.error = error
        self._record_event(self._event_for_transition(target, timestamp, error=error, action=action))

    def _event_for_transition(
        self,
        target: RunStatus,
        occurred_at: str,
        *,
        error: str | None,
        action: CancelAction,
    ) -> RunEvent:
        # Keep event construction next to the transition rules so a new status
        # cannot be added without an explicit durable event shape.
        if target == RunStatus.running:
            return RunStarted(run_id=self.run_id, thread_id=self.thread_id, occurred_at=occurred_at)
        if target == RunStatus.success:
            return RunCompleted(run_id=self.run_id, thread_id=self.thread_id, occurred_at=occurred_at)
        if target in (RunStatus.error, RunStatus.timeout):
            return RunFailed(
                run_id=self.run_id,
                thread_id=self.thread_id,
                status=target,
                occurred_at=occurred_at,
                error=error,
            )
        if target == RunStatus.interrupted:
            return RunCancelled(
                run_id=self.run_id,
                thread_id=self.thread_id,
                occurred_at=occurred_at,
                action=action,
            )
        raise InvalidRunTransition(self.status, target)

    def _record_event(self, event: RunEvent) -> None:
        self._pending_events.append(event)


__all__ = [
    "Run",
    "RunStatus",
]
