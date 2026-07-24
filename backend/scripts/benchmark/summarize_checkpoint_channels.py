#!/usr/bin/env python3
"""Summarize paired full/delta checkpoint benchmark JSONL results.

Only repetitions with one successful ``full`` row and one successful ``delta``
row enter metric medians. This prevents a failed or missing mode from turning
different workloads into a misleading ratio. Ratios are always ``delta/full``:
values below 1 mean delta used less time or storage.

Examples::

    python scripts/benchmark/summarize_checkpoint_channels.py results.jsonl
    python scripts/benchmark/summarize_checkpoint_channels.py results/*.jsonl --json
    python scripts/benchmark/summarize_checkpoint_channels.py results.jsonl \
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
_INPUT_INDEX_FIELD = "_benchmark_input_index"


def _load_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for input_index, path in enumerate(paths):
        with path.open("r", encoding="utf-8") as input_file:
            for line_number, raw_line in enumerate(input_file, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{path}:{line_number}: {exc.msg}")
                    continue
                if not isinstance(row, dict):
                    errors.append(f"{path}:{line_number}: expected a JSON object")
                    continue
                # Repetition numbers restart at zero for every benchmark
                # invocation. Keep the source input in the in-memory row so
                # separate result files cannot overwrite or pair each other.
                row[_INPUT_INDEX_FIELD] = input_index
                rows.append(row)
    if errors:
        raise ValueError("Malformed JSONL row(s):\n" + "\n".join(errors))
    return rows


def _group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in _GROUP_FIELDS)


def _numeric(row: dict[str, Any], metric: str) -> float | None:
    value = row.get(metric)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [*_GROUP_FIELDS, "paired_repetitions", "failed_rows"]
    extras = sorted({key for row in rows for key in row if key not in preferred})
    return [field for field in preferred if any(field in row for row in rows)] + extras


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no comparable full/delta pairs)")
        return
    columns = _columns(rows)
    widths = {column: len(column) for column in columns}
    for row in rows:
        for column in columns:
            widths[column] = max(widths[column], len(str(row.get(column, ""))))
    print("  ".join(column.rjust(widths[column]) for column in columns))
    for row in rows:
        print("  ".join(str(row.get(column, "")).rjust(widths[column]) for column in columns))


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
