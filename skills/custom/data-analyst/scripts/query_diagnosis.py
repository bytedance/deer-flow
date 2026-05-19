#!/usr/bin/env python
"""Query diagnosis data for fault-diagnosis--{pump,rotating,reciprocating} agents.

This script implements the **first stage** of the fault-diagnosis data pipeline
(see docs/plans/2026-05-18-fault-diagnosis-design.md §4.5 step 2 + §5.1):

- aggregate trend feature pull via the InS skill chain
  (``ins-extract-trend-features``)
- write a single ``query_diagnosis.json`` consumed by the second stage
  (``diagnosis_features.py``)

Waveform / spectrum / orbit are NOT pulled here — they are sparse and handled
by the LLM in the second stage (only for points that show anomaly_time_ms).

If the InS toolchain is not available (sandbox without ``features-tool/``,
network failure, or unknown machine ID), the script falls back to deterministic
demo data so the agent pipeline can be exercised end-to-end. The output JSON
records ``data_source`` ("ins" / "demo_fallback") and accumulates every
non-fatal error into ``warnings[]``.

Output contract (design doc §7.1)::

    {
      "kind": "centrifugal_pump",
      "equipment_ids": ["PUMP-A-001"],
      "time_window": {"start": "...", "end": "..."},
      "compare_window": {"start": "...", "end": "..."} | null,
      "mode": "oneoff" | "screening",
      "data_source": "ins" | "demo_fallback",
      "warnings": [],
      "points": [...],
      "process_signals": {...},
      "compare": {...} | null,
    }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILENAME = "query_diagnosis.json"

EQUIPMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ISO_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")

VALID_KINDS = {
    "centrifugal_pump",
    "positive_displacement_pump",
    "steam_turbine",
    "centrifugal_compressor",
    "axial_compressor",
    "geared_compressor",
    "screw_compressor",
    "gearbox",
    "reciprocating_compressor",
    "reciprocating_pump",
}
VALID_MODES = {"oneoff", "screening"}
VALID_COMPARE = {"previous_period", "none"}

# --- Default trend feature lists (per design doc §5.1) ---

ROTATING_AND_PUMP_FEATURES = [
    "pp_value",
    "rms",
    "p_value",
    "speed",
    "gap",
    "one_freq_y",
    "one_freq_x",
    "two_freq_y",
    "two_freq_x",
    "half_freq",
    "remain_freq",
]

RECIPROCATING_EXTRA_FEATURES = ["crank_angle", "cylinder_pressure"]

# Screening mode reduces features to the bare essentials (token control)
SCREENING_FEATURES = ["pp_value", "rms", "one_freq_x"]

# Process signal channels are scoped per equipment kind
PROCESS_CHANNELS_BY_KIND: dict[str, list[tuple[str, str]]] = {
    "centrifugal_pump": [
        ("discharge_pressure", "MPa"),
        ("suction_pressure", "MPa"),
        ("flow_rate", "m3/h"),
        ("motor_current", "A"),
    ],
    "positive_displacement_pump": [
        ("discharge_pressure", "MPa"),
        ("suction_pressure", "MPa"),
        ("flow_rate", "m3/h"),
        ("motor_current", "A"),
    ],
    "steam_turbine": [
        ("inlet_pressure", "MPa"),
        ("inlet_temperature", "℃"),
        ("speed", "rpm"),
        ("axial_displacement", "mm"),
        ("bearing_temperature", "℃"),
    ],
    "centrifugal_compressor": [
        ("inlet_flow", "m3/h"),
        ("anti_surge_valve_opening", "%"),
        ("speed", "rpm"),
        ("axial_displacement", "mm"),
        ("bearing_temperature", "℃"),
    ],
    "axial_compressor": [
        ("inlet_flow", "m3/h"),
        ("anti_surge_valve_opening", "%"),
        ("speed", "rpm"),
        ("axial_displacement", "mm"),
    ],
    "geared_compressor": [
        ("inlet_flow", "m3/h"),
        ("speed", "rpm"),
        ("bearing_temperature", "℃"),
    ],
    "screw_compressor": [
        ("inlet_flow", "m3/h"),
        ("speed", "rpm"),
    ],
    "gearbox": [
        ("speed", "rpm"),
        ("bearing_temperature", "℃"),
    ],
    "reciprocating_compressor": [
        ("crank_angle", "deg"),
        ("cylinder_pressure", "MPa"),
        ("unloader_state", "bool"),
        ("piston_rod_droop", "mm"),
        ("motor_current", "A"),
    ],
    "reciprocating_pump": [
        ("crank_angle", "deg"),
        ("cylinder_pressure", "MPa"),
        ("motor_current", "A"),
    ],
}


def _output_dir() -> Path:
    return Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _ins_skill_root() -> Path:
    """Locate ins-extract-trend-features run.sh.

    Honor INS_SKILL_ROOT for tests; default to ``/mnt/skills/custom/`` (sandbox path).
    """
    return Path(os.environ.get("INS_SKILL_ROOT", "/mnt/skills/custom"))


def _has_ins_toolchain() -> bool:
    """Return True if the InS skill chain is reachable.

    The sandbox path requires both the run.sh wrapper and the underlying
    features-tool repository (resolved via FEATURES_TOOL_ROOT inside run.sh).
    Tests can force-disable by clearing both env vars.
    """
    run_sh = _ins_skill_root() / "ins-extract-trend-features" / "scripts" / "run.sh"
    features_root = Path(os.environ.get("FEATURES_TOOL_ROOT", "/opt/features-tool"))
    return run_sh.exists() and features_root.exists()


# --- Deterministic demo data (mirrors query_daily.py style) ---


def _deterministic_float(seed: str, low: float, high: float) -> float:
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    ratio = int(digest[:8], 16) / 0xFFFFFFFF
    return round(low + ratio * (high - low), 4)


def _deterministic_int(seed: str, low: int, high: int) -> int:
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    ratio = int(digest[:8], 16) / 0xFFFFFFFF
    return int(low + ratio * (high - low + 1))


def _window_anchor_ms(start: str) -> int:
    return int(datetime.fromisoformat(start).timestamp() * 1000)


def _demo_features_for_kind(kind: str, mode: str) -> list[str]:
    if mode == "screening":
        return list(SCREENING_FEATURES)
    base = list(ROTATING_AND_PUMP_FEATURES)
    if kind in {"reciprocating_compressor", "reciprocating_pump"}:
        base += list(RECIPROCATING_EXTRA_FEATURES)
    return base


# CONTINUE_BELOW


def _demo_point(
    kind: str,
    equipment_id: str,
    point_idx: int,
    window: dict,
    mode: str,
) -> dict:
    """Build a single demo trend point payload."""
    features = _demo_features_for_kind(kind, mode)
    seed_root = f"{equipment_id}|{point_idx}|{window['start']}|{window['end']}"
    point_id = f"{equipment_id}-PT{point_idx:03d}"

    if "reciprocating" in kind:
        point_name = ["缸盖振动", "曲轴箱振动", "活塞杆下沉", "电机轴承"][point_idx % 4]
        point_type = 83 if point_idx % 4 < 2 else 82
    else:
        point_name = ["驱动端 X 轴振", "驱动端 Y 轴振", "非驱动端 X 轴振", "非驱动端 Y 轴振", "轴位移"][point_idx % 5]
        point_type = 83 if point_idx % 5 < 4 else 82

    anchor_ms = _window_anchor_ms(window["start"])
    end_ms = _window_anchor_ms(window["end"])
    anomaly_count = _deterministic_int(seed_root + "|anomalies", 0, 3)
    anomaly_time_ms = []
    for i in range(anomaly_count):
        offset_ratio = _deterministic_float(seed_root + f"|amt|{i}", 0.1, 0.9)
        anomaly_time_ms.append(int(anchor_ms + (end_ms - anchor_ms) * offset_ratio))

    notable_points = []
    for i, feature in enumerate(features[:3]):
        seed = seed_root + f"|notable|{feature}|{i}"
        notable_points.append(
            {
                "feature": feature,
                "time_ms": anchor_ms + i * 3600 * 1000,
                "value": _deterministic_float(seed + "|val", 30.0, 50.0),
                "threshold": 35.0,
            }
        )

    return {
        "equipment_id": equipment_id,
        "point_id": point_id,
        "point_name": point_name,
        "point_type": point_type,
        "default_features": features,
        "trend_summary": {
            "summary": f"{point_name} 演示趋势：pp_value 上升明显，1X 主导（mode={mode}）",
            "notable_points": notable_points,
            "anomaly_time_ms": anomaly_time_ms,
        },
    }


def _demo_process_signals(kind: str, window: dict) -> dict:
    channels = PROCESS_CHANNELS_BY_KIND.get(kind, [])
    anchor_ms = _window_anchor_ms(window["start"])
    series_len = 8  # ~ hourly samples for an 8h window; light enough for demo
    out: dict = {}
    for name, unit in channels:
        seed_prefix = f"proc|{kind}|{name}|{window['start']}"
        series = []
        for i in range(series_len):
            ratio = _deterministic_float(seed_prefix + f"|{i}", 0.0, 1.0)
            value = round(0.5 + ratio * 1.5, 4)
            series.append({"time_ms": anchor_ms + i * 3600 * 1000, "value": value})
        out[name] = {"unit": unit, "series": series}
    return out


def _demo_block(
    kind: str,
    equipment_ids: list[str],
    window: dict,
    mode: str,
    points_per_equipment: int = 2,
) -> dict:
    points: list[dict] = []
    for eq_id in equipment_ids:
        for idx in range(points_per_equipment):
            points.append(_demo_point(kind, eq_id, idx, window, mode))
    return {
        "points": points,
        "process_signals": _demo_process_signals(kind, window),
    }


# --- InS toolchain integration ---


def _build_component_features(point_specs: list[dict], mode: str) -> dict:
    """Build the component_features JSON expected by ins-extract-trend-features.

    Each entry is ``{point_id: [feature_names]}``. The default mapping follows
    ``ins-extract-trend-features/SKILL.md``:

    - type=83 shaft vibration: ROTATING_AND_PUMP_FEATURES (or SCREENING_FEATURES)
    - type=82 process measurement: ["value"]
    - type=81 speed: ["speed"]
    """
    base = SCREENING_FEATURES if mode == "screening" else ROTATING_AND_PUMP_FEATURES
    out: dict = {}
    for spec in point_specs:
        ptype = spec.get("point_type")
        pid = spec.get("point_id")
        if not pid:
            continue
        if ptype == 83 and "波形" not in (spec.get("point_name") or ""):
            out[str(pid)] = list(base)
        elif ptype == 82:
            out[str(pid)] = ["value"]
        elif ptype == 81:
            out[str(pid)] = ["speed"]
    return out


def _call_ins_extract_trend(
    component_features: dict,
    start: str,
    end: str,
    timeout_seconds: float = 30.0,
) -> dict:
    """Invoke ins-extract-trend-features run.sh as a subprocess.

    Raises CalledProcessError / TimeoutExpired / FileNotFoundError so the
    caller can fall back to demo data and record the warning.
    """
    run_sh = _ins_skill_root() / "ins-extract-trend-features" / "scripts" / "run.sh"
    if not run_sh.exists():
        raise FileNotFoundError(f"ins-extract-trend-features run.sh not found at {run_sh}")
    cf_json = json.dumps(component_features, ensure_ascii=False)
    bash_path = shutil.which("bash") or "bash"
    proc = subprocess.run(
        [bash_path, str(run_sh), cf_json, start, end],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=True,
    )
    return json.loads(proc.stdout)


# --- Time window helpers ---


def _parse_iso_window(start: str, end: str) -> dict:
    return {"start": start, "end": end}


def _previous_period_window(window: dict) -> dict:
    start = datetime.fromisoformat(window["start"])
    end = datetime.fromisoformat(window["end"])
    span = end - start
    prev_end = start
    prev_start = start - span
    return {
        "start": prev_start.isoformat(timespec="seconds"),
        "end": prev_end.isoformat(timespec="seconds"),
    }


# --- Result builder ---


def fetch_block(
    kind: str,
    equipment_ids: list[str],
    window: dict,
    mode: str,
    warnings: list[str],
    point_specs_by_equipment: dict[str, list[dict]] | None = None,
) -> tuple[dict, str]:
    """Fetch trend features for one window. Returns (block, source).

    ``source`` is "ins" if the InS toolchain succeeded, "demo_fallback"
    otherwise. Demo fallback is also used when ``point_specs_by_equipment``
    is not provided (the LLM only has equipment IDs at the entry point;
    in MVP the script invents demo point specs; later iterations may add
    a device-tree probe via ``ins-device-analysis``).
    """
    if not _has_ins_toolchain() or point_specs_by_equipment is None:
        return _demo_block(kind, equipment_ids, window, mode), "demo_fallback"

    points: list[dict] = []
    component_features: dict = {}
    for eq_id, specs in point_specs_by_equipment.items():
        component_features.update(_build_component_features(specs, mode))
    if not component_features:
        warnings.append("no shaft/process points resolved; using demo data")
        return _demo_block(kind, equipment_ids, window, mode), "demo_fallback"

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            ins_payload = _call_ins_extract_trend(component_features, window["start"], window["end"])
            point_results = ins_payload.get("point_results", {})
            for eq_id, specs in point_specs_by_equipment.items():
                for spec in specs:
                    pid = str(spec.get("point_id"))
                    pr = point_results.get(pid, {})
                    points.append(
                        {
                            "equipment_id": eq_id,
                            "point_id": pid,
                            "point_name": spec.get("point_name"),
                            "point_type": spec.get("point_type"),
                            "default_features": component_features.get(pid, []),
                            "trend_summary": {
                                "summary": pr.get("summary", ""),
                                "notable_points": pr.get("notable_points", []),
                                "anomaly_time_ms": pr.get("anomaly_time_ms", []),
                            },
                        }
                    )
            return (
                {
                    "points": points,
                    "process_signals": _demo_process_signals(kind, window),
                },
                "ins",
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as exc:
            last_error = exc
            continue

    warnings.append(f"ins-extract-trend-features failed twice: {type(last_error).__name__}: {last_error}")
    return _demo_block(kind, equipment_ids, window, mode), "demo_fallback"


def build_result(
    kind: str,
    equipment_ids: list[str],
    start: str,
    end: str,
    mode: str,
    compare: str,
    point_specs_by_equipment: dict[str, list[dict]] | None = None,
    equipment_names: dict[str, str] | None = None,
) -> dict:
    """Build the full payload contracted in design doc §7.1."""
    warnings: list[str] = []
    window = _parse_iso_window(start, end)

    current_block, current_source = fetch_block(
        kind, equipment_ids, window, mode, warnings, point_specs_by_equipment
    )

    compare_window: dict | None = None
    compare_block: dict | None = None
    if compare == "previous_period":
        compare_window = _previous_period_window(window)
        compare_block, _ = fetch_block(
            kind, equipment_ids, compare_window, mode, warnings, point_specs_by_equipment
        )

    name_map = equipment_names or {}
    points = current_block["points"]
    for p in points:
        eid = p.get("equipment_id")
        if eid and eid in name_map:
            p["equipment_name"] = name_map[eid]
    if compare_block is not None:
        for p in compare_block.get("points", []):
            eid = p.get("equipment_id")
            if eid and eid in name_map:
                p["equipment_name"] = name_map[eid]

    return {
        "kind": kind,
        "equipment_ids": equipment_ids,
        "equipment_names": name_map,
        "time_window": window,
        "compare_window": compare_window,
        "mode": mode,
        "data_source": current_source,
        "warnings": warnings,
        "points": points,
        "process_signals": current_block["process_signals"],
        "compare": compare_block,
    }


def write_payload(result: dict) -> Path:
    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# --- CLI argparse + validation ---


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _validate_equipment_ids(equipment_ids: list[str]) -> str | None:
    if not equipment_ids:
        return "--equipment must be a non-empty CSV"
    invalid = [item for item in equipment_ids if not EQUIPMENT_ID_PATTERN.fullmatch(item)]
    if invalid:
        return "--equipment contains invalid equipment id(s): " + ",".join(invalid)
    return None


def _validate_window(start: str, end: str) -> str | None:
    if not ISO_DATETIME_PATTERN.fullmatch(start):
        return f"--start must be ISO datetime YYYY-MM-DDTHH:MM(:SS), got: {start}"
    if not ISO_DATETIME_PATTERN.fullmatch(end):
        return f"--end must be ISO datetime YYYY-MM-DDTHH:MM(:SS), got: {end}"
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as exc:
        return f"invalid datetime: {exc}"
    if end_dt <= start_dt:
        return "--end must be strictly after --start"
    if end_dt - start_dt > timedelta(days=30):
        return "diagnosis window must not exceed 30 days"
    return None


def _error(message: str) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Query diagnosis data (stage 1: aggregate trend features)")
    parser.add_argument("--kind", required=True, help=f"Equipment kind, one of {sorted(VALID_KINDS)}")
    parser.add_argument("--equipment", required=True, help="Comma-separated equipment ids")
    parser.add_argument(
        "--equipment-names",
        default="",
        help="Comma-separated equipment names aligned with --equipment (optional, for display)",
    )
    parser.add_argument("--start", required=True, help="Window start ISO YYYY-MM-DDTHH:MM[:SS]")
    parser.add_argument("--end", required=True, help="Window end ISO YYYY-MM-DDTHH:MM[:SS]")
    parser.add_argument("--mode", default="oneoff", choices=sorted(VALID_MODES))
    parser.add_argument("--compare", default="previous_period", choices=sorted(VALID_COMPARE))
    parser.add_argument("--output", default=None, help="Override output path")
    args = parser.parse_args()

    try:
        if args.kind not in VALID_KINDS:
            return _error(f"--kind must be one of {sorted(VALID_KINDS)}, got: {args.kind}")

        equipment_ids = _dedupe_preserve_order(_parse_csv(args.equipment))
        eq_error = _validate_equipment_ids(equipment_ids)
        if eq_error:
            return _error(eq_error)

        equipment_labels = _parse_csv(args.equipment_names)
        name_map: dict[str, str] = {}
        for eid, label in zip(equipment_ids, equipment_labels):
            if label:
                name_map[eid] = label

        window_error = _validate_window(args.start, args.end)
        if window_error:
            return _error(window_error)

        result = build_result(
            kind=args.kind,
            equipment_ids=equipment_ids,
            start=args.start,
            end=args.end,
            mode=args.mode,
            compare=args.compare,
            equipment_names=name_map or None,
        )

        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            out_path = write_payload(result)
        print(
            json.dumps(
                {
                    "output": str(out_path),
                    "kind": result["kind"],
                    "data_source": result["data_source"],
                    "equipment_count": len(equipment_ids),
                    "warnings": result["warnings"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — script convention: structured stdout
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
