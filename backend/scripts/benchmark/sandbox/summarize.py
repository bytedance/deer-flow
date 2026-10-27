#!/usr/bin/env python3
"""Aggregate bench_provider JSONL results into summary tables.

Prewarm cases and resource samples use separate formats and are not summarized.

Usage::

    python scripts/benchmark/sandbox/summarize.py results.jsonl
    python scripts/benchmark/sandbox/summarize.py results/*.jsonl --group provider,scenario,workload
    python scripts/benchmark/sandbox/summarize.py results.jsonl --csv > summary.csv
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _p(arr: list[float], pct: int) -> float:
    if len(arr) < 2:
        return arr[0] if arr else 0.0
    return statistics.quantiles(arr, n=100, method="inclusive")[pct - 1]


def _load_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for p in paths:
        with p.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    errors.append(f"{p}:{line_no}: {exc.msg}")
    if errors:
        raise ValueError("Malformed JSONL row(s):\n" + "\n".join(errors))
    return rows


def _group_key(row: dict[str, Any], group_by: list[str]) -> tuple:
    return tuple(row.get(k, "?") for k in group_by)


def _summarize(rows: list[dict[str, Any]], group_by: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[_group_key(r, group_by)].append(r)

    summary: list[dict[str, Any]] = []
    for key, group in sorted(groups.items(), key=lambda item: repr(item[0])):
        ok = [r for r in group if r.get("success")]
        a = [r["acquire_ms"] for r in ok]
        ru = [r.get("run_ms", 0) for r in ok]
        rel = [r.get("release_ms", 0) for r in ok]
        t = [r["total_ms"] for r in ok]
        warm_hits = sum(1 for r in ok if r.get("warm_hit"))
        errors = len(group) - len(ok)

        entry: dict[str, Any] = {}
        for i, k in enumerate(group_by):
            entry[k] = key[i]
        entry["count"] = len(group)
        entry["ok"] = len(ok)
        entry["errors"] = errors
        entry["warm_hit_rate"] = round(warm_hits / len(ok), 3) if ok else 0
        entry["acquire_p50"] = round(_p(a, 50), 1)
        entry["acquire_p95"] = round(_p(a, 95), 1)
        entry["acquire_p99"] = round(_p(a, 99), 1)
        entry["acquire_mean"] = round(sum(a) / len(a), 1) if a else 0.0
        entry["run_p50"] = round(_p(ru, 50), 1)
        entry["run_p95"] = round(_p(ru, 95), 1)
        entry["release_p50"] = round(_p(rel, 50), 1)
        entry["total_p50"] = round(_p(t, 50), 1)
        entry["total_p95"] = round(_p(t, 95), 1)
        entry["total_p99"] = round(_p(t, 99), 1)
        entry["total_mean"] = round(sum(t) / len(t), 1) if t else 0.0

        summary.append(entry)

    return summary


_COLUMNS = [
    "provider",
    "scenario",
    "workload",
    "concurrency",
    "users",
    "no_warmpool",
    "replicas",
    "idle_timeout",
    "health_check_skip_seconds",
    "image",
    "count",
    "ok",
    "errors",
    "warm_hit_rate",
    "acquire_p50",
    "acquire_p95",
    "acquire_p99",
    "acquire_mean",
    "run_p50",
    "run_p95",
    "release_p50",
    "total_p50",
    "total_p95",
    "total_p99",
    "total_mean",
]


def _print_table(rows: list[dict[str, Any]], fmt: str = "plain") -> None:
    columns = list(dict.fromkeys(_COLUMNS + [key for row in rows for key in row if key not in _COLUMNS]))
    if fmt == "csv":
        import csv as _csv

        w = _csv.DictWriter(sys.stdout, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
        return

    # Plain text table
    if not rows:
        print("(no data)")
        return

    headers = [column for column in columns if any(row.get(column) is not None for row in rows)]
    col_widths = {h: len(h) for h in headers}
    for r in rows:
        for h in headers:
            v = str(r.get(h, ""))
            col_widths[h] = max(col_widths[h], len(v))

    def _fmt_row(vals: list[str]) -> str:
        parts = [v.rjust(col_widths[h]) for h, v in zip(headers, vals)]
        return "  ".join(parts)

    print(_fmt_row(headers))
    for r in rows:
        vals = [str(r.get(h, "")) for h in headers]
        print(_fmt_row(vals))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Aggregate bench_provider.py JSONL results (not prewarm cases or resource samples)")
    p.add_argument("inputs", nargs="+", help="JSONL file(s) from sandbox/bench_provider.py")
    p.add_argument(
        "--group",
        default="provider,scenario,workload,concurrency,users,no_warmpool,replicas,idle_timeout,health_check_skip_seconds,image",
        help="Comma-separated grouping dimensions (default includes provider configuration and user count)",
    )
    p.add_argument(
        "--csv",
        action="store_true",
        help="Output CSV instead of aligned text",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of aligned text",
    )
    args = p.parse_args(argv)

    paths = [Path(i) for i in args.inputs]
    try:
        rows = _load_jsonl(paths)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not rows:
        print("No valid JSONL rows found.", file=sys.stderr)
        return 1

    provider_rows = [row for row in rows if isinstance(row, dict) and row.get("record_type") is None and "success" in row]
    if len(provider_rows) != len(rows):
        print(f"Ignored {len(rows) - len(provider_rows)} non-provider record(s); summarize.py reports provider results only.", file=sys.stderr)
    rows = provider_rows
    if not rows:
        print("No bench_provider.py result rows found. Prewarm and resource JSONL use separate formats.", file=sys.stderr)
        return 1
    for index, row in enumerate(rows, start=1):
        missing = [field for field in ("acquire_ms", "total_ms") if field not in row]
        if row.get("success") and missing:
            print(f"Provider result {index} is missing timing fields: {', '.join(missing)}.", file=sys.stderr)
            return 1

    group_by = [g.strip() for g in args.group.split(",") if g.strip()]
    summary = _summarize(rows, group_by)

    if args.json:
        json.dump(summary, sys.stdout, indent=2)
    elif args.csv:
        _print_table(summary, fmt="csv")
    else:
        _print_table(summary, fmt="plain")

    return int(any(not row.get("success") for row in rows))


if __name__ == "__main__":
    sys.exit(main())
