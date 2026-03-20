"""Plugin registry for managing installed plugins."""

import logging
from pathlib import Path

from .loader import discover_plugins
from .mcp_merge import merge_plugin_mcp_servers
from .types import Command, PluginManifest

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry for installed plugins.

    Manages the lifecycle of discovered plugins: loading, querying,
    and providing aggregated access to plugin resources (skills, commands, MCP servers).
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}
        self._plugins_root: Path | None = None

    @property
    def plugins(self) -> dict[str, PluginManifest]:
        """Return the internal plugins dict."""
        return self._plugins

    def load(self, plugins_root: Path) -> None:
        """Load all plugins from a directory.

        Args:
            plugins_root: Path to the directory containing installed plugins.
        """
        self._plugins_root = plugins_root
        self._plugins = {}

        for manifest in discover_plugins(plugins_root):
            self._plugins[manifest.name] = manifest
            logger.info("Loaded plugin: %s v%s (%d skills, %d commands)", manifest.name, manifest.version, manifest.skills_count, len(manifest.commands))

    def reload(self) -> None:
        """Reload plugins from the same directory."""
        if self._plugins_root:
            self.load(self._plugins_root)

    def get(self, name: str) -> PluginManifest | None:
        """Get a plugin by name.

        Args:
            name: Plugin name.

        Returns:
            PluginManifest if found, None otherwise.
        """
        return self._plugins.get(name)

    def list_all(self) -> list[PluginManifest]:
        """Return all loaded plugins, sorted by name."""
        return sorted(self._plugins.values(), key=lambda p: p.name)

    def list_enabled(self) -> list[PluginManifest]:
        """Return only enabled plugins, sorted by name."""
        return [p for p in self.list_all() if p.enabled]

    def get_all_commands(self) -> list[Command]:
        """Return all commands from all loaded plugins."""
        commands: list[Command] = []
        for plugin in self._plugins.values():
            commands.extend(plugin.commands)
        return commands

    def get_command(self, plugin_name: str, command_name: str) -> Command | None:
        """Look up a specific command by plugin and command name.

        Args:
            plugin_name: Name of the plugin.
            command_name: Name of the command.

        Returns:
            Command if found, None otherwise.
        """
        plugin = self._plugins.get(plugin_name)
        if not plugin:
            return None
        return next((cmd for cmd in plugin.commands if cmd.name == command_name), None)

    def get_all_mcp_servers(self) -> dict:
        """Return aggregated, namespaced MCP servers from all plugins.

        Server names are prefixed with the plugin name to avoid conflicts:
        e.g., "sales:crm", "data:postgres".

        Returns:
            Dictionary of namespaced server name -> server config.
        """
        merged: dict = {}
        for plugin in self._plugins.values():
            if plugin.mcp_servers:
                merged = merge_plugin_mcp_servers(
                    plugin.name,
                    {"mcpServers": plugin.mcp_servers},
                    merged,
                )
        return merged


# Module-level singleton
_plugin_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    """Get the global plugin registry singleton.

    Returns:
        The cached PluginRegistry instance.
    """
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
        # Try to load from default path
        try:
            from src.config.plugins_config import PluginsConfig

            config = PluginsConfig()
            try:
                from src.config import get_app_config

                app_config = get_app_config()
                if hasattr(app_config, "plugins") and app_config.plugins:
                    config = app_config.plugins
            except Exception:
                pass
            plugins_path = config.get_plugins_path()
            if plugins_path.exists():
                _plugin_registry.load(plugins_path)
        except Exception as e:
            logger.warning("Failed to load plugins: %s", e)
    return _plugin_registry


def reset_plugin_registry() -> None:
    """Reset the plugin registry singleton. Useful for testing."""
    global _plugin_registry
    _plugin_registry = None
