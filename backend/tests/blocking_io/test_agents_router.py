"""Regression anchors: the custom-agent router must not block the event loop.

The async route handlers in ``app.gateway.routers.agents`` resolve agent and
user-profile paths (``Paths.base_dir`` calls ``Path.resolve``), probe them
(``Path.exists``), and create/update/remove them (``mkdir``, config/SOUL/USER.md
writes, ``shutil.rmtree``) — all blocking IO. Every handler offloads that work
via ``asyncio.to_thread``; if any of it regresses back onto the event loop, the
strict Blockbuster gate raises ``BlockingError`` and these tests fail.

Coverage: ``create_agent_endpoint``, ``delete_agent``, ``check_agent_name``,
``update_agent``, ``get_user_profile``, and ``update_user_profile``.

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
    UserProfileUpdateRequest,
    check_agent_name,
    create_agent_endpoint,
    delete_agent,
    get_user_profile,
    update_agent,
    update_user_profile,
)
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio


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
        # test-side seeding (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-test-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((agent_dir / "config.yaml").write_text, "name: loop-test-agent\n", encoding="utf-8")

        await delete_agent("loop-test-agent")

        assert not await asyncio.to_thread(agent_dir.exists)
    finally:
        load_agents_api_config_from_dict({})


async def test_check_agent_name_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        # An unused name in an empty home must come back available without the
        # two ``Path.exists`` probes ever touching the event loop.
        result = await check_agent_name("loop-free-name")
        assert result["available"] is True
        assert result["name"] == "loop-free-name"
    finally:
        load_agents_api_config_from_dict({})


async def test_update_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        # test-side seeding (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-update-agent")
        await asyncio.to_thread(agent_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((agent_dir / "config.yaml").write_text, "name: loop-update-agent\n", encoding="utf-8")

        response = await update_agent("loop-update-agent", AgentUpdateRequest(description="updated", soul="New soul."))

        assert response.description == "updated"
        assert response.soul == "New soul."
    finally:
        load_agents_api_config_from_dict({})


async def test_get_user_profile_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        # test-side seeding (resolution offloaded; not exercised on the loop)
        def _seed() -> None:
            paths = get_paths()
            paths.base_dir.mkdir(parents=True, exist_ok=True)
            paths.user_md_file.write_text("I am a test user.", encoding="utf-8")

        await asyncio.to_thread(_seed)

        response = await get_user_profile()
        assert response.content == "I am a test user."
    finally:
        load_agents_api_config_from_dict({})


async def test_update_user_profile_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        response = await update_user_profile(UserProfileUpdateRequest(content="Profile body."))
        assert response.content == "Profile body."

        # confirm it landed on disk (resolution offloaded; not on the loop)
        def _read() -> str:
            return get_paths().user_md_file.read_text(encoding="utf-8")

        assert await asyncio.to_thread(_read) == "Profile body."
    finally:
        load_agents_api_config_from_dict({})
