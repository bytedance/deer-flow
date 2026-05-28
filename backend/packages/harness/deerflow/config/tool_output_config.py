"""Configuration for generic tool output protection."""

from pydantic import BaseModel, Field


class ToolOutputConfig(BaseModel):
    """Config section for tool-result output limits."""

    max_bytes: int = Field(
        default=50_000,
        ge=0,
        description="Maximum UTF-8 bytes to keep from any tool result before it is sent back to the model. Set to 0 to disable truncation.",
    )
