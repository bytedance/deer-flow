"""Shared helpers for stub demo scripts in the monitoring-analysis skill.

Every Phase 6 builtin report (trend / diagnosis / failure-analysis / closure /
inspection) ships with a deterministic stub script that produces a valid
output JSON. Real production scripts will replace these by reading from a
real data source, but the shape and contracts (output paths, error envelopes,
provenance fields for interpretive reports) are stable now.

All stub scripts share:
  - ``--output-dir`` to point at the run-scoped output root injected by runtime
  - JSON output under ``{output_dir}/data/<name>.json``
  - ``schema_version: "1"``
  - Structured error envelope on stderr if the input is unusable
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_checksum(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()[:16]


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def write_json(output_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    path = (output_dir / "data" / f"{name}.json").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def emit_error(code: str, message: str, **details: Any) -> int:
    """Print a structured error to stderr; return non-zero exit code."""
    print(
        json.dumps(
            {"code": code, "message": message, "details": details},
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 1


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Run-scoped output dir injected by runtime",
    )
    return parser


def provenance_evidence(
    *,
    source_type: str,
    source_id: str,
    snapshot_path: str,
    payload_sample: Any,
    time_range: list[str] | None = None,
) -> dict[str, Any]:
    """Build a §13.2 evidence entry with checksum + retrieved_at metadata."""
    return {
        "source_type": source_type,
        "source_id": source_id,
        "snapshot_path": snapshot_path,
        "checksum": short_checksum(payload_sample),
        "time_range": time_range or [],
        "retrieved_at": iso_now(),
    }
