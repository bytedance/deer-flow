"""Configuration for ByteRover context integration."""

from pathlib import Path

from pydantic import BaseModel, Field


def _repo_root() -> Path:
    """Resolve the repository root from the DeerFlow backend package layout."""
    return Path(__file__).resolve().parents[5]


class ByteRoverConfig(BaseModel):
    """Configuration for ByteRover context injection."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable ByteRover context injection",
    )
    query_timeout: int = Field(
        default=30,
        ge=1,
        description="Timeout in seconds for brv query",
    )
    curate_timeout: int = Field(
        default=10,
        ge=1,
        description="Timeout in seconds for brv curate --detach",
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory for brv commands (None = repository root)",
    )

    @property
    def resolved_cwd(self) -> str:
        """Return the absolute working directory for brv commands."""
        if self.cwd is None:
            return str(_repo_root())

        cwd_path = Path(self.cwd).expanduser()
        if not cwd_path.is_absolute():
            cwd_path = _repo_root() / cwd_path
        return str(cwd_path.resolve())


# Global configuration instance
_byterover_config: ByteRoverConfig = ByteRoverConfig()


def get_byterover_config() -> ByteRoverConfig:
    """Get the current ByteRover configuration."""
    return _byterover_config


def set_byterover_config(config: ByteRoverConfig) -> None:
    """Set the ByteRover configuration."""
    global _byterover_config
    _byterover_config = config


def load_byterover_config_from_dict(config_dict: dict) -> None:
    """Load ByteRover configuration from a dictionary."""
    global _byterover_config
    _byterover_config = ByteRoverConfig(**config_dict)
