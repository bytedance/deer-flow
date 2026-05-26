#!/usr/bin/env python
"""Ultra-tier spectrum analysis: ONNX CNN classification, combined verdict, fault evolution.

Consumes ``waveform_data.json`` and ``spectrum_features.json``, produces
``ultra_spectrum_result.json``. Falls back to Pro methods when ONNX model is unavailable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, read_json, write_json
from _model_loader import load_model, model_available

SCHEMA_VERSION = "2"

BEARING_FAULT_ORDERS = {
    "BPFO": {"label": "外圈故障 (BPFO)", "order_factor": 3.1},
    "BPFI": {"label": "内圈故障 (BPFI)", "order_factor": 4.9},
    "BSF": {"label": "滚动体故障 (BSF)", "order_factor": 2.0},
    "FTF": {"label": "保持架故障 (FTF)", "order_factor": 0.4},
}

CNN_CLASS_LABELS = [
    "normal",
    "unbalance",
    "misalignment",
    "bearing_outer_race",
    "bearing_inner_race",
    "bearing_ball",
    "gear_mesh",
    "looseness",
    "resonance",
]


def _check_dependencies():
    missing = []
    try:
        import scipy  # noqa: F401
    except ImportError:
        missing.append("scipy")
    return len(missing) == 0, missing


def _bearing_fault_match(
    speed_hz: float | None,
    spec_freqs: list[float],
    spec_mags: list[float],
) -> list[dict]:
    """Pro bearing fault matching (inline for independence)."""
    if speed_hz is None or speed_hz <= 0:
        return []

    matches = []
    for fault_key, fault_info in BEARING_FAULT_ORDERS.items():
        target_freq = speed_hz * fault_info["order_factor"]
        best_idx = None
        best_dist = float("inf")
        for i, f in enumerate(spec_freqs):
            if f <= 0:
                continue
            dist = abs(f - target_freq) / target_freq
            if dist < 0.05 and dist < best_dist:
                best_dist = dist
                best_idx = i

        if best_idx is not None:
            matches.append({
                "fault_type": fault_key,
                "fault_label": fault_info["label"],
                "target_freq_hz": round(target_freq, 2),
                "measured_freq_hz": round(spec_freqs[best_idx], 2),
                "deviation_pct": round(best_dist * 100, 1),
                "amplitude": round(spec_mags[best_idx], 4),
            })

    matches.sort(key=lambda m: m["deviation_pct"])
    return matches


def _onnx_cnn_classify(spec_mags: list[float]) -> dict | None:
    """Classify spectrum using ONNX CNN model."""
    model = load_model("spectrum_classifier")
    if model is None:
        return None

    import numpy as np

    try:
        session = model["session"]
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name

        # Resize/pad to expected input size (1024 frequency bins)
        target_bins = 1024
        if len(spec_mags) < target_bins:
            padded = list(spec_mags) + [0.0] * (target_bins - len(spec_mags))
        else:
            padded = list(spec_mags)[:target_bins]

        X = np.array([padded], dtype=np.float32)
        logits = session.run([output_name], {input_name: X})[0][0]

        # Softmax
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / np.sum(exp_logits)

        top_idx = int(np.argmax(probs))
        top_prob = float(probs[top_idx])

        # Map to class label
        top_label = CNN_CLASS_LABELS[top_idx] if top_idx < len(CNN_CLASS_LABELS) else f"class_{top_idx}"

        probs_detail = []
        for idx in np.argsort(-probs)[:3]:
            lbl = CNN_CLASS_LABELS[idx] if idx < len(CNN_CLASS_LABELS) else f"class_{idx}"
            probs_detail.append({
                "class": lbl,
                "class_id": int(idx),
                "probability": round(float(probs[idx]), 4),
            })

        return {
            "cnn_classification": top_label,
            "cnn_confidence": round(top_prob, 4),
            "cnn_top3": probs_detail,
            "model_fallback": False,
        }
    except Exception:
        return None


def _combined_verdict(rule_matches: list[dict], cnn_result: dict | None) -> dict:
    """Combine rule-based bearing matching with CNN classification."""
    verdicts = []

    # Rule-based verdict
    if rule_matches:
        best_rule = rule_matches[0]
        verdicts.append({
            "source": "rule_based",
            "fault": best_rule["fault_label"],
            "confidence": max(0.0, 1.0 - best_rule["deviation_pct"] / 100.0),
            "detail": best_rule,
        })

    # CNN verdict
    if cnn_result and cnn_result.get("cnn_confidence", 0) >= 0.5:
        verdicts.append({
            "source": "cnn",
            "fault": cnn_result["cnn_classification"],
            "confidence": cnn_result["cnn_confidence"],
            "detail": cnn_result.get("cnn_top3", []),
        })

    # Combine
    if not verdicts:
        return {"combined_fault": "未检测到明显故障特征", "confidence": 0.0, "verdicts": []}

    # If both agree, increase confidence
    if len(verdicts) == 2:
        # Simple agreement check — if CNN top class maps to same fault family
        rule_fault = verdicts[0]["fault"]
        cnn_fault = verdicts[1]["fault"]
        # Map CNN class labels to bearing fault families
        bearing_cnn_labels = {"bearing_outer_race", "bearing_inner_race", "bearing_ball"}
        rule_is_bearing = "外圈" in rule_fault or "内圈" in rule_fault or "滚动体" in rule_fault

        if rule_is_bearing and cnn_fault in bearing_cnn_labels:
            combined_conf = (verdicts[0]["confidence"] + verdicts[1]["confidence"]) / 2
            return {
                "combined_fault": rule_fault,
                "confidence": round(combined_conf, 4),
                "agreement": "both",
                "verdicts": verdicts,
            }

    # Default: use highest confidence
    best = max(verdicts, key=lambda v: v["confidence"])
    return {
        "combined_fault": best["fault"],
        "confidence": best["confidence"],
        "agreement": "single_source",
        "verdicts": verdicts,
    }


def _fault_evolution(
    current_matches: list[dict],
    historical_spectrum: dict | None,
) -> list[dict]:
    """Track fault feature evolution over time."""
    if not current_matches or not historical_spectrum:
        return []

    prev_matches = historical_spectrum.get("bearing_fault_match", [])
    if not prev_matches:
        return []

    evolution = []
    prev_map = {m["fault_type"]: m for m in prev_matches}

    for current in current_matches:
        ft = current["fault_type"]
        if ft in prev_map:
            prev = prev_map[ft]
            amp_change = current["amplitude"] - prev["amplitude"]
            freq_shift = current["measured_freq_hz"] - prev["measured_freq_hz"]

            trend = "stable"
            if amp_change > 0.1 * prev["amplitude"]:
                trend = "worsening"
            elif amp_change < -0.1 * prev["amplitude"]:
                trend = "improving"

            evolution.append({
                "fault_type": ft,
                "fault_label": current["fault_label"],
                "amplitude_change": round(amp_change, 4),
                "amplitude_change_pct": round(amp_change / max(prev["amplitude"], 1e-6) * 100, 1),
                "frequency_shift_hz": round(freq_shift, 2),
                "trend": trend,
            })
        else:
            evolution.append({
                "fault_type": ft,
                "fault_label": current["fault_label"],
                "trend": "new",
                "current_amplitude": current["amplitude"],
            })

    return evolution


def analyze_spectrum_ultra(
    waveform_data: dict,
    spectrum_features: dict,
    equipment_type: str = "",
) -> dict:
    """Ultra-tier spectrum analysis."""
    use_onnx = model_available("spectrum_classifier")
    speed_hz = spectrum_features.get("speed_hz") or waveform_data.get("speed_hz")
    points = waveform_data.get("points", [])

    per_point: list[dict] = []

    for point in points:
        point_id = point.get("point_id", "")
        spec_x = point.get("spec_x") or point.get("data", {}).get("spec_x", [])
        spec_y = point.get("spec_y") or point.get("data", {}).get("spec_y", [])

        if len(spec_y) < 16:
            continue

        # Pro bearing fault matching
        rule_matches = _bearing_fault_match(speed_hz, spec_x, spec_y)

        # CNN classification
        cnn_result = _onnx_cnn_classify(spec_y) if use_onnx else None

        # Combined verdict
        verdict = _combined_verdict(rule_matches, cnn_result)

        per_point.append({
            "point_id": point_id,
            "bearing_fault_match": rule_matches,
            "cnn_classification": cnn_result,
            "verdict": verdict,
        })

    # Fault evolution (peer comparison across points for same equipment)
    fault_evolution: list[dict] = []
    if len(per_point) >= 2:
        # Compare first and last point as a simple evolution track
        first = per_point[0]
        last = per_point[-1]
        evolution = _fault_evolution(
            last.get("bearing_fault_match", []),
            {"bearing_fault_match": first.get("bearing_fault_match", [])},
        )
        fault_evolution = evolution

    return {
        "schema_version": SCHEMA_VERSION,
        "speed_hz": speed_hz,
        "model_fallback": not use_onnx,
        "onnx_used": use_onnx,
        "per_point": per_point,
        "fault_evolution": fault_evolution,
        "equipment_type": equipment_type,
    }


def main() -> int:
    parser = base_parser(description="Ultra-tier spectrum analysis")
    parser.add_argument("--input", required=True, help="Path to waveform_data.json")
    parser.add_argument("--features", required=True, help="Path to spectrum_features.json")
    parser.add_argument("--equipment-type", default="", help="Equipment type")
    args = parser.parse_args()

    ok, missing = _check_dependencies()
    if not ok:
        emit_error(
            "DEPENDENCY_MISSING",
            f"Ultra dependencies not installed: {', '.join(missing)}. "
            "Install with: pip install scipy",
        )
        return 0

    wf = read_json(Path(args.input))
    if wf is None:
        emit_error("BAD_INPUT", f"Failed to read {args.input}")
        return 0

    sf = read_json(Path(args.features))
    if sf is None:
        emit_error("BAD_INPUT", f"Failed to read {args.features}")
        return 0

    result = analyze_spectrum_ultra(wf, sf, equipment_type=args.equipment_type)

    out_path = write_json(Path(args.output_dir), "ultra_spectrum_result", result)

    print(json.dumps({
        "ok": True,
        "points_analyzed": len(result["per_point"]),
        "onnx_used": result["onnx_used"],
        "evolution_tracked": len(result["fault_evolution"]),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
