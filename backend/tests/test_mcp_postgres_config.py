"""Unit tests for MCP postgres-mcp configuration.

Verifies that the MCP client config builder correctly handles the
crystaldba/postgres-mcp server configuration for stdio transport.
"""

import os
from unittest.mock import patch

import pytest

from src.config.extensions_config import ExtensionsConfig, McpServerConfig
from src.mcp.client import build_server_params, build_servers_config


def _make_postgres_config(enabled: bool = True, db_uri: str = "postgresql://user:pass@localhost:5432/testdb") -> McpServerConfig:
    """Helper to create a postgres MCP server config."""
    return McpServerConfig(
        enabled=enabled,
        type="stdio",
        command="uvx",
        args=["postgres-mcp", "--access-mode=unrestricted"],
        env={"DATABASE_URI": db_uri},
        description="PostgreSQL ERP database",
    )


class TestBuildServerParams:
    """Test build_server_params for postgres-mcp configuration."""

    def test_postgres_mcp_stdio_params(self):
        """build_server_params should produce correct params for postgres-mcp."""
        config = _make_postgres_config()
        params = build_server_params("postgres", config)

        assert params["transport"] == "stdio"
        assert params["command"] == "uvx"
        assert params["args"] == ["postgres-mcp", "--access-mode=unrestricted"]
        assert params["env"] == {"DATABASE_URI": "postgresql://user:pass@localhost:5432/testdb"}

    def test_postgres_mcp_env_passed_through(self):
        """Environment variables should be included in params for stdio transport."""
        config = _make_postgres_config(db_uri="postgresql://admin:secret@db-host:5433/erp")
        params = build_server_params("postgres", config)

        assert "env" in params
        assert params["env"]["DATABASE_URI"] == "postgresql://admin:secret@db-host:5433/erp"

    def test_postgres_mcp_strips_wrapping_quotes(self):
        """Quoted URI values should be normalized before being passed to subprocess env."""
        config = _make_postgres_config(db_uri='"postgresql://user:pass@localhost:5432/testdb"')
        params = build_server_params("postgres", config)

        assert params["env"]["DATABASE_URI"] == "postgresql://user:pass@localhost:5432/testdb"

    def test_postgres_mcp_falls_back_to_database_url_when_database_uri_invalid(self):
        """Invalid DATABASE_URI (e.g., ':memory:') should fallback to DATABASE_URL when valid."""
        config = _make_postgres_config(db_uri=":memory:")
        fallback_url = "postgresql://fallback:pass@localhost:5432/fallback_db"

        with patch.dict(os.environ, {"DATABASE_URL": fallback_url}, clear=True):
            params = build_server_params("postgres", config)

        assert params["env"]["DATABASE_URI"] == fallback_url

    def test_postgres_mcp_invalid_uri_without_fallback_raises(self):
        """Invalid PostgreSQL conninfo without fallback should raise ValueError."""
        config = _make_postgres_config(db_uri=":memory:")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="requires a valid PostgreSQL connection string"):
                build_server_params("postgres", config)

    def test_missing_command_raises_error(self):
        """stdio transport without command should raise ValueError."""
        config = McpServerConfig(
            enabled=True,
            type="stdio",
            command=None,
            args=[],
        )
        with pytest.raises(ValueError, match="requires 'command' field"):
            build_server_params("postgres", config)


class TestBuildServersConfig:
    """Test build_servers_config for filtering and building multi-server configs."""

    def test_enabled_server_included(self):
        """Enabled postgres server should be included in the config dict."""
        extensions = ExtensionsConfig(
            mcp_servers={"postgres": _make_postgres_config(enabled=True)},
        )
        servers = build_servers_config(extensions)

        assert "postgres" in servers
        assert servers["postgres"]["command"] == "uvx"

    def test_disabled_server_excluded(self):
        """Disabled postgres server should be excluded from the config dict."""
        extensions = ExtensionsConfig(
            mcp_servers={"postgres": _make_postgres_config(enabled=False)},
        )
        servers = build_servers_config(extensions)

        assert "postgres" not in servers

    def test_mixed_enabled_disabled(self):
        """Only enabled servers should appear in the result."""
        extensions = ExtensionsConfig(
            mcp_servers={
                "postgres": _make_postgres_config(enabled=True),
                "other": McpServerConfig(enabled=False, type="stdio", command="echo", args=[]),
            },
        )
        servers = build_servers_config(extensions)

        assert "postgres" in servers
        assert "other" not in servers

    def test_empty_servers_returns_empty(self):
        """No MCP servers configured should return empty dict."""
        extensions = ExtensionsConfig(mcp_servers={})
        servers = build_servers_config(extensions)

        assert servers == {}


class TestEnvVariableResolution:
    """Test that environment variables in config are resolved correctly."""

    def test_env_variable_resolved(self):
        """Config values starting with $ should resolve from environment."""
        test_uri = "postgresql://resolved-user:resolved-pass@resolved-host:5432/resolved-db"
        config_data = {
            "mcpServers": {
                "postgres": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["postgres-mcp", "--access-mode=unrestricted"],
                    "env": {"DATABASE_URI": "$TEST_ERP_DB_URI"},
                    "description": "test",
                }
            }
        }

        with patch.dict(os.environ, {"TEST_ERP_DB_URI": test_uri}):
            ExtensionsConfig.resolve_env_variables(config_data)

        resolved_uri = config_data["mcpServers"]["postgres"]["env"]["DATABASE_URI"]
        assert resolved_uri == test_uri

    def test_env_variable_not_set_raises_error(self):
        """Config values with $VAR where VAR is not set should raise ValueError (fail-fast)."""
        config_data = {
            "mcpServers": {
                "postgres": {
                    "env": {"DATABASE_URI": "$NONEXISTENT_VAR_12345"},
                }
            }
        }

        # Remove the var if it somehow exists
        os.environ.pop("NONEXISTENT_VAR_12345", None)

        with pytest.raises(ValueError, match="NONEXISTENT_VAR_12345"):
            ExtensionsConfig.resolve_env_variables(config_data)
