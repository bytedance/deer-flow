"""Configuration for the plugin system."""

from pathlib import Path

from pydantic import BaseModel, Field


class PluginsConfig(BaseModel):
    """Configuration for the plugins system."""

    path: str | None = Field(
        default=None,
        description="Path to installed plugins directory. If not specified, defaults to ../plugins/installed relative to backend directory",
    )
    container_path: str = Field(
        default="/mnt/plugins",
        description="Path where plugins are mounted in the sandbox container",
    )
    auto_merge_mcp: bool = Field(
        default=True,
        description="Whether to automatically merge plugin .mcp.json configs into the system",
    )

    def get_plugins_path(self) -> Path:
        """Get the resolved plugins directory path.

        Returns:
            Path to the installed plugins directory.
        """
        if self.path:
            path = Path(self.path)
            if not path.is_absolute():
                # Resolve relative to backend/ dir
                path = Path(__file__).resolve().parent.parent.parent / path
            return path.resolve()
        else:
            # Default: ../plugins/installed relative to backend directory
            from src.plugins.loader import get_plugins_root_path

            return get_plugins_root_path()
