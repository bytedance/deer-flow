"""Plugin discovery and loading system."""

import json
import logging
from pathlib import Path

from .command_parser import parse_command_file
from .types import Command, PluginManifest

logger = logging.getLogger(__name__)


def get_plugins_root_path() -> Path:
    """Get the default path to the plugins/installed directory.

    Returns:
        Path to the plugins/installed directory (thinktank-ai/plugins/installed).
    """
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return backend_dir.parent / "plugins" / "installed"


def load_plugin_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Load a plugin manifest from a directory.

    Reads .claude-plugin/plugin.json for metadata, scans skills/ for skill count,
    parses commands/ for command definitions, and loads .mcp.json for MCP servers.

    Args:
        plugin_dir: Path to the plugin directory.

    Returns:
        PluginManifest if valid, None otherwise.
    """
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest_path.exists():
        return None

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Error reading plugin manifest %s: %s", manifest_path, e)
        return None

    # Validate required fields
    name = manifest_data.get("name")
    version = manifest_data.get("version")
    description = manifest_data.get("description")
    if not name or not version or not description:
        logger.warning("Plugin manifest %s missing required fields (name, version, description)", manifest_path)
        return None

    author = manifest_data.get("author", {})

    # Count skills
    skills_count = 0
    skills_dir = plugin_dir / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_subdir in skills_dir.iterdir():
            if skill_subdir.is_dir() and (skill_subdir / "SKILL.md").exists():
                skills_count += 1

    # Parse commands
    commands: list[Command] = []
    commands_dir = plugin_dir / "commands"
    if commands_dir.exists() and commands_dir.is_dir():
        for cmd_file in sorted(commands_dir.iterdir()):
            if cmd_file.suffix == ".md":
                cmd = parse_command_file(cmd_file, plugin_name=name)
                if cmd:
                    commands.append(cmd)

    # Load MCP servers
    mcp_servers: dict = {}
    mcp_json_path = plugin_dir / ".mcp.json"
    if mcp_json_path.exists():
        try:
            mcp_data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
            mcp_servers = mcp_data.get("mcpServers", {})
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Error reading .mcp.json for plugin %s: %s", name, e)

    return PluginManifest(
        name=name,
        version=version,
        description=description,
        author=author,
        plugin_dir=plugin_dir,
        skills_count=skills_count,
        commands=commands,
        mcp_servers=mcp_servers,
    )


def discover_plugins(plugins_root: Path) -> list[PluginManifest]:
    """Discover all valid plugins in a directory.

    Scans subdirectories of plugins_root for valid plugin manifests,
    skipping hidden directories and non-directory entries.

    Args:
        plugins_root: Path to the directory containing installed plugins.

    Returns:
        List of PluginManifest objects, sorted by name.
    """
    if not plugins_root.exists() or not plugins_root.is_dir():
        return []

    plugins: list[PluginManifest] = []

    for entry in sorted(plugins_root.iterdir()):
        # Skip non-directories and hidden directories
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        manifest = load_plugin_manifest(entry)
        if manifest:
            plugins.append(manifest)

    plugins.sort(key=lambda p: p.name)
    return plugins
