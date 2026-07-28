"""Boundary tests for the schedule_spec mapping.

This is where a `Mapping[str, Any]` is allowed to exist. The split it enforces
is the point: **structural** problems (key missing, wrong type, unknown
schedule type) are caught here, **value** problems (5-field cron, resolvable
timezone) are left to `ScheduleSpec.__post_init__` -- and both surface as the
same domain error, so the router maps one family.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.infra.schedule.spec_mapping import spec_to_domain, spec_to_wire
from deerflow.domain.schedule.model import InvalidScheduleError, ScheduleSpec, ScheduleType


class TestStructuralChecks:
    def test_unknown_schedule_type_is_rejected(self):
        """The one rule the domain cannot state: ScheduleSpec only accepts the
        enum, so a bad string has to be caught at the boundary."""
        with pytest.raises(InvalidScheduleError, match="Unsupported schedule_type"):
            spec_to_domain("teleport", {"cron": "0 9 * * *"}, "UTC")

    @pytest.mark.parametrize("spec", [{}, None, {"cron": 5}, {"run_at": "..."}])
    def test_cron_without_a_string_cron_is_rejected(self, spec):
        with pytest.raises(InvalidScheduleError, match="requires schedule_spec"):
            spec_to_domain("cron", spec, "UTC")

    @pytest.mark.parametrize("spec", [{}, None, {"run_at": 5}, {"cron": "0 9 * * *"}])
    def test_once_without_a_string_run_at_is_rejected(self, spec):
        with pytest.raises(InvalidScheduleError, match="requires run_at"):
            spec_to_domain("once", spec, "UTC")

    def test_an_unparseable_run_at_is_rejected(self):
        with pytest.raises(InvalidScheduleError, match="unparseable run_at"):
            spec_to_domain("once", {"run_at": "next tuesday"}, "UTC")


class TestValueChecksStayInTheDomain:
    """These are not re-implemented here -- they arrive from __post_init__,
    which is why the boundary can stay thin."""

    def test_a_bad_cron_expression_still_raises(self):
        with pytest.raises(InvalidScheduleError, match="exactly 5 fields"):
            spec_to_domain("cron", {"cron": "0 9 * *"}, "UTC")

    def test_a_bad_timezone_still_raises(self):
        with pytest.raises(InvalidScheduleError, match="Unknown timezone"):
            spec_to_domain("cron", {"cron": "0 9 * * *"}, "Mars/Olympus_Mons")


class TestRoundTrip:
    def test_cron_round_trips_normalized(self):
        spec = spec_to_domain("cron", {"cron": "  0  9 * * * "}, "Asia/Shanghai")
        assert spec.schedule_type is ScheduleType.CRON
        assert spec_to_wire(spec) == {"cron": "0 9 * * *"}
        assert spec_to_domain("cron", spec_to_wire(spec), "Asia/Shanghai") == spec

    def test_once_round_trips_to_the_same_instant(self):
        spec = spec_to_domain("once", {"run_at": "2026-08-01T09:00:00"}, "Asia/Shanghai")
        assert spec.run_at == datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
        assert spec_to_domain("once", spec_to_wire(spec), "Asia/Shanghai") == spec

    def test_a_trailing_z_input_parses_and_re_emits_as_an_offset(self):
        """The shape the frontend actually submits (`zonedLocalToUtcIso`).
        Both spellings parse on either side, so normalizing is deliberate."""
        spec = spec_to_domain("once", {"run_at": "2026-08-01T01:00:00Z"}, "Asia/Shanghai")
        emitted = spec_to_wire(spec)["run_at"]
        assert emitted.endswith("+00:00")
        assert spec_to_domain("once", {"run_at": emitted}, "Asia/Shanghai") == spec

    def test_wire_output_is_idempotent(self):
        spec = ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0, tzinfo=UTC), "UTC")
        once = spec_to_wire(spec)
        assert spec_to_wire(spec_to_domain("once", once, "UTC")) == once
