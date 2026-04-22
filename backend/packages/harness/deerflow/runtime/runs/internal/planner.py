"""Execution plan builder for runs domain."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from ..types import RunRecord, RunSpec


@dataclass(frozen=True)
class ExecutionPlan:
    """Normalized execution inputs derived from a run record and spec."""

    record: RunRecord
    graph_input: dict[str, Any]
    runnable_config: dict[str, Any]
    stream_modes: list[str]
    stream_subgraphs: bool
    interrupt_before: list[str] | Literal["*"] | None
    interrupt_after: list[str] | Literal["*"] | None


class ExecutionPlanner:
    """Build executor-ready plans from public run specs."""

    def build(self, record: RunRecord, spec: RunSpec) -> ExecutionPlan:
        return ExecutionPlan(
            record=record,
            graph_input=self._normalize_graph_input(spec.input),
            runnable_config=deepcopy(spec.runnable_config),
            stream_modes=list(spec.stream_modes),
            stream_subgraphs=spec.stream_subgraphs,
            interrupt_before=spec.interrupt_before,
            interrupt_after=spec.interrupt_after,
        )

    def _normalize_graph_input(self, raw_input: dict[str, Any] | None) -> dict[str, Any]:
        if raw_input is None:
            return {}
        return deepcopy(raw_input)
