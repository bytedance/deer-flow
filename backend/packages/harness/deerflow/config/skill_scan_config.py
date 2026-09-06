"""Configuration for native skill safety scanning."""

from pydantic import BaseModel, Field


class SkillScanConfig(BaseModel):
    """Configuration for deterministic SkillScan analyzers."""

    enabled: bool = Field(
        default=True,
        description="Whether native deterministic SkillScan analyzers run before the LLM skill scanner.",
    )
