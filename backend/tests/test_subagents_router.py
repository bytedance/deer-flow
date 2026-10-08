"""Gateway catalog visibility and administrator write boundaries."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.gateway.routers import subagents as router
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.subagents_config import CustomSubagentConfig, SubagentsAppConfig
from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore

pytestmark = pytest.mark.asyncio


def _request(role: str):
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role=role)))


@pytest.fixture(autouse=True)
def _environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    set_app_config(AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")))
    store = FileManagedSubagentStore()
    monkeypatch.setattr(router, "get_managed_subagent_store", lambda *_: store)
    yield
    reset_app_config()


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_managed_subagent_writes_route_through_mutation_drain(monkeypatch, operation):
    definition = router.ManagedSubagentDefinition(
        name="planner",
        description="Plans work",
        system_prompt="Plan the work.",
    )

    class Store:
        def create(self, value):
            return value

        def get(self, name):
            assert name == "planner"
            return definition

        def update(self, value):
            return value

        def delete(self, name):
            assert name == "planner"
            return True

    store = Store()
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def drained(action, func, expected_errors=(), /, *args, **kwargs):
        calls.append((func, args))
        return func(*args, **kwargs)

    monkeypatch.setattr(router, "get_managed_subagent_store", lambda *_: store)
    monkeypatch.setattr(router, "run_drained_write", drained)

    if operation == "create":
        await router.create_managed_subagent(
            _request("admin"),
            router.ManagedSubagentCreateRequest(
                name="planner",
                description="Plans work",
                system_prompt="Plan the work.",
            ),
        )
        expected = store.create
    elif operation == "update":
        await router.update_managed_subagent(
            "planner",
            _request("admin"),
            router.ManagedSubagentUpdateRequest(enabled=False),
        )
        expected = store.update
    else:
        await router.delete_managed_subagent("planner", _request("admin"))
        expected = store.delete

    assert len(calls) == 1
    assert calls[0][0] == expected


async def test_create_managed_subagent_drains_started_write_across_repeated_cancellation(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    class Store:
        def create(self, _definition):
            started.set()
            assert release.wait(timeout=2)

    monkeypatch.setattr(router, "get_managed_subagent_store", lambda *_: Store())

    task = asyncio.create_task(
        router.create_managed_subagent(
            _request("admin"),
            router.ManagedSubagentCreateRequest(
                name="planner",
                description="Plans work",
                system_prompt="Plan the work.",
            ),
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_admin_can_create_update_and_delete_managed_subagent():
    created = await router.create_managed_subagent(
        _request("admin"),
        router.ManagedSubagentCreateRequest(
            name="planner",
            description="Plans creative work",
            system_prompt="You are a creative planner.",
        ),
    )
    assert created.source == "managed"
    assert created.system_prompt == "You are a creative planner."

    updated = await router.update_managed_subagent(
        "planner",
        _request("admin"),
        router.ManagedSubagentUpdateRequest(enabled=False),
    )
    assert updated.enabled is False

    await router.delete_managed_subagent("planner", _request("admin"))
    with pytest.raises(HTTPException) as excinfo:
        await router.delete_managed_subagent("planner", _request("admin"))
    assert excinfo.value.status_code == 404


async def test_ordinary_user_can_list_but_cannot_read_prompts_or_write():
    set_app_config(
        AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            subagents=SubagentsAppConfig(
                custom_agents={
                    "config-worker": CustomSubagentConfig(
                        description="Configured worker",
                        system_prompt="Secret config prompt.",
                    )
                }
            ),
        )
    )
    await router.create_managed_subagent(
        _request("admin"),
        router.ManagedSubagentCreateRequest(
            name="writer",
            description="Writes copy",
            system_prompt="Secret worker prompt.",
        ),
    )

    catalog = await router.list_subagents(_request("user"))
    assert {item.source for item in catalog.subagents} == {
        "builtin",
        "config",
        "managed",
    }
    assert all(item.system_prompt is None for item in catalog.subagents)

    with pytest.raises(HTTPException) as excinfo:
        await router.update_managed_subagent(
            "writer",
            _request("user"),
            router.ManagedSubagentUpdateRequest(enabled=False),
        )
    assert excinfo.value.status_code == 403

    with pytest.raises(HTTPException) as excinfo:
        await router.create_managed_subagent(
            _request("user"),
            router.ManagedSubagentCreateRequest(
                name="planner",
                description="Plans work",
                system_prompt="Plan the work.",
            ),
        )
    assert excinfo.value.status_code == 403

    with pytest.raises(HTTPException) as excinfo:
        await router.delete_managed_subagent("writer", _request("user"))
    assert excinfo.value.status_code == 403


async def test_read_redaction_and_write_authorization_share_admin_fallback(monkeypatch):
    await router.create_managed_subagent(
        _request("admin"),
        router.ManagedSubagentCreateRequest(
            name="writer",
            description="Writes copy",
            system_prompt="Admin-visible worker prompt.",
        ),
    )
    request_without_middleware_user = SimpleNamespace(state=SimpleNamespace())

    async def resolve_admin(_request):
        return SimpleNamespace(system_role="admin")

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", resolve_admin)

    catalog = await router.list_subagents(request_without_middleware_user)
    writer = next(item for item in catalog.subagents if item.name == "writer")
    assert writer.system_prompt == "Admin-visible worker prompt."

    updated = await router.update_managed_subagent(
        "writer",
        request_without_middleware_user,
        router.ManagedSubagentUpdateRequest(enabled=False),
    )
    assert updated.enabled is False


async def test_builtin_name_is_rejected_at_create():
    with pytest.raises(HTTPException) as excinfo:
        await router.create_managed_subagent(
            _request("admin"),
            router.ManagedSubagentCreateRequest(
                name="general-purpose",
                description="Duplicate",
                system_prompt="Duplicate.",
            ),
        )
    assert excinfo.value.status_code == 409


async def test_config_name_is_rejected_at_create():
    set_app_config(
        AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            subagents=SubagentsAppConfig(
                custom_agents={
                    "planner": CustomSubagentConfig(
                        description="Config planner",
                        system_prompt="Config owns this name.",
                    )
                }
            ),
        )
    )

    with pytest.raises(HTTPException) as excinfo:
        await router.create_managed_subagent(
            _request("admin"),
            router.ManagedSubagentCreateRequest(
                name="planner",
                description="Duplicate",
                system_prompt="Duplicate.",
            ),
        )
    assert excinfo.value.status_code == 409


async def test_catalog_marks_config_definition_shadowed_by_builtin_as_conflict():
    set_app_config(
        AppConfig(
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
            subagents=SubagentsAppConfig(
                custom_agents={
                    "general-purpose": CustomSubagentConfig(
                        description="Shadowed config worker",
                        system_prompt="This definition must not win.",
                    )
                }
            ),
        )
    )

    catalog = await router.list_subagents(_request("admin"))
    same_name = [item for item in catalog.subagents if item.name == "general-purpose"]

    assert [(item.source, item.conflict) for item in same_name] == [
        ("builtin", False),
        ("config", True),
    ]


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_invalid_path_name_returns_422(operation: str):
    with pytest.raises(HTTPException) as excinfo:
        if operation == "update":
            await router.update_managed_subagent(
                "../planner",
                _request("admin"),
                router.ManagedSubagentUpdateRequest(enabled=False),
            )
        else:
            await router.delete_managed_subagent("../planner", _request("admin"))
    assert excinfo.value.status_code == 422
