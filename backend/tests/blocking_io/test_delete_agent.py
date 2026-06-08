"""Regression anchor: deleting a custom agent must not block the event loop.

``app.gateway.routers.agents.delete_agent`` resolves the agent directory
(``Paths.base_dir`` calls ``Path.resolve``), probes it (``Path.exists``), and
removes it (``shutil.rmtree``) — all blocking IO. The async route handler
offloads them via ``asyncio.to_thread``; if any regresses back onto the event
loop, the strict Blockbuster gate raises ``BlockingError`` and this test fails.

Imports live at module scope so the one-time FastAPI app construction (which
reads files while building OpenAPI schemas) happens at collection time, not on
the event loop under test. Test-side path resolution is itself offloaded with
``asyncio.to_thread`` (matching ``test_uploads_middleware``) so only
``delete_agent``'s own filesystem access is exercised on the loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.gateway.routers.agents import delete_agent
from deerflow.config.agents_api_config import load_agents_api_config_from_dict
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio


async def test_delete_agent_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    load_agents_api_config_from_dict({"enabled": True})
    try:
        user_id = get_effective_user_id()
        # test-side seeding (resolution offloaded; not exercised on the loop)
        agent_dir = await asyncio.to_thread(get_paths().user_agent_dir, user_id, "loop-test-agent")
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "config.yaml").write_text("name: loop-test-agent\n", encoding="utf-8")

        await delete_agent("loop-test-agent")

        assert not agent_dir.exists()
    finally:
        load_agents_api_config_from_dict({})
