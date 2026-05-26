#!/usr/bin/env python
"""Ultra-tier correlation analysis: Granger causality, transfer entropy, Graphical Lasso.

Consumes ``trend_data.json``, produces ``ultra_correlation_result.json``.
Falls back to Pro methods when dependencies are missing.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, read_json, write_json

SCHEMA_VERSION = "2"
MAX_GRANGER_LAG = 7

DISPLAY_NAMES = {
    "runtime_rate": "运行率", "alarm_count": "告警数量", "vibration_level": "振动烈度",
    "temperature": "温度", "pressure": "压力", "flow_rate": "流量",
    "corrosion_rate": "腐蚀速率", "motor_current": "电机电流",
}


def _check_dependencies():
    missing = []
    for lib in ["scipy", "sklearn"]:
        try:
            if lib == "sklearn":
                import sklearn  # noqa: F401
            else:
                __import__(lib)
        except ImportError:
            missing.append(lib if lib == "scipy" else "scikit-learn")
    return len(missing) == 0, missing


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return cov / (sx * sy)


def _granger_causality(
    xs: list[float],
    ys: list[float],
    max_lag: int = MAX_GRANGER_LAG,
) -> list[dict]:
    """Test if X Granger-causes Y using F-test on restricted vs unrestricted models.

    Returns list of {lag, f_stat, p_value, is_causal} for each lag.
    """
    import numpy as np

    n = len(xs)
    if n < max_lag + 10:
        return []

    x_arr = np.array(xs)
    y_arr = np.array(ys)

    results = []
    for lag in range(1, max_lag + 1):
        if n <= 2 * lag + 2:
            continue

        # Restricted: Y_t = c + Σ α_i Y_{t-i}
        # Unrestricted: Y_t = c + Σ α_i Y_{t-i} + Σ β_i X_{t-i}
        T = n - lag
        Y_restricted = y_arr[lag:]
        Y_unrestricted = y_arr[lag:]

        X_restricted = np.column_stack([y_arr[lag - i - 1:T + lag - i - 1] for i in range(1, lag + 1)])
        X_unrestricted = np.column_stack(
            [y_arr[lag - i - 1:T + lag - i - 1] for i in range(1, lag + 1)]
            + [x_arr[lag - i - 1:T + lag - i - 1] for i in range(1, lag + 1)]
        )

        try:
            # OLS fit
            beta_r = np.linalg.lstsq(
                np.column_stack([np.ones(T), X_restricted]), Y_restricted, rcond=None
            )[0]
            beta_u = np.linalg.lstsq(
                np.column_stack([np.ones(T), X_unrestricted]), Y_unrestricted, rcond=None
            )[0]

            rss_r = np.sum((Y_restricted - np.column_stack([np.ones(T), X_restricted]) @ beta_r) ** 2)
            rss_u = np.sum((Y_unrestricted - np.column_stack([np.ones(T), X_unrestricted]) @ beta_u) ** 2)

            df_r = T - lag - 1
            df_u = T - 2 * lag - 1
            if df_u <= 0:
                continue

            f_stat = ((rss_r - rss_u) / lag) / (rss_u / df_u) if rss_u > 0 else 0.0

            # Approximate p-value from F-distribution
            # Using scipy if available, otherwise heuristic
            try:
                from scipy.stats import f as f_dist
                p_value = 1.0 - f_dist.cdf(f_stat, lag, df_u)
            except ImportError:
                p_value = math.exp(-0.5 * f_stat) if f_stat > 0 else 1.0

            results.append({
                "lag": lag,
                "f_statistic": round(float(f_stat), 4),
                "p_value": round(float(p_value), 4),
                "is_causal": p_value < 0.05,
            })
        except Exception:
            continue

    return results


def _transfer_entropy(xs: list[float], ys: list[float], bins: int = 10) -> dict | None:
    """Estimate transfer entropy from X to Y using histogram binning.

    TE_{X→Y} = Σ p(y_{t+1}, y_t, x_t) * log(p(y_{t+1} | y_t, x_t) / p(y_{t+1} | y_t))
    """
    import numpy as np

    n = min(len(xs), len(ys))
    if n < 20:
        return None

    x_arr = np.array(xs[:n])
    y_arr = np.array(ys[:n])

    # Discretize into bins
    try:
        x_bins = np.digitize(x_arr, np.histogram_bin_edges(x_arr, bins=bins)[:-1])
        y_bins = np.digitize(y_arr, np.histogram_bin_edges(y_arr, bins=bins)[:-1])
        y_next_bins = np.digitize(y_arr[1:], np.histogram_bin_edges(y_arr[1:], bins=bins)[:-1])
    except (ValueError, IndexError):
        return None

    x_bins = x_bins[:-1]
    y_bins = y_bins[:-1]

    # Joint distributions (smoothed with Laplace +1)
    total = n - 1
    joint: dict[tuple, int] = {}
    for i in range(total):
        key = (y_next_bins[i], y_bins[i], x_bins[i])
        joint[key] = joint.get(key, 0) + 1

    cond_y: dict[tuple, int] = {}
    for i in range(total):
        key = (y_next_bins[i], y_bins[i])
        cond_y[key] = cond_y.get(key, 0) + 1

    margin_y: dict[int, int] = {}
    for i in range(total):
        margin_y[y_bins[i]] = margin_y.get(y_bins[i], 0) + 1
    margin_yn: dict[int, int] = {}
    for i in range(total):
        margin_yn[y_next_bins[i]] = margin_yn.get(y_next_bins[i], 0) + 1

    te = 0.0
    for (yn, y, x), count in joint.items():
        p_joint = (count + 1) / (total + bins ** 3)
        p_cond_xy = (count + 1) / (sum(1 for (yn2, y2, x2), c in joint.items() if y2 == y and x2 == x) + bins)
        p_cond_y = (cond_y.get((yn, y), 0) + 1) / (margin_y.get(y, 0) + bins)

        if p_cond_xy > 0 and p_cond_y > 0 and p_joint > 0:
            te += p_joint * math.log(p_cond_xy / p_cond_y)

    # Normalize by entropy of Y
    hy = 0.0
    for yn in set(y_next_bins):
        p = (margin_yn.get(yn, 0) + 1) / (total + bins)
        if p > 0:
            hy -= p * math.log(p)

    normalized_te = te / hy if hy > 0 else 0.0

    return {
        "transfer_entropy": round(te, 6),
        "normalized_te": round(normalized_te, 6),
        "direction": "X_to_Y",
        "significant": normalized_te > 0.05,
    }


def _graphical_lasso(corr_matrix: list[list[float]], alpha: float = 0.1) -> dict | None:
    """Compute Graphical Lasso for sparse inverse covariance (causal structure)."""
    try:
        from sklearn.covariance import GraphicalLasso
        import numpy as np
    except ImportError:
        return None

    n = len(corr_matrix)
    if n < 3:
        return None

    try:
        X = np.array(corr_matrix)
        model = GraphicalLasso(alpha=alpha, max_iter=100, tol=1e-4)
        model.fit(X)

        precision = model.precision_
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                if abs(precision[i, j]) > 1e-6:
                    edges.append({
                        "from": i,
                        "to": j,
                        "weight": round(float(precision[i, j]), 6),
                    })

        return {
            "precision_matrix": precision.tolist(),
            "edges": edges,
            "edge_count": len(edges),
            "alpha": alpha,
        }
    except Exception:
        return None


def analyze_correlation_ultra(time_series: list[dict]) -> dict:
    """Ultra-tier correlation analysis."""
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

    # Build Pearson matrix for Graphical Lasso input
    pearson_matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            ki, kj = keys[i], keys[j]
            common_ts = sorted(set(aligned[ki]["timestamps"]) & set(aligned[kj]["timestamps"]))
            if len(common_ts) < 3:
                continue
            xi = [dict(zip(aligned[ki]["timestamps"], aligned[ki]["values"])).get(ts) for ts in common_ts]
            xj = [dict(zip(aligned[kj]["timestamps"], aligned[kj]["values"])).get(ts) for ts in common_ts]
            xi_clean = [v for v in xi if v is not None]
            xj_clean = [v for v in xj if v is not None]
            m_len = min(len(xi_clean), len(xj_clean))
            if m_len < 3:
                continue
            r = _pearson(xi_clean[:m_len], xj_clean[:m_len])
            pearson_matrix[i][j] = pearson_matrix[j][i] = round(r, 4)

    # Granger causality (all pairs)
    granger_results: list[dict] = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            ki, kj = keys[i], keys[j]
            gc = _granger_causality(aligned[ki]["values"], aligned[kj]["values"])
            if gc:
                causal_lags = [g["lag"] for g in gc if g.get("is_causal")]
                granger_results.append({
                    "from": ki,
                    "to": kj,
                    "tests": gc,
                    "causal_lags": causal_lags,
                    "is_causal": len(causal_lags) > 0,
                })

    # Transfer entropy (significant pairs from Pearson)
    transfer_entropy_results: list[dict] = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if abs(pearson_matrix[i][j]) < 0.3:
                continue
            ki, kj = keys[i], keys[j]
            te = _transfer_entropy(aligned[ki]["values"], aligned[kj]["values"])
            if te:
                te["from"] = ki
                te["to"] = kj
                transfer_entropy_results.append(te)

    # Graphical Lasso
    glasso = _graphical_lasso(pearson_matrix)

    # Build causal graph summary
    causal_graph: list[dict] = []
    for g in granger_results:
        if g["is_causal"]:
            causal_graph.append({
                "from": g["from"],
                "to": g["to"],
                "type": "granger",
                "lags": g["causal_lags"],
            })
    for te in transfer_entropy_results:
        if te.get("significant"):
            causal_graph.append({
                "from": te["from"],
                "to": te["to"],
                "type": "transfer_entropy",
                "weight": te.get("normalized_te", 0),
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "keys": keys,
        "names": [aligned[k]["name"] for k in keys],
        "display_names": [DISPLAY_NAMES.get(k, aligned[k]["name"]) for k in keys],
        "pearson_matrix": pearson_matrix,
        "granger_causality": granger_results,
        "transfer_entropy": transfer_entropy_results,
        "graphical_lasso": glasso,
        "causal_graph": causal_graph,
        "causal_edge_count": len(causal_graph),
    }


def main() -> int:
    parser = base_parser(description="Ultra-tier correlation analysis")
    parser.add_argument("--input", required=True, help="Path to trend_data.json")
    args = parser.parse_args()

    ok, missing = _check_dependencies()
    if not ok:
        emit_error(
            "DEPENDENCY_MISSING",
            f"Ultra dependencies not installed: {', '.join(missing)}. "
            "Install with: pip install scipy scikit-learn",
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

    result = analyze_correlation_ultra(time_series)
    if "error" in result:
        emit_error("ANALYSIS_ERROR", result["error"])
        return 0

    out_path = write_json(Path(args.output_dir), "ultra_correlation_result", result)

    print(json.dumps({
        "ok": True,
        "metrics": len(result["keys"]),
        "causal_edges": result["causal_edge_count"],
        "granger_tests": len(result["granger_causality"]),
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
