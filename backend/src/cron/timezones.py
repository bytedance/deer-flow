"""Timezone helpers for cron scheduling and display."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .types import CronSchedule

DEFAULT_TIMEZONE_NAME = "Asia/Shanghai"
_FIXED_UTC_OFFSET_RE = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")


def get_default_timezone_name() -> str:
    """Read the configured default timezone, falling back to Asia/Shanghai."""
    try:
        from deerflow.config.app_config import get_app_config

        app_config = get_app_config()
        extra = app_config.model_extra or {}
        channels = extra.get("channels", {})
        if isinstance(channels, dict):
            session = channels.get("session", {})
            if isinstance(session, dict):
                context = session.get("context", {})
                if isinstance(context, dict):
                    configured = normalize_iana_timezone(context.get("timezone"))
                    if configured:
                        return configured
    except Exception:
        pass
    return DEFAULT_TIMEZONE_NAME


def _local_timezone() -> tzinfo:
    """Return the current process timezone, falling back to UTC."""
    return datetime.now().astimezone().tzinfo or UTC


def normalize_iana_timezone(value: Any) -> str | None:
    """Return a valid IANA timezone name or None."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return None
    return normalized


def resolve_timezone_name(tz_name: str) -> tzinfo:
    """Resolve an explicit timezone name or fixed UTC offset into tzinfo."""
    if tz_name == "UTC":
        return UTC

    fixed_offset_match = _FIXED_UTC_OFFSET_RE.fullmatch(tz_name)
    if fixed_offset_match:
        sign = 1 if fixed_offset_match.group(1) == "+" else -1
        hours = int(fixed_offset_match.group(2))
        minutes = int(fixed_offset_match.group(3))
        offset = timedelta(hours=hours, minutes=minutes) * sign
        return timezone(offset, name=tz_name)

    return ZoneInfo(tz_name)


def resolve_timezone(tz_name: str | None) -> tzinfo:
    """Resolve a timezone name or fixed UTC offset into a tzinfo."""
    if not tz_name:
        return _local_timezone()
    return resolve_timezone_name(tz_name)

def normalize_cron_schedule_timezone(schedule: CronSchedule) -> CronSchedule:
    """Backfill a cron schedule timezone using the configured default."""
    if schedule.kind == "cron" and not schedule.tz:
        schedule.tz = get_default_timezone_name()
    return schedule


def get_schedule_timezone(schedule: CronSchedule | Mapping[str, Any] | None) -> tzinfo:
    """Resolve the display/execution timezone for a schedule-like object."""
    if schedule is None:
        return UTC

    if isinstance(schedule, CronSchedule):
        kind = schedule.kind
        tz_name = schedule.tz
    else:
        kind = schedule.get("kind")
        tz_name = schedule.get("tz")

    if kind == "cron":
        if isinstance(tz_name, str) and tz_name:
            return resolve_timezone(tz_name)
        return resolve_timezone(None)

    return UTC


def format_timestamp_ms(timestamp_ms: int | None, *, schedule: CronSchedule | Mapping[str, Any] | None = None) -> str | None:
    """Format a millisecond timestamp using the schedule's effective timezone."""
    if timestamp_ms is None:
        return None
    tz = get_schedule_timezone(schedule)
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=tz).isoformat()
