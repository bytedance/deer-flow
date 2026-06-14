from pydantic import BaseModel, Field


class SkillEvolutionConfig(BaseModel):
    """Configuration for agent-managed skill evolution."""

    enabled: bool = Field(
        default=False,
        description="Whether the agent can create and modify skills under skills/custom.",
    )
    moderation_model_name: str | None = Field(
        default=None,
        description="Optional model name for skill security moderation. Defaults to the primary chat model.",
    )
    scanner_fail_open: bool = Field(
        default=False,
        description=(
            "When True, non-executable skill content is allowed (with a warning) if the moderation model "
            "is unavailable. Executable content is always blocked when the scanner cannot run. "
            "Defaults to False (fail-closed: block all content on scanner unavailability)."
        ),
    )
