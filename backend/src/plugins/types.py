"""Type definitions for the plugin system."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Command:
    """Represents a slash command from a plugin.

    Commands are markdown files in a plugin's commands/ directory.
    They contain frontmatter metadata and a markdown body with instructions.
    """

    name: str  # e.g., "call-summary"
    description: str  # From frontmatter
    argument_hint: str  # e.g., "<call notes or transcript>"
    content: str  # Full markdown body (instructions)
    plugin_name: str  # e.g., "sales"

    @property
    def full_name(self) -> str:
        """Return the fully qualified command name (e.g., 'sales:call-summary')."""
        return f"{self.plugin_name}:{self.name}"

    def __repr__(self) -> str:
        return f"Command(name={self.full_name!r}, description={self.description!r})"


@dataclass
class PluginManifest:
    """Represents a plugin with its metadata, skills, commands, and MCP servers.

    Plugins are directories containing:
    - .claude-plugin/plugin.json (manifest metadata)
    - skills/ (optional, SKILL.md files)
    - commands/ (optional, slash command .md files)
    - .mcp.json (optional, MCP server connections)
    """

    name: str  # e.g., "sales"
    version: str  # e.g., "1.0.0"
    description: str  # Human-readable description
    author: dict  # e.g., {"name": "Anthropic"}
    plugin_dir: Path  # Physical directory path
    skills_count: int = 0  # Number of skills discovered
    commands: list[Command] = field(default_factory=list)
    mcp_servers: dict = field(default_factory=dict)  # From .mcp.json
    enabled: bool = False  # From extensions_config.json

    @property
    def skills_dir(self) -> Path:
        """Path to the plugin's skills directory."""
        return self.plugin_dir / "skills"

    @property
    def commands_dir(self) -> Path:
        """Path to the plugin's commands directory."""
        return self.plugin_dir / "commands"

    @property
    def mcp_json_path(self) -> Path:
        """Path to the plugin's .mcp.json file."""
        return self.plugin_dir / ".mcp.json"

    @property
    def manifest_path(self) -> Path:
        """Path to the plugin's plugin.json manifest."""
        return self.plugin_dir / ".claude-plugin" / "plugin.json"

    def get_container_path(self, container_base_path: str = "/mnt/plugins") -> str:
        """Get the full path to this plugin in the container.

        Args:
            container_base_path: Base path where plugins are mounted in the container.

        Returns:
            Full container path to the plugin directory.
        """
        return f"{container_base_path}/{self.name}"

    def __repr__(self) -> str:
        return (
            f"PluginManifest(name={self.name!r}, version={self.version!r}, "
            f"skills={self.skills_count}, commands={len(self.commands)})"
        )
