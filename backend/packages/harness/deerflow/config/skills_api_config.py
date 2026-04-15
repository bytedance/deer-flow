"""Configuration for the HTTP skill-management API."""

from pydantic import BaseModel, Field


class SkillsApiConfig(BaseModel):
    """Configuration for skill install and custom-skill management routes."""

    enabled: bool = Field(
        default=False,
        description=(
            "Whether to expose skill install, custom-skill management, and skill state "
            "mutation routes over HTTP. When disabled, the gateway rejects these "
            "routes and hides custom-skill metadata from unauthenticated skill listing."
        ),
    )


_skills_api_config: SkillsApiConfig = SkillsApiConfig()


def get_skills_api_config() -> SkillsApiConfig:
    """Get the current skills API configuration."""
    return _skills_api_config


def set_skills_api_config(config: SkillsApiConfig) -> None:
    """Set the skills API configuration."""
    global _skills_api_config
    _skills_api_config = config


def load_skills_api_config_from_dict(config_dict: dict) -> None:
    """Load skills API configuration from a dictionary."""
    global _skills_api_config
    _skills_api_config = SkillsApiConfig(**config_dict)
