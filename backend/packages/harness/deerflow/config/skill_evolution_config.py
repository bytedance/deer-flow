"""Configuration for skill self-evolution."""

from pydantic import BaseModel, Field


class SkillEvolutionConfig(BaseModel):
    """Configuration for the skill self-evolution feature."""

    enabled: bool = Field(
        default=False,
        description="Enable the experimental skill_manage tool and prompt guidance for editing skills/custom/.",
    )
