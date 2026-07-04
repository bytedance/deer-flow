from datetime import UTC, datetime

import pytest

from deerflow.scheduler.schedules import (
    next_run_at,
    normalize_cron_expression,
    validate_timezone,
)


def test_validate_timezone_accepts_iana_name():
    assert validate_timezone("Asia/Shanghai") == "Asia/Shanghai"


def test_validate_timezone_rejects_unknown_name():
    with pytest.raises(ValueError):
        validate_timezone("Mars/Base")


def test_normalize_cron_accepts_five_fields():
    assert normalize_cron_expression("0 9 * * 1") == "0 9 * * 1"


def test_normalize_cron_rejects_seconds_field():
    with pytest.raises(ValueError):
        normalize_cron_expression("0 0 9 * * 1")


def test_next_run_at_for_once_returns_none_after_fire_time():
    now = datetime(2026, 7, 2, 2, 0, tzinfo=UTC)
    result = next_run_at(
        "once",
        {"run_at": "2026-07-02T01:00:00+00:00"},
        "UTC",
        now=now,
    )
    assert result is None


def test_next_run_at_for_cron_uses_timezone():
    now = datetime(2026, 7, 1, 0, 30, tzinfo=UTC)
    result = next_run_at(
        "cron",
        {"cron": "0 9 * * *"},
        "Asia/Shanghai",
        now=now,
    )
    assert result == datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
