from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contract import Protocol
from .grading import grade_all_rows
from .runner import (
    MARKER_SCHEMA_VERSION,
    ROW_SCHEMA_VERSION,
    _atomic_write_json,
    _case_fingerprint,
    protocol_artifacts,
    row_is_intact,
)


class RowIntegrityError(ValueError):
    pass


def _read_row(path: Path) -> dict[str, Any]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RowIntegrityError(f"missing or invalid benchmark row: {path}") from exc
    if not isinstance(row, dict) or row.get("schema_version") != ROW_SCHEMA_VERSION:
        raise RowIntegrityError(f"unsupported benchmark row schema: {path}")
    if not row_is_intact(row):
        raise RowIntegrityError(f"benchmark row failed its result-integrity hash: {path}")
    return row


def collect_rows(
    protocol: Protocol,
    output_dir: Path,
    marker: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    # 1. Scope isolation rows
    scope_rows: list[dict[str, Any]] = []
    for case in protocol.scope_isolation_cases:
        row_path = output_dir / "rows" / "scope_isolation" / f"{case.case_id}.json"
        row = _read_row(row_path)
        case_dict = {
            "id": case.case_id,
            "thread_a": case.thread_a.__dict__,
            "thread_b": case.thread_b.__dict__,
            "expected_thread_a_canaries": case.expected_thread_a_canaries,
            "expected_thread_b_canaries": case.expected_thread_b_canaries,
            "expected_rejected_canaries": case.expected_rejected_canaries,
        }
        if row.get("row_id") != case.case_id or row.get("suite") != "scope_isolation":
            raise RowIntegrityError(f"row {case.case_id} does not match expected suite or id")
        if row.get("request_fingerprint") != _case_fingerprint("scope_isolation", case_dict, marker):
            raise RowIntegrityError(f"row {case.case_id} does not match the current protocol definition")
        scope_rows.append(row)

    # 2. Turn invalidation rows
    inv_rows: list[dict[str, Any]] = []
    for case in protocol.turn_invalidation_cases:
        row_path = output_dir / "rows" / "turn_invalidation" / f"{case.case_id}.json"
        row = _read_row(row_path)
        case_dict = {
            "id": case.case_id,
            "user_id": case.user_id,
            "agent_name": case.agent_name,
            "seed_facts": case.seed_facts,
            "expected_turn_1_canaries": case.expected_turn_1_canaries,
            "expected_turn_2_present_canaries": case.expected_turn_2_present_canaries,
            "expected_turn_2_absent_canaries": case.expected_turn_2_absent_canaries,
        }
        if row.get("row_id") != case.case_id or row.get("suite") != "turn_invalidation":
            raise RowIntegrityError(f"row {case.case_id} does not match expected suite or id")
        if row.get("request_fingerprint") != _case_fingerprint("turn_invalidation", case_dict, marker):
            raise RowIntegrityError(f"row {case.case_id} does not match the current protocol definition")
        inv_rows.append(row)

    # 3. Token overhead rows
    tok_rows: list[dict[str, Any]] = []
    for case in protocol.token_overhead_cases:
        row_path = output_dir / "rows" / "token_overhead" / f"{case.case_id}.json"
        row = _read_row(row_path)
        case_dict = {
            "id": case.case_id,
            "user_id": case.user_id,
            "agent_name": case.agent_name,
            "user_facts": case.user_facts,
            "agent_facts": case.agent_facts,
            "project_context": case.project_context,
        }
        if row.get("row_id") != case.case_id or row.get("suite") != "token_overhead":
            raise RowIntegrityError(f"row {case.case_id} does not match expected suite or id")
        if row.get("request_fingerprint") != _case_fingerprint("token_overhead", case_dict, marker):
            raise RowIntegrityError(f"row {case.case_id} does not match the current protocol definition")
        tok_rows.append(row)

    return scope_rows, inv_rows, tok_rows


def build_report(
    protocol: Protocol,
    output_dir: Path,
    marker: dict[str, Any],
) -> dict[str, Any]:
    scope_rows, inv_rows, tok_rows = collect_rows(protocol, output_dir, marker)
    summary = grade_all_rows(scope_rows, inv_rows, tok_rows)

    return {
        "schema_version": 1,
        "protocol_id": protocol.protocol_id,
        "mode": marker["mode"],
        "artifacts": marker["artifacts"],
        "model": marker["model"],
        "summary": summary,
    }


def write_report(
    protocol: Protocol,
    *,
    manifest_path: Path,
    output_dir: Path,
) -> Path:
    marker_path = output_dir / "run.json"
    if not marker_path.exists():
        raise ValueError(f"{marker_path} is missing; run the benchmark first")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("mode") != "offline":
        raise ValueError(f"{marker_path} has an invalid execution mode")
    if (
        marker.get("schema_version") != MARKER_SCHEMA_VERSION
        or marker.get("protocol_id") != protocol.protocol_id
        or marker.get("artifacts") != protocol_artifacts(manifest_path)
    ):
        raise ValueError(f"{marker_path} no longer matches the current protocol or source revision")

    target = output_dir / "report.json"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {target}")

    report_content = build_report(protocol, output_dir, marker)
    _atomic_write_json(target, report_content)
    return target
