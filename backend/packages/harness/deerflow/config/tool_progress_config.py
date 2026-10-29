"""Configuration for tool progress tracking middleware."""

from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class ToolProgressConfig(BaseModel):
    """Configuration for task-level tool call progress tracking."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable tool progress tracking middleware",
    )
    stagnation_threshold: int = Field(
        default=3,
        ge=1,
        description="Number of consecutive problem calls before injecting a warning hint",
    )
    warn_escalation_count: int = Field(
        default=2,
        ge=1,
        description="Additional problem occurrences after WARNED before escalating to BLOCKED",
    )
    inject_assessment: bool = Field(
        default=True,
        description="Whether to inject progress assessment hints into model requests",
    )
    jaccard_similarity_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Word-set Jaccard similarity threshold for near-duplicate result detection",
    )
    min_word_count_for_similarity: int = Field(
        default=10,
        ge=1,
        description="Minimum unique word count to apply Jaccard check; shorter content skips near-duplicate detection entirely",
    )
    exempt_tools: set[str] = Field(
        default_factory=lambda: {"ask_clarification", "write_todos", "present_files", "task"},
        description="Tool names excluded from progress tracking",
    )
    max_tracked_threads: int = Field(
        default=100,
        ge=1,
        description="Maximum number of thread histories to keep in memory (LRU eviction)",
    )

    @field_validator("stagnation_threshold", "warn_escalation_count", "min_word_count_for_similarity", "max_tracked_threads", mode="before")
    @classmethod
    def _reject_boolean_int_settings(cls, value: Any, info: ValidationInfo) -> Any:
        """Reject booleans before Pydantic coerces them to 1/0, which every bound below accepts as 1."""
        if isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a positive integer, not a boolean")
        return value

    @field_validator("jaccard_similarity_threshold", mode="before")
    @classmethod
    def _reject_boolean_similarity_threshold(cls, value: Any) -> Any:
        """Reject booleans before Pydantic coerces them to 1.0/0.0, both of which sit inside the 0..1 bound."""
        if isinstance(value, bool):
            raise ValueError("jaccard_similarity_threshold must be a number between 0.0 and 1.0, not a boolean")
        return value
