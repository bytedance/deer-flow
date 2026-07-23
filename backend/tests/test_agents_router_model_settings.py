"""API tests for per-agent model settings (issue #4336).

Exercises the ``/api/agents`` create/update handlers directly: the new
``model_settings`` / ``thinking_enabled`` / ``reasoning_effort`` fields
persist and round-trip, an omitted field is preserved on update, and an
unknown ``model`` is rejected before it reaches the runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.gateway.routers.agents import (
    AgentCreateRequest,
    AgentUpdateRequest,
    create_agent_endpoint,
    get_agent,
    update_agent,
)
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

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
