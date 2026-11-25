"""API tests for per-agent model settings (issue #4336).

Exercises the ``/api/agents`` create/update handlers directly: the new
``model_settings`` / ``thinking_enabled`` / ``reasoning_effort`` fields
persist and round-trip, an omitted field is preserved on update, and an
unknown ``model`` is rejected before it reaches the runtime.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.gateway.routers import agents as agents_router
from app.gateway.routers.agents import (
    AgentCreateRequest,
    AgentUpdateRequest,
    create_agent_endpoint,
    get_agent,
    update_agent,
)
from deerflow.config.agent_storage_config import AgentStorageConfig
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config, set_app_config
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import get_sync_sessionmaker
from deerflow.tools.builtins.setup_agent_tool import setup_agent
from deerflow.tools.builtins.update_agent_tool import update_agent as update_agent_tool

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _agent_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    set_app_config(
        AppConfig(
            models=[ModelConfig(name="agent-model", display_name="Agent Model", description=None, use="langchain_openai:ChatOpenAI", model="agent-model")],
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        )
    )
    try:
        yield
    finally:
        load_agents_api_config_from_dict({})
        reset_app_config()


async def test_create_persists_model_settings(_agent_env) -> None:
    resp = await create_agent_endpoint(
        AgentCreateRequest(
            name="researcher",
            model="agent-model",
            model_settings={"temperature": 0.2, "max_tokens": 12000},
            thinking_enabled=True,
            reasoning_effort="high",
            soul="You are a researcher.",
        )
    )
    assert resp.model == "agent-model"
    assert resp.model_settings is not None
    assert resp.model_settings.temperature == 0.2
    assert resp.model_settings.max_tokens == 12000
    assert resp.thinking_enabled is True
    assert resp.reasoning_effort == "high"

    # Reload through the read path to confirm it round-tripped to disk.
    fetched = await get_agent("researcher")
    assert fetched.model_settings is not None
    assert fetched.model_settings.temperature == 0.2
    assert fetched.reasoning_effort == "high"


async def test_create_and_update_subagent_policy_round_trip_and_merge(_agent_env) -> None:
    created = await create_agent_endpoint(
        AgentCreateRequest(
            name="bounded",
            model="agent-model",
            subagent_policy={"max_concurrent": 4, "max_total": 10},
        )
    )
    assert created.subagent_policy is not None
    assert created.subagent_policy.max_concurrent == 4
    assert created.subagent_policy.max_total == 10

    partial = await update_agent("bounded", AgentUpdateRequest(subagent_policy={"max_concurrent": 2}))
    assert partial.subagent_policy.max_concurrent == 2
    assert partial.subagent_policy.max_total == 10

    cleared_limit = await update_agent("bounded", AgentUpdateRequest(subagent_policy={"max_total": None}))
    assert cleared_limit.subagent_policy.max_concurrent == 2
    assert cleared_limit.subagent_policy.max_total is None

    cleared_policy = await update_agent("bounded", AgentUpdateRequest(subagent_policy=None))
    assert cleared_policy.subagent_policy is None


async def test_update_description_preserves_subagent_policy(_agent_env) -> None:
    await create_agent_endpoint(
        AgentCreateRequest(
            name="bounded",
            model="agent-model",
            subagent_policy={"max_concurrent": 3, "max_total": 9},
        )
    )

    updated = await update_agent("bounded", AgentUpdateRequest(description="updated"))

    assert updated.description == "updated"
    assert updated.subagent_policy is not None
    assert updated.subagent_policy.max_concurrent == 3
    assert updated.subagent_policy.max_total == 9


@pytest.fixture(params=["file", "sqlite"])
def _agent_store(_agent_env, tmp_path, request):
    if request.param == "file":
        yield agents_router.get_agent_store()
        return

    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    engine = get_sync_sessionmaker(database.app_sync_sqlalchemy_url).kw["bind"]
    AgentRow.__table__.create(engine)
    set_app_config(get_app_config().model_copy(update={"agent_storage": AgentStorageConfig(backend="db"), "database": database}))
    try:
        yield agents_router.get_agent_store()
    finally:
        engine.dispose()


@pytest.fixture
def pause_next_agent_update(monkeypatch):
    before_write = asyncio.Event()
    resume_write = asyncio.Event()
    original = agents_router.run_drained_write

    async def pause_first_write(action, *args, **kwargs):
        if action == "Update agent" and not before_write.is_set():
            before_write.set()
            await resume_write.wait()
        return await original(action, *args, **kwargs)

    monkeypatch.setattr(agents_router, "run_drained_write", pause_first_write)
    return before_write, resume_write


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ({"subagent_policy": {"max_concurrent": 2}}, {"subagent_policy": {"max_total": 3}}, {"max_concurrent": 2, "max_total": 3}),
        ({"subagent_policy": {"max_concurrent": 2}}, {"subagent_policy": {"max_total": None}}, {"max_concurrent": 2, "max_total": None}),
        ({"description": "Renamed"}, {"subagent_policy": None}, None),
    ],
    ids=["independent-caps", "clear-one", "clear-both"],
)
async def test_overlapping_saves_keep_the_latest_omitted_cap(_agent_store, pause_next_agent_update, first, second, expected):
    await create_agent_endpoint(AgentCreateRequest(name="bounded", subagent_policy={"max_concurrent": 4, "max_total": 10}))
    before_write, resume_write = pause_next_agent_update
    pending = asyncio.create_task(update_agent("bounded", AgentUpdateRequest(**first)))
    try:
        await asyncio.wait_for(before_write.wait(), timeout=10)
        await update_agent("bounded", AgentUpdateRequest(**second))
    finally:
        resume_write.set()
        await pending

    result = await get_agent("bounded")
    assert result.model_dump()["subagent_policy"] == expected
    assert result.description == first.get("description", "")


async def test_paused_agent_save_does_not_recreate_a_deleted_agent(_agent_store, pause_next_agent_update):
    await create_agent_endpoint(AgentCreateRequest(name="bounded", subagent_policy={"max_total": 10}, soul="Original"))
    before_write, resume_write = pause_next_agent_update
    pending = asyncio.create_task(update_agent("bounded", AgentUpdateRequest(subagent_policy={"max_concurrent": 2}, soul="Edited")))
    try:
        await asyncio.wait_for(before_write.wait(), timeout=10)
        assert await asyncio.to_thread(_agent_store.delete, "bounded") == "deleted"
    finally:
        resume_write.set()
        (outcome,) = await asyncio.gather(pending, return_exceptions=True)

    assert isinstance(outcome, HTTPException)
    assert outcome.status_code == 404
    assert not await asyncio.to_thread(_agent_store.exists, "bounded")


@pytest.mark.parametrize("tool", [setup_agent, update_agent_tool], ids=["setup", "update"])
async def test_agent_tool_does_not_restore_a_cap_changed_by_the_api(_agent_store, monkeypatch, tool):
    await create_agent_endpoint(AgentCreateRequest(name="bounded", subagent_policy={"max_concurrent": 4, "max_total": 10}, soul="Original"))
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = Event()
    store_type = type(_agent_store)
    original = store_type.update
    worker_id = None

    def pause_tool_write(self, *args, **kwargs):
        if get_ident() == worker_id:
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=15)
        return original(self, *args, **kwargs)

    def call_tool():
        nonlocal worker_id
        worker_id = get_ident()
        runtime = SimpleNamespace(context={"agent_name": "bounded"}, tool_call_id="overlapping-save")
        return tool.func(runtime=runtime, soul="Edited", description="Updated by tool")

    monkeypatch.setattr(store_type, "update", pause_tool_write)
    pending = asyncio.create_task(asyncio.to_thread(call_tool))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        await update_agent("bounded", AgentUpdateRequest(subagent_policy={"max_total": None}))
    finally:
        release.set()
        await pending

    result = await get_agent("bounded")
    assert result.model_dump()["subagent_policy"] == {"max_concurrent": 4, "max_total": None}
    assert result.description == "Updated by tool"
    assert result.soul == "Edited"


async def test_create_rejects_unknown_model(_agent_env) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await create_agent_endpoint(AgentCreateRequest(name="bad", model="ghost-model"))
    assert excinfo.value.status_code == 422


async def test_update_preserves_unset_model_settings(_agent_env) -> None:
    await create_agent_endpoint(
        AgentCreateRequest(
            name="researcher",
            model="agent-model",
            model_settings={"temperature": 0.2, "max_tokens": 12000},
            thinking_enabled=True,
        )
    )

    # Update only the description — model_settings / thinking must be preserved.
    resp = await update_agent("researcher", AgentUpdateRequest(description="updated"))
    assert resp.description == "updated"
    assert resp.model_settings is not None
    assert resp.model_settings.temperature == 0.2
    assert resp.thinking_enabled is True


async def test_update_changes_model_settings(_agent_env) -> None:
    await create_agent_endpoint(AgentCreateRequest(name="researcher", model="agent-model", model_settings={"temperature": 0.2}))

    resp = await update_agent(
        "researcher",
        AgentUpdateRequest(model_settings={"temperature": 0.9, "max_tokens": 2048}),
    )
    assert resp.model_settings is not None
    assert resp.model_settings.temperature == 0.9
    assert resp.model_settings.max_tokens == 2048


async def test_update_model_settings_merges_omitted_subfields(_agent_env) -> None:
    await create_agent_endpoint(
        AgentCreateRequest(
            name="researcher",
            model="agent-model",
            model_settings={"temperature": 0.2, "max_tokens": 12000},
        )
    )

    resp = await update_agent("researcher", AgentUpdateRequest(model_settings={"temperature": 0.9}))

    assert resp.model_settings is not None
    assert resp.model_settings.temperature == 0.9
    assert resp.model_settings.max_tokens == 12000


async def test_update_model_settings_null_subfield_clears_only_that_subfield(_agent_env) -> None:
    await create_agent_endpoint(
        AgentCreateRequest(
            name="researcher",
            model="agent-model",
            model_settings={"temperature": 0.2, "max_tokens": 12000},
        )
    )

    resp = await update_agent("researcher", AgentUpdateRequest(model_settings={"max_tokens": None}))

    assert resp.model_settings is not None
    assert resp.model_settings.temperature == 0.2
    assert resp.model_settings.max_tokens is None


async def test_update_rejects_unknown_model(_agent_env) -> None:
    await create_agent_endpoint(AgentCreateRequest(name="researcher", model="agent-model"))
    with pytest.raises(HTTPException) as excinfo:
        await update_agent("researcher", AgentUpdateRequest(model="ghost-model"))
    assert excinfo.value.status_code == 422


async def test_allowed_subagents_round_trip_and_explicit_null_clears(_agent_env) -> None:
    created = await create_agent_endpoint(AgentCreateRequest(name="delegator", allowed_subagents=["planner"]))
    assert created.allowed_subagents == ["planner"]

    denied = await update_agent("delegator", AgentUpdateRequest(allowed_subagents=[]))
    assert denied.allowed_subagents == []

    unrestricted = await update_agent("delegator", AgentUpdateRequest(allowed_subagents=None))
    assert unrestricted.allowed_subagents is None


async def test_plugin_selection_persists_empty_omitted_and_null(_agent_env):
    created = await create_agent_endpoint(AgentCreateRequest(name="selected", mcp_plugins=["stable-installation"], skills=["research"]))
    assert created.mcp_plugins == ["stable-installation"]
    fetched = await get_agent("selected")
    assert fetched.mcp_plugins == ["stable-installation"]
    assert (await update_agent("selected", AgentUpdateRequest(description="changed"))).mcp_plugins == ["stable-installation"]
    assert (await update_agent("selected", AgentUpdateRequest(mcp_plugins=[]))).mcp_plugins == []
    assert (await get_agent("selected")).mcp_plugins == []
    cleared = await update_agent("selected", AgentUpdateRequest(mcp_plugins=None))
    assert cleared.mcp_plugins is None
    assert cleared.skills == ["research"]
