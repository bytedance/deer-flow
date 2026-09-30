"""Opt-in, thread-local working notes and compacted source recall."""

from pydantic import BaseModel, Field


class TaskContinuityConfig(BaseModel):
    enabled: bool = False
    max_batches: int = Field(default=32, ge=1, le=64)
    max_records_per_batch: int = Field(default=256, ge=1, le=1024)
    max_record_chars: int = Field(default=16000, ge=1000, le=64000)
