from __future__ import annotations

from pydantic import BaseModel, Field


class SchedulerConfig(BaseModel):
    """Configuration for conversation-created scheduled runs."""

    enabled: bool = Field(default=False, description="Whether Gateway starts the scheduled-run service.")
    poll_interval_seconds: float = Field(default=5.0, ge=0.5, description="How often the service checks for due tasks.")
    max_concurrent_runs: int = Field(default=2, ge=1, description="Maximum scheduled runs executed concurrently by this Gateway process.")
    claim_ttl_seconds: int = Field(default=300, ge=30, description="How long a running-task lease stays valid before another worker may reclaim it.")
    misfire_grace_time_seconds: int = Field(default=300, ge=0, description="How late a one-time task may run before it is marked missed.")
