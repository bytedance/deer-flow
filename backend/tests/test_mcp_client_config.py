"""Core behavior tests for MCP client server config building."""

import pytest

from src.config.extensions_config import ExtensionsConfig, McpServerConfig
from src.mcp.client import build_server_params, build_servers_config


def test_build_server_params_stdio_success():
    config = McpServerConfig(
        type="stdio",
        command="npx",
        args=["-y", "my-mcp-server"],
        env={"API_KEY": "secret"},
    )

    params = build_server_params("my-server", config)

    assert params == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "my-mcp-server"],
        "env": {"API_KEY": "secret"},
    }


def test_build_server_params_stdio_requires_command():
    config = McpServerConfig(type="stdio", command=None)

    with pytest.raises(ValueError, match="requires 'command' field"):
        build_server_params("broken-stdio", config)


@pytest.mark.parametrize("transport", ["sse", "http"])
def test_build_server_params_http_like_success(transport: str):
    config = McpServerConfig(
        type=transport,
        url="https://example.com/mcp",
        headers={"Authorization": "Bearer token"},
    )

    params = build_server_params("remote-server", config)

    assert params == {
        "transport": transport,
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer token"},
    }


@pytest.mark.parametrize("transport", ["sse", "http"])
def test_build_server_params_http_like_requires_url(transport: str):
    config = McpServerConfig(type=transport, url=None)

    with pytest.raises(ValueError, match="requires 'url' field"):
        build_server_params("broken-remote", config)


def test_build_server_params_rejects_unsupported_transport():
    config = McpServerConfig(type="websocket")

    with pytest.raises(ValueError, match="unsupported transport type"):
        build_server_params("bad-transport", config)


def test_build_servers_config_returns_empty_when_no_enabled_servers():
    extensions = ExtensionsConfig(
        mcp_servers={
            "disabled-a": McpServerConfig(enabled=False, type="stdio", command="echo"),
            "disabled-b": McpServerConfig(enabled=False, type="http", url="https://example.com"),
        },
        skills={},
    )

    assert build_servers_config(extensions) == {}


def test_build_servers_config_skips_invalid_server_and_keeps_valid_ones():
    extensions = ExtensionsConfig(
        mcp_servers={
            "valid-stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["server"]),
            "invalid-stdio": McpServerConfig(enabled=True, type="stdio", command=None),
            "disabled-http": McpServerConfig(enabled=False, type="http", url="https://disabled.example.com"),
        },
        skills={},
    )

    result = build_servers_config(extensions)

    assert "valid-stdio" in result
    assert result["valid-stdio"]["transport"] == "stdio"
    assert "invalid-stdio" not in result
    assert "disabled-http" not in result
