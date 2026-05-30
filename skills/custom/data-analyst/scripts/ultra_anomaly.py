#!/usr/bin/env python
"""Ultra-tier anomaly detection: ONNX Autoencoder, cross-validation, fault signature root cause.

Consumes ``trend_data.json``, produces ``ultra_anomaly_result.json``.
Falls back to Pro methods when ONNX model is unavailable.
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

THRESHOLDS = {
    "vibration_level": {"upper": 7.1, "warning_ratio": 0.8},
    "temperature": {"upper": 85, "warning_ratio": 0.8},
    "pressure": {"upper": 2.5, "lower": 0.5, "warning_ratio": 0.8},
    "flow_rate": {"lower": 50, "warning_ratio": 0.8},
    "corrosion_rate": {"upper": 0.5, "warning_ratio": 0.8},
}

# Fault signature patterns: (metric, direction) → possible root causes
FAULT_SIGNATURES = {
    ("vibration_level", "high"): [
        {"cause": "转子不平衡", "confidence": 0.85, "evidence": "振动烈度持续偏高"},
        {"cause": "轴承磨损", "confidence": 0.75, "evidence": "振动烈度上升伴随温度升高"},
        {"cause": "联轴器不对中", "confidence": 0.65, "evidence": "振动烈度波动异常"},
    ],
    ("temperature", "high"): [
        {"cause": "润滑不足", "confidence": 0.80, "evidence": "温度升高且振动同步上升"},
        {"cause": "冷却系统故障", "confidence": 0.70, "evidence": "温度单独快速上升"},
        {"cause": "过载运行", "confidence": 0.65, "evidence": "温度升高伴随负荷增大"},
    ],
    ("pressure", "high"): [
        {"cause": "管路堵塞", "confidence": 0.80, "evidence": "压力偏高且流量偏低"},
        {"cause": "阀门故障", "confidence": 0.70, "evidence": "压力波动异常"},
    ],
    ("pressure", "low"): [
        {"cause": "泄漏", "confidence": 0.85, "evidence": "压力持续偏低"},
        {"cause": "泵故障", "confidence": 0.75, "evidence": "压力偏低伴随流量下降"},
    ],
    ("flow_rate", "low"): [
        {"cause": "过滤器堵塞", "confidence": 0.80, "evidence": "流量下降且压差增大"},
        {"cause": "泵效率下降", "confidence": 0.70, "evidence": "流量下降伴随电流增大"},
    ],
    ("corrosion_rate", "high"): [
        {"cause": "介质腐蚀性增强", "confidence": 0.75, "evidence": "腐蚀速率持续上升"},
        {"cause": "防腐层失效", "confidence": 0.70, "evidence": "腐蚀速率突然增大"},
    ],
}


def _check_dependencies():
    missing = []
    try:
        import sklearn  # noqa: F401
    except ImportError:
        missing.append("scikit-learn")
    return len(missing) == 0, missing


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) <= 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _onnx_autoencoder_score(multivariate: list[list[float]]) -> dict | None:
    """Score anomalies via Autoencoder reconstruction error. Returns per-row scores."""
    model = load_model("anomaly_autoencoder")
    if model is None:
        return None

    import numpy as np

    try:
        session = model["session"]
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name

        X = np.array(multivariate, dtype=np.float32)
        recon = session.run([output_name], {input_name: X})[0]
        mse = np.mean((X - recon) ** 2, axis=1)

        threshold = np.percentile(mse, 95)
        anomaly_mask = mse > threshold

        return {
            "reconstruction_error": mse.tolist(),
            "threshold": float(threshold),
            "anomaly_indices": [int(i) for i, v in enumerate(anomaly_mask) if v],
            "model_fallback": False,
        }
    except Exception:
        return None


def _pro_anomaly_detect(values: list[float]) -> list[int]:
    """Isolation Forest anomaly detection (Pro fallback)."""
    try:
        from sklearn.ensemble import IsolationForest
        import numpy as np
    except ImportError:
        return []

    clean = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(clean) < 10:
        return []

    indices, vals = zip(*clean)
    X = np.array(vals).reshape(-1, 1)
    model = IsolationForest(contamination=0.05, random_state=42)
    preds = model.fit_predict(X)
    return [indices[i] for i, p in enumerate(preds) if p == -1]


def _cross_validate(
    timestamp: str,
    all_anomalies: list[dict],
    metrics_available: set[str],
) -> dict:
    """Cross-validate anomalies across multiple sensors."""
    same_ts = [a for a in all_anomalies if a["timestamp"] == timestamp]
    metric_count = len(set(a["metric_key"] for a in same_ts))
    total_metrics = len(metrics_available)

    if metric_count >= 2:
        return {
            "cross_validated": True,
            "confidence": "high",
            "supporting_metrics": metric_count,
            "total_metrics": total_metrics,
            "rationale": f"{metric_count} 个指标同时异常，降低误报概率",
        }
    else:
        return {
            "cross_validated": False,
            "confidence": "medium",
            "supporting_metrics": 1,
            "total_metrics": total_metrics,
            "rationale": "单指标异常，建议结合趋势判断",
        }


def _root_cause_ranking(anomalies: list[dict]) -> list[dict]:
    """Rank potential root causes by matching fault signatures."""
    anomaly_map: dict[str, list[str]] = {}
    for a in anomalies:
        anomaly_map.setdefault(a["metric_key"], []).append(a.get("direction", "high"))

    causes: dict[str, float] = {}
    evidence_map: dict[str, list[str]] = {}

    for metric_key, directions in anomaly_map.items():
        for direction in set(directions):
            patterns = FAULT_SIGNATURES.get((metric_key, direction), [])
            for pattern in patterns:
                name = pattern["cause"]
                causes[name] = causes.get(name, 0) + pattern["confidence"]
                evidence_map.setdefault(name, []).append(pattern["evidence"])

    ranked = sorted(causes.items(), key=lambda x: x[1], reverse=True)
    return [
        {
            "rank": i + 1,
            "cause": cause,
            "score": round(score, 2),
            "confidence": "high" if score >= 1.5 else "medium" if score >= 0.8 else "low",
            "evidence": evidence_map.get(cause, []),
        }
        for i, (cause, score) in enumerate(ranked[:5])
    ]


def analyze_anomaly_ultra(time_series: list[dict]) -> dict:
    """Ultra-tier anomaly detection with ONNX fallback."""
    use_onnx = model_available("anomaly_autoencoder")
    model_fallback = not use_onnx

    # Build multivariate matrix for Autoencoder
    metrics_keys = []
    metrics_values: list[list[float]] = []
    for series in time_series:
        values = series.get("values", [])
        metric_key = series.get("metric_key", "")
        if len([v for v in values if v is not None]) < 5:
            continue
        metrics_keys.append(metric_key)
        metrics_values.append(values)

    # Autoencoder scoring
    ae_result = None
    if use_onnx and len(metrics_keys) >= 2:
        min_len = min(len(v) for v in metrics_values)
        aligned = []
        for i in range(min_len):
            row = [metrics_values[j][i] if metrics_values[j][i] is not None else 0.0
                   for j in range(len(metrics_keys))]
            aligned.append(row)
        ae_result = _onnx_autoencoder_score(aligned)

    metrics_available = set(metrics_keys)
    all_anomalies: list[dict] = []

    for idx, series in enumerate(time_series):
        values = series.get("values", [])
        timestamps = series.get("timestamps", [])
        metric_key = series.get("metric_key", f"metric_{idx}")
        metric_name = series.get("name", metric_key)
        unit = series.get("unit", "")

        clean_vals = [v for v in values if v is not None]
        if len(clean_vals) < 5:
            continue

        tconf = THRESHOLDS.get(metric_key, {})
        alarm_upper = tconf.get("upper")
        alarm_lower = tconf.get("lower")
        warn_ratio = tconf.get("warning_ratio", 0.8)

        # Pro detection (threshold + iforest)
        iforest_indices = set(_pro_anomaly_detect(values))

        for i, v in enumerate(values):
            if v is None:
                continue

            severity = None
            methods = []

            # Threshold check
            if alarm_upper is not None and v > alarm_upper:
                severity = "critical"
                methods.append("threshold")
            elif alarm_lower is not None and v < alarm_lower:
                severity = "critical"
                methods.append("threshold")
            elif alarm_upper is not None and v > alarm_upper * warn_ratio:
                if severity is None:
                    severity = "warning"
                methods.append("threshold")

            # Isolation Forest
            if i in iforest_indices:
                if severity is None:
                    severity = "warning"
                methods.append("iforest")

            # Autoencoder
            if ae_result and i in set(ae_result.get("anomaly_indices", [])):
                if severity is None:
                    severity = "warning"
                methods.append("autoencoder")

            if severity:
                deviation = 0.0
                if alarm_upper:
                    deviation = (v - alarm_upper) / alarm_upper * 100
                elif alarm_lower:
                    deviation = (alarm_lower - v) / max(alarm_lower, 0.001) * 100

                direction = "high" if alarm_upper and v > alarm_upper else "low"

                all_anomalies.append({
                    "timestamp": timestamps[i] if i < len(timestamps) else str(i),
                    "metric_key": metric_key,
                    "metric_name": metric_name,
                    "value": v,
                    "unit": unit,
                    "threshold_upper": alarm_upper,
                    "threshold_lower": alarm_lower,
                    "deviation_pct": round(deviation, 1),
                    "severity": severity,
                    "methods": methods,
                    "direction": direction,
                })

    # Cross-validation enrichment
    for a in all_anomalies:
        cv = _cross_validate(a["timestamp"], all_anomalies, metrics_available)
        a.update(cv)

    # Root cause ranking
    root_causes = _root_cause_ranking(all_anomalies)

    # Anomaly summary
    by_metric: dict[str, int] = {}
    by_severity = {"critical": 0, "warning": 0}
    for a in all_anomalies:
        by_metric[a["metric_key"]] = by_metric.get(a["metric_key"], 0) + 1
        by_severity[a["severity"]] = by_severity.get(a["severity"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "model_fallback": model_fallback,
        "onnx_used": use_onnx,
        "anomalies": all_anomalies,
        "total": len(all_anomalies),
        "by_metric": by_metric,
        "by_severity": by_severity,
        "root_cause_ranking": root_causes,
        "autoencoder": {
            "available": ae_result is not None,
            "threshold": ae_result.get("threshold") if ae_result else None,
            "anomaly_count": len(ae_result.get("anomaly_indices", [])) if ae_result else 0,
        } if ae_result or not use_onnx else None,
    }


def main() -> int:
    parser = base_parser(description="Ultra-tier anomaly detection")
    parser.add_argument("--input", required=True, help="Path to trend_data.json")
    args = parser.parse_args()

    ok, missing = _check_dependencies()
    if not ok:
        emit_error(
            "DEPENDENCY_MISSING",
            f"Ultra dependencies not installed: {', '.join(missing)}. "
            "Install with: pip install scikit-learn",
        )
        return 0

    data = read_json(Path(args.input))
    if data is None:
        emit_error("BAD_INPUT", f"Failed to read {args.input}")
        return 0
    if "error" in data:
        emit_error("UPSTREAM_ERROR", data["error"])
        return 0

    time_series = data.get("time_series", [])
    if not time_series:
        emit_error("EMPTY_DATA", "No time_series in input")
        return 0

    result = analyze_anomaly_ultra(time_series)

    out_path = write_json(Path(args.output_dir), "ultra_anomaly_result", result)

    print(json.dumps({
        "ok": True,
        "anomalies_found": result["total"],
        "onnx_used": result["onnx_used"],
        "root_causes": len(result["root_cause_ranking"]),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
