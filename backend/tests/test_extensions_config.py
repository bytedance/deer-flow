"""Tests for deerflow.config.extensions_config — MCP server & skill config.

Tests the ExtensionsConfig model, environment variable resolution,
JSON file loading, MCP server filtering, skill enablement logic,
and singleton cache management.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure heavy dependencies are mocked before importing deerflow modules.
# ---------------------------------------------------------------------------
for _mod in ("yaml", "dotenv", "langchain", "langchain_core", "langchain_core.tools"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_harness_path = str(Path(__file__).resolve().parents[1] / "packages" / "harness")
if _harness_path not in sys.path:
    sys.path.insert(0, _harness_path)

from deerflow.config.extensions_config import (  # noqa: E402
    ExtensionsConfig,
    McpOAuthConfig,
    McpServerConfig,
    SkillStateConfig,
    get_extensions_config,
    reload_extensions_config,
    reset_extensions_config,
    set_extensions_config,
)
import deerflow.config.extensions_config as _ext_mod  # noqa: E402


# ---------------------------------------------------------------------------
# McpServerConfig
# ---------------------------------------------------------------------------


class TestMcpServerConfig:
    def test_defaults(self):
        cfg = McpServerConfig()
        assert cfg.enabled is True
        assert cfg.type == "stdio"
        assert cfg.command is None
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.url is None
        assert cfg.headers == {}
        assert cfg.oauth is None
        assert cfg.description == ""

    def test_custom_values(self):
        cfg = McpServerConfig(
            enabled=False,
            type="sse",
            url="https://example.com",
            headers={"Authorization": "Bearer tok"},
            description="test server",
        )
        assert cfg.enabled is False
        assert cfg.type == "sse"
        assert cfg.url == "https://example.com"
        assert cfg.description == "test server"

    def test_stdio_with_command(self):
        cfg = McpServerConfig(
            type="stdio",
            command="node",
            args=["server.js", "--port", "3000"],
            env={"NODE_ENV": "production"},
        )
        assert cfg.command == "node"
        assert cfg.args == ["server.js", "--port", "3000"]
        assert cfg.env == {"NODE_ENV": "production"}


# ---------------------------------------------------------------------------
# McpOAuthConfig
# ---------------------------------------------------------------------------


class TestMcpOAuthConfig:
    def test_defaults(self):
        cfg = McpOAuthConfig(token_url="https://auth.example.com/token")
        assert cfg.enabled is True
        assert cfg.grant_type == "client_credentials"
        assert cfg.token_field == "access_token"
        assert cfg.default_token_type == "Bearer"
        assert cfg.refresh_skew_seconds == 60
        assert cfg.extra_token_params == {}

    def test_refresh_token_grant(self):
        cfg = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            grant_type="refresh_token",
            refresh_token="rt_abc123",
        )
        assert cfg.grant_type == "refresh_token"
        assert cfg.refresh_token == "rt_abc123"

    def test_custom_fields(self):
        cfg = McpOAuthConfig(
            token_url="https://auth.example.com/token",
            client_id="my-client",
            client_secret="my-secret",
            scope="read write",
            audience="api.example.com",
        )
        assert cfg.client_id == "my-client"
        assert cfg.client_secret == "my-secret"
        assert cfg.scope == "read write"
        assert cfg.audience == "api.example.com"


# ---------------------------------------------------------------------------
# SkillStateConfig
# ---------------------------------------------------------------------------


class TestSkillStateConfig:
    def test_default_enabled(self):
        cfg = SkillStateConfig()
        assert cfg.enabled is True

    def test_disabled(self):
        cfg = SkillStateConfig(enabled=False)
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# ExtensionsConfig — resolve_env_variables
# ---------------------------------------------------------------------------


class TestResolveEnvVariables:
    def test_resolves_env_var(self):
        with patch.dict(os.environ, {"MY_API_KEY": "secret123"}):
            data = {"key": "$MY_API_KEY"}
            result = ExtensionsConfig.resolve_env_variables(data)
            assert result["key"] == "secret123"

    def test_unresolved_env_var_becomes_empty(self):
        env = os.environ.copy()
        env.pop("NONEXISTENT_VAR_XYZ", None)
        with patch.dict(os.environ, env, clear=True):
            data = {"key": "$NONEXISTENT_VAR_XYZ"}
            result = ExtensionsConfig.resolve_env_variables(data)
            assert result["key"] == ""

    def test_non_env_string_unchanged(self):
        data = {"key": "plain_value"}
        result = ExtensionsConfig.resolve_env_variables(data)
        assert result["key"] == "plain_value"

    def test_nested_dict(self):
        with patch.dict(os.environ, {"NESTED_KEY": "resolved"}):
            data = {"outer": {"inner": "$NESTED_KEY"}}
            result = ExtensionsConfig.resolve_env_variables(data)
            assert result["outer"]["inner"] == "resolved"

    def test_list_with_dicts(self):
        with patch.dict(os.environ, {"LIST_VAL": "found"}):
            data = {"items": [{"val": "$LIST_VAL"}, "plain"]}
            result = ExtensionsConfig.resolve_env_variables(data)
            assert result["items"][0]["val"] == "found"
            assert result["items"][1] == "plain"

    def test_empty_dict(self):
        result = ExtensionsConfig.resolve_env_variables({})
        assert result == {}

    def test_non_string_values_untouched(self):
        data = {"count": 42, "flag": True, "ratio": 3.14}
        result = ExtensionsConfig.resolve_env_variables(data)
        assert result == {"count": 42, "flag": True, "ratio": 3.14}


# ---------------------------------------------------------------------------
# ExtensionsConfig — get_enabled_mcp_servers
# ---------------------------------------------------------------------------


class TestGetEnabledMcpServers:
    def test_filters_disabled(self):
        cfg = ExtensionsConfig(
            mcp_servers={
                "server1": McpServerConfig(enabled=True),
                "server2": McpServerConfig(enabled=False),
                "server3": McpServerConfig(enabled=True),
            }
        )
        enabled = cfg.get_enabled_mcp_servers()
        assert "server1" in enabled
        assert "server2" not in enabled
        assert "server3" in enabled

    def test_empty_servers(self):
        cfg = ExtensionsConfig(mcp_servers={})
        assert cfg.get_enabled_mcp_servers() == {}

    def test_all_disabled(self):
        cfg = ExtensionsConfig(
            mcp_servers={
                "a": McpServerConfig(enabled=False),
                "b": McpServerConfig(enabled=False),
            }
        )
        assert cfg.get_enabled_mcp_servers() == {}


# ---------------------------------------------------------------------------
# ExtensionsConfig — is_skill_enabled
# ---------------------------------------------------------------------------


class TestIsSkillEnabled:
    def test_public_skill_enabled_by_default(self):
        cfg = ExtensionsConfig()
        assert cfg.is_skill_enabled("unknown-skill", "public") is True

    def test_custom_skill_enabled_by_default(self):
        cfg = ExtensionsConfig()
        assert cfg.is_skill_enabled("my-skill", "custom") is True

    def test_other_category_disabled_by_default(self):
        cfg = ExtensionsConfig()
        assert cfg.is_skill_enabled("some-skill", "experimental") is False

    def test_explicit_disabled(self):
        cfg = ExtensionsConfig(
            skills={"my-skill": SkillStateConfig(enabled=False)}
        )
        assert cfg.is_skill_enabled("my-skill", "public") is False

    def test_explicit_enabled_overrides_category(self):
        cfg = ExtensionsConfig(
            skills={"my-skill": SkillStateConfig(enabled=True)}
        )
        assert cfg.is_skill_enabled("my-skill", "experimental") is True


# ---------------------------------------------------------------------------
# ExtensionsConfig — from_file
# ---------------------------------------------------------------------------


class TestFromFile:
    def test_load_valid_json(self):
        data = {
            "mcpServers": {
                "test-server": {
                    "type": "stdio",
                    "command": "node",
                    "args": ["server.js"],
                }
            },
            "skills": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            cfg = ExtensionsConfig.from_file(f.name)
        os.unlink(f.name)
        assert "test-server" in cfg.mcp_servers
        assert cfg.mcp_servers["test-server"].command == "node"

    def test_load_invalid_json_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            f.flush()
            with pytest.raises(ValueError, match="not valid JSON"):
                ExtensionsConfig.from_file(f.name)
        os.unlink(f.name)

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            ExtensionsConfig.from_file("/tmp/definitely_does_not_exist_12345.json")

    def test_no_config_returns_empty(self):
        with patch.object(ExtensionsConfig, "resolve_config_path", return_value=None):
            cfg = ExtensionsConfig.from_file()
            assert cfg.mcp_servers == {}
            assert cfg.skills == {}

    def test_env_var_resolution_in_file(self):
        with patch.dict(os.environ, {"TEST_API_KEY": "resolved_key"}):
            data = {
                "mcpServers": {
                    "server": {
                        "type": "stdio",
                        "command": "cmd",
                        "env": {"API_KEY": "$TEST_API_KEY"},
                    }
                }
            }
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(data, f)
                f.flush()
                cfg = ExtensionsConfig.from_file(f.name)
            os.unlink(f.name)
            assert cfg.mcp_servers["server"].env["API_KEY"] == "resolved_key"


# ---------------------------------------------------------------------------
# ExtensionsConfig — resolve_config_path
# ---------------------------------------------------------------------------


class TestResolveConfigPath:
    def test_explicit_path(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b"{}")
            f.flush()
            result = ExtensionsConfig.resolve_config_path(f.name)
            assert result == Path(f.name)
        os.unlink(f.name)

    def test_explicit_path_missing_raises(self):
        with pytest.raises(FileNotFoundError, match="config_path"):
            ExtensionsConfig.resolve_config_path("/tmp/no_such_config_file.json")

    def test_env_var_path(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b"{}")
            f.flush()
            with patch.dict(os.environ, {"DEER_FLOW_EXTENSIONS_CONFIG_PATH": f.name}):
                result = ExtensionsConfig.resolve_config_path()
                assert result == Path(f.name)
        os.unlink(f.name)

    def test_env_var_missing_file_raises(self):
        with patch.dict(os.environ, {"DEER_FLOW_EXTENSIONS_CONFIG_PATH": "/tmp/nope.json"}):
            with pytest.raises(FileNotFoundError, match="environment variable"):
                ExtensionsConfig.resolve_config_path()


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------


class TestSingletonManagement:
    def test_set_and_get(self):
        custom = ExtensionsConfig(mcp_servers={}, skills={})
        set_extensions_config(custom)
        assert get_extensions_config() is custom
        reset_extensions_config()

    def test_reset_clears_cache(self):
        custom = ExtensionsConfig(mcp_servers={}, skills={})
        set_extensions_config(custom)
        assert _ext_mod._extensions_config is custom
        reset_extensions_config()
        assert _ext_mod._extensions_config is None

    def test_reload_loads_from_file(self):
        data = {"mcpServers": {"srv": {"type": "stdio", "command": "echo"}}, "skills": {}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            cfg = reload_extensions_config(f.name)
        os.unlink(f.name)
        assert "srv" in cfg.mcp_servers
        reset_extensions_config()
