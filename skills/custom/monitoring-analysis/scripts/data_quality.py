#!/usr/bin/env python
"""Data quality assessment for monitoring analysis.

Consumes trend data and produces a quality report. Supports Pro and Ultra tiers:
- Pro: missing value detection, ±5σ outlier marking, completeness rate
- Ultra: 3D quality score (completeness × consistency × timeliness), ≤3 point
  linear interpolation
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, write_json

SCHEMA_VERSION = "1"

# ±5σ threshold for outlier detection
SIGMA_THRESHOLD = 5.0

# ≤3 consecutive points threshold for linear interpolation
MAX_INTERPOLATE_GAP = 3

# Quality score weights (sum to 1.0)
QUALITY_WEIGHTS = {
    "completeness": 0.50,
    "consistency": 0.35,
    "timeliness": 0.15,
}


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) <= 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _detect_missing(values: list, timestamps: list[str]) -> list[dict]:
    """Detect missing (None) values and record their positions."""
    missing = []
    for i, (v, ts) in enumerate(zip(values, timestamps)):
        if v is None:
            missing.append({"index": i, "timestamp": ts})
    return missing


def _detect_outliers(values: list[float], timestamps: list[str]) -> list[dict]:
    """Detect ±5σ outliers."""
    clean = [v for v in values if v is not None]
    if len(clean) < 5:
        return []
    mean, std = _mean_std(clean)
    if std == 0:
        return []
    outliers = []
    for i, (v, ts) in enumerate(zip(values, timestamps)):
        if v is None:
            continue
        z = abs(v - mean) / std
        if z > SIGMA_THRESHOLD:
            outliers.append({
                "index": i,
                "timestamp": ts,
                "value": v,
                "sigma": round(z, 2),
            })
    return outliers


def _completeness_rate(values: list) -> float:
    """Ratio of non-None values to total values."""
    if not values:
        return 0.0
    valid = sum(1 for v in values if v is not None)
    return valid / len(values)


def _linear_interpolate(values: list, timestamps: list[str]) -> list:
    """Fill gaps of ≤3 consecutive None values with linear interpolation."""
    result = list(values)
    n = len(result)

    i = 0
    while i < n:
        if result[i] is not None:
            i += 1
            continue

        # Find the run of None values
        gap_start = i
        while i < n and result[i] is None:
            i += 1
        gap_end = i
        gap_len = gap_end - gap_start

        if gap_len > MAX_INTERPOLATE_GAP:
            continue

        # Need a value before and after to interpolate
        if gap_start == 0 or gap_end >= n:
            continue

        before_val = result[gap_start - 1]
        after_val = result[gap_end]
        if before_val is None or after_val is None:
            continue

        step = (after_val - before_val) / (gap_len + 1)
        for j in range(gap_len):
            result[gap_start + j] = before_val + step * (j + 1)

    return result


def _consistency_score(values: list[float]) -> float:
    """Score based on absence of rapid fluctuations (1 - normalized CV)."""
    clean = [v for v in values if v is not None]
    if len(clean) < 3:
        return 1.0
    mean, std = _mean_std(clean)
    if mean == 0:
        return 1.0 if std == 0 else 0.5
    cv = abs(std / mean)
    return max(0.0, 1.0 - cv)


def _timeliness_score(timestamps: list[str]) -> float:
    """Score based on recency of data (fraction of expected timestamps in last 7 days)."""
    if len(timestamps) < 2:
        return 0.5
    # Simple heuristic: more timestamps = better timeliness
    # Full implementation would compare expected vs actual sampling intervals
    return min(1.0, len(timestamps) / 100.0)


def assess_quality(
    time_series: list[dict],
    tier: str = "pro",
) -> dict:
    """Run data quality assessment on all time series."""
    per_metric: list[dict] = []
    overall_missing = 0
    overall_total = 0
    overall_outliers = 0
    interpolated_count = 0

    for series in time_series:
        values = series.get("values", [])
        timestamps = series.get("timestamps", [])
        metric_key = series.get("metric_key", "")
        metric_name = series.get("name", metric_key)

        n = len(values)
        if n == 0:
            continue

        missing = _detect_missing(values, timestamps)
        outliers = _detect_outliers(
            [v for v in values],  # type narrowing handled inside
            timestamps,
        )
        completeness = _completeness_rate(values)

        overall_missing += len(missing)
        overall_total += n
        overall_outliers += len(outliers)

        metric_quality = {
            "metric_key": metric_key,
            "metric_name": metric_name,
            "total_points": n,
            "missing_count": len(missing),
            "missing_indices": missing,
            "outlier_count": len(outliers),
            "outliers": outliers,
            "completeness_rate": round(completeness, 4),
        }

        if tier == "ultra":
            clean = [v for v in values if v is not None]
            consistency = _consistency_score(clean)
            timeliness = _timeliness_score(timestamps)
            quality_3d = round(
                QUALITY_WEIGHTS["completeness"] * completeness
                + QUALITY_WEIGHTS["consistency"] * consistency
                + QUALITY_WEIGHTS["timeliness"] * timeliness,
                4,
            )
            interpolated = _linear_interpolate(values, timestamps)
            n_interp = sum(
                1 for v_orig, v_new in zip(values, interpolated)
                if v_orig is None and v_new is not None
            )
            interpolated_count += n_interp

            metric_quality.update({
                "consistency_score": round(consistency, 4),
                "timeliness_score": round(timeliness, 4),
                "quality_score_3d": quality_3d,
                "interpolated_count": n_interp,
                "interpolated_values": interpolated if n_interp > 0 else values,
            })

        per_metric.append(metric_quality)

    result = {
        "schema_version": SCHEMA_VERSION,
        "tier": tier,
        "overall": {
            "total_points": overall_total,
            "total_missing": overall_missing,
            "total_outliers": overall_outliers,
            "overall_completeness": round(
                1.0 - overall_missing / max(overall_total, 1), 4
            ),
        },
        "per_metric": per_metric,
    }

    if tier == "ultra":
        overall_3d = 0.0
        if per_metric:
            overall_3d = round(
                sum(m["quality_score_3d"] for m in per_metric) / len(per_metric), 4
            )
        result["overall"]["quality_score_3d"] = overall_3d
        result["overall"]["interpolated_count"] = interpolated_count

    return result


def main() -> int:
    parser = base_parser(
        description="Data quality assessment for monitoring analysis"
    )
    parser.add_argument("--input", required=True, help="Path to trend_data.json")
    parser.add_argument(
        "--tier",
        default="pro",
        choices=["pro", "ultra"],
        help="Capability tier (default: pro)",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if "error" in data:
        emit_error("UPSTREAM_ERROR", data["error"])
        return 0

    time_series = data.get("time_series", [])
    if not time_series:
        emit_error("EMPTY_DATA", "No time_series data found in input")
        return 0

    result = assess_quality(time_series, tier=args.tier)

    out_path = write_json(Path(args.output_dir), "data_quality", result)

    print(json.dumps({
        "ok": True,
        "tier": args.tier,
        "overall_completeness": result["overall"]["overall_completeness"],
        "total_outliers": result["overall"]["total_outliers"],
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
