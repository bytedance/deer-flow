"""Regression test for ACP workspace setup on the event loop."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any

import acp
import pytest

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.tools.builtins import invoke_acp_agent_tool as acp_tool

pytestmark = pytest.mark.asyncio


async def test_invoke_acp_agent_creates_workspace_off_event_loop(monkeypatch, tmp_path) -> None:
    from deerflow.config import paths as paths_module

    configured_paths = SimpleNamespace(
        base_dir=tmp_path,
        acp_workspace_dir=lambda thread_id, user_id=None: tmp_path / "threads" / thread_id / "acp-workspace",
    )
    monkeypatch.setattr(paths_module, "get_paths", lambda: configured_paths)
    monkeypatch.setattr(acp_tool, "_build_acp_mcp_servers", lambda: [])

    captured: dict[str, Any] = {}

    class _Connection:
        async def initialize(self, **kwargs: Any) -> None:
            captured["initialize"] = kwargs

        async def new_session(self, **kwargs: Any) -> SimpleNamespace:
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="session-1")

        async def prompt(self, **kwargs: Any) -> None:
            captured["prompt"] = kwargs

    @contextlib.asynccontextmanager
    async def fake_spawn_agent_process(client, command, *args, env=None, cwd=None):
        captured["cwd"] = cwd
        yield _Connection(), SimpleNamespace()

    monkeypatch.setattr(acp, "spawn_agent_process", fake_spawn_agent_process)

    tool = acp_tool.build_invoke_acp_agent_tool(
        {"test-agent": ACPAgentConfig(command="test-agent", description="Test agent")},
    )
    result = await tool.coroutine(
        agent="test-agent",
        prompt="run",
        config={"configurable": {"thread_id": "thread-1"}},
    )

    expected_cwd = tmp_path / "threads" / "thread-1" / "acp-workspace"
    assert result == "(no response)"
    assert captured["cwd"] == str(expected_cwd)
    assert expected_cwd.is_dir()
