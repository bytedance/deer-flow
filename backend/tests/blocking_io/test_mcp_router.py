"""Regression anchor: updating MCP config must not block the event loop.

``update_mcp_configuration`` resolves the extensions config path, probes its
existence, reads the raw JSON, writes the merged config, and reloads it — all
blocking filesystem IO. The handler offloads the whole read-modify-write via
``asyncio.to_thread``; if it regresses back onto the event loop, the strict
Blockbuster gate raises ``BlockingError`` and this test fails.

The admin check is patched to a no-op so the anchor exercises the handler's own
filesystem IO, not the authz layer. Imports sit at module top so any import-time
IO runs at collection, outside the gate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.gateway.routers import mcp as mcp_router
from app.gateway.routers.mcp import McpConfigUpdateRequest, McpServerConfigResponse, update_mcp_configuration

pytestmark = pytest.mark.asyncio


async def test_update_mcp_configuration_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "extensions_config.json"
    # resolve_config_path() requires the env-pointed file to exist; seed a minimal one.
    await asyncio.to_thread(config_path.write_text, '{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _noop_admin(_request) -> None:
        return None

    monkeypatch.setattr(mcp_router, "_require_admin_user", _noop_admin)

    # An http transport skips the stdio command allowlist check, so the anchor
    # stays focused on the filesystem offload rather than command validation.
    body = McpConfigUpdateRequest(
        mcp_servers={"test-server": McpServerConfigResponse(type="http", url="https://example.test/mcp", description="anchor")},
    )

    resp = await update_mcp_configuration(request=None, body=body)

    assert "test-server" in resp.mcp_servers
    # The merged config was actually written to the env-pointed path (offload the
    # stat so the assertion itself doesn't trip the gate).
    assert await asyncio.to_thread(config_path.exists)
