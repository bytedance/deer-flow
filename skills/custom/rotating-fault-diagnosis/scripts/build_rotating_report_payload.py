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
RULES_SKILL = "vibration-fault-diagnosis"


def _output_dir() -> Path:
    path = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_result_path() -> Path:
    return _output_dir() / "rotating_rule_result.json"


def _default_output_path() -> Path:
    return _output_dir() / "diagnosis_features.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


def _iso_from_ms(value: Any) -> str | None:
    try:
        timestamp = int(str(value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _severity_rank(verdict: str) -> int:
    return {"exceed": 0, "marginal": 1, "normal": 2}.get(verdict, 3)


def _confidence_from_score(score: Any) -> str:
    numeric = _safe_float(score) or 0.0
    if numeric >= 0.8:
        return "high"
    if numeric >= 0.5:
        return "medium"
    return "low"


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _cache_dir(result_payload: dict[str, Any]) -> Path:
    artifacts = result_payload.get("artifacts") or {}
    raw = artifacts.get("cache_dir")
    if isinstance(raw, str) and raw.strip():
        return Path(raw)
    return _output_dir() / "rotating_rule_cache"


def _iter_cache(cache_dir: Path, prefix: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if not cache_dir.exists():
        return payloads
    for path in sorted(cache_dir.glob(f"{prefix}_*.json")):
        try:
            payloads.append(_read_json(path))
        except (OSError, json.JSONDecodeError):
            continue
    return payloads


def _extract_kind(rule_result: dict[str, Any]) -> str:
    debug = rule_result.get("debug") or {}
    lines = debug.get("reasoning_summary") or []
    if isinstance(lines, list):
        for raw in lines:
            line = str(raw or "").strip()
            if line.startswith("target_device_type="):
                return line.split("=", 1)[1].strip() or "rotating_machinery"
    return "rotating_machinery"


def _collect_rule_rows(
    device_id: str,
    sub_device_id: str,
    primary_detail: dict[str, Any] | None,
    alternatives: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_rows: list[dict[str, Any]] = []
    rule_matches: list[dict[str, Any]] = []

    def append_match(candidate: dict[str, Any], confidence: str | None = None) -> None:
        fault_type = str(candidate.get("fault_type") or "").strip()
        if not fault_type:
            return

        supporting_indices: list[int] = []
        for condition in candidate.get("matched_conditions") or []:
            supporting_indices.append(len(evidence_rows))
            evidence_rows.append(
                {
                    "category": "rule",
                    "equipment_id": device_id,
                    "point": sub_device_id,
                    "feature": str(condition),
                    "value": round(_safe_float(candidate.get("score")) or 0.0, 4),
                    "threshold": "matched",
                    "verdict": "exceed",
                }
            )

        for contradiction in candidate.get("contradictions") or []:
            evidence_rows.append(
                {
                    "category": "rule-contradiction",
                    "equipment_id": device_id,
                    "point": sub_device_id,
                    "feature": str(contradiction),
                    "value": None,
                    "threshold": "contradiction",
                    "verdict": "normal",
                }
            )

        rule_matches.append(
            {
                "equipment_id": device_id,
                "kind": "rotating_machinery",
                "fault_family": fault_type,
                "fault_subtype": candidate.get("fault_subtype") or None,
                "confidence": confidence or _confidence_from_score(candidate.get("score")),
                "score": round(_safe_float(candidate.get("score")) or 0.0, 4),
                "supporting_evidence_indices": supporting_indices,
                "marginal_evidence_indices": [],
                "missing_evidence": [str(item) for item in (candidate.get("missing_evidence") or []) if str(item).strip()],
                "rule_section": str(candidate.get("rule_id") or fault_type),
            }
        )

    if isinstance(primary_detail, dict):
        append_match(primary_detail, None)
    for candidate in alternatives:
        if isinstance(candidate, dict):
            append_match(candidate)
    return evidence_rows, rule_matches


def _trend_rows(
    device_id: str,
    trend_feature_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in trend_feature_payloads:
        for point_result in payload.get("point_results") or []:
            component_id = str(point_result.get("component_id") or "").strip()
            feature_stats = point_result.get("feature_stats") or {}
            if not component_id or not isinstance(feature_stats, dict):
                continue
            for feature, detail in feature_stats.items():
                if not isinstance(detail, dict):
                    continue
                current = _safe_float(detail.get("current"))
                mean = _safe_float(detail.get("mean"))
                std = _safe_float(detail.get("std")) or 0.0
                if current is None:
                    continue
                threshold = mean + max(std, abs(mean) * 0.1) if mean is not None else None
                verdict = "normal"
                if threshold is not None:
                    if current >= threshold:
                        verdict = "exceed"
                    elif current >= threshold - max(abs(threshold) * 0.05, 1e-6):
                        verdict = "marginal"
                rows.append(
                    {
                        "category": "trend",
                        "equipment_id": device_id,
                        "point": component_id,
                        "feature": str(feature),
                        "value": round(current, 6),
                        "threshold": round(threshold, 6) if threshold is not None else None,
                        "verdict": verdict,
                    }
                )
    rows.sort(key=lambda item: (_severity_rank(str(item.get("verdict"))), -(abs(_safe_float(item.get("value")) or 0.0))))
    return rows[:24]


def _waveform_rows(device_id: str, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        component_id = str(payload.get("component_id") or "").strip()
        detail = payload.get("feature_details") or {}
        if not component_id or not isinstance(detail, dict):
            continue
        metrics = (
            ("amp_1x_ratio", 0.55),
            ("amp_2x_to_1x_ratio", 0.45),
            ("crest_factor", 4.5),
        )
        for feature, threshold in metrics:
            value = _safe_float(detail.get(feature))
            if value is None:
                continue
            verdict = "exceed" if value >= threshold else "normal"
            if verdict == "normal" and value >= threshold * 0.9:
                verdict = "marginal"
            rows.append(
                {
                    "category": "waveform",
                    "equipment_id": device_id,
                    "point": component_id,
                    "feature": feature,
                    "value": round(value, 6),
                    "threshold": threshold,
                    "verdict": verdict,
                }
            )
    return rows[:12]


def _orbit_rows(device_id: str, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        bearing_id = str(payload.get("bearing_id") or "").strip()
        detail = payload.get("feature_details") or {}
        if not bearing_id or not isinstance(detail, dict):
            continue
        metrics = (
            ("first_cycle_axis_ratio", 1.5),
            ("raw_repetition_score", 0.75),
        )
        for feature, threshold in metrics:
            value = _safe_float(detail.get(feature))
            if value is None:
                continue
            verdict = "exceed" if value >= threshold else "normal"
            if verdict == "normal" and value >= threshold * 0.9:
                verdict = "marginal"
            rows.append(
                {
                    "category": "orbit",
                    "equipment_id": device_id,
                    "point": bearing_id,
                    "feature": feature,
                    "value": round(value, 6),
                    "threshold": threshold,
                    "verdict": verdict,
                }
            )
    return rows[:12]


def _build_trend_chart(cache_payloads: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
    if not cache_payloads:
        warnings.append("缺少趋势缓存，趋势图已跳过")
        return {"title": {"text": "真实规则趋势数据"}, "series": []}

    best_payload = max(
        cache_payloads,
        key=lambda item: sum(len(series or []) for series in (item.get("data") or {}).values()),
    )
    data = best_payload.get("data") or {}
    if not isinstance(data, dict):
        warnings.append("趋势缓存格式异常，趋势图已跳过")
        return {"title": {"text": "真实规则趋势数据"}, "series": []}

    series_list: list[dict[str, Any]] = []
    for component_id, items in data.items():
        if not isinstance(items, list):
            continue
        sample = next((item for item in items if isinstance(item, dict) and isinstance(item.get("values"), dict) and item.get("values")), None)
        if sample is None:
            continue
        for feature in list((sample.get("values") or {}).keys())[:2]:
            pairs: list[list[Any]] = []
            for point in items:
                if not isinstance(point, dict):
                    continue
                value = _safe_float((point.get("values") or {}).get(feature))
                if value is None:
                    continue
                label = _iso_from_ms(point.get("time_ms")) or str(point.get("time_ms") or "")
                if not label:
                    continue
                pairs.append([label, round(value, 6)])
            if pairs:
                series_list.append(
                    {
                        "name": f"{component_id}:{feature}",
                        "type": "line",
                        "showSymbol": False,
                        "smooth": True,
                        "data": pairs,
                    }
                )
        if len(series_list) >= 8:
            break

    if not series_list:
        warnings.append("趋势缓存中没有可绘制的数据点")
    return {
        "title": {"text": "真实规则趋势数据"},
        "tooltip": {"trigger": "axis"},
        "legend": {"type": "scroll"},
        "xAxis": {"type": "category"},
        "yAxis": {"type": "value"},
        "series": series_list[:8],
    }


def _build_spectrum_charts(payloads: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for payload in payloads:
        component_id = str(payload.get("component_id") or "").strip()
        time_ms = str(payload.get("time_ms") or "").strip()
        data = payload.get("data") or {}
        spec_x = data.get("spec_x") or []
        spec_y = data.get("spec_y") or []
        pairs = [
            [round(float(x), 6), round(float(y), 6)]
            for x, y in zip(spec_x, spec_y)
            if isinstance(x, (int, float)) and isinstance(y, (int, float))
        ]
        if not pairs:
            warnings.append(f"频谱缓存缺少有效数据: {component_id or 'unknown'}@{time_ms or 'unknown'}")
            continue
        charts.append(
            {
                "point": component_id or "unknown",
                "option": {
                    "title": {"text": f"频谱图 · {component_id}"},
                    "tooltip": {"trigger": "axis"},
                    "xAxis": {"type": "value", "name": "Hz"},
                    "yAxis": {"type": "value", "name": "Amplitude"},
                    "series": [{"name": "spectrum", "type": "line", "showSymbol": False, "data": pairs}],
                },
            }
        )
    return charts


def _build_orbit_charts(payloads: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for payload in payloads:
        bearing_id = str(payload.get("bearing_id") or "").strip()
        data = payload.get("data") or {}
        points = data.get("points") or []
        pairs = [
            [round(float(item[0]), 6), round(float(item[1]), 6)]
            for item in points
            if isinstance(item, list) and len(item) >= 2 and isinstance(item[0], (int, float)) and isinstance(item[1], (int, float))
        ]
        if not pairs:
            warnings.append(f"轨迹缓存缺少有效数据: {bearing_id or 'unknown'}")
            continue
        charts.append(
            {
                "bearing": bearing_id or "unknown",
                "option": {
                    "title": {"text": f"轴心轨迹 · {bearing_id}"},
                    "tooltip": {"trigger": "axis"},
                    "xAxis": {"type": "value", "name": "X"},
                    "yAxis": {"type": "value", "name": "Y", "scale": True},
                    "series": [{"name": "orbit", "type": "line", "showSymbol": False, "data": pairs}],
                },
            }
        )
    return charts


def build_payload(result_payload: dict[str, Any]) -> dict[str, Any]:
    if not result_payload.get("ok"):
        error = result_payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or "rotating rule runtime failed"))

    rule_result = result_payload.get("result") or {}
    cache_dir = _cache_dir(result_payload)
    warnings = [str(item) for item in (result_payload.get("warnings") or []) if str(item).strip()]

    trend_raw = _iter_cache(cache_dir, "trend")
    trend_features = _iter_cache(cache_dir, "trend_features")
    waveform_raw = _iter_cache(cache_dir, "waveform")
    waveform_features = _iter_cache(cache_dir, "waveform_features")
    orbit_raw = _iter_cache(cache_dir, "orbit")
    orbit_features = _iter_cache(cache_dir, "orbit_features")

    evidence_rows, rule_matches = _collect_rule_rows(
        device_id=str(result_payload.get("device_id") or ""),
        sub_device_id=str(result_payload.get("sub_device_id") or ""),
        primary_detail=rule_result.get("primary_rule_detail") if isinstance(rule_result.get("primary_rule_detail"), dict) else None,
        alternatives=[item for item in (rule_result.get("alternative_faults") or []) if isinstance(item, dict)],
    )
    evidence_rows.extend(_trend_rows(str(result_payload.get("device_id") or ""), trend_features))
    evidence_rows.extend(_waveform_rows(str(result_payload.get("device_id") or ""), waveform_features))
    evidence_rows.extend(_orbit_rows(str(result_payload.get("device_id") or ""), orbit_features))

    trend_chart = _build_trend_chart(trend_raw, warnings)
    spectrum_charts = _build_spectrum_charts(waveform_raw, warnings)
    orbit_charts = _build_orbit_charts(orbit_raw, warnings)

    diagnostic_recommendations = _dedupe_keep_order(
        [str(item) for item in (rule_result.get("running_actions") or [])]
        + [str(item) for item in (rule_result.get("maintenance_actions") or [])]
        + [str(item) for item in (rule_result.get("rule_optimization_conclusion") or [])]
    )

    max_row = next(
        (
            row
            for row in evidence_rows
            if row.get("category") in {"trend", "waveform", "orbit"} and isinstance(row.get("value"), (int, float))
        ),
        None,
    )
    alarm_status = "warning" if any(row.get("verdict") == "exceed" for row in evidence_rows) else "info"
    if not any(row.get("verdict") in {"exceed", "marginal"} for row in evidence_rows):
        alarm_status = "ok"

    payload = {
        "report_meta": {
            "kind": _extract_kind(rule_result),
            "rules_skill": RULES_SKILL,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "data_source": "rotating_rule_runtime",
            "runtime": result_payload.get("runtime") or {},
            "cache_dir": str(cache_dir),
        },
        "equipment_summary": [
            {
                "equipment_id": str(result_payload.get("device_id") or ""),
                "operation_phase": str(rule_result.get("stage") or "running"),
                "alarm_status": alarm_status,
                "max_value": {
                    "point": max_row.get("point") if max_row else str(result_payload.get("sub_device_id") or ""),
                    "feature": max_row.get("feature") if max_row else str(rule_result.get("fault_type") or ""),
                    "value": max_row.get("value") if max_row else round(_safe_float(rule_result.get("score")) or 0.0, 4),
                    "unit": "",
                },
            }
        ],
        "evidence_chain": evidence_rows,
        "trend_chart": trend_chart,
        "spectrum_charts": spectrum_charts,
        "orbit_charts": orbit_charts,
        "rule_matches": rule_matches
        or [
            {
                "equipment_id": str(result_payload.get("device_id") or ""),
                "kind": _extract_kind(rule_result),
                "fault_family": str(rule_result.get("fault_type") or "unknown"),
                "fault_subtype": rule_result.get("fault_subtype") or None,
                "confidence": str(rule_result.get("confidence") or "low"),
                "score": round(_safe_float(rule_result.get("score")) or 0.0, 4),
                "supporting_evidence_indices": [],
                "marginal_evidence_indices": [],
                "missing_evidence": [],
                "rule_section": "rotating-rule-runtime",
            }
        ],
        "historical_cases": [],
        "recommendations": diagnostic_recommendations,
        "warnings": _dedupe_keep_order(warnings),
        "result_summary": {
            "primary_fault": str(rule_result.get("fault_type") or ""),
            "confidence": str(rule_result.get("confidence") or ""),
            "score": round(_safe_float(rule_result.get("score")) or 0.0, 4),
            "evidence_summary": [str(item) for item in (rule_result.get("evidence_summary") or []) if str(item).strip()],
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Deer Flow diagnosis payload from rotating rule runtime output")
    parser.add_argument("--input", default=None, help="Path to rotating_rule_result.json")
    parser.add_argument("--output", default=None, help="Path to diagnosis_features.json")
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else _default_result_path()
    output_path = Path(args.output) if args.output else _default_output_path()

    if not input_path.exists():
        print(json.dumps({"error": f"input not found: {input_path}"}, ensure_ascii=False))
        return 0

    try:
        result_payload = _read_json(input_path)
        payload = build_payload(result_payload)
    except Exception as exc:  # noqa: BLE001
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
