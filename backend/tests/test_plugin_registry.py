"""Tests for the plugin registry singleton."""

import json
from pathlib import Path

from src.plugins.registry import PluginRegistry


def _create_plugin_dir(base: Path, name: str, version: str = "1.0.0", description: str = "Test") -> Path:
    """Create a minimal plugin directory structure."""
    plugin_dir = base / name
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": version, "description": description, "author": {"name": "Test"}}
    (manifest_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return plugin_dir


class TestPluginRegistry:
    """Tests for the PluginRegistry class."""

    def test_load_from_directory(self, tmp_path: Path):
        """Should load all plugins from a directory."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()
        _create_plugin_dir(plugins_root, "sales")
        _create_plugin_dir(plugins_root, "data")

        registry = PluginRegistry()
        registry.load(plugins_root)

        assert len(registry.plugins) == 2
        assert registry.get("sales") is not None
        assert registry.get("data") is not None

    def test_get_returns_none_for_unknown(self, tmp_path: Path):
        """Should return None for unknown plugin names."""
        registry = PluginRegistry()
        registry.load(tmp_path)

        assert registry.get("nonexistent") is None

    def test_list_all_plugins(self, tmp_path: Path):
        """Should return all loaded plugins."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()
        _create_plugin_dir(plugins_root, "alpha")
        _create_plugin_dir(plugins_root, "beta")

        registry = PluginRegistry()
        registry.load(plugins_root)

        all_plugins = registry.list_all()
        assert len(all_plugins) == 2
        names = {p.name for p in all_plugins}
        assert names == {"alpha", "beta"}

    def test_list_enabled_plugins(self, tmp_path: Path):
        """Should return only enabled plugins."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()
        _create_plugin_dir(plugins_root, "enabled-one")
        _create_plugin_dir(plugins_root, "disabled-one")

        registry = PluginRegistry()
        registry.load(plugins_root)

        # Enable one, disable the other
        registry.get("enabled-one").enabled = True
        registry.get("disabled-one").enabled = False

        enabled = registry.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "enabled-one"

    def test_get_all_commands(self, tmp_path: Path):
        """Should return all commands from all loaded plugins."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        # Create plugin with commands
        sales_dir = _create_plugin_dir(plugins_root, "sales")
        commands_dir = sales_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "forecast.md").write_text("---\ndescription: Forecast\n---\n\nBody.\n")

        data_dir = _create_plugin_dir(plugins_root, "data")
        commands_dir = data_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "query.md").write_text("---\ndescription: Query data\n---\n\nBody.\n")

        registry = PluginRegistry()
        registry.load(plugins_root)

        all_commands = registry.get_all_commands()
        assert len(all_commands) == 2
        full_names = {cmd.full_name for cmd in all_commands}
        assert full_names == {"sales:forecast", "data:query"}

    def test_get_command(self, tmp_path: Path):
        """Should look up a specific command by plugin:command name."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        sales_dir = _create_plugin_dir(plugins_root, "sales")
        commands_dir = sales_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "forecast.md").write_text("---\ndescription: Forecast\n---\n\nBody.\n")

        registry = PluginRegistry()
        registry.load(plugins_root)

        cmd = registry.get_command("sales", "forecast")
        assert cmd is not None
        assert cmd.name == "forecast"
        assert cmd.plugin_name == "sales"

    def test_get_command_returns_none_for_unknown(self, tmp_path: Path):
        """Should return None for unknown plugin or command name."""
        registry = PluginRegistry()
        registry.load(tmp_path)

        assert registry.get_command("nonexistent", "cmd") is None

    def test_reload(self, tmp_path: Path):
        """Should reload plugins from the same directory."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()
        _create_plugin_dir(plugins_root, "alpha")

        registry = PluginRegistry()
        registry.load(plugins_root)
        assert len(registry.plugins) == 1

        # Add a new plugin
        _create_plugin_dir(plugins_root, "beta")
        registry.reload()
        assert len(registry.plugins) == 2

    def test_get_all_mcp_servers(self, tmp_path: Path):
        """Should return aggregated MCP servers from all plugins."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        sales_dir = _create_plugin_dir(plugins_root, "sales")
        (sales_dir / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"crm": {"type": "http", "url": "http://crm"}}
        }))

        data_dir = _create_plugin_dir(plugins_root, "data")
        (data_dir / ".mcp.json").write_text(json.dumps({
            "mcpServers": {"postgres": {"type": "stdio", "command": "pg"}}
        }))

        registry = PluginRegistry()
        registry.load(plugins_root)

        all_mcp = registry.get_all_mcp_servers()
        # Should be namespaced
        assert "sales:crm" in all_mcp
        assert "data:postgres" in all_mcp
