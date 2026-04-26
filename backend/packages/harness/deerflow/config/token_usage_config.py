from pydantic import BaseModel, Field


class TokenUsageConfig(BaseModel):
    """Configuration for token usage tracking."""

    enabled: bool = Field(default=False, description="Enable token usage tracking middleware")
