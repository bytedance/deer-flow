from datetime import UTC, datetime, timedelta

import pytest

from deerflow.scheduler.schedules import (
    next_run_at,
    normalize_cron_expression,
    parse_interval_seconds,
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


def test_next_run_at_for_once_normalizes_naive_run_at_to_utc():
    now = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
    result = next_run_at(
        "once",
        {"run_at": "2026-08-01T09:00:00"},
        "Asia/Shanghai",
        now=now,
    )
    assert result == datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
    assert result.utcoffset() == timedelta(0)


def test_next_run_at_for_once_normalizes_aware_run_at_to_utc():
    now = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
    result = next_run_at(
        "once",
        {"run_at": "2026-08-01T09:00:00+08:00"},
        "UTC",
        now=now,
    )
    assert result == datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
    assert result.utcoffset() == timedelta(0)


def test_next_run_at_for_cron_uses_timezone():
    now = datetime(2026, 7, 1, 0, 30, tzinfo=UTC)
    result = next_run_at(
        "cron",
        {"cron": "0 9 * * *"},
        "Asia/Shanghai",
        now=now,
    )
    assert result == datetime(2026, 7, 1, 1, 0, tzinfo=UTC)


def test_next_run_at_for_interval_adds_seconds_in_utc():
    now = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    result = next_run_at(
        "interval",
        {"every_seconds": 90},
        "UTC",
        now=now,
    )
    assert result == datetime(2026, 7, 1, 0, 1, 30, tzinfo=UTC)
    assert result.utcoffset() == timedelta(0)


def test_next_run_at_for_interval_ignores_timezone():
    now = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    shanghai = next_run_at(
        "interval",
        {"every_seconds": 5400},
        "Asia/Shanghai",
        now=now,
    )
    utc = next_run_at(
        "interval",
        {"every_seconds": 5400},
        "UTC",
        now=now,
    )
    assert shanghai == utc == datetime(2026, 7, 1, 1, 30, tzinfo=UTC)


def test_next_run_at_for_interval_does_not_catch_up_from_a_stale_now():
    # A late poller must schedule from the compute instant, not fill missed beats.
    now = datetime(2026, 7, 1, 0, 10, tzinfo=UTC)
    result = next_run_at(
        "interval",
        {"every_seconds": 60},
        "UTC",
        now=now,
    )
    assert result == datetime(2026, 7, 1, 0, 11, tzinfo=UTC)


@pytest.mark.parametrize(
    "spec",
    [
        {},
        {"every_seconds": "90"},
        {"every_seconds": 90.0},
        {"every_seconds": True},
        {"every_seconds": 0},
        {"every_seconds": -30},
    ],
)
def test_parse_interval_seconds_rejects_invalid_spec(spec):
    with pytest.raises(ValueError, match="every_seconds"):
        parse_interval_seconds(spec)


def test_next_run_at_for_cron_skips_repeated_hour_on_dst_fall_back():
    """Regression test for GH#6052.

    On a DST fall-back day a wall-clock time inside the repeated hour occurs
    twice. A daily cron must fire once, not twice.
    """
    from datetime import date
    from zoneinfo import ZoneInfo

    zone_name = "Europe/Berlin"
    zone = ZoneInfo(zone_name)
    spec = {"cron": "30 2 * * *"}

    # Berlin falls back from CEST to CET on 2026-10-25, so 02:30 occurs twice.
    now = datetime(2026, 10, 24, 12, 0, tzinfo=zone)
    first = next_run_at("cron", spec, zone_name, now=now)
    second = next_run_at("cron", spec, zone_name, now=first)

    first_local = first.astimezone(zone)
    second_local = second.astimezone(zone)

    assert first_local.date() == date(2026, 10, 25)
    assert (first_local.hour, first_local.minute) == (2, 30)
    # the repeated occurrence is skipped, so the next run is the following day
    assert second_local.date() == date(2026, 10, 26)
    assert (second_local.hour, second_local.minute) == (2, 30)


def test_next_run_at_for_cron_outside_repeated_hour_is_unaffected():
    """A cron outside the repeated hour still advances one day at a time."""
    from datetime import date
    from zoneinfo import ZoneInfo

    zone_name = "Europe/Berlin"
    zone = ZoneInfo(zone_name)
    spec = {"cron": "30 12 * * *"}

    now = datetime(2026, 10, 24, 0, 0, tzinfo=zone)
    first = next_run_at("cron", spec, zone_name, now=now)
    second = next_run_at("cron", spec, zone_name, now=first)

    assert first.astimezone(zone).date() == date(2026, 10, 24)
    assert second.astimezone(zone).date() == date(2026, 10, 25)
