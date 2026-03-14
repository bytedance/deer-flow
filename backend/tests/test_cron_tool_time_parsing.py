"""Tests for cron tool time parsing edge cases."""

import importlib
from datetime import datetime

cron_tool_module = importlib.import_module("deerflow.tools.builtins.cron_tool")


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 3, 13, 0, 7, 16)
        if tz is not None:
            return base.replace(tzinfo=tz)
        return base


def test_parse_time_to_ms_supports_same_day_clock_time(monkeypatch):
    monkeypatch.setattr(cron_tool_module, "datetime", _FrozenDatetime)

    parsed = cron_tool_module._parse_time_to_ms("00:08")

    assert parsed == int(_FrozenDatetime(2026, 3, 13, 0, 8, 0).timestamp() * 1000)


def test_parse_time_to_ms_rolls_to_next_day_when_clock_time_has_passed(monkeypatch):
    class _LateFrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = cls(2026, 3, 13, 0, 9, 0)
            if tz is not None:
                return base.replace(tzinfo=tz)
            return base

    monkeypatch.setattr(cron_tool_module, "datetime", _LateFrozenDatetime)

    parsed = cron_tool_module._parse_time_to_ms("00:08")

    assert parsed == int(_LateFrozenDatetime(2026, 3, 14, 0, 8, 0).timestamp() * 1000)
