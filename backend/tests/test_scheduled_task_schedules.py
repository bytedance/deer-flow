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


def test_next_run_at_for_cron_skips_duplicate_fixed_hour_run_on_dst_fallback():
    """A fixed-hour task runs once per day on DST fall-back (Vixie cron contract)."""
    # Europe/Berlin fall-back: 2026-10-25 03:00 CEST turns back to 02:00 CET.
    # 02:30 is ambiguous and occurs twice.
    now = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    first = next_run_at("cron", {"cron": "30 2 * * *"}, "Europe/Berlin", now=now)
    assert first == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # 02:30 CEST (+02:00)

    second = next_run_at("cron", {"cron": "30 2 * * *"}, "Europe/Berlin", now=first)
    assert second == datetime(2026, 10, 26, 1, 30, tzinfo=UTC)  # 02:30 CET (+01:00) next day

    # America/New_York fall-back: 2026-11-01 02:00 EDT turns back to 01:00 EST.
    # 01:30 is ambiguous and occurs twice.
    ny_now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    ny_first = next_run_at("cron", {"cron": "30 1 * * *"}, "America/New_York", now=ny_now)
    assert ny_first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 01:30 EDT (-04:00)

    ny_second = next_run_at("cron", {"cron": "30 1 * * *"}, "America/New_York", now=ny_first)
    assert ny_second == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)  # 01:30 EST (-05:00) next day

    # Australia/Sydney fall-back (Southern Hemisphere): 2027-04-04 03:00 AEDT (+11:00) turns back to 02:00 AEST (+10:00).
    # 02:30 is ambiguous and occurs twice.
    syd_now = datetime(2027, 4, 3, 12, 0, tzinfo=UTC)
    syd_first = next_run_at("cron", {"cron": "30 2 * * *"}, "Australia/Sydney", now=syd_now)
    assert syd_first == datetime(2027, 4, 3, 15, 30, tzinfo=UTC)  # 02:30 AEDT (+11:00)

    syd_second = next_run_at("cron", {"cron": "30 2 * * *"}, "Australia/Sydney", now=syd_first)
    assert syd_second == datetime(2027, 4, 4, 16, 30, tzinfo=UTC)  # 02:30 AEST (+10:00) next day


def test_next_run_at_for_cron_spring_forward_does_not_skip_day():
    """Europe/Berlin spring-forward: 2027-03-28 02:00 CET jumps to 03:00 CEST.
    02:30 does not exist and resolves to 03:00 with fold=0; must not be skipped."""
    b_now = datetime(2027, 3, 27, 13, 0, tzinfo=UTC)
    first = next_run_at("cron", {"cron": "30 2 * * *"}, "Europe/Berlin", now=b_now)
    assert first == datetime(2027, 3, 28, 1, 0, tzinfo=UTC)  # 03:00 CEST (+02:00)

    second = next_run_at("cron", {"cron": "30 2 * * *"}, "Europe/Berlin", now=first)
    assert second == datetime(2027, 3, 29, 0, 30, tzinfo=UTC)  # 02:30 CEST next day


def test_next_run_at_for_cron_wildcards_fire_in_repeated_dst_hour():
    """Wildcard schedules (e.g. hourly) fire in both occurrences of the repeated hour."""
    now = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    # 02:00 CEST (+02:00) -> 00:00 UTC
    dt1 = next_run_at("cron", {"cron": "0 * * * *"}, "Europe/Berlin", now=now)
    assert dt1 == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)

    # 02:00 CET (+01:00) -> 01:00 UTC
    dt2 = next_run_at("cron", {"cron": "0 * * * *"}, "Europe/Berlin", now=dt1)
    assert dt2 == datetime(2026, 10, 25, 1, 0, tzinfo=UTC)

    # 03:00 CET (+01:00) -> 02:00 UTC
    dt3 = next_run_at("cron", {"cron": "0 * * * *"}, "Europe/Berlin", now=dt2)
    assert dt3 == datetime(2026, 10, 25, 2, 0, tzinfo=UTC)

    # Step-minute schedule (*/15 2 * * *) fires in both occurrences of the repeated hour
    now_step = datetime(2026, 10, 24, 23, 45, tzinfo=UTC)
    step_first = next_run_at("cron", {"cron": "*/15 2 * * *"}, "Europe/Berlin", now=now_step)
    assert step_first == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)  # 02:00 CEST

    # Hour range schedule (0 0-23 * * *) is semantically hourly and fires in both occurrences
    range_dt1 = next_run_at("cron", {"cron": "0 0-23 * * *"}, "Europe/Berlin", now=now)
    assert range_dt1 == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)  # 02:00 CEST (+02:00)

    range_dt2 = next_run_at("cron", {"cron": "0 0-23 * * *"}, "Europe/Berlin", now=range_dt1)
    assert range_dt2 == datetime(2026, 10, 25, 1, 0, tzinfo=UTC)  # 02:00 CET (+01:00)

    range_dt3 = next_run_at("cron", {"cron": "0 0-23 * * *"}, "Europe/Berlin", now=range_dt2)
    assert range_dt3 == datetime(2026, 10, 25, 2, 0, tzinfo=UTC)  # 03:00 CET (+01:00)

    # Hour list schedule (0 1,2,3 * * *) also fires in both occurrences of hour 2
    list_dt1 = next_run_at("cron", {"cron": "0 1,2,3 * * *"}, "Europe/Berlin", now=now)
    assert list_dt1 == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)  # 02:00 CEST

    list_dt2 = next_run_at("cron", {"cron": "0 1,2,3 * * *"}, "Europe/Berlin", now=list_dt1)
    assert list_dt2 == datetime(2026, 10, 25, 1, 0, tzinfo=UTC)  # 02:00 CET


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
