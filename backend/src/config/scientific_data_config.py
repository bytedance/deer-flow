"""Configuration for scientific data analysis tools."""

from pydantic import BaseModel, Field


class ScientificDataConfig(BaseModel):
    """Configuration for scientific data analysis."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable scientific data analysis tools (e.g. analyze_fcs, analyze_embedding_csv).",
    )

_scientific_data_config: ScientificDataConfig = ScientificDataConfig()


def get_scientific_data_config() -> ScientificDataConfig:
    """Get the current scientific data configuration."""
    return _scientific_data_config


def set_scientific_data_config(config: ScientificDataConfig) -> None:
    """Set the scientific data configuration."""
    global _scientific_data_config
    _scientific_data_config = config


def load_scientific_data_config_from_dict(config_dict: dict) -> None:
    """Load scientific data configuration from a dictionary."""
    global _scientific_data_config
    _scientific_data_config = ScientificDataConfig(**config_dict)
