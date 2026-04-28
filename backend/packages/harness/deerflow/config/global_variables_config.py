"""Configuration for global variables mechanism."""

from pydantic import BaseModel, Field


class GlobalVariablesConfig(BaseModel):
    """Configuration for global variables mechanism."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable global variables mechanism",
    )
    injection_enabled: bool = Field(
        default=True,
        description="Whether to inject global variables into system prompt",
    )
    max_variables_per_scope: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of variables per scope (project or thread)",
    )
    max_value_length: int = Field(
        default=500,
        ge=10,
        le=5000,
        description="Maximum length of a single variable value",
    )
    max_total_prompt_length: int = Field(
        default=3000,
        ge=100,
        le=10000,
        description="Maximum total length of injected variables section in prompt",
    )


# Global configuration instance
_global_variables_config: GlobalVariablesConfig = GlobalVariablesConfig()


def get_global_variables_config() -> GlobalVariablesConfig:
    """Get the current global variables configuration."""
    return _global_variables_config


def set_global_variables_config(config: GlobalVariablesConfig) -> None:
    """Set the global variables configuration."""
    global _global_variables_config
    _global_variables_config = config


def load_global_variables_config_from_dict(config_dict: dict) -> None:
    """Load global variables configuration from a dictionary."""
    global _global_variables_config
    _global_variables_config = GlobalVariablesConfig(**config_dict)
