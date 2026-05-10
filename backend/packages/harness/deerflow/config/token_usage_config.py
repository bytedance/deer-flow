from pydantic import BaseModel, Field


class TokenUsageConfig(BaseModel):
    """Configuration for token usage tracking."""

    enabled: bool = Field(default=True, description="Enable token usage tracking middleware")
