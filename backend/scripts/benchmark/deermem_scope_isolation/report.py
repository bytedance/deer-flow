from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _rate(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def compute_metrics(
    semantic_rows: list[dict[str, Any]],
    identity_rows: list[dict[str, Any]],
) -> dict[str, dict[str, int | float | None]]:
    persist = [check for row in semantic_rows for check in row.get("persist_checks", [])]
    reject = [check for row in semantic_rows for check in row.get("reject_checks", [])]
    corrections = [check for row in semantic_rows for check in row.get("correction_checks", [])]
    same_scope = [row for row in identity_rows if row.get("dimension") == "same_scope"]
    cross_agent = [row for row in identity_rows if row.get("dimension") == "cross_agent"]
    cross_user = [row for row in identity_rows if row.get("dimension") == "cross_user"]
    return {
        "durable_retention_rate": _rate(sum(bool(check.get("passed")) for check in persist), len(persist)),
        "unsafe_persistence_rate": _rate(sum(bool(check.get("observed")) for check in reject), len(reject)),
        "atomic_correction_success_rate": _rate(sum(bool(check.get("passed")) for check in corrections), len(corrections)),
        "identity_retention_rate": _rate(sum(bool(row.get("observed_visible")) for row in same_scope), len(same_scope)),
        "cross_agent_contamination_rate": _rate(sum(bool(row.get("observed_visible")) for row in cross_agent), len(cross_agent)),
        "cross_user_contamination_rate": _rate(sum(bool(row.get("observed_visible")) for row in cross_user), len(cross_user)),
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} must contain a JSON object")
        rows.append(row)
    return rows


def load_semantic_rows(output_dir: Path) -> list[dict[str, Any]]:
    return _load_jsonl(output_dir / "semantic.rows.jsonl")


def load_identity_rows(output_dir: Path) -> list[dict[str, Any]]:
    return _load_jsonl(output_dir / "identity.rows.jsonl")
