#!/usr/bin/env python3
"""Summarize paired full/delta checkpoint benchmark JSONL results.

Only repetitions with one successful ``full`` row and one successful ``delta``
row enter metric medians. This prevents a failed or missing mode from turning
different workloads into a misleading ratio. Ratios are always ``delta/full``:
values below 1 mean delta used less time or storage.

Examples::

    python scripts/benchmark/checkpoint/summarize_channels.py results.jsonl
    python scripts/benchmark/checkpoint/summarize_channels.py results/*.jsonl --json
    python scripts/benchmark/checkpoint/summarize_channels.py results.jsonl \
        --metrics write_total_ms,cold_read_ms,logical_checkpoint_bytes --csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_METRICS = [
    "write_total_ms",
    "write_p50_ms",
    "write_p95_ms",
    "write_last_window_ms",
    "warm_read_ms",
    "cold_read_ms",
    "checkpoint_rows",
    "checkpoint_bytes",
    "blob_rows",
    "blob_bytes",
    "write_rows",
    "write_bytes",
    "logical_checkpoint_bytes",
    "logical_write_bytes",
    "durable_db_bytes",
    "reducer_replay_ms",
    "peak_rss_bytes",
]

_GROUP_FIELDS = (
    "backend",
    "scenario",
    "snapshot_frequency",
    "update_count",
    "payload_bytes",
)

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


def _group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in _GROUP_FIELDS)


def _group_sort_key(key: tuple[Any, ...]) -> tuple[tuple[int, Any], ...]:
    return tuple((0, value) if isinstance(value, (int, float)) and not isinstance(value, bool) else (1, str(value)) for value in key)


def _summarize(rows: list[dict[str, Any]], *, metrics: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("profiled"):
            continue
        groups[_group_key(row)].append(row)

    summaries: list[dict[str, Any]] = []
    for key, group in sorted(groups.items(), key=lambda item: _group_sort_key(item[0])):
        by_repetition: dict[Any, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in group:
            if row.get("success") and row.get("mode") in {"full", "delta"}:
                repetition_key = (row.get(_INPUT_INDEX_FIELD), row.get("repetition"))
                by_repetition[repetition_key][row["mode"]] = row
        pairs = [pair for pair in by_repetition.values() if "full" in pair and "delta" in pair]
        if not pairs:
            continue

        summary: dict[str, Any] = {field: key[index] for index, field in enumerate(_GROUP_FIELDS)}
        summary["paired_repetitions"] = len(pairs)
        summary["failed_rows"] = sum(1 for row in group if not row.get("success"))
        for metric in metrics:
            full_values: list[float] = []
            delta_values: list[float] = []
            for pair in pairs:
                full_value = _numeric(pair["full"], metric)
                delta_value = _numeric(pair["delta"], metric)
                if full_value is None or delta_value is None:
                    continue
                full_values.append(full_value)
                delta_values.append(delta_value)
            if not full_values:
                continue
            full_median = statistics.median(full_values)
            delta_median = statistics.median(delta_values)
            summary[f"full_{metric}"] = round(full_median, 6)
            summary[f"delta_{metric}"] = round(delta_median, 6)
            summary[f"ratio_{metric}"] = round(delta_median / full_median, 6) if full_median != 0 else None
        summaries.append(summary)
    return summaries


def _print_csv(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=_columns(rows), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize paired full/delta checkpoint benchmark results")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--metrics", default=",".join(DEFAULT_METRICS), help="Comma-separated numeric result fields")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--csv", action="store_true")
    args = parser.parse_args(argv)

    metrics = [metric.strip() for metric in args.metrics.split(",") if metric.strip()]
    if not metrics:
        parser.error("--metrics must contain at least one field")
    try:
        rows = _load_jsonl(args.inputs)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    profiled_rows = sum(1 for row in rows if row.get("profiled"))
    if profiled_rows:
        print(f"Skipping {profiled_rows} profiled row(s); profiled timings are excluded from baseline summaries.", file=sys.stderr)
    summaries = _summarize(rows, metrics=metrics)
    if args.json:
        json.dump(summaries, sys.stdout, ensure_ascii=False, indent=2)
        print()
    elif args.csv:
        _print_csv(summaries)
    else:
        _print_table(summaries)
    return 0 if summaries else 1


if __name__ == "__main__":
    raise SystemExit(main())
