"""Application command DTOs for run use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..domain import AssistantId, CancelAction, DisconnectMode, MultitaskStrategy, RunId, RunScope, ThreadId


@dataclass(frozen=True)
class CreateRunCommand:
    thread_id: ThreadId
    assistant_id: AssistantId | None = None
    input: dict[str, Any] | None = None
    command: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    scope: RunScope = RunScope.stateful
    on_disconnect: DisconnectMode = DisconnectMode.cancel
    multitask_strategy: MultitaskStrategy = MultitaskStrategy.reject
    stream_mode: list[str] | str | None = None
    stream_subgraphs: bool = False
    interrupt_before: list[str] | Literal["*"] | None = None
    interrupt_after: list[str] | Literal["*"] | None = None


@dataclass(frozen=True)
class CancelRunCommand:
    run_id: RunId
    action: CancelAction = CancelAction.interrupt
    wait: bool = False


@dataclass(frozen=True)
class JoinRunStreamCommand:
    run_id: RunId
    last_event_id: str | None = None


__all__ = [
    "CancelRunCommand",
    "CreateRunCommand",
    "JoinRunStreamCommand",
]
