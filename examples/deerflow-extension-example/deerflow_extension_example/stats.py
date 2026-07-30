"""What this extension actually records.

Two scopes, one flush. The host creates a task-scoped ``ExtensionData`` per
agent execution and drops it when that execution returns, so anything a probe
accumulates during a run has to be moved into the app-scoped store before the
task ends -- which is what ``on_task_stop`` is for. Nothing here reaches back
into the host: these are plain objects the extension owns.

``ExtensionData`` locks its own storage, but the values you put *inside* it are
yours to protect. Each counter object therefore carries its own lock: probes on
the model axis and the tool axis can be re-entered while another await is in
flight, and a real extension should not have to reason about which of its
increments happen to be atomic.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from deerflow_extension_api import ExtensionData

#: Keeps ``/stats`` bounded regardless of what an operator configures.
MAX_RECENT_TASKS = 500
DEFAULT_RECENT_TASKS = 20


@dataclass
class TaskRecord:
    """Counters for one agent execution. Lives in the task-scoped store.

    Type-keyed storage is why this class exists at all: ``ExtensionData`` is
    keyed by type, not by string, so no other extension can collide with it.
    """

    task_id: str
    kind: str
    thread_id: str
    resumed: bool = False
    agent_name: str | None = None

    logical_model_calls: int = 0
    physical_model_calls: int = 0
    model_seconds: float = 0.0

    tool_calls: int = 0
    raw_result_chars: int = 0
    visible_result_chars: int = 0
    tools_used: dict[str, int] = field(default_factory=dict)

    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def note_logical_model_call(self) -> None:
        with self._lock:
            self.logical_model_calls += 1

    def note_physical_model_call(self, seconds: float) -> None:
        with self._lock:
            self.physical_model_calls += 1
            self.model_seconds += seconds

    def note_visible_tool_result(self, tool_name: str, chars: int) -> None:
        with self._lock:
            self.tool_calls += 1
            self.visible_result_chars += chars
            self.tools_used[tool_name] = self.tools_used.get(tool_name, 0) + 1

    def note_raw_tool_result(self, chars: int) -> None:
        with self._lock:
            self.raw_result_chars += chars

    def summary(self, outcome: str) -> dict[str, Any]:
        with self._lock:
            return {
                "task_id": self.task_id,
                "kind": self.kind,
                "thread_id": self.thread_id,
                "agent_name": self.agent_name,
                "resumed": self.resumed,
                "outcome": outcome,
                "logical_model_calls": self.logical_model_calls,
                "physical_model_calls": self.physical_model_calls,
                "model_seconds": round(self.model_seconds, 3),
                "tool_calls": self.tool_calls,
                "raw_result_chars": self.raw_result_chars,
                "visible_result_chars": self.visible_result_chars,
                "tools_used": dict(self.tools_used),
            }


@dataclass
class RunStats:
    """Process-wide totals. Lives in the app-scoped store.

    The app store outlives every run, so this is where per-task records go to
    be aggregated. ``recent_tasks`` is a bounded deque on purpose: an extension
    that grows without limit inside the host's process is a leak, not a feature.
    """

    recent_limit: int = DEFAULT_RECENT_TASKS

    builds_by_scope: dict[str, int] = field(default_factory=dict)
    models_seen: dict[str, int] = field(default_factory=dict)
    policy_max_subagents_per_run: int | None = None
    host_policy: dict[str, Any] | None = None

    tasks_started: int = 0
    tasks_by_outcome: dict[str, int] = field(default_factory=dict)
    tasks_by_kind: dict[str, int] = field(default_factory=dict)

    logical_model_calls: int = 0
    physical_model_calls: int = 0
    model_seconds: float = 0.0
    tool_calls: int = 0
    raw_result_chars: int = 0
    visible_result_chars: int = 0

    system_calls: dict[str, dict[str, Any]] = field(default_factory=dict)

    recent_tasks: deque[dict[str, Any]] = field(default_factory=deque)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.recent_limit = max(1, min(int(self.recent_limit), MAX_RECENT_TASKS))
        self.recent_tasks = deque(self.recent_tasks, maxlen=self.recent_limit)

    def note_agent_build(self, scope: str, model_name: str | None, max_subagents_per_run: int | None) -> None:
        """Record that the host asked us what to contribute to one agent build."""
        with self._lock:
            self.builds_by_scope[scope] = self.builds_by_scope.get(scope, 0) + 1
            if model_name:
                self.models_seen[model_name] = self.models_seen.get(model_name, 0) + 1
            # Proof that the narrow host-policy projection reaches the builder,
            # not just service startup. A real extension would use it to make a
            # decision (size a buffer, skip work the host already caps).
            if max_subagents_per_run is not None:
                self.policy_max_subagents_per_run = max_subagents_per_run

    def note_host_policy(self, policy: dict[str, Any]) -> None:
        with self._lock:
            self.host_policy = policy

    def note_task_start(self, kind: str) -> None:
        with self._lock:
            self.tasks_started += 1
            self.tasks_by_kind[kind] = self.tasks_by_kind.get(kind, 0) + 1

    def absorb(self, record: TaskRecord | None, outcome: str) -> None:
        """Fold one finished task into the totals.

        ``record`` is None when the task produced no observations at all (a run
        that failed before its first model call). The outcome is still counted:
        losing the task entirely would make failures invisible.
        """
        summary = record.summary(outcome) if record is not None else None
        with self._lock:
            self.tasks_by_outcome[outcome] = self.tasks_by_outcome.get(outcome, 0) + 1
            if summary is None:
                return
            self.logical_model_calls += summary["logical_model_calls"]
            self.physical_model_calls += summary["physical_model_calls"]
            self.model_seconds += summary["model_seconds"]
            self.tool_calls += summary["tool_calls"]
            self.raw_result_chars += summary["raw_result_chars"]
            self.visible_result_chars += summary["visible_result_chars"]
            self.recent_tasks.append(summary)

    def note_system_call(self, kind: str, seconds: float | None, failed: bool) -> None:
        with self._lock:
            entry = self.system_calls.setdefault(kind, {"calls": 0, "errors": 0, "seconds": 0.0})
            entry["calls"] += 1
            if failed:
                entry["errors"] += 1
            if seconds is not None:
                entry["seconds"] = round(entry["seconds"] + seconds, 3)

    def snapshot(self) -> dict[str, Any]:
        """A JSON-safe copy. Callers never get the live objects."""
        with self._lock:
            return {
                "agent_builds": {
                    "by_scope": dict(self.builds_by_scope),
                    "models_seen": dict(self.models_seen),
                    "policy_max_subagents_per_run": self.policy_max_subagents_per_run,
                },
                "host_policy": dict(self.host_policy) if self.host_policy else None,
                "tasks": {
                    "started": self.tasks_started,
                    "by_outcome": dict(self.tasks_by_outcome),
                    "by_kind": dict(self.tasks_by_kind),
                },
                "model_calls": {
                    # The gap between these two is the host's retry behaviour --
                    # the guarantee MODEL_LOGICAL and MODEL_PHYSICAL encode.
                    "logical": self.logical_model_calls,
                    "physical": self.physical_model_calls,
                    "seconds": round(self.model_seconds, 3),
                },
                "tool_calls": {
                    "count": self.tool_calls,
                    # The gap here is truncation and sanitization: TOOL_RAW sees
                    # the tool's own return, TOOL_VISIBLE sees what survived.
                    "raw_chars": self.raw_result_chars,
                    "visible_chars": self.visible_result_chars,
                },
                "system_model_calls": {kind: dict(entry) for kind, entry in self.system_calls.items()},
                "recent_tasks": list(self.recent_tasks),
            }


@dataclass(frozen=True)
class StatsAccess:
    """The one seam every component uses to reach the app-scoped stats.

    ``get_or_init`` rather than ``set``: the host hands the same app store to
    the builder, the lifecycle hooks, the observer and the service, and any of
    them can be the first to run. Whoever gets there first creates it.
    """

    recent_limit: int = DEFAULT_RECENT_TASKS

    def of(self, app_store: ExtensionData) -> RunStats:
        return app_store.get_or_init(RunStats, lambda: RunStats(recent_limit=self.recent_limit))
