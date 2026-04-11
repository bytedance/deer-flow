"""Configuration for loop detection middleware.

Allows users to tune the thresholds that control when the loop detector
fires warnings and hard-stops, reducing false positives on models with
smaller context windows (e.g. DeepSeek) or on legitimate retry-heavy tasks.
"""

from pydantic import BaseModel, Field


class LoopDetectionConfig(BaseModel):
    """Configuration for the LoopDetectionMiddleware.

    Attributes:
        warn_threshold: Number of identical tool call sets within the
            sliding window before injecting a "you are repeating yourself"
            warning.  Higher values reduce false positives at the cost of
            slower detection.
        hard_limit: Number of identical tool call sets before forcibly
            stripping tool_calls so the agent must produce a final text
            answer.  Must be >= warn_threshold.
        window_size: Size of the sliding window that tracks recent tool
            call hashes per thread.
        max_tracked_threads: Maximum threads tracked concurrently before
            LRU eviction kicks in.
    """

    warn_threshold: int = Field(
        default=3,
        ge=1,
        description="Inject a loop warning after this many identical tool call sets (default: 3)",
    )
    hard_limit: int = Field(
        default=5,
        ge=2,
        description="Force-stop tool calls after this many identical sets (default: 5)",
    )
    window_size: int = Field(
        default=20,
        ge=1,
        description="Number of recent tool call hashes to track per thread (default: 20)",
    )
    max_tracked_threads: int = Field(
        default=100,
        ge=1,
        description="Max threads tracked before LRU eviction (default: 100)",
    )
