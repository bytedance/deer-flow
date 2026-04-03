"""Tests for cron tool time parsing edge cases."""

import importlib
from datetime import datetime, timedelta, timezone

cron_tool_module = importlib.import_module("deerflow.tools.builtins.cron_tool")
FIXED_TZ = timezone(timedelta(hours=8))


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 3, 13, 0, 7, 16, tzinfo=FIXED_TZ)
        if tz is not None:
            return base.astimezone(tz)
        return base

    def astimezone(self, tz=None):
        return super().astimezone(FIXED_TZ if tz is None else tz)


def test_parse_time_to_ms_supports_same_day_clock_time(monkeypatch):
    monkeypatch.setattr(cron_tool_module, "datetime", _FrozenDatetime)

    parsed = cron_tool_module._parse_time_to_ms("00:08")
    now = _FrozenDatetime.now().astimezone()
    expected = now.replace(hour=0, minute=8, second=0, microsecond=0)

    assert parsed == int(expected.timestamp() * 1000)


def test_parse_time_to_ms_rolls_to_next_day_when_clock_time_has_passed(monkeypatch):
    class _LateFrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = cls(2026, 3, 13, 0, 9, 0, tzinfo=FIXED_TZ)
            if tz is not None:
                return base.astimezone(tz)
            return base

        def astimezone(self, tz=None):
            return super().astimezone(FIXED_TZ if tz is None else tz)

    monkeypatch.setattr(cron_tool_module, "datetime", _LateFrozenDatetime)

    parsed = cron_tool_module._parse_time_to_ms("00:08")
    now = _LateFrozenDatetime.now().astimezone()
    expected = now.replace(hour=0, minute=8, second=0, microsecond=0)
    if expected <= now:
        expected += timedelta(days=1)

    assert parsed == int(expected.timestamp() * 1000)
