"""Boundary tests for the two schedule_spec mappings, run against both.

`schedule_spec` crosses two boundaries -- an HTTP body field and a JSON column
-- and each side owns its own translation, because a primary adapter must not
import a secondary one. The shapes are equal today only by coincidence.

Coincidence is exactly what needs a test. Every case here runs against both
implementations, so the day one side is changed without the other, this file
fails instead of production accepting a spec the repository cannot read back.
That is the same N-cases-x-2-implementations shape `test_schedule_fakes.py`
uses for the repository ports.

The split each side enforces is the point: **structural** problems (key
missing, wrong type, unknown schedule type) are caught at the boundary,
**value** problems (5-field cron, resolvable timezone) are left to
`ScheduleSpec.__post_init__` -- and both surface as the same domain error, so
the router maps one family.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.schedule.spec_column import column_to_spec, spec_to_column
from app.gateway.routers.schedule.spec_wire import spec_to_wire, wire_to_spec
from deerflow.domain.schedule.model import InvalidScheduleError, ScheduleSpec, ScheduleType


@pytest.fixture(
    params=[
        pytest.param((column_to_spec, spec_to_column), id="column"),
        pytest.param((wire_to_spec, spec_to_wire), id="wire"),
    ]
)
def mapping(request):
    """The (parse, emit) pair under test, once per boundary."""
    return request.param


@pytest.fixture
def parse(mapping):
    return mapping[0]


@pytest.fixture
def emit(mapping):
    return mapping[1]


class TestStructuralChecks:
    def test_unknown_schedule_type_is_rejected(self, parse):
        """The one rule the domain cannot state: ScheduleSpec only accepts the
        enum, so a bad string has to be caught at the boundary."""
        with pytest.raises(InvalidScheduleError, match="Unsupported schedule_type"):
            parse("teleport", {"cron": "0 9 * * *"}, "UTC")

    @pytest.mark.parametrize("spec", [{}, None, {"cron": 5}, {"run_at": "..."}])
    def test_cron_without_a_string_cron_is_rejected(self, parse, spec):
        with pytest.raises(InvalidScheduleError, match="requires schedule_spec"):
            parse("cron", spec, "UTC")

    @pytest.mark.parametrize("spec", [{}, None, {"run_at": 5}, {"cron": "0 9 * * *"}])
    def test_once_without_a_string_run_at_is_rejected(self, parse, spec):
        with pytest.raises(InvalidScheduleError, match="requires run_at"):
            parse("once", spec, "UTC")

    def test_an_unparseable_run_at_is_rejected(self, parse):
        with pytest.raises(InvalidScheduleError, match="unparseable run_at"):
            parse("once", {"run_at": "next tuesday"}, "UTC")


class TestValueChecksStayInTheDomain:
    """These are not re-implemented on either side -- they arrive from
    __post_init__, which is why each boundary can stay thin and why the
    duplication between them is bounded."""

    def test_a_bad_cron_expression_still_raises(self, parse):
        with pytest.raises(InvalidScheduleError, match="exactly 5 fields"):
            parse("cron", {"cron": "0 9 * *"}, "UTC")

    def test_a_bad_timezone_still_raises(self, parse):
        with pytest.raises(InvalidScheduleError, match="Unknown timezone"):
            parse("cron", {"cron": "0 9 * * *"}, "Mars/Olympus_Mons")


class TestRoundTrip:
    def test_cron_round_trips_normalized(self, parse, emit):
        spec = parse("cron", {"cron": "  0  9 * * * "}, "Asia/Shanghai")
        assert spec.schedule_type is ScheduleType.CRON
        assert emit(spec) == {"cron": "0 9 * * *"}
        assert parse("cron", emit(spec), "Asia/Shanghai") == spec

    def test_once_round_trips_to_the_same_instant(self, parse, emit):
        spec = parse("once", {"run_at": "2026-08-01T09:00:00"}, "Asia/Shanghai")
        assert spec.run_at == datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
        assert parse("once", emit(spec), "Asia/Shanghai") == spec

    def test_a_trailing_z_input_parses_and_re_emits_as_an_offset(self, parse, emit):
        """The shape the frontend actually submits (`zonedLocalToUtcIso`).
        Both spellings parse on either side, so normalizing is deliberate."""
        spec = parse("once", {"run_at": "2026-08-01T01:00:00Z"}, "Asia/Shanghai")
        emitted = emit(spec)["run_at"]
        assert emitted.endswith("+00:00")
        assert parse("once", {"run_at": emitted}, "Asia/Shanghai") == spec

    def test_emitted_output_is_idempotent(self, parse, emit):
        spec = ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0, tzinfo=UTC), "UTC")
        once = emit(spec)
        assert emit(parse("once", once, "UTC")) == once


class TestCrossBoundaryParity:
    """The two sides must agree, not merely each be self-consistent.

    The cases above run against both and would catch a behavioural drift;
    these compare the outputs directly, which is what catches a *silent* one --
    a side that starts emitting a different but still-self-consistent shape.
    """

    @pytest.mark.parametrize(
        ("schedule_type", "spec", "timezone"),
        [
            ("cron", {"cron": "0 9 * * *"}, "UTC"),
            ("cron", {"cron": "  30 2 * * 1 "}, "Asia/Shanghai"),
            ("once", {"run_at": "2026-08-01T09:00:00"}, "Asia/Shanghai"),
            ("once", {"run_at": "2026-08-01T01:00:00Z"}, "UTC"),
        ],
    )
    def test_both_sides_parse_to_the_same_value_object(self, schedule_type, spec, timezone):
        assert column_to_spec(schedule_type, spec, timezone) == wire_to_spec(schedule_type, spec, timezone)

    @pytest.mark.parametrize(
        "spec",
        [
            ScheduleSpec.cron_schedule("0 9 * * *", "UTC"),
            ScheduleSpec.once_at(datetime(2026, 8, 1, 9, 0, tzinfo=UTC), "Asia/Shanghai"),
        ],
    )
    def test_both_sides_emit_the_same_shape(self, spec):
        assert spec_to_column(spec) == spec_to_wire(spec)

    @pytest.mark.parametrize(
        ("schedule_type", "spec"),
        [
            ("teleport", {"cron": "0 9 * * *"}),
            ("cron", {}),
            ("cron", {"cron": 5}),
            ("once", {}),
            ("once", {"run_at": 5}),
            ("once", {"run_at": "next tuesday"}),
        ],
    )
    def test_both_sides_reject_the_same_inputs_with_the_same_message(self, schedule_type, spec):
        """Same message, not just same type: the router turns this text into a
        422 detail, so a divergence here is user-visible."""
        with pytest.raises(InvalidScheduleError) as from_column:
            column_to_spec(schedule_type, spec, "UTC")
        with pytest.raises(InvalidScheduleError) as from_wire:
            wire_to_spec(schedule_type, spec, "UTC")
        assert str(from_column.value) == str(from_wire.value)
