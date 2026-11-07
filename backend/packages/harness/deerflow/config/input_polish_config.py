from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean


class InputPolishConfig(BaseModel):
    """Configuration for pre-send input polishing."""

    enabled: bool = Field(default=True, description="Whether to enable pre-send input polishing in the composer")
    max_chars: int = Field(default=4000, ge=1, description="Maximum number of draft characters accepted by the input polishing endpoint")
    model_name: str | None = Field(default=None, description="Optional model name override for input polishing")

    @field_validator("max_chars", mode="before")
    @classmethod
    def _reject_boolean_max_chars(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")
