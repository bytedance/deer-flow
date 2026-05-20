"""Core behavior tests for MCP client server config building."""

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


# ---------------------------------------------------------------------------
# resolve_env_variables: inline $VAR interpolation (#2855)
# ---------------------------------------------------------------------------


class TestResolveEnvVariablesInlineInterpolation:
    """Inline $VAR interpolation in MCP server config string values."""

    def test_whole_string_var_still_resolves(self, monkeypatch):
        monkeypatch.setenv("GITHUB_MCP_AUTH_HEADER", "Bearer ghp_token")
        cfg = {"Authorization": "$GITHUB_MCP_AUTH_HEADER"}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["Authorization"] == "Bearer ghp_token"

    def test_whole_string_var_unset_gives_empty_string(self, monkeypatch):
        monkeypatch.delenv("UNSET_VAR_XYZ", raising=False)
        cfg = {"key": "$UNSET_VAR_XYZ"}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["key"] == ""

    def test_inline_bearer_token_interpolated(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc123")
        cfg = {"Authorization": "Bearer $GITHUB_TOKEN"}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["Authorization"] == "Bearer ghp_abc123"

    def test_inline_unresolved_token_left_as_literal(self, monkeypatch):
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        cfg = {"Authorization": "Bearer $MISSING_TOKEN"}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["Authorization"] == "Bearer $MISSING_TOKEN"

    def test_multiple_inline_tokens_in_one_value(self, monkeypatch):
        monkeypatch.setenv("SCHEME", "Bearer")
        monkeypatch.setenv("SECRET", "tok123")
        # Inline interpolation (does not start with $):
        cfg = {"Authorization": "auth $SCHEME $SECRET"}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["Authorization"] == "auth Bearer tok123"

    def test_string_starting_with_dollar_uses_whole_string_lookup(self, monkeypatch):
        # "$SCHEME $SECRET" starts with $ → treated as a single env var key "SCHEME $SECRET"
        # which doesn't exist, so falls back to empty string (existing behaviour preserved).
        monkeypatch.delenv("SCHEME $SECRET", raising=False)
        cfg = {"key": "$SCHEME $SECRET"}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["key"] == ""

    def test_inline_token_in_nested_dict(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "key-xyz")
        cfg = {"headers": {"X-Api-Key": "prefix-$API_KEY-suffix"}}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["headers"]["X-Api-Key"] == "prefix-key-xyz-suffix"

    def test_no_dollar_sign_unchanged(self):
        cfg = {"Authorization": "Bearer static-token"}
        result = ExtensionsConfig.resolve_env_variables(cfg)
        assert result["Authorization"] == "Bearer static-token"
