"""Gateway API router for plugin management."""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config.extensions_config import ExtensionsConfig, reload_extensions_config
from src.plugins.registry import get_plugin_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


# --- Response Models ---


class CommandResponse(BaseModel):
    """Response model for a single command."""

    name: str
    full_name: str
    description: str
    argument_hint: str
    plugin_name: str


class PluginResponse(BaseModel):
    """Response model for a single plugin."""

    name: str
    version: str
    description: str
    author: dict
    skills_count: int
    commands_count: int
    mcp_servers_count: int
    enabled: bool


class PluginListResponse(BaseModel):
    """Response model for listing plugins."""

    plugins: list[PluginResponse]
    total: int


class PluginUpdateRequest(BaseModel):
    """Request model for updating plugin state."""

    enabled: bool


class CommandListResponse(BaseModel):
    """Response model for listing plugin commands."""

    commands: list[CommandResponse]
    total: int


# --- Helper Functions ---


def _plugin_to_response(manifest) -> PluginResponse:
    """Convert a PluginManifest to a PluginResponse."""
    return PluginResponse(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        skills_count=manifest.skills_count,
        commands_count=len(manifest.commands),
        mcp_servers_count=len(manifest.mcp_servers),
        enabled=manifest.enabled,
    )


def _update_plugin_state(plugin_name: str, enabled: bool) -> None:
    """Persist plugin enabled state to extensions_config.json.

    Args:
        plugin_name: Name of the plugin to update.
        enabled: New enabled state.
    """
    config_path = ExtensionsConfig.resolve_config_path()
    if config_path is None:
        logger.warning("No extensions config file found, cannot persist plugin state")
        return

    with open(config_path) as f:
        config_data = json.load(f)

    if "plugins" not in config_data:
        config_data["plugins"] = {}

    config_data["plugins"][plugin_name] = {"enabled": enabled}

    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    reload_extensions_config()


# --- Endpoints ---


@router.get("", response_model=PluginListResponse)
async def list_plugins():
    """List all installed plugins."""
    registry = get_plugin_registry()
    plugins = registry.list_all()

    # Apply enabled state from config
    try:
        extensions_config = ExtensionsConfig.from_file()
        for plugin in plugins:
            plugin.enabled = extensions_config.is_plugin_enabled(plugin.name)
    except Exception as e:
        logger.warning("Failed to load extensions config for plugin state: %s", e)

    return PluginListResponse(
        plugins=[_plugin_to_response(p) for p in plugins],
        total=len(plugins),
    )


@router.get("/{plugin_name}", response_model=PluginResponse)
async def get_plugin(plugin_name: str):
    """Get details for a specific plugin."""
    registry = get_plugin_registry()
    manifest = registry.get(plugin_name)

    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")

    # Apply enabled state from config
    try:
        extensions_config = ExtensionsConfig.from_file()
        manifest.enabled = extensions_config.is_plugin_enabled(manifest.name)
    except Exception:
        pass

    return _plugin_to_response(manifest)


@router.put("/{plugin_name}", response_model=PluginResponse)
async def update_plugin(plugin_name: str, request: PluginUpdateRequest):
    """Enable or disable a plugin."""
    registry = get_plugin_registry()
    manifest = registry.get(plugin_name)

    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")

    manifest.enabled = request.enabled
    _update_plugin_state(plugin_name, request.enabled)

    return _plugin_to_response(manifest)


@router.get("/{plugin_name}/commands", response_model=CommandListResponse)
async def list_plugin_commands(plugin_name: str):
    """List commands for a specific plugin."""
    registry = get_plugin_registry()
    manifest = registry.get(plugin_name)

    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")

    commands = [
        CommandResponse(
            name=cmd.name,
            full_name=cmd.full_name,
            description=cmd.description,
            argument_hint=cmd.argument_hint,
            plugin_name=cmd.plugin_name,
        )
        for cmd in manifest.commands
    ]

    return CommandListResponse(commands=commands, total=len(commands))
