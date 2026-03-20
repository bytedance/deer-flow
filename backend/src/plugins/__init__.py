"""Plugin system for integrating Anthropic's knowledge-work plugins."""

from .command_parser import parse_command_file
from .loader import discover_plugins, get_plugins_root_path, load_plugin_manifest
from .mcp_merge import merge_plugin_mcp_servers
from .prompt import build_commands_prompt_section
from .registry import PluginRegistry, get_plugin_registry, reset_plugin_registry
from .types import Command, PluginManifest

__all__ = [
    "Command",
    "PluginManifest",
    "PluginRegistry",
    "build_commands_prompt_section",
    "discover_plugins",
    "get_plugin_registry",
    "get_plugins_root_path",
    "load_plugin_manifest",
    "merge_plugin_mcp_servers",
    "parse_command_file",
    "reset_plugin_registry",
]
