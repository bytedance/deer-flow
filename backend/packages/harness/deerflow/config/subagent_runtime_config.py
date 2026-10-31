"""Startup-only process capacity for native subagent execution."""

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean


class SubagentRuntimeConfig(BaseModel):
    """Process-local admission and execution limits shared by all subagents."""

    max_running: int = Field(
        default=3,
        ge=1,
        le=64,
        description="Maximum native subagents that may execute concurrently in one Gateway process.",
    )
    max_queued: int = Field(
        default=64,
        ge=0,
        le=10_000,
        description="Maximum native subagents waiting for a process execution slot.",
    )
    admission_policy: Literal["queue", "reject"] = Field(
        default="queue",
        description="Whether a full execution pool queues work or rejects it immediately.",
    )
    queue_timeout_seconds: int = Field(
        default=300,
        ge=1,
        le=86_400,
        description="Maximum wait for a queued native subagent before it fails admission.",
    )

    @field_validator("max_running", "max_queued", "queue_timeout_seconds", mode="before")
    @classmethod
    def _reject_boolean_limits(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")
