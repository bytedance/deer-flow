#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
RULES_SKILL = "pump-fault-diagnosis"


def _output_dir() -> Path:
    path = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_result_path() -> Path:
    return _output_dir() / "pump_rule_result.json"


def _default_output_path() -> Path:
    return _output_dir() / "diagnosis_features.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None


def _confidence(probability: Any) -> str:
    value = _safe_float(probability) or 0.0
    if value >= 0.75:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _rule_matches(result_payload: dict[str, Any], evidence_count: int) -> list[dict[str, Any]]:
    machine_id = str(result_payload.get("machine_id") or "")
    matches: list[dict[str, Any]] = []
    for index, finding in enumerate(result_payload.get("malfunction_findings") or []):
        probability = round(float(finding.get("probability") or 0.0), 4)
        if probability < 0.5:
            continue
        matches.append(
            {
                "equipment_id": machine_id,
                "kind": "pump",
                "fault_family": finding.get("type") or "",
                "fault_subtype": finding.get("name") or None,
                "confidence": _confidence(probability),
                "score": probability,
                "supporting_evidence_indices": [min(index, max(evidence_count - 1, 0))] if evidence_count else [],
                "marginal_evidence_indices": [],
                "missing_evidence": [],
                "rule_section": finding.get("type") or "",
            }
        )
    return matches


def build_payload(result_payload: dict[str, Any]) -> dict[str, Any]:
    if not result_payload.get("ok"):
        error = result_payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or "pump rule runtime failed"))

    target = result_payload.get("target_info") or {}
    warnings = [str(item) for item in (result_payload.get("warnings") or []) if str(item).strip()]
    evidence_rows = list(result_payload.get("evidence") or [])
    matches = _rule_matches(result_payload, len(evidence_rows))
    top_score = max([_safe_float(match.get("score")) or 0.0 for match in matches], default=0.0)
    is_normal = not matches
    primary_fault = "机泵未形成有效规则结论" if is_normal else str(matches[0].get("fault_family") or "")
    alarm_status = "ok" if is_normal else ("warning" if top_score >= 0.7 else "info")

    recommendations = []
    if matches:
        recommendations = [
            "结合现场工艺条件复核该子设备关联测点的振动与温度趋势。",
            "对命中故障对应部件安排点检复核，必要时补充波形和频谱采样。",
        ]

    return {
        "report_meta": {
            "kind": "pump",
            "rules_skill": RULES_SKILL,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "data_source": "pump_rule_runtime",
            "runtime": result_payload.get("runtime") or {},
            "cache_dir": (result_payload.get("artifacts") or {}).get("cache_dir"),
        },
        "equipment_summary": [
            {
                "equipment_id": result_payload.get("machine_id"),
                "equipment_name": target.get("target_name") or result_payload.get("component_id"),
                "component_id": result_payload.get("component_id"),
                "component_name": target.get("target_name"),
                "target_kind": target.get("target_kind"),
                "operation_phase": "not_evaluated",
                "alarm_status": alarm_status,
                "max_value": {
                    "point": result_payload.get("component_id"),
                    "feature": primary_fault,
                    "value": top_score,
                    "unit": "",
                },
            }
        ],
        "evidence_chain": evidence_rows,
        "trend_chart": {},
        "spectrum_charts": [],
        "orbit_charts": [],
        "rule_matches": matches,
        "historical_cases": [],
        "recommendations": recommendations,
        "warnings": _dedupe(warnings),
        "result_summary": {
            "overall_verdict": "normal" if is_normal else "fault",
            "primary_fault": primary_fault,
            "confidence": "low" if is_normal else str(matches[0].get("confidence") or ""),
            "score": 0.0 if is_normal else top_score,
            "evidence_summary": [
                f"健康异常 {len(result_payload.get('health_findings') or [])} 项",
                f"故障候选 {len(result_payload.get('malfunction_findings') or [])} 项",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Deer Flow diagnosis payload from pump rule runtime output")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else _default_result_path()
    output_path = Path(args.output) if args.output else _default_output_path()
    if not input_path.exists():
        print(json.dumps({"error": f"input not found: {input_path}"}, ensure_ascii=False))
        return 0
    try:
        payload = build_payload(_read_json(input_path))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "input": str(input_path)}, ensure_ascii=False))
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"output": str(output_path), "rule_matches_count": len(payload.get("rule_matches") or []), "warnings": payload.get("warnings") or []},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
