#!/usr/bin/env python
"""Pro-tier correlation analysis: Spearman/Kendall, lag cross-correlation, partial correlation.

Consumes ``trend_data.json`` and produces ``pro_correlation_result.json``.
Output is a superset of the Basic correlation result.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, read_json, write_json

SCHEMA_VERSION = "2"
MAX_LAG = 7
DISPLAY_NAMES = {
    "runtime_rate": "运行率", "alarm_count": "告警数量", "vibration_level": "振动烈度",
    "temperature": "温度", "pressure": "压力", "flow_rate": "流量",
    "corrosion_rate": "腐蚀速率",
}


def _check_dependencies():
    missing = []
    try:
        import sklearn  # noqa: F401
    except ImportError:
        missing.append("scikit-learn")
    try:
        from scipy import stats  # noqa: F401
    except ImportError:
        missing.append("scipy")
    return len(missing) == 0, missing


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs[:n]))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys[:n]))
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return cov / (sx * sy)


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation."""
    from scipy import stats as sp_stats

    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    try:
        r, _ = sp_stats.spearmanr(xs[:n], ys[:n])
        return float(r) if not math.isnan(r) else 0.0
    except Exception:
        return 0.0


def _kendall(xs: list[float], ys: list[float]) -> float:
    """Kendall tau rank correlation."""
    from scipy import stats as sp_stats

    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    try:
        tau, _ = sp_stats.kendalltau(xs[:n], ys[:n])
        return float(tau) if not math.isnan(tau) else 0.0
    except Exception:
        return 0.0


def _lag_correlation(xs: list[float], ys: list[float], max_lag: int = MAX_LAG) -> list[dict]:
    """Cross-correlation at lags -max_lag to +max_lag."""
    n = min(len(xs), len(ys))
    if n < max_lag * 2 + 3:
        return []

    results = []
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x_seg = xs[-lag:n]
            y_seg = ys[0:n + lag]
        elif lag > 0:
            x_seg = xs[0:n - lag]
            y_seg = ys[lag:n]
        else:
            x_seg = xs[:n]
            y_seg = ys[:n]

        if len(x_seg) < 3:
            continue
        r = _pearson(x_seg, y_seg)
        results.append({"lag": lag, "r": round(r, 4)})

    return results


def _partial_correlation(matrix: list[list[float]], k: int) -> dict[str, float]:
    """Compute partial correlation for variable k controlling all others."""
    n = len(matrix)
    if n <= 2 or k >= n:
        return {}

    try:
        import numpy as np

        corr = np.array(matrix)
        # For each pair (k, j), compute partial correlation controlling others
        partials: dict[str, float] = {}
        for j in range(n):
            if j == k:
                continue
            # Get precision matrix (inverse of correlation submatrix)
            idx = [i for i in range(n) if i not in (k, j)]
            if not idx:
                partials[f"k{k}_j{j}"] = corr[k, j]
                continue

            try:
                sub = corr[np.ix_([k, j] + idx, [k, j] + idx)]
                prec = np.linalg.inv(sub)
                pcorr = -prec[0, 1] / math.sqrt(prec[0, 0] * prec[1, 1])
                partials[f"k{k}_j{j}"] = round(float(pcorr), 4)
            except np.linalg.LinAlgError:
                partials[f"k{k}_j{j}"] = 0.0

        return partials
    except ImportError:
        return {}


