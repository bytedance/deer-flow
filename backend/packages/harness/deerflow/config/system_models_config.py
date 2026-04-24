"""Configuration for system-level model defaults."""

from pydantic import BaseModel, Field


class SystemModelsConfig(BaseModel):
    """Default model configuration for system-level LLM tasks.

    When a system task (title generation, memory, summarization, suggestions,
    skill security scanning) has no explicit model_name override, it falls back
    to the 'default' model specified here. If this section is absent or default
    is null, the first model in the models[] list is used (backward compatible).
    """

    default: str | None = Field(
        default=None,
        description=("Default model name for system-level LLM tasks (title, memory, summarization, suggestions, security scanning). null = use the first model in the models list."),
    )


# Global configuration instance
_system_models_config: SystemModelsConfig = SystemModelsConfig()


def get_system_models_config() -> SystemModelsConfig:
    """Get the current system models configuration."""
    return _system_models_config


def set_system_models_config(config: SystemModelsConfig) -> None:
    """Set the system models configuration."""
    global _system_models_config
    _system_models_config = config


def load_system_models_config_from_dict(config_dict: dict) -> None:
    """Load system models configuration from a dictionary."""
    global _system_models_config
    _system_models_config = SystemModelsConfig(**config_dict)
