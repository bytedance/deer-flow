"""Narrow host contract for delegated workers; providers report facts only."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol


def freeze_config(value: Any) -> Any:
    """Detach and freeze the JSON-shaped operator snapshot before approval."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_config(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_config(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Worker configuration must be JSON-shaped")


@dataclass(frozen=True)
class WorkerCapabilities:
    context_snapshot: bool = False
    model_override: bool = False
    pause_resume: bool = False
    trusted_evidence: bool = False


@dataclass(frozen=True)
class WorkerOperation:
    """Policy-visible operation; only the prompt argument is editable."""

    name: str
    arguments: Mapping[str, Any]
    prompt_argument: str = "prompt"
    description: str = "Delegate a bounded task to an external worker."

    def __post_init__(self):
        object.__setattr__(self, "arguments", freeze_config(self.arguments))


@dataclass(frozen=True)
class WorkerPlan:
    name: str
    backend: str
    description: str
    timeout_seconds: int
    config: Mapping[str, Any]

    def __post_init__(self):
        object.__setattr__(self, "config", freeze_config(self.config))


@dataclass(frozen=True)
class WorkerOutcome:
    status: str = "completed"
    result: str | None = None
    error: str | None = None
    stop_reason: str | None = None
    error_code: str | None = None
    backend_stop_reason: str | None = None
    external_usage: dict[str, Any] | None = None
    workspace_ref: str | None = None
    token_usage_records: list[dict] | None = None
    tool_receipts: list[dict] | None = None


@dataclass(frozen=True)
class WorkerExecution:
    execution_id: str
    prompt: str
    workspace: str
    publish: Callable[[str], None] = field(repr=False)


class WorkerBackend(Protocol):
    capabilities: WorkerCapabilities

    def bind(self, name: str, config: Mapping[str, Any], app_config: Any) -> Mapping[str, Any]: ...

    async def execute(self, plan: WorkerPlan, execution: WorkerExecution) -> WorkerOutcome: ...


def validate_backend(provider: Any) -> None:
    if not isinstance(getattr(provider, "capabilities", None), WorkerCapabilities):
        raise TypeError("Worker backend must declare WorkerCapabilities")
    if not callable(getattr(provider, "bind", None)) or not inspect.iscoroutinefunction(getattr(provider, "execute", None)):
        raise TypeError("Worker backend requires bind() and async execute()")
