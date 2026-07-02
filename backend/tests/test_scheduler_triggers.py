from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deerflow.scheduler.cron_parser import CronParseError, compute_next_cron, parse_cron_expr
from deerflow.scheduler.stagger import DEFAULT_TOP_OF_HOUR_STAGGER_MS, stable_offset_ms
from deerflow.scheduler.triggers import CronTrigger


def test_cron_trigger_stagger_uses_job_id() -> None:
    trigger = CronTrigger("0 * * * *", tz="UTC")
    now = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    base_next = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)

    first_offset = stable_offset_ms("job-a", DEFAULT_TOP_OF_HOUR_STAGGER_MS)
    second_offset = stable_offset_ms("job-b", DEFAULT_TOP_OF_HOUR_STAGGER_MS)
    assert first_offset != second_offset

    assert trigger.compute_next(None, now=now, job_id="job-a") == base_next + timedelta(milliseconds=first_offset)
    assert trigger.compute_next(None, now=now, job_id="job-b") == base_next + timedelta(milliseconds=second_offset)


def test_cron_day_of_week_uses_vixie_sunday_zero() -> None:
    after = datetime(2026, 6, 20, 23, 0, tzinfo=UTC)

    sunday_fields = parse_cron_expr("0 8 * * 0")
    monday_fields = parse_cron_expr("0 8 * * 1")

    assert compute_next_cron(sunday_fields, after, "UTC") == datetime(2026, 6, 21, 8, 0, tzinfo=UTC)
    assert compute_next_cron(monday_fields, after, "UTC") == datetime(2026, 6, 22, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize("expr", ["5-3 * * * *", "5-3/1 * * * *"])
def test_cron_parser_rejects_reversed_ranges(expr: str) -> None:
    with pytest.raises(CronParseError, match="range start must be <= end"):
        parse_cron_expr(expr)
