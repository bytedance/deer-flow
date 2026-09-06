"""The example's five deliberately small contribution implementations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from deerflow_extension_api import (
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    ExtensionRuntimeDeps,
    MiddlewarePlacement,
    Placement,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskOutcome,
    task_store_from_runtime,
)
from fastapi import APIRouter, Depends, HTTPException
from langchain.agents.middleware import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest


@dataclass
class ExampleStats:
    """Small extension-owned value used in both app and task stores."""

    tool_calls: int = 0
    tasks: dict[str, int] = field(default_factory=dict)
    system_model_calls: dict[str, dict[str, int]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def note_tool_call(self) -> None:
        with self._lock:
            self.tool_calls += 1

    def task_tool_calls(self) -> int:
        with self._lock:
            return self.tool_calls

    def absorb_task(self, tool_calls: int, outcome: TaskOutcome) -> None:
        with self._lock:
            self.tool_calls += tool_calls
            key = outcome.value
            self.tasks[key] = self.tasks.get(key, 0) + 1

    def note_system_call(self, kind: SystemOperationKind, *, failed: bool) -> None:
        with self._lock:
            entry = self.system_model_calls.setdefault(
                kind.value,
                {"calls": 0, "errors": 0},
            )
            entry["calls"] += 1
            if failed:
                entry["errors"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tasks": dict(self.tasks),
                "tool_calls": self.tool_calls,
                "system_model_calls": {kind: dict(counts) for kind, counts in self.system_model_calls.items()},
            }


def _stats(store: ExtensionData) -> ExampleStats:
    return store.get_or_init(ExampleStats, ExampleStats)


class ExampleMiddleware(AgentMiddleware):
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        task_store = task_store_from_runtime(getattr(request, "runtime", None))
        task_stats = task_store.get(ExampleStats) if task_store is not None else None
        if task_stats is not None:
            task_stats.note_tool_call()
        return await handler(request)


class ExampleMiddlewareContributor:
    def contribute_middlewares(
        self,
        app_store: ExtensionData,
        ctx: AgentBuildContext,
    ) -> Sequence[MiddlewarePlacement]:
        return (
            MiddlewarePlacement(
                ExampleMiddleware(),
                Placement.TOOL_VISIBLE,
                AgentScope.BOTH,
            ),
        )


class ExampleTaskLifecycle:
    async def on_task_start(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: TaskInfo,
    ) -> None:
        task_store.set(ExampleStats())

    async def on_task_stop(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: TaskInfo,
        outcome: TaskOutcome,
    ) -> None:
        task_stats = task_store.remove(ExampleStats)
        _stats(app_store).absorb_task(
            task_stats.task_tool_calls() if task_stats is not None else 0,
            outcome,
        )


class ExampleSystemObserver:
    async def on_system_model_call(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        kind: SystemOperationKind,
        request: SystemModelRequest,
        result: SystemModelResult,
    ) -> None:
        _stats(app_store).note_system_call(kind, failed=result.error is not None)


class ExampleService:
    def __init__(self) -> None:
        self._deps: ExtensionRuntimeDeps | None = None

    async def start(self, deps: ExtensionRuntimeDeps) -> None:
        self._deps = deps

    async def stop(self) -> None:
        self._deps = None

    async def require_deps(self) -> ExtensionRuntimeDeps:
        deps = self._deps
        if deps is None or deps.app_store is None:
            raise HTTPException(
                status_code=503,
                detail="extension-example is not running",
            )
        return deps


def build_router(service: ExampleService) -> APIRouter:
    """Build paths during registration, before runtime dependencies exist."""
    router = APIRouter(prefix="/api/extension-example", tags=["extension-example"])

    @router.get("/stats")
    async def read_stats(
        deps: ExtensionRuntimeDeps = Depends(service.require_deps),
    ) -> dict[str, Any]:
        assert deps.app_store is not None
        return {
            "scope_id": deps.app_store.scope_id,
            "session_factory_available": deps.session_factory is not None,
            "host_policy": {
                "max_subagents_per_run": deps.policy.max_subagents_per_run,
            },
            **_stats(deps.app_store).snapshot(),
        }

    return router
