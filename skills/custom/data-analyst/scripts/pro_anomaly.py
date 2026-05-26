#!/usr/bin/env python
"""Pro-tier anomaly detection: Isolation Forest, DBSCAN clustering, adaptive rolling threshold.

Consumes ``trend_data.json`` and produces ``pro_anomaly_result.json``.
Output format is a superset of the Basic anomaly result for report compatibility.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, read_json, write_json

SCHEMA_VERSION = "2"

# Default KPI thresholds (same as Basic for compatibility)
THRESHOLDS = {
    "vibration_level": {"upper": 7.1, "warning_ratio": 0.8},
    "temperature": {"upper": 85, "warning_ratio": 0.8},
    "pressure": {"upper": 2.5, "lower": 0.5, "warning_ratio": 0.8},
    "flow_rate": {"lower": 50, "warning_ratio": 0.8},
    "motor_current": {"upper": 150, "warning_ratio": 0.8},
    "corrosion_rate": {"upper": 0.5, "warning_ratio": 0.8},
}

ROLLING_WINDOW_DAYS = 30


def _check_dependencies():
    missing = []
    try:
        import sklearn  # noqa: F401
    except ImportError:
        missing.append("scikit-learn")
    return len(missing) == 0, missing


def _detect_iforest(values: list[float], contamination: float = 0.05) -> list[int]:
    """Isolation Forest outlier detection. Returns indices of anomalies."""
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
    model = IsolationForest(contamination=contamination, random_state=42)
    preds = model.fit_predict(X)
    scores = model.score_samples(X)

    anomaly_indices = [indices[i] for i, p in enumerate(preds) if p == -1]
    return anomaly_indices


def _dbscan_clusters(
    timestamps: list[str],
    values: list[float],
    anomaly_mask: set[int],
) -> list[dict]:
    """Cluster anomalies with DBSCAN on (index, value) space."""
    try:
        from sklearn.cluster import DBSCAN
        import numpy as np
    except ImportError:
        return []

    anomaly_points = [(i, values[i]) for i in anomaly_mask if values[i] is not None]
    if len(anomaly_points) < 2:
        return []

    indices, vals = zip(*anomaly_points)
    X = np.column_stack([np.array(indices), np.array(vals)])
    # Normalize
    X_norm = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-8)

    clustering = DBSCAN(eps=0.5, min_samples=2).fit(X_norm)
    labels = clustering.labels_

    clusters: dict[int, list[int]] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        clusters.setdefault(int(label), []).append(indices[i])

    return [
        {
            "cluster_id": cid,
            "member_count": len(members),
            "member_indices": members,
            "time_span": (
                f"{timestamps[min(members)]} ~ {timestamps[max(members)]}"
                if timestamps
                else ""
            ),
            "dominant_pattern": (
                "持续恶化" if len(members) >= 3 else "波动异常"
            ),
        }
        for cid, members in sorted(clusters.items())
    ]


def _rolling_threshold(
    values: list[float],
    window: int = ROLLING_WINDOW_DAYS,
) -> dict:
    """Compute adaptive rolling thresholds."""
    clean = [v for v in values if v is not None]
    if len(clean) < window:
        return {"upper": None, "lower": None, "window": window, "insufficient_data": True}

    import numpy as np

    arr = np.array(clean)
    rolling_mean = np.convolve(arr, np.ones(window) / window, mode="valid")
    rolling_std = np.array([np.std(arr[i:i + window]) for i in range(len(arr) - window + 1)])

    # Use the last rolling window's mean ± 3σ
    upper = float(rolling_mean[-1] + 3 * rolling_std[-1]) if len(rolling_mean) > 0 else None
    lower = float(rolling_mean[-1] - 3 * rolling_std[-1]) if len(rolling_mean) > 0 else None

    return {
        "upper": round(upper, 4) if upper is not None else None,
        "lower": round(lower, 4) if lower is not None else None,
        "window": window,
        "insufficient_data": False,
    }


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) <= 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def analyze_anomaly_pro(time_series: list[dict]) -> dict:
    """Pro-tier anomaly detection across all time series."""
    all_anomalies: list[dict] = []
    all_clusters: list[dict] = []
    rolling_thresholds: dict[str, dict] = {}

    for idx, series in enumerate(time_series):
        values = series.get("values", [])
        timestamps = series.get("timestamps", [])
        metric_key = series.get("metric_key", f"metric_{idx}")
        metric_name = series.get("name", metric_key)
        unit = series.get("unit", "")

        if len([v for v in values if v is not None]) < 5:
            continue

        tconf = THRESHOLDS.get(metric_key, {})
        alarm_upper = tconf.get("upper")
        alarm_lower = tconf.get("lower")
        warn_ratio = tconf.get("warning_ratio", 0.8)

        # Isolation Forest
        iforest_indices = set(_detect_iforest(values))

        # Rolling threshold
        rt = _rolling_threshold(values)
        rolling_thresholds[metric_key] = rt
        rt_upper = rt.get("upper")
        rt_lower = rt.get("lower")

        # Combined detection
        for i, v in enumerate(values):
            if v is None:
                continue

            severity = None
            methods = []

            # Threshold check (same as Basic)
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
            elif alarm_lower is not None and v < alarm_lower / warn_ratio:
                if severity is None:
                    severity = "warning"
                methods.append("threshold")

            # Isolation Forest
            if i in iforest_indices:
                if severity is None:
                    severity = "warning"
                methods.append("iforest")

            # Rolling threshold
            if rt_upper is not None and v > rt_upper:
                if severity is None:
                    severity = "warning"
                methods.append("rolling_threshold")
            elif rt_lower is not None and v < rt_lower:
                if severity is None:
                    severity = "warning"
                methods.append("rolling_threshold")

            if severity:
                deviation = 0.0
                if alarm_upper:
                    deviation = (v - alarm_upper) / alarm_upper * 100
                elif alarm_lower:
                    deviation = (alarm_lower - v) / alarm_lower * 100

                # Pattern classification
                pattern = "突跳"
                if i >= 2:
                    prev_anomalous = sum(
                        1 for j in range(max(0, i - 2), i)
                        if values[j] is not None and (
                            (alarm_upper and values[j] > alarm_upper * warn_ratio)
                            or (alarm_lower and values[j] < alarm_lower / warn_ratio)
                        )
                    )
                    if prev_anomalous >= 2:
                        pattern = "持续恶化"
                    elif prev_anomalous == 1:
                        pattern = "波动异常"

                # If only iforest detected, higher artifact risk
                artifact_risk = "possible_sensor_fault" if methods == ["iforest"] else "low"

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
                    "pattern": pattern,
                    "artifact_risk": artifact_risk,
                })

        # DBSCAN clustering on detected anomalies
        anomaly_indices = {
            i for a in all_anomalies
            if a["metric_key"] == metric_key
            for i, ts in enumerate(timestamps)
            if ts == a["timestamp"]
        }
        clusters = _dbscan_clusters(timestamps, values, anomaly_indices)
        for c in clusters:
            c["metric_key"] = metric_key
            c["metric_name"] = metric_name
        all_clusters.extend(clusters)

    # Cross-validation: multi-metric simultaneous anomalies reduce artifact risk
    ts_map: dict[str, list[dict]] = {}
    for a in all_anomalies:
        ts_map.setdefault(a["timestamp"], []).append(a)
    for ts, items in ts_map.items():
        if len(items) >= 2:
            for item in items:
                item["artifact_risk"] = "low"
                item["cross_validated"] = True

    return {
        "schema_version": SCHEMA_VERSION,
        "anomalies": all_anomalies,
        "total": len(all_anomalies),
        "clusters": all_clusters,
        "rolling_thresholds": rolling_thresholds,
    }


def main() -> int:
    parser = base_parser(description="Pro-tier anomaly detection")
    parser.add_argument("--input", required=True, help="Path to trend_data.json")
    args = parser.parse_args()

    ok, missing = _check_dependencies()
    if not ok:
        emit_error(
            "DEPENDENCY_MISSING",
            f"Pro dependencies not installed: {', '.join(missing)}. "
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

    result = analyze_anomaly_pro(time_series)

    out_path = write_json(Path(args.output_dir), "pro_anomaly_result", result)

    print(json.dumps({
        "ok": True,
        "anomalies_found": result["total"],
        "clusters_found": len(result["clusters"]),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
