"""Core behavior tests for MCP client server config building."""

import logging

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.mcp.client import build_server_params, build_servers_config


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


def test_extensions_config_resolves_env_variables_inside_nested_collections(monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "secret")
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    raw_config = {
        "args": ["--token", "$MCP_TOKEN", {"nested": ["$MCP_TOKEN", "$MISSING_TOKEN"]}],
        "tuple_args": ("$MCP_TOKEN", "$MISSING_TOKEN"),
        "env": {"API_KEY": "$MCP_TOKEN"},
        "enabled": True,
        "timeout": 30,
    }

    resolved = ExtensionsConfig.resolve_env_variables(raw_config)

    assert resolved["args"] == ["--token", "secret", {"nested": ["secret", ""]}]
    assert resolved["tuple_args"] == ("secret", "")
    assert resolved["env"] == {"API_KEY": "secret"}
    assert resolved["enabled"] is True
    assert resolved["timeout"] == 30


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


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("Bearer static-secret-123\n", "line break"),
        ("Bearer static-secret-caf\u00e9", "outside ASCII"),
        ("Bearer static-secret-456 ", "whitespace"),
    ],
    ids=["trailing-newline", "non-ascii", "trailing-space"],
)
def test_build_server_params_rejects_illegal_header_value(value: str, reason: str):
    """A statically configured value the transport would refuse is denied here.

    h11 renders the full value into its exception message on a line break or
    surrounding whitespace, which ToolErrorHandlingMiddleware turns into a
    model-visible ToolMessage. These values are API keys often enough that the
    denial names the header and the reason instead.
    """
    config = McpServerConfig(type="http", url="https://example.com/mcp", headers={"Authorization": value})

    with pytest.raises(ValueError) as excinfo:
        build_server_params("remote-server", config)

    message = str(excinfo.value)
    assert reason in message
    assert "static-secret" not in message
    assert "Authorization" in message


def test_build_servers_config_drops_only_the_server_with_an_illegal_header(caplog):
    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "broken": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer static-secret-123\n"},
                },
                "healthy": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": "Bearer fine"},
                },
            }
        }
    )

    with caplog.at_level(logging.ERROR, logger="deerflow.mcp.client"):
        servers_config = build_servers_config(config)

    # One bad server does not take the others down with it, and the log that
    # explains the drop does not carry the value either.
    assert set(servers_config) == {"healthy"}
    assert "static-secret" not in caplog.text


@pytest.mark.parametrize("transport", ["sse", "http"])
def test_mcp_server_config_accepts_transport_alias(transport: str):
    """The MCP-spec ``transport`` field should be accepted as an alias for ``type``.

    Regression test for https://github.com/bytedance/deer-flow/issues/3238 — a
    remote MCP server configured with only ``transport: sse`` was previously
    misidentified as ``stdio`` (the default for ``type``).
    """
    config = McpServerConfig.model_validate(
        {
            "transport": transport,
            "url": "https://example.com/mcp",
        }
    )

    assert config.type == transport

    params = build_server_params("aliased-server", config)
    assert params["transport"] == transport
    assert params["url"] == "https://example.com/mcp"


def test_mcp_server_config_type_takes_precedence_over_transport():
    """When both ``type`` and ``transport`` are provided, ``type`` wins."""
    config = McpServerConfig.model_validate(
        {
            "type": "http",
            "transport": "sse",
            "url": "https://example.com/mcp",
        }
    )

    assert config.type == "http"


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


def test_build_server_params_excludes_tool_call_timeout():
    """tool_call_timeout must NOT appear in the connection dict.

    langchain-mcp-adapters passes the connection dict to create_session(),
    which forwards unknown keys to _create_stdio_session(), causing TypeError.
    The timeout is read from McpServerConfig at the tool wrapper call-site
    instead.  Regression for PR #3843 P1 bug.
    """
    config = McpServerConfig(
        type="stdio",
        command="npx",
        args=["-y", "my-mcp-server"],
        tool_call_timeout=30.0,
    )

    params = build_server_params("my-server", config)

    assert "tool_call_timeout" not in params
    assert params == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "my-mcp-server"],
    }
