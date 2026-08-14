"""Regression anchors: the custom-agent router must not block the event loop.

``app.gateway.routers.agents.create_agent_endpoint`` and ``delete_agent`` are
async route handlers that resolve the agent directory (``Paths.base_dir`` calls
``Path.resolve``), probe it (``Path.exists``), and create/remove it (``mkdir``,
config/SOUL writes, ``shutil.rmtree``) — all blocking IO. Both offload that work
via ``asyncio.to_thread``; if any of it regresses back onto the event loop, the
strict Blockbuster gate raises ``BlockingError`` and these tests fail.

``get_user_profile`` and ``update_user_profile`` are the same shape on the global
``USER.md`` file (``exists``/``read_text``/``mkdir``/``write_text``); they offload
via ``asyncio.to_thread`` too, and the two tests at the end anchor that.

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
    UserProfileUpdateRequest,
    check_agent_name,
    create_agent_endpoint,
    delete_agent,
    get_agent,
    get_user_profile,
    list_agents,
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


async def test_get_user_profile_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    # get_user_profile reads USER.md with exists()/read_text(); both must stay
    # off the event loop via asyncio.to_thread, or the strict Blockbuster gate
    # raises BlockingError. Covers both the "file absent" and "file present"
    # branches.
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        # USER.md does not exist yet — exists() is the blocking call on this branch.
        absent = await get_user_profile()
        assert absent.content is None

        # Seed USER.md off the loop, then read it back — read_text() is the
        # blocking call on this branch.
        user_md = await asyncio.to_thread(lambda: get_paths().user_md_file)
        await asyncio.to_thread(user_md.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(user_md.write_text, "# About me\nI like tests.", encoding="utf-8")

        present = await get_user_profile()
        assert present.content == "# About me\nI like tests."
    finally:
        load_agents_api_config_from_dict({})


async def test_update_user_profile_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    # update_user_profile mkdir()s the base dir and write_text()s USER.md; both
    # must stay off the event loop via asyncio.to_thread, or the strict
    # Blockbuster gate raises BlockingError.
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        response = await update_user_profile(UserProfileUpdateRequest(content="I prefer concise answers."))
        assert response.content == "I prefer concise answers."

        # test-side check (read offloaded; not exercised on the loop)
        user_md = await asyncio.to_thread(lambda: get_paths().user_md_file)
        written = await asyncio.to_thread(user_md.read_text, encoding="utf-8")
        assert written == "I prefer concise answers."
    finally:
        load_agents_api_config_from_dict({})
