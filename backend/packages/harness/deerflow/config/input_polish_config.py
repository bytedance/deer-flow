from pydantic import BaseModel, Field


class InputPolishConfig(BaseModel):
    """Configuration for pre-send input polishing."""

    enabled: bool = Field(default=True, description="Whether to enable pre-send input polishing in the composer")
    max_chars: int = Field(default=4000, ge=1, description="Maximum number of draft characters accepted by the input polishing endpoint")
    model_name: str | None = Field(default=None, description="Optional model name override for input polishing")
