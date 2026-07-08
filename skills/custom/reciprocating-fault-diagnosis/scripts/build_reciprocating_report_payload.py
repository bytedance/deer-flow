#!/usr/bin/env python3
"""Build Deer Flow diagnosis payload from reciprocating rule runtime output.

Maps ``reciprocating_rule_result.json`` → ``diagnosis_features.json``
in the standard Deer Flow report payload format.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
RULES_SKILL = "reciprocating-fault-diagnosis"


def _output_dir() -> Path:
    path = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_result_path() -> Path:
    return _output_dir() / "reciprocating_rule_result.json"


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


def _health_to_alarm(health_value: int) -> str:
    if health_value >= 40:
        return "warning"
    if health_value >= 20:
        return "info"
    return "ok"


def _level_to_confidence(level_value: int) -> str:
    if level_value >= 40:
        return "high"
    if level_value >= 30:
        return "medium"
    if level_value >= 20:
        return "low"
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


def _build_equipment_summary(result_payload: dict[str, Any]) -> list[dict[str, Any]]:
    machine_id = str(result_payload.get("machine_id") or "")
    machine_name = str(result_payload.get("machine_name") or machine_id)

    channels = result_payload.get("channels") or []
    cylinder_diag = result_payload.get("cylinder_diagnosis") or []
    machine_diag = result_payload.get("machine_diagnosis") or []

    # Find the worst channel
    worst_channel = max(channels, key=lambda ch: ch.get("health_value", 0), default=None)

    # Find the worst diagnosis
    all_diag = cylinder_diag + machine_diag
    worst_diag = max(all_diag, key=lambda d: d.get("level_value", 0), default=None)

    alarm_status = "ok"
    if worst_diag:
        alarm_status = _health_to_alarm(worst_diag.get("level_value", 0))
    elif worst_channel:
        alarm_status = _health_to_alarm(worst_channel.get("health_value", 0))

    # Only populate max_value when there is an actual alarm; otherwise leave it
    # empty so the renderer shows "本次诊断未识别到异常" instead of a fabricated
    # zero-value entry (e.g. "pp 最大值：0") for a stopped or healthy machine.
    max_value: dict[str, Any] | None = None

    if worst_diag:
        max_value = {
            "point": worst_diag.get("component") or "",
            "feature": worst_diag.get("name") or worst_diag.get("code") or "",
            "value": worst_diag.get("level_value", 0),
            "unit": "",
        }
    elif worst_channel and alarm_status != "ok":
        max_value = {
            "point": worst_channel.get("name") or "",
            "feature": worst_channel.get("main_feature") or "",
            "value": worst_channel.get("main_value") or 0.0,
            "unit": "",
        }

    return [{
        "equipment_id": machine_id,
        "equipment_name": machine_name,
        "operation_phase": "running" if result_payload.get("ss_state") == "NORMAL" else "stopped",
        "alarm_status": alarm_status,
        "max_value": max_value,
    }]


def _pick_channel_threshold(health_value: int, thresholds: dict[str, Any]) -> float | None:
    """Return the numeric threshold that was crossed, based on health level.

    D(40) → value >= hh  → show hh
    C(30) → value >= h   → show h
    B(20) → value >= h×0.38 → show h×0.38
    """
    hh = _safe_float(thresholds.get("hh"))
    h = _safe_float(thresholds.get("h"))
    if health_value >= 40 and hh:
        return hh
    if health_value >= 30 and h:
        return h
    if health_value >= 20 and h:
        return round(h * 0.38, 4)
    # Fallback: show hh if available, else h
    return hh or h or None


def _pick_seg_threshold(seg_name: str, seg_health: str, seg_thresholds: dict[str, Any]) -> float | None:
    """Return the numeric segment threshold that was crossed.

    Parse segment index from name (e.g. 'A0' → 0), then:
      D → hh[i], C → h[i], B → h[i]×0.38
    """
    try:
        seg_idx = int(seg_name[1:])
    except (ValueError, IndexError):
        return None

    hh_arr = seg_thresholds.get("hh") or []
    h_arr = seg_thresholds.get("h") or []

    hh_val = _safe_float(hh_arr[seg_idx]) if seg_idx < len(hh_arr) else None
    h_val = _safe_float(h_arr[seg_idx]) if seg_idx < len(h_arr) else None

    if seg_health == "D" and hh_val:
        return hh_val
    if seg_health == "C" and h_val:
        return h_val
    if seg_health in ("B", "B+", "B-") and h_val:
        return round(h_val * 0.38, 4)
    return hh_val or h_val or None


def _build_evidence_chain(result_payload: dict[str, Any]) -> list[dict[str, Any]]:
    machine_id = str(result_payload.get("machine_id") or "")
    rows: list[dict[str, Any]] = []

    # Channel-level evidence (abnormal health)
    for ch in result_payload.get("channels") or []:
        health_value = ch.get("health_value", 0)
        if health_value > 10:  # Not A
            ch_thresholds = ch.get("thresholds") or {}
            rows.append({
                "category": "channel",
                "equipment_id": machine_id,
                "point": ch.get("name") or "",
                "feature": f"{ch.get('main_feature', '')}={ch.get('main_value', 0):.4f}",
                "value": ch.get("main_value"),
                "threshold": _pick_channel_threshold(health_value, ch_thresholds),
                "verdict": "exceed" if health_value >= 30 else "marginal",
            })
            # Segment-level evidence
            ch_seg_thresholds = ch.get("seg_thresholds") or {}
            for seg_name, seg_health in (ch.get("seg_health") or {}).items():
                rows.append({
                    "category": "segment",
                    "equipment_id": machine_id,
                    "point": f"{ch.get('name', '')} {seg_name}",
                    "feature": f"角域健康度={seg_health}",
                    "value": seg_health,
                    "threshold": _pick_seg_threshold(seg_name, seg_health, ch_seg_thresholds),
                    "verdict": "exceed" if seg_health in ("C", "C+", "C-", "D") else "marginal",
                })

    # Diagnosis-level evidence
    for diag in (result_payload.get("cylinder_diagnosis") or []):
        rows.append({
            "category": "diagnosis",
            "equipment_id": machine_id,
            "point": diag.get("component") or "",
            "feature": diag.get("code") or "",
            "value": diag.get("level_value"),
            "threshold": diag.get("level"),
            "verdict": "exceed",
        })

    for diag in (result_payload.get("machine_diagnosis") or []):
        rows.append({
            "category": "machine_diagnosis",
            "equipment_id": machine_id,
            "point": diag.get("component") or "",
            "feature": diag.get("code") or "",
            "value": diag.get("level_value"),
            "threshold": diag.get("level"),
            "verdict": "exceed",
        })

    return rows


def _build_rule_matches(result_payload: dict[str, Any]) -> list[dict[str, Any]]:
    machine_id = str(result_payload.get("machine_id") or "")
    matches: list[dict[str, Any]] = []

    all_diag = (result_payload.get("cylinder_diagnosis") or []) + \
               (result_payload.get("machine_diagnosis") or [])

    for diag in all_diag:
        level_value = diag.get("level_value", 0)
        if level_value < 20:
            continue
        matches.append({
            "equipment_id": machine_id,
            "kind": "reciprocating",
            "fault_family": diag.get("code") or "",
            "fault_subtype": diag.get("name") or None,
            "confidence": _level_to_confidence(level_value),
            "score": min(level_value / 40.0, 1.0),
            "supporting_evidence_indices": [],
            "marginal_evidence_indices": [],
            "missing_evidence": [],
            "rule_section": diag.get("code") or "",
            "desc": diag.get("desc") or "",
            "recommend": diag.get("recommend") or "",
            "component": diag.get("component") or "",
        })

    # Sort by score descending
    matches.sort(key=lambda m: m.get("score", 0), reverse=True)
    return matches


def _build_recommendations(rule_matches: list[dict[str, Any]]) -> list[str]:
    if not rule_matches:
        return []
    recs: list[str] = []
    for match in rule_matches:
        recommend = match.get("recommend") or ""
        if recommend:
            component = match.get("component") or ""
            fault = match.get("fault_subtype") or match.get("fault_family") or ""
            recs.append(f"[{component}] {fault}: {recommend}")
    return _dedupe(recs)


def build_payload(result_payload: dict[str, Any]) -> dict[str, Any]:
    if not result_payload.get("ok"):
        error = result_payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or "reciprocating rule runtime failed"))

    warnings = [str(item) for item in (result_payload.get("warnings") or []) if str(item).strip()]
    equipment_summary = _build_equipment_summary(result_payload)
    evidence_chain = _build_evidence_chain(result_payload)
    rule_matches = _build_rule_matches(result_payload)
    recommendations = _build_recommendations(rule_matches)

    is_normal = not rule_matches
    primary_fault = "往复机未形成有效规则结论" if is_normal else str(rule_matches[0].get("fault_family") or "")
    top_score = max([m.get("score", 0.0) for m in rule_matches], default=0.0)

    return {
        "report_meta": {
            "kind": "reciprocating",
            "rules_skill": RULES_SKILL,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "data_source": "reciprocating_rule_runtime",
            "runtime": result_payload.get("runtime") or {},
            "cache_dir": (result_payload.get("artifacts") or {}).get("cache_dir"),
        },
        "equipment_summary": equipment_summary,
        "evidence_chain": evidence_chain,
        "trend_chart": {},
        "spectrum_charts": [],
        "orbit_charts": [],
        "rule_matches": rule_matches,
        "historical_cases": [],
        "recommendations": recommendations,
        "warnings": _dedupe(warnings),
        "result_summary": {
            "overall_verdict": "normal" if is_normal else "fault",
            "primary_fault": primary_fault,
            "confidence": "low" if is_normal else str(rule_matches[0].get("confidence") or ""),
            "score": 0.0 if is_normal else top_score,
            "evidence_summary": [
                f"通道异常 {sum(1 for ch in (result_payload.get('channels') or []) if ch.get('health_value', 0) > 10)} 项",
                f"气缸诊断 {len(result_payload.get('cylinder_diagnosis') or [])} 项",
                f"机组诊断 {len(result_payload.get('machine_diagnosis') or [])} 项",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Deer Flow diagnosis payload from reciprocating rule runtime output"
    )
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
    except Exception as exc:
        print(json.dumps({"error": str(exc), "input": str(input_path)}, ensure_ascii=False))
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "rule_matches_count": len(payload.get("rule_matches") or []),
                "warnings": payload.get("warnings") or [],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
