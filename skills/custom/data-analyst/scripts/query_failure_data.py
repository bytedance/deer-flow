"""Failure-analysis demo data with method-specific branching.

Sprint S3 enhancement — replaces the 60-line stub. Output common signals
(operations / maintenance / inspections / spares / environment) PLUS one
method-specific block per analysis method so the downstream transform doesn't
have to invent placeholder structures.

Method-specific blocks (one is populated per request):
- ``five_why_seed``: 5-level cause chain seed (5 questions + initial hypotheses)
- ``fishbone_seed``: 6-category cause tree skeleton (人/机/料/法/环/测)
- ``fmea_seed``: failure mode rows with severity/occurrence/detection scores

Other fields are always populated so renderers can fall back to factual data.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    write_json,
)

import _data_provider_impls  # noqa: F401 — register-only
from _data_providers import fetch_with_fallback


SCHEMA_VERSION = "1"

VALID_METHODS = {"five_why", "fishbone", "fmea"}


def _seed_int(seed: str, low: int, high: int) -> int:
    digest = abs(hash(seed))
    span = high - low + 1
    return low + (digest % span) if span > 0 else low


def _operations(today: date, asset_id: str) -> list[dict]:
    """30-day daily vibration + temp samples, with deterministic drift."""
    series: list[dict] = []
    for d in range(30, 0, -1):
        ts = (today - timedelta(days=d)).isoformat()
        progress = (30 - d) / 30.0
        series.append(
            {
                "id": f"OP-{asset_id}-{ts}-vib",
                "t": ts,
                "metric": "vibration_level",
                "value": round(0.40 + 0.50 * progress + 0.02 * _seed_int(f"v|{ts}", -2, 2) / 10, 4),
                "unit": "mm/s",
            }
        )
        series.append(
            {
                "id": f"OP-{asset_id}-{ts}-temp",
                "t": ts,
                "metric": "bearing_temp",
                "value": round(55.0 + 18.0 * progress + 0.5 * _seed_int(f"t|{ts}", -3, 3), 4),
                "unit": "℃",
            }
        )
    return series


def _maintenance(today: date, asset_id: str) -> list[dict]:
    return [
        {
            "id": "MR-2025-1115",
            "type": "annual_overhaul",
            "asset": asset_id,
            "date": (today - timedelta(days=180)).isoformat(),
            "owner": "维修部",
            "note": "年度大修，更换轴承与密封件",
        },
        {
            "id": "MR-2026-0301",
            "type": "oil_change",
            "asset": asset_id,
            "date": (today - timedelta(days=75)).isoformat(),
            "owner": "维修部",
            "note": "季度换油",
        },
        {
            "id": "MR-2026-0418",
            "type": "vibration_calibration",
            "asset": asset_id,
            "date": (today - timedelta(days=27)).isoformat(),
            "owner": "运行部",
            "note": "传感器零点漂移校正",
        },
    ]


def _inspections(today: date, asset_id: str) -> list[dict]:
    return [
        {
            "id": "INSP-2026-014",
            "date": (today - timedelta(days=14)).isoformat(),
            "asset": asset_id,
            "result": "minor_oil_seepage",
            "severity": "low",
            "note": "前轴承端发现轻微渗油",
        },
        {
            "id": "INSP-2026-021",
            "date": (today - timedelta(days=7)).isoformat(),
            "asset": asset_id,
            "result": "vibration_warning",
            "severity": "medium",
            "note": "巡检员手测振动接近上限",
        },
    ]


def _spares(today: date, asset_id: str) -> list[dict]:
    return [
        {
            "part_number": "bearing-6308",
            "asset": asset_id,
            "last_replaced": (today - timedelta(days=180)).isoformat(),
            "expected_life_days": 365,
            "remaining_pct": 50,
        },
        {
            "part_number": "seal-MFP-22",
            "asset": asset_id,
            "last_replaced": (today - timedelta(days=180)).isoformat(),
            "expected_life_days": 365,
            "remaining_pct": 50,
        },
    ]


def _environment() -> dict:
    return {
        "ambient_temp_c": 32,
        "humidity_pct": 55,
        "dust_index": 1.2,
        "vibration_neighbor_mm_s": 0.18,
    }


def _five_why_seed(failure_mode: str) -> dict:
    """5-level Why chain skeleton. Each level seeded with a question + a
    placeholder evidence pointer so failure_analysis can fill in hypotheses.
    """
    return {
        "method": "five_why",
        "root_failure": failure_mode,
        "levels": [
            {"level": 1, "why": f"为什么发生 {failure_mode}？", "candidate_cause": "工作面温度异常升高", "evidence_hint": "bearing_temp"},
            {"level": 2, "why": "为什么温度异常升高？", "candidate_cause": "润滑油膜失稳", "evidence_hint": "oil_seepage"},
            {"level": 3, "why": "为什么润滑油膜失稳？", "candidate_cause": "密封件渗漏导致油位下降", "evidence_hint": "INSP-2026-014"},
            {"level": 4, "why": "为什么密封件渗漏？", "candidate_cause": "密封件超过设计使用周期", "evidence_hint": "seal-MFP-22"},
            {"level": 5, "why": "为什么超期未更换？", "candidate_cause": "巡检与备件管理未触发更换工单", "evidence_hint": "MR-2025-1115"},
        ],
    }


def _fishbone_seed(failure_mode: str) -> dict:
    """6-category fishbone skeleton (人/机/料/法/环/测)."""
    return {
        "method": "fishbone",
        "root_failure": failure_mode,
        "branches": [
            {
                "category": "人",
                "items": [
                    {"label": "巡检员对振动手测阈值不熟悉", "weight": "medium", "evidence_hint": "INSP-2026-021"},
                ],
            },
            {
                "category": "机",
                "items": [
                    {"label": "轴承已达期望寿命 50%", "weight": "high", "evidence_hint": "bearing-6308"},
                    {"label": "传感器零点漂移", "weight": "low", "evidence_hint": "MR-2026-0418"},
                ],
            },
            {
                "category": "料",
                "items": [
                    {"label": "润滑油牌号是否匹配工况未确认", "weight": "medium", "evidence_hint": "MR-2026-0301"},
                ],
            },
            {
                "category": "法",
                "items": [
                    {"label": "巡检表未覆盖油位检查", "weight": "high", "evidence_hint": "INSP-2026-014"},
                ],
            },
            {
                "category": "环",
                "items": [
                    {"label": "环境温度 32℃，接近设计上限", "weight": "medium", "evidence_hint": "environment"},
                ],
            },
            {
                "category": "测",
                "items": [
                    {"label": "未做油液实测", "weight": "low", "evidence_hint": "未接入"},
                ],
            },
        ],
    }


def _fmea_seed(failure_mode: str) -> dict:
    """FMEA seed rows with severity/occurrence/detection values + RPN.

    RPN = severity × occurrence × detection (FMEA standard).
    """
    rows = [
        {
            "id": "FMEA-001",
            "mode": "润滑不足导致轴承磨损",
            "effect": "运行率下降、温度异常",
            "cause": "密封件老化渗油",
            "severity": 8,
            "occurrence": 4,
            "detection": 6,
            "current_controls": "季度换油 + 周振动监测",
            "evidence_hint": "INSP-2026-014",
        },
        {
            "id": "FMEA-002",
            "mode": "动不平衡引发振动加剧",
            "effect": "轴承疲劳",
            "cause": "联轴器对中漂移",
            "severity": 7,
            "occurrence": 3,
            "detection": 4,
            "current_controls": "年度大修对中复测",
            "evidence_hint": "MR-2025-1115",
        },
        {
            "id": "FMEA-003",
            "mode": "传感器零点漂移导致漏报",
            "effect": "告警延迟",
            "cause": "传感器寿命接近",
            "severity": 5,
            "occurrence": 5,
            "detection": 8,
            "current_controls": "校准任务但频率偏低",
            "evidence_hint": "MR-2026-0418",
        },
    ]
    for r in rows:
        r["rpn"] = r["severity"] * r["occurrence"] * r["detection"]
    return {"method": "fmea", "root_failure": failure_mode, "rows": rows}


def main() -> int:
    parser = base_parser("Failure-analysis demo data")
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--asset-name", default="", help="Asset name (falls back to ID when empty)")
    parser.add_argument("--failure-mode", required=True)
    parser.add_argument("--analysis-method", default="five_why")
    parser.add_argument("--evidence-range", default="")
    args = parser.parse_args()

    method = args.analysis_method
    if method not in VALID_METHODS:
        return emit_error(
            "INVALID_METHOD",
            f"analysis_method must be one of {sorted(VALID_METHODS)}, got {method!r}",
        )

    asset_id = args.asset_id.strip()
    if not asset_id:
        return emit_error("INVALID_ASSET_ID", "--asset-id must be non-empty")
    asset_name = (args.asset_name or "").strip() or None
    failure_mode = args.failure_mode.strip()
    if not failure_mode:
        return emit_error("INVALID_FAILURE_MODE", "--failure-mode must be non-empty")

    today = date.today()
    result = fetch_with_fallback(
        source="failure_data",
        fetch_args={
            "asset_id": asset_id,
            "failure_mode": failure_mode,
            "analysis_method": method,
            "evidence_range": args.evidence_range,
        },
    )
    payload = result.data
    output = {
        "schema_version": SCHEMA_VERSION,
        "asset_id": asset_id,
        "asset_name": asset_name or asset_id,
        "failure_mode": failure_mode,
        "analysis_method": method,
        "evidence_range_raw": args.evidence_range,
        "data_source": result.data_source,
        "operations": payload.get("operations") or [],
        "maintenance": payload.get("maintenance") or [],
        "inspections": payload.get("inspections") or [],
        "spares": payload.get("spares") or [],
        "environment": payload.get("environment") or {},
        "method_seed": payload.get("method_seed") or {
            "five_why": None, "fishbone": None, "fmea": None,
        },
        "_meta": {"stub": True, "generated_at": iso_now(), "fetched_at": today.isoformat(), "provider_notes": result.notes},
    }
    write_json(Path(args.output_dir), "failure_data", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
