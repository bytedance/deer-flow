"""Opt-in, thread-local working notes and compacted source recall."""

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean


class TaskContinuityConfig(BaseModel):
    enabled: bool = False
    max_batches: int = Field(default=32, ge=1, le=64)
    max_records_per_batch: int = Field(default=256, ge=1, le=1024)
    max_record_chars: int = Field(default=16000, ge=1000, le=64000)

    @field_validator("max_batches", "max_records_per_batch", "max_record_chars", mode="before")
    @classmethod
    def _reject_boolean_limits(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")
