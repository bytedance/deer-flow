#!/usr/bin/env python3
"""Summarize paired full/delta production-benchmark JSONL results.

Full rows carry snapshot_frequency=None; each delta frequency group pairs
against the full row at the same (turns, payload_bytes, repetition). Ratios
are always delta/full. Decision metrics: snapshot_write_spike (delta
checkpoint_write p99/p50), cache_effect_ms (state cold - warm p50), and
checkpoint_write_share (checkpoint_write p50 / run_turn p50). Unless
--metrics is given, history_limit_*_cold_ms / history_limit_*_warm_p50_ms
fields found in the input rows are appended to the default metric list.

Example::

    python scripts/benchmark/checkpoint/summarize_production.py results.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_METRICS = [
    "run_turn_p50_ms",
    "run_turn_p95_ms",
    "checkpoint_write_p50_ms",
    "checkpoint_write_p95_ms",
    "state_cold_ms",
    "state_warm_p50_ms",
    "state_warm_p95_ms",
    "db_bytes",
    "peak_rss_bytes",
]

_GROUP_FIELDS = ("turns", "payload_bytes", "snapshot_frequency")

# checkpoint_bench_common.py is a sibling script file, not a package (see its
# docstring) -- the same sys.path-insert-then-import pattern bench_channels.py
# and bench_production.py already use, reused here so JSONL reading and table
# reporting have one implementation for the whole checkpoint benchmark family.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkpoint_bench_common as _common  # noqa: E402

_INPUT_INDEX_FIELD = _common.INPUT_INDEX_FIELD
_load_jsonl = _common.load_jsonl
_numeric = _common.numeric_value


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    return _common.table_columns(rows, _GROUP_FIELDS)


def _print_table(rows: list[dict[str, Any]]) -> None:
    _common.print_table(rows, _GROUP_FIELDS)


_HISTORY_METRIC_RE = re.compile(r"history_limit_(\d+)_(?:cold_ms|warm_p50_ms)")


def _discover_history_metrics(rows: list[dict[str, Any]]) -> list[str]:
    """Auto-discover per-limit history metrics present in the input rows."""
    discovered = {key for row in rows for key in row if _HISTORY_METRIC_RE.fullmatch(key)}
    return sorted(discovered, key=lambda key: (int(_HISTORY_METRIC_RE.fullmatch(key).group(1)), key))  # type: ignore[union-attr]


def _medians(rows: list[dict[str, Any]], metric: str) -> float | None:
    values = [v for row in rows if (v := _numeric(row, metric)) is not None]
    return statistics.median(values) if values else None


def _summarize(rows: list[dict[str, Any]], *, metrics: list[str]) -> list[dict[str, Any]]:
    # Full rows are frequency-less; index them for broadcast pairing.
    full_rows: dict[tuple, dict[str, Any]] = {}
    delta_groups: dict[tuple, dict[tuple, dict[str, Any]]] = defaultdict(dict)
    failed_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("profiled"):
            continue
        if not row.get("success"):
            failed_rows.append(row)
            continue
        rep_key = (row.get(_INPUT_INDEX_FIELD), row.get("repetition"), row.get("turns"), row.get("payload_bytes"))
        if row.get("mode") == "full":
            full_rows[rep_key] = row
        elif row.get("mode") == "delta":
            group_key = tuple(row.get(field) for field in _GROUP_FIELDS)
            delta_groups[group_key][rep_key] = row

    summaries: list[dict[str, Any]] = []
    for group_key in sorted(delta_groups, key=str):
        deltas = delta_groups[group_key]
        pairs = [(full_rows[k], d) for k, d in deltas.items() if k in full_rows]
        if not pairs:
            continue
        summary: dict[str, Any] = {field: group_key[index] for index, field in enumerate(_GROUP_FIELDS)}
        summary["paired_repetitions"] = len(pairs)
        # Per-group failures: a failed delta row counts toward the group whose
        # (turns, payload_bytes, snapshot_frequency) it matches; a failed full
        # row (frequency-less) counts toward every group at the same
        # (turns, payload_bytes).
        summary["failed_rows"] = sum(1 for row in failed_rows if row.get("turns") == group_key[0] and row.get("payload_bytes") == group_key[1] and (row.get("snapshot_frequency") is None or row.get("snapshot_frequency") == group_key[2]))
        full_pair_rows = [pair[0] for pair in pairs]
        delta_pair_rows = [pair[1] for pair in pairs]
        for metric in metrics:
            full_median = _medians(full_pair_rows, metric)
            delta_median = _medians(delta_pair_rows, metric)
            if full_median is None or delta_median is None:
                continue
            summary[f"full_{metric}"] = round(full_median, 6)
            summary[f"delta_{metric}"] = round(delta_median, 6)
            summary[f"ratio_{metric}"] = round(delta_median / full_median, 6) if full_median != 0 else None
        for label, group_rows in (("full", full_pair_rows), ("delta", delta_pair_rows)):
            p50 = _medians(group_rows, "checkpoint_write_p50_ms")
            p99 = _medians(group_rows, "checkpoint_write_p99_ms")
            run_p50 = _medians(group_rows, "run_turn_p50_ms")
            cold = _medians(group_rows, "state_cold_ms")
            warm = _medians(group_rows, "state_warm_p50_ms")
            if p50 and p99 is not None:
                summary[f"{label}_snapshot_write_spike"] = round(p99 / p50, 6)
            if p50 is not None and run_p50:
                summary[f"{label}_checkpoint_write_share"] = round(p50 / run_p50, 6)
            if cold is not None and warm is not None:
                summary[f"{label}_cache_effect_ms"] = round(cold - warm, 6)
        summaries.append(summary)
    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize production-shaped checkpoint benchmark results")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--metrics", default=None, help="comma-separated metric fields; defaults to the built-in list plus auto-discovered history_limit_* metrics")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--csv", action="store_true")
    args = parser.parse_args(argv)

    try:
        rows = _load_jsonl(args.inputs)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.metrics is None:
        metrics = [*DEFAULT_METRICS, *_discover_history_metrics(rows)]
    else:
        metrics = [metric.strip() for metric in args.metrics.split(",") if metric.strip()]
        if not metrics:
            parser.error("--metrics must contain at least one field")
    summaries = _summarize(rows, metrics=metrics)
    if args.json:
        json.dump(summaries, sys.stdout, ensure_ascii=False, indent=2)
        print()
    elif args.csv:
        writer = csv.DictWriter(sys.stdout, fieldnames=_columns(summaries), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)
    else:
        _print_table(summaries)
    return 0 if summaries else 1


if __name__ == "__main__":
    raise SystemExit(main())
