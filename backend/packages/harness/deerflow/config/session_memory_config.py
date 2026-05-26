"""Configuration for session memory mechanism."""

from pydantic import BaseModel, Field


class SessionMemoryConfig(BaseModel):
    """Configuration for thread-scoped session memory."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable session memory mechanism",
    )
    model_name: str | None = Field(
        default=None,
        description="Model name to use for session memory updates (None = use default model)",
    )
    debounce_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Seconds to wait before processing queued session updates (debounce)",
    )
    max_facts: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Maximum number of facts to store per session",
    )
    fact_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for storing facts",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject session memory into system prompt",
    )
    max_injection_tokens: int = Field(
        default=2000,
        ge=100,
        le=8000,
        description="Maximum tokens to use for session memory injection",
    )


# Global configuration instance
_session_memory_config: SessionMemoryConfig = SessionMemoryConfig()


def get_session_memory_config() -> SessionMemoryConfig:
    """Get the current session memory configuration."""
    return _session_memory_config


def set_session_memory_config(config: SessionMemoryConfig) -> None:
    """Set the session memory configuration."""
    global _session_memory_config
    _session_memory_config = config


def load_session_memory_config_from_dict(config_dict: dict) -> None:
    """Load session memory configuration from a dictionary."""
    global _session_memory_config
    _session_memory_config = SessionMemoryConfig(**config_dict)
