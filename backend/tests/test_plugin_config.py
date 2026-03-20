"""Tests for plugin configuration integration."""

import json
from pathlib import Path

from src.config.extensions_config import ExtensionsConfig
from src.config.plugins_config import PluginsConfig


class TestPluginsConfig:
    """Tests for the PluginsConfig model."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = PluginsConfig()
        assert config.path is None
        assert config.container_path == "/mnt/plugins"
        assert config.auto_merge_mcp is True

    def test_custom_path(self):
        """Should accept a custom path."""
        config = PluginsConfig(path="../plugins/installed")
        assert config.path == "../plugins/installed"

    def test_get_plugins_path_default(self):
        """Should return default path (project root / plugins / installed) when no path configured."""
        config = PluginsConfig()
        path = config.get_plugins_path()
        assert isinstance(path, Path)
        assert path.name == "installed"
        assert path.parent.name == "plugins"

    def test_get_plugins_path_custom(self, tmp_path: Path):
        """Should resolve a custom relative path."""
        config = PluginsConfig(path=str(tmp_path / "custom-plugins"))
        path = config.get_plugins_path()
        assert path == (tmp_path / "custom-plugins").resolve()


class TestExtensionsConfigPlugins:
    """Tests for the plugins section of ExtensionsConfig."""

    def test_plugins_field_defaults_empty(self):
        """Should default to an empty plugins dict."""
        config = ExtensionsConfig(mcp_servers={}, skills={})
        assert config.plugins == {}

    def test_load_plugins_from_json(self, tmp_path: Path):
        """Should load plugins enabled state from JSON."""
        config_data = {
            "mcpServers": {},
            "skills": {},
            "plugins": {
                "sales": {"enabled": True},
                "data": {"enabled": False},
            },
        }
        config_path = tmp_path / "extensions_config.json"
        config_path.write_text(json.dumps(config_data))

        config = ExtensionsConfig.from_file(str(config_path))

        assert "sales" in config.plugins
        assert config.plugins["sales"].enabled is True
        assert "data" in config.plugins
        assert config.plugins["data"].enabled is False

    def test_is_plugin_enabled_explicit(self, tmp_path: Path):
        """Should return the explicit enabled state from config."""
        config_data = {
            "mcpServers": {},
            "skills": {},
            "plugins": {
                "sales": {"enabled": True},
                "data": {"enabled": False},
            },
        }
        config_path = tmp_path / "extensions_config.json"
        config_path.write_text(json.dumps(config_data))

        config = ExtensionsConfig.from_file(str(config_path))

        assert config.is_plugin_enabled("sales") is True
        assert config.is_plugin_enabled("data") is False

    def test_is_plugin_enabled_default(self):
        """Should default to enabled for plugins not in config."""
        config = ExtensionsConfig(mcp_servers={}, skills={})
        assert config.is_plugin_enabled("unknown-plugin") is True

    def test_backward_compatible_without_plugins_key(self, tmp_path: Path):
        """Should work with config files that don't have a plugins key."""
        config_data = {
            "mcpServers": {},
            "skills": {},
        }
        config_path = tmp_path / "extensions_config.json"
        config_path.write_text(json.dumps(config_data))

        config = ExtensionsConfig.from_file(str(config_path))

        assert config.plugins == {}
        # Default behavior: plugins not in config are enabled
        assert config.is_plugin_enabled("any-plugin") is True
