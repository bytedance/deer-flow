"""Schemas and validation helpers for the built-in cron scheduler."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {value}") from exc
    return value


def _validate_cron(value: str) -> str:
    try:
        croniter(value)
    except CroniterBadCronError as exc:
        raise ValueError(f"Invalid cron expression: {value}") from exc
    return value


def compute_next_fire_at(cron_expression: str, timezone: str, *, now: float | None = None) -> float:
    """Return the next scheduled fire timestamp for a cron expression."""
    current_time = now if now is not None else time.time()
    tz = ZoneInfo(timezone)
    base = datetime.fromtimestamp(current_time, tz=tz)
    next_fire = croniter(cron_expression, base).get_next(datetime)
    if next_fire.tzinfo is None:
        next_fire = next_fire.replace(tzinfo=tz)
    return next_fire.timestamp()


class CronJobPayload(BaseModel):
    """Payload forwarded into the standard DeerFlow run launch path."""

    model_config = ConfigDict(extra="forbid")

    assistant_id: str | None = None
    input: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    multitask_strategy: Literal["reject", "rollback", "interrupt", "enqueue"] = "enqueue"


class CronJobCreate(CronJobPayload):
    """Persisted cron job creation payload."""

    thread_id: str
    cron: str
    timezone: str = "UTC"
    enabled: bool = True

    _validate_cron_field = field_validator("cron")(_validate_cron)
    _validate_timezone_field = field_validator("timezone")(_validate_timezone)


class CronJobUpdate(BaseModel):
    """Partial update for a persisted cron job."""

    model_config = ConfigDict(extra="forbid")

    assistant_id: str | None = None
    input: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    multitask_strategy: Literal["reject", "rollback", "interrupt", "enqueue"] | None = None
    cron: str | None = None
    timezone: str | None = None
    enabled: bool | None = None

    @field_validator("cron")
    @classmethod
    def _validate_optional_cron(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_cron(value)

    @field_validator("timezone")
    @classmethod
    def _validate_optional_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_timezone(value)


class CronJobRecord(CronJobCreate):
    """Store-backed representation of a scheduled cron job."""

    job_id: str
    created_at: float
    updated_at: float
    next_fire_at: float | None = None
    last_fire_at: float | None = None
    last_run_id: str | None = None
