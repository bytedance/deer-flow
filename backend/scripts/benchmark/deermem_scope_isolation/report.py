from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contract import Protocol
from .grading import grade_routing_row, grade_semantic_rows
from .runner import MARKER_SCHEMA_VERSION, ROW_SCHEMA_VERSION, _atomic_write_json, _case_fingerprint, _routing_fingerprint, protocol_artifacts, row_is_intact


class RowIntegrityError(ValueError):
    pass


def _read_row(path: Path) -> dict[str, Any]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RowIntegrityError(f"missing or invalid benchmark row: {path}") from exc
    if not isinstance(row, dict) or row.get("schema_version") != ROW_SCHEMA_VERSION:
        raise RowIntegrityError(f"unsupported benchmark row: {path}")
    if not row_is_intact(row):
        raise RowIntegrityError(f"benchmark row failed its result-integrity hash: {path}")
    return row


def collect_rows(protocol: Protocol, output_dir: Path, marker: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    semantic: list[dict[str, Any]] = []
    for case in protocol.semantic_cases:
        row = _read_row(output_dir / "rows" / f"{case.case_id}.json")
        if row.get("row_id") != case.case_id or row.get("suite") != "semantic_model_quality" or row.get("request_fingerprint") != _case_fingerprint(case, marker):
            raise RowIntegrityError(f"row {case.case_id} does not match the current protocol")
        if row.get("update_succeeded") is not True:
            raise RowIntegrityError(f"row {case.case_id} contains a failed memory update; rerun the benchmark")
        if (
            row.get("expected_persisted_canaries") != list(case.expected_persisted_canaries)
            or row.get("expected_rejected_canaries") != list(case.expected_rejected_canaries)
            or row.get("expected_removed_canaries") != list(case.expected_removed_canaries)
        ):
            raise RowIntegrityError(f"row {case.case_id} expected outcomes were changed")
        semantic.append(row)
    routing = None
    if marker["mode"] == "offline":
        routing = _read_row(output_dir / "rows" / f"{protocol.routing_case.case_id}.json")
        if routing.get("row_id") != protocol.routing_case.case_id or routing.get("suite") != "deterministic_identity_routing" or routing.get("request_fingerprint") != _routing_fingerprint(protocol, marker):
            raise RowIntegrityError("routing row does not match the current protocol")
    return semantic, routing


def build_report(protocol: Protocol, output_dir: Path, marker: dict[str, Any]) -> dict[str, Any]:
    semantic, routing = collect_rows(protocol, output_dir, marker)
    report = {
        "schema_version": 1,
        "protocol_id": protocol.protocol_id,
        "mode": marker["mode"],
        "artifacts": marker["artifacts"],
        "model": marker["model"],
        "semantic_model_quality": grade_semantic_rows(semantic),
        "deterministic_identity_routing": grade_routing_row(routing) if routing is not None else None,
    }
    return report


def write_report(protocol: Protocol, *, manifest_path: Path, output_dir: Path) -> Path:
    marker_path = output_dir / "run.json"
    if not marker_path.exists():
        raise ValueError(f"{marker_path} is missing; run the benchmark first")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("mode") not in {"offline", "live"}:
        raise ValueError(f"{marker_path} has an invalid execution mode")
    if marker.get("schema_version") != MARKER_SCHEMA_VERSION or marker.get("protocol_id") != protocol.protocol_id or marker.get("artifacts") != protocol_artifacts(manifest_path) or not isinstance(marker.get("model"), dict):
        raise ValueError(f"{marker_path} no longer matches the current protocol/source")
    target = output_dir / "report.json"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {target}")
    _atomic_write_json(target, build_report(protocol, output_dir, marker))
    return target
