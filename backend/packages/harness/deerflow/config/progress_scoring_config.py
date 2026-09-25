"""Configuration for LLM-scored progress evaluation middleware (#2805 MVP).

Experimental, default-off. When enabled, the lead agent asks the model to
append a compact step evaluation to each response that follows tool results
(``task_progress`` / ``tool_usefulness`` scores), cross-checks those scores
against objective signals (repeated tool calls, repeated result hashes,
status transitions), and injects a replan-first intervention hint when a
sliding window shows stagnation.
"""

from pydantic import BaseModel, Field, model_validator


class ProgressScoringConfig(BaseModel):
    """Configuration for LLM-scored progress-aware loop detection."""

    enabled: bool = Field(
        default=False,
        description="Whether to enable LLM-scored progress evaluation (experimental; #2805 MVP)",
    )
    window_size: int = Field(
        default=8,
        ge=1,
        description="Number of recent steps (model turns with tool results) in the sliding window",
    )
    min_evals: int = Field(
        default=3,
        ge=1,
        description="Minimum valid model self-evaluations in the window before a stagnation decision is allowed",
    )
    progress_floor: float = Field(
        default=1.0,
        ge=0.0,
        le=3.0,
        description="Window-average task_progress below this value counts as low progress",
    )
    rearm_progress: float = Field(
        default=2.0,
        ge=0.0,
        le=3.0,
        description="Window-average task_progress at or above this value re-arms the intervention after one fired",
    )
    repetition_threshold: float = Field(
        default=0.6,
        gt=0.0,
        le=1.0,
        description=(
            "Share of repeated tool-call keys or result hashes in the window that counts as high repetition. "
            "Default 0.6 so an exactly-repeating window fires on its third step, level with loop_detection.warn_threshold "
            "and before loop_detection.hard_limit — the replan hint must precede any forced stop."
        ),
    )
    max_tracked_threads: int = Field(
        default=100,
        ge=1,
        description="Maximum number of thread/run window states to keep in memory (LRU eviction)",
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "ProgressScoringConfig":
        """A re-arm threshold at or below the floor would flap every step."""
        if self.rearm_progress < self.progress_floor:
            raise ValueError("rearm_progress must be greater than or equal to progress_floor")
        if self.min_evals > self.window_size:
            raise ValueError("min_evals must be less than or equal to window_size")
        return self
