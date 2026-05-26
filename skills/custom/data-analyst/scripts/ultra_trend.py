#!/usr/bin/env python
"""Ultra-tier trend analysis: ONNX LSTM forecast, co-trending detection, adaptive thresholds.

Consumes ``trend_data.json``, produces ``ultra_trend_result.json``.
Falls back to Pro methods when ONNX model is unavailable.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import base_parser, emit_error, iso_now, read_json, write_json
from _model_loader import load_model, model_available

SCHEMA_VERSION = "2"
FORECAST_HORIZON = 14


def _check_dependencies():
    missing = []
    for lib in ["scikit-learn", "statsmodels", "ruptures"]:
        try:
            __import__(lib.replace("-", "_"))
        except ImportError:
            missing.append(lib)
    return len(missing) == 0, missing


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) <= 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return (values[-1] - values[0]) / (len(values) - 1)


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


def _best_pro_model(values: list[float]) -> dict:
    """Fit multi-model regression and return best model by R²_adj (Pro logic inline)."""
    import numpy as np
    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import PolynomialFeatures
    from sklearn.pipeline import make_pipeline

    x = list(range(len(values)))
    y = values
    X = np.array(x).reshape(-1, 1)
    Y = np.array(y)
    n = len(x)

    models = []

    # Linear
    lin = LinearRegression().fit(X, Y)
    y_pred_lin = lin.predict(X).tolist()
    r2_lin = _r2(y, y_pred_lin)
    models.append({
        "model": "linear",
        "r2_adj": _r2_adj(r2_lin, n, 2),
        "params": {"slope": float(lin.coef_[0]), "intercept": float(lin.intercept_)},
        "fitted": y_pred_lin,
    })

    # Polynomial d=2
    if n >= 4:
        pipe = make_pipeline(PolynomialFeatures(2), LinearRegression())
        pipe.fit(X, Y)
        y_pred_p2 = pipe.predict(X).tolist()
        r2_p2 = _r2(y, y_pred_p2)
        models.append({
            "model": "polynomial_d2",
            "r2_adj": _r2_adj(r2_p2, n, 4),
            "fitted": y_pred_p2,
        })

    # Exponential
    valid = [(xi, yi) for xi, yi in zip(x, y) if yi > 0]
    if len(valid) >= 2:
        xv, yv = zip(*valid)
        Xe = np.array(xv).reshape(-1, 1)
        log_y = np.log(yv)
        reg_e = LinearRegression().fit(Xe, log_y)
        log_pred = reg_e.predict(Xe)
        y_pred_e = np.exp(log_pred).tolist()
        r2_e = _r2(list(yv), y_pred_e)
        models.append({
            "model": "exponential",
            "r2_adj": _r2_adj(r2_e, len(xv), 2),
            "params": {"log_slope": float(reg_e.coef_[0]), "log_intercept": float(reg_e.intercept_)},
            "fitted": y_pred_e,
        })

    best = max(models, key=lambda m: m.get("r2_adj", 0.0))
    return best


def _r2(y_true: list[float], y_pred: list[float]) -> float:
    n = len(y_true)
    if n < 2:
        return 0.0
    mean_y = sum(y_true) / n
    ss_res = sum((y_true[i] - y_pred[i]) ** 2 for i in range(n))
    ss_tot = sum((y - mean_y) ** 2 for y in y_true)
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1.0 - ss_res / ss_tot


def _r2_adj(r2: float, n: int, p: int) -> float:
    if n <= p + 1:
        return r2
    return 1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)


def _onnx_forecast(values: list[float], horizon: int = FORECAST_HORIZON) -> dict | None:
    """Run ONNX LSTM forecast. Returns None on failure (caller falls back to Pro)."""
    model = load_model("trend_forecaster")
    if model is None:
        return None

    import numpy as np

    try:
        session = model["session"]
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name

        # Prepare input: (1, seq_len, 1) — single feature, batch=1
        seq = np.array(values[-30:], dtype=np.float32).reshape(1, -1, 1)
        pred = session.run([output_name], {input_name: seq})[0]
        forecast = pred.flatten()[:horizon].tolist()
        return {
            "forecast": forecast,
            "model": "lstm_onnx",
            "model_path": model["model_path"],
            "model_fallback": False,
        }
    except Exception:
        return None


def _pro_forecast(values: list[float], best: dict, horizon: int = FORECAST_HORIZON) -> list[float]:
    """Generate forecast using best Pro model."""
    import numpy as np

    n = len(values)
    x_future = list(range(n, n + horizon))

    if best["model"] == "linear" and best.get("params"):
        sl = best["params"]["slope"]
        ic = best["params"]["intercept"]
        return [sl * xi + ic for xi in x_future]
    elif best["model"].startswith("polynomial"):
        from sklearn.preprocessing import PolynomialFeatures
        from sklearn.linear_model import LinearRegression
        from sklearn.pipeline import make_pipeline

        degree = int(best["model"].split("_d")[1])
        X = np.array(list(range(n))).reshape(-1, 1)
        Y = np.array(values)
        pipe = make_pipeline(PolynomialFeatures(degree), LinearRegression())
        pipe.fit(X, Y)
        return pipe.predict(np.array(x_future).reshape(-1, 1)).tolist()
    elif best["model"] == "exponential" and best.get("params"):
        ls = best["params"]["log_slope"]
        li = best["params"]["log_intercept"]
        return [math.exp(ls * xi + li) for xi in x_future]

    return [values[-1]] * horizon


def _confidence_bands(
    values: list[float],
    fitted: list[float],
    forecast: list[float],
) -> dict:
    """Compute 80% and 95% confidence bands from residual std."""
    n = min(len(values), len(fitted))
    residuals = [values[i] - fitted[i] for i in range(n)]
    _, res_std = _mean_std(residuals)

    z80 = 1.28
    z95 = 1.96

    return {
        "confidence_80_lower": [fv - z80 * res_std for fv in forecast],
        "confidence_80_upper": [fv + z80 * res_std for fv in forecast],
        "confidence_95_lower": [fv - z95 * res_std for fv in forecast],
        "confidence_95_upper": [fv + z95 * res_std for fv in forecast],
        "residual_std": round(res_std, 4),
    }


def _co_trending_groups(
    series_data: list[dict],
    threshold: float = 0.7,
) -> list[dict]:
    """Detect groups of metrics whose trend components move together."""
    import numpy as np

    trends = {}
    for s in series_data:
        stl = s.get("pro_stl")
        if stl and stl.get("trend"):
            trends[s["metric_key"]] = stl["trend"]

    if len(trends) < 2:
        return []

    keys = list(trends.keys())
    n = len(keys)
    groups = []
    visited: set = set()

    for i in range(n):
        if keys[i] in visited:
            continue
        group = [keys[i]]
        for j in range(i + 1, n):
            if keys[j] in visited:
                continue
            min_len = min(len(trends[keys[i]]), len(trends[keys[j]]))
            r = _pearson(trends[keys[i]][:min_len], trends[keys[j]][:min_len])
            if r >= threshold:
                group.append(keys[j])
                visited.add(keys[j])
        if len(group) >= 2:
            visited.add(keys[i])
            groups.append({
                "members": group,
                "size": len(group),
                "strength": "strong" if len(group) >= 3 else "moderate",
            })

    return groups


def _adaptive_thresholds(values: list[float]) -> dict:
    """Recommend adaptive alert thresholds from historical percentiles."""
    if len(values) < 10:
        return {"available": False}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def _percentile(pct: float) -> float:
        idx = int(n * pct / 100)
        return sorted_vals[min(idx, n - 1)]

    return {
        "available": True,
        "p50": round(_percentile(50), 4),
        "p95": round(_percentile(95), 4),
        "p99": round(_percentile(99), 4),
        "recommended_upper_warning": round(_percentile(95), 4),
        "recommended_upper_critical": round(_percentile(99), 4),
        "mean": round(sum(sorted_vals) / n, 4),
    }


def analyze_trend_ultra(time_series: list[dict], forecast_horizon: int = FORECAST_HORIZON) -> dict:
    """Ultra-tier trend analysis with ONNX fallback."""
    use_onnx = model_available("trend_forecaster")
    model_fallback = not use_onnx

    per_metric: list[dict] = []
    for idx, series in enumerate(time_series):
        values_raw = series.get("values", [])
        timestamps = series.get("timestamps", [])
        metric_key = series.get("metric_key", f"metric_{idx}")
        metric_name = series.get("name", metric_key)

        values = [v for v in values_raw if v is not None]
        n = len(values)
        if n < 5:
            continue

        # Fit best Pro model
        best = _best_pro_model(values)

        # Forecast: ONNX or Pro fallback
        onnx_result = _onnx_forecast(values, forecast_horizon) if use_onnx else None
        if onnx_result:
            forecast = onnx_result["forecast"]
            forecast_model = "lstm_onnx"
        else:
            forecast = _pro_forecast(values, best, forecast_horizon)
            forecast_model = best["model"]

        # Confidence bands
        fitted = best.get("fitted", [])
        if not fitted or len(fitted) != n:
            fitted = [values[0] + _slope(values) * i for i in range(n)]
        bands = _confidence_bands(values, fitted, forecast)

        # Adaptive thresholds
        thresholds = _adaptive_thresholds(values)

        direction = "stable"
        slope_val = _slope(values)
        if slope_val > 0.01:
            direction = "trending_up"
        elif slope_val < -0.01:
            direction = "trending_down"

        per_metric.append({
            "metric_key": metric_key,
            "metric_name": metric_name,
            "direction": direction,
            "slope": round(slope_val, 6),
            "best_model": best["model"],
            "r2_adj": best.get("r2_adj", 0.0),
            "forecast_model": forecast_model,
            "model_fallback": model_fallback and onnx_result is None,
            "forecast": forecast,
            "confidence_bands": bands,
            "adaptive_thresholds": thresholds,
        })

    # Co-trending groups
    co_trending = _co_trending_groups(time_series)

    forecast_count = sum(1 for m in per_metric if m.get("forecast"))

    return {
        "schema_version": SCHEMA_VERSION,
        "model_fallback": model_fallback,
        "forecast_horizon": forecast_horizon,
        "per_metric": per_metric,
        "co_trending_groups": co_trending,
        "generated_at": iso_now(),
        "summary": {
            "metrics_analyzed": len(per_metric),
            "metrics_forecasted": forecast_count,
            "onnx_used": use_onnx,
            "co_trending_group_count": len(co_trending),
        },
    }


def main() -> int:
    parser = base_parser(description="Ultra-tier trend analysis")
    parser.add_argument("--input", required=True, help="Path to trend_data.json")
    parser.add_argument("--forecast-horizon", type=int, default=FORECAST_HORIZON)
    args = parser.parse_args()

    ok, missing = _check_dependencies()
    if not ok:
        emit_error(
            "DEPENDENCY_MISSING",
            f"Ultra dependencies not installed: {', '.join(missing)}. "
            "Install with: pip install scikit-learn statsmodels ruptures",
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

    result = analyze_trend_ultra(time_series, forecast_horizon=args.forecast_horizon)

    out_path = write_json(Path(args.output_dir), "ultra_trend_result", result)

    print(json.dumps({
        "ok": True,
        "metrics": result["summary"]["metrics_analyzed"],
        "forecasted": result["summary"]["metrics_forecasted"],
        "onnx_used": result["summary"]["onnx_used"],
        "co_trending_groups": result["summary"]["co_trending_group_count"],
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
