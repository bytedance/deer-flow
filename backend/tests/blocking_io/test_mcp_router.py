"""Regression anchor: updating MCP config must not block the event loop.

The PUT and PATCH handlers resolve the extensions config path, probe its
existence, read raw JSON, atomically write it, and reload it — all blocking
filesystem IO. They offload the whole read-modify-write via
``asyncio.to_thread``; if either regresses back onto the event loop, the strict
Blockbuster gate raises ``BlockingError`` and this test fails.

The admin check is patched to a no-op so the anchor exercises the handler's own
filesystem IO, not the authz layer. Imports sit at module top so any import-time
IO runs at collection, outside the gate.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.routers import mcp as mcp_router
from app.gateway.routers.mcp import (
    McpConfigUpdateRequest,
    McpServerConfigResponse,
    McpServerStateUpdateRequest,
    update_mcp_configuration,
    update_mcp_server_state,
)

pytestmark = pytest.mark.asyncio


async def test_update_mcp_configuration_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "extensions_config.json"
    # resolve_config_path() requires the env-pointed file to exist; seed a minimal one.
    await asyncio.to_thread(config_path.write_text, '{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)

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


async def test_update_mcp_server_state_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "extensions_config.json"
    await asyncio.to_thread(
        config_path.write_text,
        '{"mcpServers":{"remote":{"enabled":false,"transport":"http","url":"https://example.test/mcp"}},"skills":{}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)
    monkeypatch.setattr(mcp_router, "reset_mcp_tools_cache", lambda: None)

    response = await update_mcp_server_state(
        request=None,
        body=McpServerStateUpdateRequest(server_name="remote", enabled=True),
    )

    assert response.mcp_servers["remote"].enabled is True
    assert response.mcp_servers["remote"].type == "http"


async def test_concurrent_mcp_put_and_patch_updates_are_serialized(tmp_path: Path, monkeypatch) -> None:
    """The write lock keeps the offloaded read-modify-write atomic within the process.

    Offloading the RMW to a worker thread dropped the implicit serialization the
    single-threaded event loop provided. ``extensions_config_write_lock`` restores
    it — and, being shared with the skills router (the other writer of this file),
    also serializes against skill toggles: even with several concurrent
    mix of ``PUT /api/mcp/config`` and ``PATCH /api/mcp/config`` calls, only one
    RMW is inside the critical section at a time. (Without the lock the tracked
    max concurrency would exceed 1.)

    The tracker is injected *inside* the real worker (via ``reload_extensions_config``,
    the last step under the lock) rather than replacing ``_apply_mcp_config_update``,
    because the lock now lives in the worker — stubbing the worker out would bypass
    the very thing under test.
    """
    config_path = tmp_path / "extensions_config.json"
    await asyncio.to_thread(
        config_path.write_text,
        '{"mcpServers":{"s":{"enabled":true,"type":"http","url":"https://example.test/mcp"}},"skills":{}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)
    monkeypatch.setattr(mcp_router, "_validate_mcp_update_request", lambda _body: None)

    state_lock = threading.Lock()
    counters = {"active": 0, "max": 0}

    def _tracking_reload(*_args, **_kwargs):
        # Runs inside the real worker, under extensions_config_write_lock.
        with state_lock:
            counters["active"] += 1
            counters["max"] = max(counters["max"], counters["active"])
        time.sleep(0.02)  # worker thread (off-loop): hold long enough to expose overlap
        with state_lock:
            counters["active"] -= 1
        return SimpleNamespace(mcp_servers={})

    monkeypatch.setattr(mcp_router, "reload_extensions_config", _tracking_reload)

    body = McpConfigUpdateRequest(
        mcp_servers={"s": McpServerConfigResponse(type="http", url="https://example.test/mcp")},
    )

    await asyncio.gather(
        *[update_mcp_configuration(request=None, body=body) for _ in range(4)],
        update_mcp_server_state(
            request=None,
            body=McpServerStateUpdateRequest(server_name="s", enabled=False),
        ),
    )

    assert counters["max"] == 1, f"config updates were not serialized (max concurrency {counters['max']})"
