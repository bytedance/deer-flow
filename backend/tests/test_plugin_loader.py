"""Tests for plugin discovery and loading."""

import json
from pathlib import Path

from src.plugins.loader import discover_plugins, get_plugins_root_path, load_plugin_manifest


def _create_plugin(plugin_dir: Path, name: str, version: str = "1.0.0", description: str = "Test plugin", author: str = "Test Author") -> None:
    """Create a minimal plugin directory structure for testing."""
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": version,
        "description": description,
        "author": {"name": author},
    }
    (manifest_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")


def _create_plugin_skill(plugin_dir: Path, skill_name: str, description: str = "Test skill") -> None:
    """Create a skill inside a plugin's skills directory."""
    skill_dir = plugin_dir / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {skill_name}\ndescription: {description}\n---\n\n# {skill_name}\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def _create_plugin_command(plugin_dir: Path, command_name: str, description: str = "Test command", argument_hint: str = "<args>") -> None:
    """Create a command file inside a plugin's commands directory."""
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\ndescription: {description}\nargument-hint: \"{argument_hint}\"\n---\n\n# /{command_name}\n\nCommand instructions here.\n"
    (commands_dir / f"{command_name}.md").write_text(content, encoding="utf-8")


def _create_plugin_mcp(plugin_dir: Path, servers: dict) -> None:
    """Create a .mcp.json file inside a plugin directory."""
    mcp_data = {"mcpServers": servers}
    (plugin_dir / ".mcp.json").write_text(json.dumps(mcp_data), encoding="utf-8")


class TestLoadPluginManifest:
    """Tests for loading a single plugin manifest from a directory."""

    def test_load_valid_manifest(self, tmp_path: Path):
        """Should parse plugin.json and return a PluginManifest."""
        plugin_dir = tmp_path / "sales"
        _create_plugin(plugin_dir, "sales", "1.0.0", "Sales plugin", "Anthropic")

        manifest = load_plugin_manifest(plugin_dir)

        assert manifest is not None
        assert manifest.name == "sales"
        assert manifest.version == "1.0.0"
        assert manifest.description == "Sales plugin"
        assert manifest.author == {"name": "Anthropic"}
        assert manifest.plugin_dir == plugin_dir

    def test_load_manifest_with_skills(self, tmp_path: Path):
        """Should count skills discovered in the skills/ subdirectory."""
        plugin_dir = tmp_path / "sales"
        _create_plugin(plugin_dir, "sales")
        _create_plugin_skill(plugin_dir, "call-prep", "Prepare for sales calls")
        _create_plugin_skill(plugin_dir, "account-research", "Research accounts")

        manifest = load_plugin_manifest(plugin_dir)

        assert manifest is not None
        assert manifest.skills_count == 2

    def test_load_manifest_with_commands(self, tmp_path: Path):
        """Should parse command .md files from commands/ directory."""
        plugin_dir = tmp_path / "sales"
        _create_plugin(plugin_dir, "sales")
        _create_plugin_command(plugin_dir, "call-summary", "Summarize a call", "<transcript>")
        _create_plugin_command(plugin_dir, "forecast", "Generate forecast", "<period>")

        manifest = load_plugin_manifest(plugin_dir)

        assert manifest is not None
        assert len(manifest.commands) == 2
        cmd_names = {cmd.name for cmd in manifest.commands}
        assert cmd_names == {"call-summary", "forecast"}
        # Check command attributes
        call_summary = next(c for c in manifest.commands if c.name == "call-summary")
        assert call_summary.description == "Summarize a call"
        assert call_summary.argument_hint == "<transcript>"
        assert call_summary.plugin_name == "sales"
        assert call_summary.full_name == "sales:call-summary"

    def test_load_manifest_with_mcp_json(self, tmp_path: Path):
        """Should load .mcp.json contents into the manifest."""
        plugin_dir = tmp_path / "data"
        _create_plugin(plugin_dir, "data")
        _create_plugin_mcp(plugin_dir, {
            "postgres": {"type": "stdio", "command": "uvx", "args": ["postgres-mcp"]},
        })

        manifest = load_plugin_manifest(plugin_dir)

        assert manifest is not None
        assert "postgres" in manifest.mcp_servers
        assert manifest.mcp_servers["postgres"]["type"] == "stdio"

    def test_load_manifest_missing_plugin_json(self, tmp_path: Path):
        """Should return None if .claude-plugin/plugin.json is missing."""
        plugin_dir = tmp_path / "bad-plugin"
        plugin_dir.mkdir()

        manifest = load_plugin_manifest(plugin_dir)
        assert manifest is None

    def test_load_manifest_invalid_json(self, tmp_path: Path):
        """Should return None if plugin.json is malformed."""
        plugin_dir = tmp_path / "bad-plugin"
        manifest_dir = plugin_dir / ".claude-plugin"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text("not json", encoding="utf-8")

        manifest = load_plugin_manifest(plugin_dir)
        assert manifest is None

    def test_load_manifest_missing_required_fields(self, tmp_path: Path):
        """Should return None if required fields (name, version, description) are missing."""
        plugin_dir = tmp_path / "bad-plugin"
        manifest_dir = plugin_dir / ".claude-plugin"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text(json.dumps({"name": "test"}), encoding="utf-8")

        manifest = load_plugin_manifest(plugin_dir)
        assert manifest is None

    def test_load_manifest_no_skills_or_commands(self, tmp_path: Path):
        """Should work fine with a plugin that has no skills or commands."""
        plugin_dir = tmp_path / "minimal"
        _create_plugin(plugin_dir, "minimal")

        manifest = load_plugin_manifest(plugin_dir)

        assert manifest is not None
        assert manifest.skills_count == 0
        assert manifest.commands == []
        assert manifest.mcp_servers == {}


class TestDiscoverPlugins:
    """Tests for discovering all plugins in a directory."""

    def test_discover_multiple_plugins(self, tmp_path: Path):
        """Should discover all valid plugin directories."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        _create_plugin(plugins_root / "sales", "sales")
        _create_plugin(plugins_root / "data", "data")
        _create_plugin(plugins_root / "finance", "finance")

        plugins = discover_plugins(plugins_root)

        assert len(plugins) == 3
        names = {p.name for p in plugins}
        assert names == {"sales", "data", "finance"}

    def test_discover_skips_invalid_plugins(self, tmp_path: Path):
        """Should skip directories without valid plugin.json."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        _create_plugin(plugins_root / "valid", "valid")
        (plugins_root / "not-a-plugin").mkdir()  # No plugin.json
        (plugins_root / "some-file.txt").write_text("not a dir")  # Not a directory

        plugins = discover_plugins(plugins_root)

        assert len(plugins) == 1
        assert plugins[0].name == "valid"

    def test_discover_skips_hidden_directories(self, tmp_path: Path):
        """Should skip hidden directories (starting with .)."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        _create_plugin(plugins_root / "visible", "visible")
        _create_plugin(plugins_root / ".hidden", "hidden")

        plugins = discover_plugins(plugins_root)

        assert len(plugins) == 1
        assert plugins[0].name == "visible"

    def test_discover_empty_directory(self, tmp_path: Path):
        """Should return empty list for empty directory."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        plugins = discover_plugins(plugins_root)
        assert plugins == []

    def test_discover_nonexistent_directory(self, tmp_path: Path):
        """Should return empty list for nonexistent directory."""
        plugins = discover_plugins(tmp_path / "nonexistent")
        assert plugins == []

    def test_discover_plugins_sorted_by_name(self, tmp_path: Path):
        """Should return plugins sorted by name."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        _create_plugin(plugins_root / "zebra", "zebra")
        _create_plugin(plugins_root / "alpha", "alpha")
        _create_plugin(plugins_root / "mid", "mid")

        plugins = discover_plugins(plugins_root)

        assert [p.name for p in plugins] == ["alpha", "mid", "zebra"]

    def test_discover_with_full_plugin_structure(self, tmp_path: Path):
        """Should correctly discover plugins with skills, commands, and MCP."""
        plugins_root = tmp_path / "installed"
        plugins_root.mkdir()

        sales_dir = plugins_root / "sales"
        _create_plugin(sales_dir, "sales", "1.0.0", "Sales tools")
        _create_plugin_skill(sales_dir, "call-prep")
        _create_plugin_skill(sales_dir, "account-research")
        _create_plugin_command(sales_dir, "forecast", "Generate forecast", "<period>")
        _create_plugin_mcp(sales_dir, {"crm": {"type": "http", "url": "http://localhost"}})

        plugins = discover_plugins(plugins_root)

        assert len(plugins) == 1
        sales = plugins[0]
        assert sales.name == "sales"
        assert sales.skills_count == 2
        assert len(sales.commands) == 1
        assert "crm" in sales.mcp_servers


class TestGetPluginsRootPath:
    """Tests for resolving the plugins root path."""

    def test_returns_path_object(self):
        """Should return a Path object."""
        path = get_plugins_root_path()
        assert isinstance(path, Path)

    def test_path_is_sibling_to_backend(self):
        """Should point to plugins/installed relative to project root."""
        path = get_plugins_root_path()
        # Should end with plugins/installed
        assert path.name == "installed"
        assert path.parent.name == "plugins"
