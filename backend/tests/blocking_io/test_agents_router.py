"""Regression anchors: the custom-agent router must not block the event loop.

The custom-agent handlers resolve the active store, access agent directories,
and may perform filesystem or database IO. Create/read/check/update/delete all
offload their complete blocking operations via ``asyncio.to_thread``; if any of
that work regresses onto the event loop, the strict Blockbuster gate raises
``BlockingError`` and these tests fail.

Imports live at module scope so the one-time FastAPI app construction (which
reads files while building OpenAPI schemas) happens at collection time, not on
the event loop under test. Test-side path resolution is itself offloaded with
``asyncio.to_thread`` (matching ``test_uploads_middleware``) so only the
handlers' own filesystem access is exercised on the loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.gateway.routers.agents import (
    AgentCreateRequest,
    AgentUpdateRequest,
    check_agent_name,
    create_agent_endpoint,
    delete_agent,
    get_agent,
    list_agents,
    update_agent,
)
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolate_agent_store_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("deerflow.config.app_config._legacy_config_candidates", lambda: ())


async def test_create_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        response = await create_agent_endpoint(AgentCreateRequest(name="loop-make-agent", soul="You are a test agent."))
        assert response is not None

        user_id = get_effective_user_id()
        # test-side check (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-make-agent")
        assert await asyncio.to_thread((agent_dir / "config.yaml").exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_delete_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        user_id = get_effective_user_id()
        # test-side seeding (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-test-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((agent_dir / "config.yaml").write_text, "name: loop-test-agent\n", encoding="utf-8")

        await delete_agent("loop-test-agent")

        assert not await asyncio.to_thread(agent_dir.exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_read_endpoints_do_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    # list/get/check read through the sync agent store; on the db backend each is
    # a DB round trip. They must offload via asyncio.to_thread, or the strict
    # Blockbuster gate raises BlockingError here (finding: reads on the loop).
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        await create_agent_endpoint(AgentCreateRequest(name="loop-read-agent", soul="You are a test agent."))

        listed = await list_agents()
        assert any(a.name == "loop-read-agent" for a in listed.agents)

        got = await get_agent("loop-read-agent")
        assert got.name == "loop-read-agent"

        check = await check_agent_name("loop-read-agent")
        assert check["available"] is False
        assert (await check_agent_name("never-created-agent"))["available"] is True
    finally:
        load_agents_api_config_from_dict({})


async def test_update_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        await create_agent_endpoint(AgentCreateRequest(name="loop-update-agent", soul="Original soul"))

        response = await update_agent("loop-update-agent", AgentUpdateRequest(description="Updated description"))

        assert response.description == "Updated description"
    finally:
        load_agents_api_config_from_dict({})
