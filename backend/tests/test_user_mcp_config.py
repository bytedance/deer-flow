"""MCP configuration files belong to a single authenticated tenant."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.gateway.routers.user_mcp import McpConfigUpdateRequest, McpServerConfigResponse, _replace_user_servers, validate_user_mcp_update
from deerflow.config.extensions_config import McpServerConfig
from deerflow.config.paths import Paths
from deerflow.mcp.cache import initialize_user_mcp_tools, reset_user_mcp_tools_cache
from deerflow.mcp.user_config import load_user_mcp_config, save_user_mcp_config


def test_user_mcp_config_does_not_cross_tenant_boundaries(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: paths)

    save_user_mcp_config(
        "alice",
        {"private": McpServerConfig(command="uvx", args=["alice-server"])},
    )

    assert set(load_user_mcp_config("alice").mcp_servers) == {"private"}
    assert load_user_mcp_config("bob").mcp_servers == {}


def test_user_mcp_tool_cache_loads_the_selected_tenant_only(monkeypatch):
    import deerflow.mcp.tools as mcp_tools

    reset_user_mcp_tools_cache("alice")
    reset_user_mcp_tools_cache("bob")
    seen = []

    async def fake_load(config):
        seen.append(config)
        return ["tool"]

    monkeypatch.setattr(mcp_tools, "get_mcp_tools", fake_load)
    monkeypatch.setattr(
        "deerflow.mcp.user_config.load_user_mcp_config",
        lambda user_id: {"alice": "alice-config", "bob": "bob-config"}[user_id],
    )

    assert asyncio.run(initialize_user_mcp_tools("alice")) == ["tool"]
    assert asyncio.run(initialize_user_mcp_tools("bob")) == ["tool"]
    assert seen == ["alice-config", "bob-config"]


def test_user_mcp_update_writes_only_the_authenticated_owner(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: paths)
    body = McpConfigUpdateRequest(mcp_servers={"private": McpServerConfigResponse(type="http", url="https://alice.example/mcp")})

    _replace_user_servers("alice", body)

    assert set(load_user_mcp_config("alice").mcp_servers) == {"private"}
    assert load_user_mcp_config("bob").mcp_servers == {}


def test_user_mcp_rejects_loopback_remote_server():
    request = McpConfigUpdateRequest(mcp_servers={"internal": McpServerConfigResponse(type="http", url="http://127.0.0.1:8000/mcp")})

    with pytest.raises(HTTPException, match="private or local"):
        validate_user_mcp_update(request)
