"""Trigger types for scheduled jobs.

Three trigger shapes are supported, discriminated by ``type``:

- ``AtTrigger``: one-shot absolute time (ISO 8601, epoch ms, or relative
  duration like ``"20m"``). Returns ``None`` from ``compute_next`` after
  the first run.
- ``EveryTrigger``: fixed interval in seconds, optionally anchored to a
  specific epoch-ms timestamp. Uses the anchor (not last_run_at) so
  restarts don't drift the schedule.
- ``CronTrigger``: standard 5-field cron expression with optional
  timezone and per-job stagger window.

All triggers implement the ``Trigger`` protocol and round-trip through
``to_dict`` / ``from_dict`` for JSON persistence in
``scheduled_jobs.trigger_data``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from deerflow.scheduler.cron_parser import (
    compute_next_cron,
    is_recurring_top_of_hour,
    parse_cron_expr,
)
from deerflow.scheduler.stagger import DEFAULT_TOP_OF_HOUR_STAGGER_MS, stable_offset_ms
from deerflow.scheduler.time_parser import is_relative_duration, parse_time_expr

logger = logging.getLogger(__name__)


# Minimum interval for EveryTrigger — prevents runaway loops.
MIN_EVERY_SECONDS: int = 30


@runtime_checkable
class Trigger(Protocol):
    """A scheduling trigger.

    Implementations must be JSON-serialisable via ``to_dict`` /
    ``from_dict``. ``compute_next`` is pure: it must not depend on
    external state, only on ``last_run``, ``now``, and ``job_id``.
    """

    type: str

    def compute_next(
        self,
        last_run: datetime | None,
        *,
        now: datetime,
        job_id: str = "",
    ) -> datetime | None:
        """Return the next run time strictly after ``last_run``.

        Return ``None`` when the trigger will never fire again (one-shot
        triggers after first run).
        """
        ...

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Trigger: ...

    def human_readable(self) -> str:
        """User-facing description, e.g. ``"every day at 09:00"``."""
        ...


# ---------------------------------------------------------------------------
# AtTrigger
# ---------------------------------------------------------------------------


class AtTrigger:
    """One-shot trigger that fires once at a specific absolute time.

    The constructor accepts either a ``datetime`` or a string (ISO 8601,
    epoch ms, or relative duration like ``"20m"``). Relative durations
    are resolved against the current UTC time at construction.

    After firing once, ``compute_next`` returns ``None`` permanently.
    """

    type: str = "at"

    def __init__(self, at: datetime | str) -> None:
        if isinstance(at, datetime):
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            self.at_time: datetime = at
            self._at_input: str = at.isoformat()
        else:
            self.at_time = parse_time_expr(at)
            self._at_input = at

    def compute_next(self, last_run: datetime | None, *, now: datetime, job_id: str = "") -> datetime | None:
        # Already fired → never again
        if last_run is not None:
            return None
        # In the past relative to now → still return it; the scheduler
        # decides whether to fire immediately or skip. This keeps the
        # trigger pure (a function of inputs).
        return self.at_time

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "at", "at": self._at_input}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AtTrigger:
        return cls(at=data["at"])

    def human_readable(self) -> str:
        return f"once at {self.at_time.isoformat()}"


# ---------------------------------------------------------------------------
# EveryTrigger
# ---------------------------------------------------------------------------


class EveryTrigger:
    """Fixed-interval trigger.

    ``every_seconds`` must be >= ``MIN_EVERY_SECONDS`` (30). ``anchor_ms``
    is an optional epoch-millisecond timestamp that anchors the schedule
    so that scheduler restarts don't drift the cadence; when omitted,
    the trigger falls back to ``last_run + every_seconds`` (or
    ``now + every_seconds`` on first run).
    """

    type: str = "every"

    def __init__(self, seconds: int, anchor_ms: int | None = None) -> None:
        if seconds < MIN_EVERY_SECONDS:
            raise ValueError(f"every interval must be >= {MIN_EVERY_SECONDS}s (got {seconds}s)")
        self.every_seconds = int(seconds)
        self.anchor_ms = anchor_ms

    def _anchor_dt(self, fallback: datetime) -> datetime:
        if self.anchor_ms is None:
            return fallback
        return datetime.fromtimestamp(self.anchor_ms / 1000.0, tz=UTC)

    def compute_next(self, last_run: datetime | None, *, now: datetime, job_id: str = "") -> datetime | None:
        # No anchor → simple "last_run + interval" cadence (or "now +
        # interval" for first run). Drift across restarts is acceptable
        # because the user did not pin a schedule.
        if self.anchor_ms is None:
            base = last_run or now
            if base.tzinfo is None:
                base = base.replace(tzinfo=UTC)
            return base + timedelta(seconds=self.every_seconds)

        # Anchored schedule: compute the next slot aligned to the anchor.
        anchor = self._anchor_dt(now)
        if now < anchor:
            return anchor

        # Use last_run if available, otherwise now. Using ``now`` (not
        # anchor) for first-run ensures we skip already-missed historical
        # slots rather than scheduling a run in the past.
        base = last_run or now
        if base.tzinfo is None:
            base = base.replace(tzinfo=UTC)
        elapsed = (base - anchor).total_seconds()
        steps = int(elapsed // self.every_seconds) + 1
        next_dt = anchor + timedelta(seconds=steps * self.every_seconds)
        # Guarantee strictly-after last_run
        if last_run is not None and next_dt <= last_run:
            next_dt = last_run + timedelta(seconds=self.every_seconds)
        return next_dt

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": "every",
            "every_seconds": self.every_seconds,
        }
        if self.anchor_ms is not None:
            data["anchor_ms"] = self.anchor_ms
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EveryTrigger:
        return cls(
            seconds=int(data["every_seconds"]),
            anchor_ms=int(data["anchor_ms"]) if data.get("anchor_ms") is not None else None,
        )

    def human_readable(self) -> str:
        if self.every_seconds >= 3600 and self.every_seconds % 3600 == 0:
            hours = self.every_seconds // 3600
            return f"every {hours} hour{'s' if hours > 1 else ''}"
        if self.every_seconds >= 60 and self.every_seconds % 60 == 0:
            minutes = self.every_seconds // 60
            return f"every {minutes} minute{'s' if minutes > 1 else ''}"
        return f"every {self.every_seconds} seconds"


# ---------------------------------------------------------------------------
# CronTrigger
# ---------------------------------------------------------------------------


class CronTrigger:
    """5-field cron trigger with timezone and optional stagger.

    ``stagger_ms`` controls per-job jitter applied to the next-run
    timestamp:

    - ``None``: auto — apply default 5-minute stagger only to recurring
      top-of-hour expressions (``0 * * * *``, ``0 */N * * *``)
    - ``0``: disable staggering (run exactly on schedule)
    - ``> 0``: explicit stagger window in milliseconds
    """

    type: str = "cron"

    def __init__(
        self,
        expr: str,
        tz: str = "UTC",
        stagger_ms: int | None = None,
    ) -> None:
        self.expr = expr
        self.tz = tz
        self.stagger_ms = stagger_ms
        self._fields = parse_cron_expr(expr)

    @property
    def fields(self) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
        return self._fields  # type: ignore[return-value]

    def _resolved_stagger_ms(self) -> int:
        if self.stagger_ms is not None:
            return self.stagger_ms
        if is_recurring_top_of_hour(self._fields):
            return DEFAULT_TOP_OF_HOUR_STAGGER_MS
        return 0

    def _apply_stagger(self, base: datetime, job_id: str) -> datetime:
        stagger_ms = self._resolved_stagger_ms()
        if stagger_ms <= 1:
            return base
        offset_ms = stable_offset_ms(job_id, stagger_ms)
        return base + timedelta(milliseconds=offset_ms)

    def compute_next(
        self,
        last_run: datetime | None,
        *,
        now: datetime,
        job_id: str = "",
    ) -> datetime | None:
        base_next = compute_next_cron(self._fields, last_run or now, self.tz)
        if base_next is None:
            return None
        return self._apply_stagger(base_next, job_id)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": "cron", "expr": self.expr, "tz": self.tz}
        if self.stagger_ms is not None:
            data["stagger_ms"] = self.stagger_ms
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronTrigger:
        return cls(
            expr=data["expr"],
            tz=data.get("tz", "UTC"),
            stagger_ms=int(data["stagger_ms"]) if data.get("stagger_ms") is not None else None,
        )

    def human_readable(self) -> str:
        return f"cron {self.expr!r} ({self.tz})"


# ---------------------------------------------------------------------------
# Convenience: dispatch helpers
# ---------------------------------------------------------------------------


_TRIGGER_CLASSES: dict[str, type[Trigger]] = {
    "at": AtTrigger,
    "every": EveryTrigger,
    "cron": CronTrigger,
}


def trigger_from_dict(data: dict[str, Any]) -> Trigger:
    """Reconstruct a Trigger from its persisted dict form.

    ``data`` must contain a ``kind`` field set to ``"at"`` / ``"every"`` /
    ``"cron"``.
    """
    kind = data.get("kind")
    if kind not in _TRIGGER_CLASSES:
        raise ValueError(f"unknown trigger kind: {kind!r}")
    cls = _TRIGGER_CLASSES[kind]
    return cls.from_dict(data)  # type: ignore[attr-defined]


def trigger_from_persisted(trigger_type: str, trigger_data: dict[str, Any]) -> Trigger:
    """Reconstruct from the (trigger_type, trigger_data) pair stored in
    ``scheduled_jobs``. The ``kind`` field inside ``trigger_data`` is
    authoritative; ``trigger_type`` is the column value used for indexing.
    """
    # Defensive: some writers may store trigger_data without an explicit
    # ``kind``. Fall back to the trigger_type column.
    data = dict(trigger_data)
    if "kind" not in data:
        data["kind"] = trigger_type
    return trigger_from_dict(data)


def parse_user_when(when: str, *, tz: str = "UTC") -> Trigger:
    """Parse a free-form user string into the right Trigger subclass.

    Heuristics:

    - ``"every <duration>"`` (e.g. ``"every 5m"``, ``"every 1h"``) → EveryTrigger
    - 5 whitespace-separated tokens → CronTrigger
    - Relative duration alone (``"20m"``, ``"1h"``) → AtTrigger
    - ISO 8601 / epoch ms → AtTrigger
    """
    raw = when.strip()
    if not raw:
        raise ValueError("empty schedule expression")

    lower = raw.lower()
    if lower.startswith("every "):
        rest = raw[len("every ") :].strip()
        if not is_relative_duration(rest):
            raise ValueError(f"invalid 'every' interval: {rest!r}")
        # Reuse the relative-duration parser to extract seconds.
        from deerflow.scheduler.time_parser import parse_relative_duration

        duration = parse_relative_duration(rest)
        seconds = int(duration.total_seconds())
        return EveryTrigger(seconds=seconds)

    if len(raw.split()) == 5:
        return CronTrigger(expr=raw, tz=tz)

    # Default: treat as a one-shot AtTrigger (relative or absolute)
    return AtTrigger(at=raw)
