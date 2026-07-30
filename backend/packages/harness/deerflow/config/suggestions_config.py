from pydantic import BaseModel, Field

DEFAULT_MAX_SUGGESTIONS = 3
MAX_SUGGESTIONS_LIMIT = 5


class SuggestionsConfig(BaseModel):
    """Configuration for automatic follow-up suggestions."""

    enabled: bool = Field(default=True, description="Whether to enable follow-up question suggestions at the end of an AI response")
    max_suggestions: int = Field(
        default=DEFAULT_MAX_SUGGESTIONS,
        ge=1,
        le=MAX_SUGGESTIONS_LIMIT,
        description="Maximum number of follow-up suggestions to generate.",
    )
