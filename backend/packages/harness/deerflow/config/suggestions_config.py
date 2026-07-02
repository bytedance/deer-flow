from pydantic import BaseModel, Field


class SuggestionsConfig(BaseModel):
    """Configuration for automatic follow-up suggestions."""

    enabled: bool = Field(default=True, description="Whether to enable follow-up question suggestions at the end of an AI response")
