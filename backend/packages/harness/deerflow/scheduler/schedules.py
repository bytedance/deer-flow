from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

MAX_INTERVAL_SECONDS = 30 * 24 * 60 * 60


def validate_timezone(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    return timezone_name


def normalize_cron_expression(expr: str) -> str:
    parts = [part for part in expr.split() if part]
    if len(parts) != 5:
        raise ValueError("Cron expression must contain exactly 5 fields")
    return " ".join(parts)


def parse_interval_seconds(schedule_spec: dict[str, object]) -> int:
    raw = schedule_spec.get("every_seconds")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError("interval schedule requires every_seconds as a positive integer")
    return raw


def _is_fixed_time_cron(cron_expr: str) -> bool:
    """Return whether a cron expression specifies a single fixed minute and hour.

    Expressions with wildcards ('*'), steps ('/'), ranges ('-'), or lists (',')
    in either the minute or hour field (e.g. '0 0-23 * * *' or '*/15 2 * * *')
    fire multiple times and should preserve all occurrences across repeated hours.
    """
    parts = cron_expr.strip().split()
    if len(parts) >= 2:
        minute, hour = parts[0], parts[1]
        special = ("*", "/", "-", ",")
        return not any(ch in minute or ch in hour for ch in special)
    return False


def _is_ambiguous_datetime(dt: datetime) -> bool:
    """Return whether a local datetime is ambiguous (e.g. during a DST fall-back)."""
    return dt.replace(fold=0).utcoffset() != dt.replace(fold=1).utcoffset()


def next_run_at(
    schedule_type: str,
    schedule_spec: dict[str, object],
    timezone_name: str,
    *,
    now: datetime,
) -> datetime | None:
    validate_timezone(timezone_name)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    if schedule_type == "once":
        run_at_raw = schedule_spec.get("run_at")
        if not isinstance(run_at_raw, str):
            raise ValueError("once schedule requires run_at")
        run_at = datetime.fromisoformat(run_at_raw)
        if run_at.tzinfo is None:
            # A naive run_at means "wall-clock time in the task's declared
            # timezone", matching how cron schedules interpret it.
            run_at = run_at.replace(tzinfo=ZoneInfo(timezone_name))
        # Normalize to UTC like the cron branch: next_run_at is persisted to
        # timezone-discarding columns (SQLite), where a non-UTC offset shifts
        # the effective fire time by the whole offset.
        run_at = run_at.astimezone(UTC)
        return run_at if run_at > now else None

    if schedule_type == "cron":
        cron_expr = normalize_cron_expression(str(schedule_spec.get("cron", "")))
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone)
        it = croniter(cron_expr, local_now)
        next_local = it.get_next(datetime)
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=zone)

        # During a daylight-saving fall-back (e.g. 03:00 -> 02:00), an ambiguous
        # wall-clock hour repeats twice. croniter returns both occurrences (the
        # first with fold=0, the second with fold=1). For fixed-time tasks
        # (where neither minute nor hour contains '*'), running twice on the
        # same calendar day violates the cron contract (Vixie cron / POSIX
        # behavior). Skip the second occurrence (fold=1) to preserve once-per-day
        # semantics while letting wildcard schedules (e.g. '0 * * * *') fire each hour.
        if next_local.fold == 1 and _is_fixed_time_cron(cron_expr) and _is_ambiguous_datetime(next_local):
            next_local = it.get_next(datetime)
            if next_local.tzinfo is None:
                next_local = next_local.replace(tzinfo=zone)

        return next_local.astimezone(UTC)
    if schedule_type == "interval":
        every_seconds = parse_interval_seconds(schedule_spec)
        return now.astimezone(UTC) + timedelta(seconds=every_seconds)

    raise ValueError(f"Unsupported schedule_type: {schedule_type}")
