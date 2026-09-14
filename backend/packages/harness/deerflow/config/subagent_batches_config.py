"""Startup-only configuration for durable native-subagent batches."""

from pydantic import BaseModel, Field, model_validator


class SubagentBatchesConfig(BaseModel):
    """Durable batch scheduler limits and recovery settings."""

    enabled: bool = Field(default=False)
    poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    lease_seconds: int = Field(default=120, ge=10, le=3600)
    max_items_per_batch: int = Field(default=5_000, ge=1, le=100_000)
    default_max_live_items: int = Field(default=100, ge=1, le=10_000)
    max_live_items_per_batch: int = Field(default=1_000, ge=1, le=100_000)
    default_max_running_items: int = Field(default=3, ge=1, le=64)
    max_running_items_per_batch: int = Field(default=64, ge=1, le=1_000)
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_result_chars: int = Field(default=100_000, ge=1_000, le=1_000_000)
    result_preview_max_chars: int = Field(default=2_000, ge=64, le=100_000)

    @model_validator(mode="after")
    def validate_default_limits(self) -> "SubagentBatchesConfig":
        if self.default_max_live_items > self.max_live_items_per_batch:
            raise ValueError("default_max_live_items must not exceed max_live_items_per_batch")
        if self.default_max_running_items > self.max_running_items_per_batch:
            raise ValueError("default_max_running_items must not exceed max_running_items_per_batch")
        if self.default_max_running_items > self.default_max_live_items:
            raise ValueError("default_max_running_items must not exceed default_max_live_items")
        if self.result_preview_max_chars > self.max_result_chars:
            raise ValueError("result_preview_max_chars must not exceed max_result_chars")
        return self
