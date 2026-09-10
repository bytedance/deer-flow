from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from deerflow_extension_api import (
    EXTENSION_TASK_STORE_KEY,
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    ExtensionRegistry,
    ExtensionRuntimeDeps,
    HostPolicySnapshot,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskOutcome,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from deerflow_extension_example import install


class FakeRegistry:
    def __init__(self) -> None:
        self.middleware_contributors: list[Any] = []
        self.task_lifecycle_contributors: list[Any] = []
        self.system_model_observers: list[Any] = []
        self.agent_assembly_observers: list[Any] = []
        self.context_compaction_observers: list[Any] = []
        self.services: list[Any] = []
        self.contributed_routers: list[Any] = []

    def middlewares(self, contributor: Any) -> None:
        self.middleware_contributors.append(contributor)

    def task_lifecycle(self, contributor: Any) -> None:
        self.task_lifecycle_contributors.append(contributor)

    def system_model_observer(self, observer: Any) -> None:
        self.system_model_observers.append(observer)

    def agent_assembly_observer(self, observer: Any) -> None:
        self.agent_assembly_observers.append(observer)

    def context_compaction_observer(self, observer: Any) -> None:
        self.context_compaction_observers.append(observer)

    def service(self, service: Any) -> None:
        self.services.append(service)

    def routers(self, routers: Any) -> None:
        self.contributed_routers.extend(routers)


@dataclass
class FakeRuntime:
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeToolRequest:
    runtime: FakeRuntime


def test_install_registers_all_five_contribution_kinds() -> None:
    registry = FakeRegistry()

    install(registry, {})

    assert isinstance(registry, ExtensionRegistry)
    assert len(registry.middleware_contributors) == 1
    assert len(registry.task_lifecycle_contributors) == 1
    assert len(registry.system_model_observers) == 1
    assert len(registry.services) == 1
    assert len(registry.contributed_routers) == 1
    assert [route.path for route in registry.contributed_routers[0].routes] == ["/api/extension-example/stats"]
    assert install.__deerflow_api__ == "0.2.0"
    assert install.__deerflow_name__ == "example"


def test_disabled_extension_registers_nothing() -> None:
    registry = FakeRegistry()

    install(registry, {"enabled": False})

    assert registry.middleware_contributors == []
    assert registry.task_lifecycle_contributors == []
    assert registry.system_model_observers == []
    assert registry.services == []
    assert registry.contributed_routers == []


def test_registered_contributions_publish_one_shared_stats_snapshot() -> None:
    registry = FakeRegistry()
    install(registry, {})
    app_store = ExtensionData("app")
    task_store = ExtensionData("task-1")
    task = TaskInfo(
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        kind="lead",
    )

    async def exercise_contributions() -> tuple[int, int, dict[str, Any], int]:
        lifecycle = registry.task_lifecycle_contributors[0]
        await lifecycle.on_task_start(app_store, task_store, task)
        placement = registry.middleware_contributors[0].contribute_middlewares(
            app_store,
            AgentBuildContext(scope=AgentScope.LEAD),
        )[0]

        async def tool_handler(_request: object) -> str:
            return "tool-result"

        request = FakeToolRequest(runtime=FakeRuntime(context={EXTENSION_TASK_STORE_KEY: task_store}))
        assert await placement.middleware.awrap_tool_call(request, tool_handler) == "tool-result"

        await registry.system_model_observers[0].on_system_model_call(
            app_store,
            task_store,
            SystemOperationKind.TITLE,
            SystemModelRequest(messages="title prompt"),
            SystemModelResult(error=RuntimeError("provider unavailable")),
        )
        await lifecycle.on_task_stop(
            app_store,
            task_store,
            task,
            TaskOutcome.COMPLETED,
        )

        app = FastAPI()
        app.include_router(registry.contributed_routers[0])
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            before_start = await client.get("/api/extension-example/stats")
            await registry.services[0].start(
                ExtensionRuntimeDeps(
                    app_store=app_store,
                    policy=HostPolicySnapshot(max_subagents_per_run=6),
                    session_factory=object(),
                )
            )
            response = await client.get("/api/extension-example/stats")
            await registry.services[0].stop()
            after_stop = await client.get("/api/extension-example/stats")
        return (
            before_start.status_code,
            response.status_code,
            response.json(),
            after_stop.status_code,
        )

    before_start, status_code, body, after_stop = asyncio.run(exercise_contributions())

    assert before_start == 503
    assert status_code == 200
    assert after_stop == 503
    assert body == {
        "scope_id": "app",
        "session_factory_available": True,
        "host_policy": {"max_subagents_per_run": 6},
        "tasks": {"completed": 1},
        "tool_calls": 1,
        "system_model_calls": {"title": {"calls": 1, "errors": 1}},
    }
