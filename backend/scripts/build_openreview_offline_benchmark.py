#!/usr/bin/env python3
"""Build offline benchmark raw payload from OpenReview export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_source_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    payload = json.loads(text)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("records", "rows", "submissions", "notes"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [payload]
    return []


def _write_json(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert OpenReview export into DeerFlow offline benchmark raw payload.")
    parser.add_argument("--input", required=True, help="OpenReview export path (.json or .jsonl).")
    parser.add_argument(
        "--output",
        default="src/evals/academic/templates/offline_benchmark_suite/openreview_top_venue_raw.json",
        help="Output raw payload file path.",
    )
    parser.add_argument("--dataset-name", default="openreview_top_venue", help="Dataset name metadata field.")
    parser.add_argument("--benchmark-split", default="openreview_offline_benchmark", help="Benchmark split metadata field.")
    parser.add_argument("--source-name", default="openreview", help="Source name metadata field.")
    parser.add_argument("--venue-default", default="OpenReview", help="Fallback venue when missing in source row.")
    parser.add_argument("--overwrite", action="store_true", default=False, help="Allow overwriting output file.")
    return parser


def main() -> int:
    from src.evals.academic.openreview_importer import build_openreview_raw_payload

    args = build_parser().parse_args()
    input_path = Path(args.input).expanduser()
    if not input_path.is_absolute():
        input_path = (Path.cwd() / input_path).resolve()
    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (Path.cwd() / output_path).resolve()

    rows = _load_source_rows(input_path)
    payload = build_openreview_raw_payload(
        rows,
        dataset_name=args.dataset_name,
        benchmark_split=args.benchmark_split,
        source_name=args.source_name,
        venue_default=args.venue_default,
    )
    _write_json(output_path, payload, overwrite=args.overwrite)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(input_path),
                "output": str(output_path),
                "source_row_count": len(rows),
                "record_count": len(payload.get("records") or []),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

