"""Aggregate metrics computed from retrieval trace JSONL files.

This module reads persisted ``RetrievalTrace`` records (one JSON object per
line) and computes on-demand aggregate metrics over a sliding window of
recent traces.  Metrics are **read-only aggregations** — they are never
stored as running counters (RFC #1908 design decision D5).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from deerflow.agents.memory.retrieval_trace import resolve_trace_path

logger = logging.getLogger(__name__)

# Default threshold for staleness detection (days).
_DEFAULT_STALENESS_DAYS = 30


# ---------------------------------------------------------------------------
# Lookup structure for candidate metadata (replaces raw 4-tuple)
# ---------------------------------------------------------------------------


class _CandidateLookup(NamedTuple):
    """Per-trace lookup tables built from candidate metadata."""

    categories: dict[str, str]
    confidences: dict[str, float]
    created_ats: dict[str, str | None]
    selections: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RetrievalMetrics:
    """Aggregate retrieval quality metrics over a window of recent traces."""

    budget_utilization: float
    """Average ``tokens_used / max_tokens`` across the window."""

    drop_rate: float
    """Average ``dropped_count / total_candidates`` across the window."""

    correction_hit_rate: float
    """Proportion of *correction*-category candidates that were selected.

    Computed across **all** traces in the window:
    ``sum(correction_selected) / sum(correction_total)``.
    Returns 0.0 when no correction candidates exist.
    """

    category_distribution: dict[str, int]
    """Selected facts grouped by category.

    Keys are category names (e.g. ``"preference"``, ``"knowledge"``),
    values are the total number of selected facts in that category
    across the window.  Empty dict when no facts are selected.
    """

    staleness_ratio: float
    """Fraction of selected facts older than *staleness_days*.

    Returns 0.0 when no selected facts have a ``created_at`` timestamp.
    """

    confidence_floor: float
    """Lowest confidence among all selected facts across the window.

    Returns 0.0 when no facts are selected.
    """

    window_size: int
    """Number of traces actually analysed (may be < requested window)."""

    trace_count: int
    """Total number of traces found in the JSONL file."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_metrics(*, trace_count: int = 0) -> RetrievalMetrics:
    """Return a zero-valued metrics instance.

    Each call creates a **fresh** ``category_distribution`` dict so that
    callers cannot accidentally mutate a shared object.
    """
    return RetrievalMetrics(
        budget_utilization=0.0,
        drop_rate=0.0,
        correction_hit_rate=0.0,
        category_distribution={},
        staleness_ratio=0.0,
        confidence_floor=0.0,
        window_size=0,
        trace_count=trace_count,
    )