def analyze_correlation_pro(time_series: list[dict]) -> dict:
    """Pro-tier correlation analysis."""
    # Align timestamps (same as Basic)
    aligned: dict[str, dict] = {}
    for s in time_series:
        key = s.get("metric_key", "")
        name = s.get("name", key)
        unit = s.get("unit", "")
        ts = s.get("timestamps", [])
        vals = s.get("values", [])
        valid = [(t, v) for t, v in zip(ts, vals) if v is not None]
        if len(valid) < 10:
            continue
        aligned[key] = {
            "name": name,
            "unit": unit,
            "values": [v for _, v in valid],
            "timestamps": [t for t, _ in valid],
        }

    keys = list(aligned.keys())
    n = len(keys)
    if n < 2:
        return {"error": "Need at least 2 metrics for correlation analysis"}

    # Build correlation matrices
    pearson_matrix = [[0.0] * n for _ in range(n)]
    spearman_matrix = [[0.0] * n for _ in range(n)]
    kendall_matrix = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                pearson_matrix[i][j] = spearman_matrix[i][j] = kendall_matrix[i][j] = 1.0
            elif i < j:
                ki, kj = keys[i], keys[j]
                common_ts = sorted(
                    set(aligned[ki]["timestamps"]) & set(aligned[kj]["timestamps"])
                )
                if len(common_ts) < 3:
                    continue

                xi = [dict(zip(aligned[ki]["timestamps"], aligned[ki]["values"])).get(ts)
                      for ts in common_ts]
                xj = [dict(zip(aligned[kj]["timestamps"], aligned[kj]["values"])).get(ts)
                      for ts in common_ts]
                xi_clean = [v for v in xi if v is not None]
                xj_clean = [v for v in xj if v is not None]
                m_len = min(len(xi_clean), len(xj_clean))
                if m_len < 3:
                    continue

                xi_vals = xi_clean[:m_len]
                xj_vals = xj_clean[:m_len]

                pearson_matrix[i][j] = pearson_matrix[j][i] = round(_pearson(xi_vals, xj_vals), 4)
                spearman_matrix[i][j] = spearman_matrix[j][i] = round(_spearman(xi_vals, xj_vals), 4)
                kendall_matrix[i][j] = kendall_matrix[j][i] = round(_kendall(xi_vals, xj_vals), 4)

    # Lag correlations for significant Pearson pairs
    lag_results: dict[str, list[dict]] = {}
    for i in range(n):
        for j in range(i + 1, n):
            if abs(pearson_matrix[i][j]) < 0.3:
                continue
            ki, kj = keys[i], keys[j]
            lags = _lag_correlation(aligned[ki]["values"], aligned[kj]["values"])
            if lags:
                key = f"{ki}__{kj}"
                lag_results[key] = lags

    # Partial correlations
    partials: dict[str, dict[str, float]] = {}
    if n >= 3:
        for k in range(n):
            partials[keys[k]] = _partial_correlation(pearson_matrix, k)

    # Significant pairs
    significant = []
    for i in range(n):
        for j in range(i + 1, n):
            r = pearson_matrix[i][j]
            if abs(r) >= 0.3:
                significant.append({
                    "metric_a": keys[i], "name_a": aligned[keys[i]]["name"],
                    "metric_b": keys[j], "name_b": aligned[keys[j]]["name"],
                    "r": r, "abs_r": abs(r),
                    "r_spearman": spearman_matrix[i][j],
                    "r_kendall": kendall_matrix[i][j],
                    "direction": "正相关" if r > 0 else "负相关",
                    "strength": "强" if abs(r) >= 0.7 else "中等" if abs(r) >= 0.4 else "弱",
                })
    significant.sort(key=lambda x: x["abs_r"], reverse=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "keys": keys,
        "names": [aligned[k]["name"] for k in keys],
        "display_names": [DISPLAY_NAMES.get(k, aligned[k]["name"]) for k in keys],
        "units": [aligned[k]["unit"] for k in keys],
        "pearson_matrix": pearson_matrix,
        "spearman_matrix": spearman_matrix,
        "kendall_matrix": kendall_matrix,
        "lag_correlations": lag_results,
        "partial_correlations": partials,
        "significant": significant[:10],
    }


def main() -> int:
    parser = base_parser(description="Pro-tier correlation analysis")
    parser.add_argument("--input", required=True, help="Path to trend_data.json")
    args = parser.parse_args()

    ok, missing = _check_dependencies()
    if not ok:
        emit_error(
            "DEPENDENCY_MISSING",
            f"Pro dependencies not installed: {', '.join(missing)}. "
            "Install with: pip install scikit-learn scipy",
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

    result = analyze_correlation_pro(time_series)
    if "error" in result:
        emit_error("ANALYSIS_ERROR", result["error"])
        return 0

    out_path = write_json(Path(args.output_dir), "pro_correlation_result", result)

    print(json.dumps({
        "ok": True,
        "metrics": len(result["keys"]),
        "significant_pairs": len(result["significant"]),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
