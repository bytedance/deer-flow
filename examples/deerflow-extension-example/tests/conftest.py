"""A fake host, built from the contract alone.

This is the part worth copying. ``ExtensionRegistry`` is a runtime-checkable
Protocol and every contract type is importable without the harness, so a
third-party extension can prove it registers correctly, that its probes count
correctly, and that its route reports 503 before startup -- with no DeerFlow
host installed anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deerflow_extension_api import (
    EXTENSION_TASK_STORE_KEY,
    ExtensionData,
    ExtensionService,
    MiddlewareContributor,
    SystemModelCallObserver,
    TaskLifecycleContributor,
)


class FakeRegistry:
    """Records what an extension registers. Mirrors the contract's five methods."""

    # Collections are named apart from the contract's method names on purpose:
    # ``task_lifecycle`` and ``routers`` are both methods, so an attribute of the
    # same name would shadow them on the instance and break registration.
    def __init__(self) -> None:
        self.registered_services: list[ExtensionService] = []
        self.registered_middlewares: list[MiddlewareContributor] = []
        self.registered_lifecycle: list[TaskLifecycleContributor] = []
        self.registered_observers: list[SystemModelCallObserver] = []
        self.registered_routers: list[Any] = []

    def service(self, service: ExtensionService) -> None:
        self.registered_services.append(service)

    def middlewares(self, contributor: MiddlewareContributor) -> None:
        self.registered_middlewares.append(contributor)

    def task_lifecycle(self, contributor: TaskLifecycleContributor) -> None:
        self.registered_lifecycle.append(contributor)

    def system_model_observer(self, observer: SystemModelCallObserver) -> None:
        self.registered_observers.append(observer)

    def routers(self, routers: Any) -> None:
        self.registered_routers.extend(routers)


@dataclass
class FakeRuntime:
    """Stands in for LangGraph's Runtime: middlewares only read ``context``."""

    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeModelRequest:
    runtime: FakeRuntime | None = None


@dataclass
class FakeToolRequest:
    tool_call: dict[str, Any] = field(default_factory=dict)
    runtime: FakeRuntime | None = None


def task_scope() -> tuple[ExtensionData, FakeRuntime]:
    """A task-scoped store, installed the way the host installs it."""
    task_store = ExtensionData("task-1")
    return task_store, FakeRuntime(context={EXTENSION_TASK_STORE_KEY: task_store})
