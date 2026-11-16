"""MCP config 500s keep host paths out of the response detail.

An ``OSError`` raised while the router resolves, reads or writes
``extensions_config.json`` names the absolute host path in ``str(e)``. The
custom-agent and user-profile routes already return a fixed detail for exactly
this reason (#7255, and ``routers/AGENTS.md`` states the rule); the five MCP
mutation routes still concatenated the exception text into the 500 body, so a
caller learned where ``DEER_FLOW_HOME`` lives on the server.

Each test drives one handler to the write step and asserts the response carries
a fixed detail while the exception itself never reaches the caller. The full
error still goes to the server log.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.gateway.routers import mcp as mcp_router
from app.gateway.routers.mcp import (
    McpConfigUpdateRequest,
    McpServerConfigResponse,
    McpServerConfigUpdateRequest,
    McpServerStateUpdateRequest,
    create_mcp_servers,
    delete_mcp_server,
    update_mcp_configuration,
    update_mcp_server,
    update_mcp_server_state,
)

pytestmark = pytest.mark.asyncio

HOST_PATH = "/srv/private/deer-flow/extensions_config.json"


@pytest.fixture
def written_config(tmp_path: Path, monkeypatch) -> Path:
    """A minimal extensions config the handlers can load before the write fails."""
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(
        '{"mcpServers": {"remote": {"enabled": true, "type": "http", "url": "https://example.test/mcp"}}, "skills": {}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    async def _noop_admin(_request, **_kwargs) -> None:
        return None

    monkeypatch.setattr(mcp_router, "require_admin_user", _noop_admin)
    return config_path


@pytest.fixture
def failing_write(monkeypatch):
    """Fail the commit with an OSError whose message names an absolute host path."""

    def _raise(path, data, **_kwargs):
        raise PermissionError(13, "Permission denied", HOST_PATH)

    monkeypatch.setattr(mcp_router, "atomic_write_extensions_config", _raise)


def _assert_fixed_detail(exc: HTTPException, expected: str) -> None:
    assert exc.status_code == 500
    assert exc.detail == expected, f"detail must be fixed text, got {exc.detail!r}"
    assert HOST_PATH not in str(exc.detail)


async def test_update_mcp_configuration_hides_the_host_path(written_config, failing_write, caplog) -> None:
    body = McpConfigUpdateRequest(mcp_servers={"remote": McpServerConfigResponse(type="http", url="https://example.test/mcp")})

    with caplog.at_level(logging.ERROR, logger="app.gateway.routers.mcp"):
        with pytest.raises(HTTPException) as excinfo:
            await update_mcp_configuration(request=None, body=body)

    _assert_fixed_detail(excinfo.value, "Failed to update MCP configuration")
    assert HOST_PATH in caplog.text, "the full error must stay in the server log"


async def test_create_mcp_servers_hides_the_host_path(written_config, failing_write, caplog) -> None:
    body = McpConfigUpdateRequest(mcp_servers={"added": McpServerConfigResponse(type="http", url="https://example.test/mcp")})

    with caplog.at_level(logging.ERROR, logger="app.gateway.routers.mcp"):
        with pytest.raises(HTTPException) as excinfo:
            await create_mcp_servers(request=None, body=body)

    _assert_fixed_detail(excinfo.value, "Failed to add MCP servers")
    assert HOST_PATH in caplog.text


async def test_update_mcp_server_hides_the_host_path(written_config, failing_write, caplog) -> None:
    body = McpServerConfigUpdateRequest(server_name="remote", server=McpServerConfigResponse(type="http", url="https://example.test/mcp"))

    with caplog.at_level(logging.ERROR, logger="app.gateway.routers.mcp"):
        with pytest.raises(HTTPException) as excinfo:
            await update_mcp_server(request=None, body=body)

    _assert_fixed_detail(excinfo.value, "Failed to update MCP server")
    assert HOST_PATH in caplog.text


async def test_delete_mcp_server_hides_the_host_path(written_config, failing_write, caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="app.gateway.routers.mcp"):
        with pytest.raises(HTTPException) as excinfo:
            await delete_mcp_server(request=None, server_name="remote")

    _assert_fixed_detail(excinfo.value, "Failed to delete MCP server")
    assert HOST_PATH in caplog.text


async def test_update_mcp_server_state_hides_the_host_path(written_config, failing_write, caplog) -> None:
    body = McpServerStateUpdateRequest(server_name="remote", enabled=False)

    with caplog.at_level(logging.ERROR, logger="app.gateway.routers.mcp"):
        with pytest.raises(HTTPException) as excinfo:
            await update_mcp_server_state(request=None, body=body)

    _assert_fixed_detail(excinfo.value, "Failed to update MCP server state")
    assert HOST_PATH in caplog.text
