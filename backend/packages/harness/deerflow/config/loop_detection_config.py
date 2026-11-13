"""Configuration for loop detection middleware."""

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from deerflow.config._boolean_guards import reject_boolean


class ToolFreqOverride(BaseModel):
    """Per-tool frequency threshold override.

    Can be higher or lower than the global observability thresholds. Commonly
    used to tune reporting for high-frequency tools like bash in batch workflows
    without changing loop protection on every other tool.
    """

    warn: int = Field(ge=1)
    hard_limit: int = Field(ge=1)

    @field_validator("warn", "hard_limit", mode="before")
    @classmethod
    def reject_boolean_thresholds(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    @model_validator(mode="after")
    def _validate(self) -> "ToolFreqOverride":
        if self.hard_limit < self.warn:
            raise ValueError("hard_limit must be >= warn")
        return self


class LoopDetectionConfig(BaseModel):
    """Configuration for repetitive tool-call loop detection."""

    enabled: bool = Field(
        default=True,
        description="Whether to enable repetitive tool-call loop detection",
    )
    warn_threshold: int = Field(
        default=3,
        ge=1,
        description="Number of identical tool-call sets before injecting a warning",
    )
    hard_limit: int = Field(
        default=5,
        ge=1,
        description="Number of identical tool-call sets before forcing a stop",
    )
    window_size: int = Field(
        default=20,
        ge=1,
        description="Number of recent tool-call sets to track per thread",
    )
    max_tracked_threads: int = Field(
        default=100,
        ge=1,
        description="Maximum number of thread/run histories to keep in memory (legacy field name)",
    )
    tool_freq_warn: int = Field(
        default=30,
        ge=1,
        description="Number of same-tool calls in the observation window before recording a frequency metric",
    )
    tool_freq_hard_limit: int = Field(
        default=50,
        ge=1,
        description="Second same-tool frequency metric threshold; it does not stop the run",
    )
    tool_freq_overrides: dict[str, ToolFreqOverride] = Field(
        default_factory=dict,
        description=("Per-tool observability thresholds for tool_freq_warn / tool_freq_hard_limit, keyed by tool name."),
    )

    @field_validator(
        "warn_threshold",
        "hard_limit",
        "window_size",
        "max_tracked_threads",
        "tool_freq_warn",
        "tool_freq_hard_limit",
        mode="before",
    )
    @classmethod
    def reject_boolean_thresholds(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    @model_validator(mode="after")
    def validate_thresholds(self) -> "LoopDetectionConfig":
        """Keep thresholds ordered for predictable metric reporting."""
        if self.hard_limit < self.warn_threshold:
            raise ValueError("hard_limit must be greater than or equal to warn_threshold")
        if self.tool_freq_hard_limit < self.tool_freq_warn:
            raise ValueError("tool_freq_hard_limit must be greater than or equal to tool_freq_warn")
        return self
