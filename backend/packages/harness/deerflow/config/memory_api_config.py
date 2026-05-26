"""Configuration for the Memory API and UI."""

from __future__ import annotations

from pydantic import BaseModel, Field

_memory_api_config: MemoryApiConfig | None = None


class MemoryApiConfig(BaseModel):
    """Configuration for memory API endpoints and UI features."""

    enabled: bool = Field(
        default=True,
        description="Whether the memory API endpoints are enabled",
    )
    max_content_length: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Maximum content length for memory facts",
    )
    audit_log_retention_days: int = Field(
        default=90,
        ge=1,
        le=3650,
        description="Number of days to retain audit log entries",
    )


def get_memory_api_config() -> MemoryApiConfig:
    """Get the current memory API configuration."""
    global _memory_api_config
    if _memory_api_config is None:
        _memory_api_config = MemoryApiConfig()
    return _memory_api_config


def set_memory_api_config(config: MemoryApiConfig) -> None:
    """Set the memory API configuration."""
    global _memory_api_config
    _memory_api_config = config


def load_memory_api_config_from_dict(config_dict: dict) -> None:
    """Load memory API configuration from a dictionary."""
    global _memory_api_config
    _memory_api_config = MemoryApiConfig(**config_dict)