def _read_all_lines(path: Path) -> list[str]:
    """Return all non-empty lines from a text file.

    Returns an empty list when the file cannot be read.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        logger.warning("Failed to read trace file %s: %s", path, exc)
        return []

    return [line for line in lines if line.strip()]


def _parse_traces(raw_lines: list[str]) -> list[dict[str, Any]]:
    """Parse JSONL lines into trace dicts, skipping malformed entries."""
    traces: list[dict[str, Any]] = []
    for line in raw_lines:
        try:
            traces.append(json.loads(line))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("Skipping malformed trace line: %s", exc)
    return traces


def _build_lookups(traces: list[dict[str, Any]]) -> list[_CandidateLookup]:
    """Build per-trace lookup structures for candidate metadata."""
    result: list[_CandidateLookup] = []
    for trace in traces:
        candidates = trace.get("candidates", [])
        selections = trace.get("selections", [])

        categories: dict[str, str] = {}
        confidences: dict[str, float] = {}
        created_ats: dict[str, str | None] = {}

        for c in candidates:
            fid = c.get("fact_id", "")
            if fid:
                categories[fid] = c.get("category", "")
                confidences[fid] = c.get("confidence", 0.0)
                created_ats[fid] = c.get("created_at")

        result.append(_CandidateLookup(categories, confidences, created_ats, selections))
    return result


def _iter_selected(lookups: list[_CandidateLookup]) -> Iterator[tuple[str, _CandidateLookup]]:
    """Yield ``(fact_id, lookup)`` for every *selected* fact across all traces.

    This is the single iteration pattern shared by category_distribution,
    staleness_ratio, and confidence_floor.
    """
    for lookup in lookups:
        for sel in lookup.selections:
            if sel.get("included", False):
                fid = sel.get("fact_id", "")
                if fid:
                    yield fid, lookup


def _safe_avg_ratio(
    traces: list[dict[str, Any]],
    numerator_key: str,
    denominator_key: str,
) -> float:
    """Compute ``avg(numerator / denominator)`` across traces, skipping zero denominators."""
    ratios: list[float] = []
    for t in traces:
        denominator = t.get(denominator_key, 0)
        numerator = t.get(numerator_key, 0)
        if denominator > 0:
            ratios.append(numerator / denominator)
    return sum(ratios) / len(ratios) if ratios else 0.0


# ---------------------------------------------------------------------------
# Metric computations
# ---------------------------------------------------------------------------


def _compute_correction_hit_rate(lookups: list[_CandidateLookup]) -> float:
    """Compute correction_hit_rate across all traces in the window."""
    total_corrections = 0
    selected_corrections = 0

    for lookup in lookups:
        for sel in lookup.selections:
            fid = sel.get("fact_id", "")
            if lookup.categories.get(fid) == "correction":
                total_corrections += 1
                if sel.get("included", False):
                    selected_corrections += 1

    if total_corrections == 0:
        return 0.0
    return selected_corrections / total_corrections


def _compute_category_distribution(lookups: list[_CandidateLookup]) -> dict[str, int]:
    """Count selected facts grouped by category across all traces."""
    dist: dict[str, int] = {}
    for fid, lookup in _iter_selected(lookups):
        cat = lookup.categories.get(fid, "unknown")
        dist[cat] = dist.get(cat, 0) + 1
    return dist


def _compute_staleness_ratio(
    lookups: list[_CandidateLookup],
    staleness_days: int,
) -> float:
    """Fraction of selected facts with created_at older than *staleness_days*."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=staleness_days)

    total_with_date = 0
    stale_count = 0

    for fid, lookup in _iter_selected(lookups):
        created_at_str = lookup.created_ats.get(fid)
        if not created_at_str:
            continue
        try:
            # Support both "Z" suffix and "+00:00" formats.
            ts_str = created_at_str.replace("Z", "+00:00")
            created_dt = datetime.fromisoformat(ts_str)
            total_with_date += 1
            if created_dt < cutoff:
                stale_count += 1
        except (ValueError, TypeError):
            continue

    if total_with_date == 0:
        return 0.0
    return stale_count / total_with_date


def _compute_confidence_floor(lookups: list[_CandidateLookup]) -> float:
    """Lowest confidence among all selected facts across the window."""
    min_confidence: float | None = None
    for fid, lookup in _iter_selected(lookups):
        conf = lookup.confidences.get(fid)
        if conf is not None:
            if min_confidence is None or conf < min_confidence:
                min_confidence = conf
    return min_confidence if min_confidence is not None else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_retrieval_metrics(
    trace_path: Path | None = None,
    window: int = 50,
    staleness_days: int = _DEFAULT_STALENESS_DAYS,
) -> RetrievalMetrics:
    """Read the last *window* traces from a JSONL file and compute metrics.

    Args:
        trace_path: Explicit path to the JSONL trace file.  When ``None``,
            the default path is resolved via
            :func:`~deerflow.agents.memory.retrieval_trace.resolve_trace_path`.
        window: Number of most-recent traces to include in the aggregation.
        staleness_days: Facts older than this many days are considered stale
            for ``staleness_ratio`` computation.  Defaults to 30.

    Returns:
        A :class:`RetrievalMetrics` instance.  All ratio fields are ``0.0``
        when there are no traces to analyse.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    path = trace_path if trace_path is not None else resolve_trace_path()

    if not path.exists():
        return _empty_metrics()

    all_lines = _read_all_lines(path)
    total_line_count = len(all_lines)

    if not all_lines:
        return _empty_metrics()

    # Take the last `window` lines for metrics computation.
    windowed_lines = all_lines[-window:]
    traces = _parse_traces(windowed_lines)

    if not traces:
        return _empty_metrics(trace_count=total_line_count)

    # Build shared lookup structures (avoids redundant iteration).
    lookups = _build_lookups(traces)

    return RetrievalMetrics(
        budget_utilization=_safe_avg_ratio(traces, "tokens_used", "max_tokens"),
        drop_rate=_safe_avg_ratio(traces, "dropped_count", "total_candidates"),
        correction_hit_rate=_compute_correction_hit_rate(lookups),
        category_distribution=_compute_category_distribution(lookups),
        staleness_ratio=_compute_staleness_ratio(lookups, staleness_days),
        confidence_floor=_compute_confidence_floor(lookups),
        window_size=len(traces),
        trace_count=total_line_count,
    )
