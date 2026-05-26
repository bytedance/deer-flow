#!/usr/bin/env python
"""Pro-tier trend analysis: multi-model regression, STL decomposition, PELT change points.

Consumes ``trend_data.json`` (same format as Basic trend_analysis.py) and produces
a superset output with additional Pro fields.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    provenance_evidence,
    read_json,
    write_json,
)

SCHEMA_VERSION = "2"

KIND_CONFIDENCE = {
    "trending_up": "medium",
    "trending_down": "medium",
    "volatility_spike": "medium",
    "anomaly_cluster": "high",
}

SERIES_BASE_COLORS = ["#5470c6", "#91cc75", "#ee6666", "#73c0de", "#3ba272", "#fc8452"]


def _check_dependencies():
    """Verify Pro dependencies are available. Returns (ok, missing_list)."""
    missing = []
    try:
        import sklearn  # noqa: F401
    except ImportError:
        missing.append("scikit-learn")
    try:
        import statsmodels  # noqa: F401
    except ImportError:
        missing.append("statsmodels")
    try:
        import ruptures  # noqa: F401
    except ImportError:
        missing.append("ruptures")
    return len(missing) == 0, missing


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return (values[-1] - values[0]) / (len(values) - 1)


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) <= 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _r2(y_true: list[float], y_pred: list[float]) -> float:
    """Coefficient of determination."""
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
    """Adjusted R² penalizing model complexity."""
    if n <= p + 1:
        return r2
    return 1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)


def _fit_linear(x: list[float], y: list[float]) -> dict:
    """Simple OLS linear regression."""
    n = len(x)
    if n < 2:
        return {"model": "linear", "r2_adj": 0.0, "params": {}}

    from sklearn.linear_model import LinearRegression
    import numpy as np

    X = np.array(x).reshape(-1, 1)
    Y = np.array(y)
    reg = LinearRegression().fit(X, Y)
    y_pred = reg.predict(X).tolist()
    r2 = _r2(y, y_pred)
    n_params = 2  # slope + intercept
    return {
        "model": "linear",
        "r2": round(r2, 6),
        "r2_adj": round(_r2_adj(r2, n, n_params), 6),
        "params": {"slope": float(reg.coef_[0]), "intercept": float(reg.intercept_)},
        "fitted": y_pred,
    }


def _fit_polynomial(x: list[float], y: list[float], degree: int = 2) -> dict:
    """Polynomial regression of specified degree."""
    n = len(x)
    if n < degree + 2:
        return {"model": f"polynomial_d{degree}", "r2_adj": 0.0, "params": {}}

    import numpy as np
    from sklearn.preprocessing import PolynomialFeatures
    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import make_pipeline

    X = np.array(x).reshape(-1, 1)
    Y = np.array(y)
    model = make_pipeline(PolynomialFeatures(degree), LinearRegression())
    model.fit(X, Y)
    y_pred = model.predict(X).tolist()
    r2 = _r2(y, y_pred)
    n_params = degree + 2
    return {
        "model": f"polynomial_d{degree}",
        "r2": round(r2, 6),
        "r2_adj": round(_r2_adj(r2, n, n_params), 6),
        "fitted": y_pred,
    }


def _fit_exponential(x: list[float], y: list[float]) -> dict:
    """Exponential regression via log-transform linear regression."""
    import numpy as np
    from sklearn.linear_model import LinearRegression

    # Filter non-positive y values
    valid = [(xi, yi) for xi, yi in zip(x, y) if yi > 0]
    if len(valid) < 2:
        return {"model": "exponential", "r2_adj": 0.0, "params": {}}

    xv, yv = zip(*valid)
    X = np.array(xv).reshape(-1, 1)
    log_y = np.log(yv)
    reg = LinearRegression().fit(X, log_y)
    log_pred = reg.predict(X)
    y_pred = np.exp(log_pred).tolist()
    r2 = _r2(list(yv), y_pred)
    n = len(xv)
    return {
        "model": "exponential",
        "r2": round(r2, 6),
        "r2_adj": round(_r2_adj(r2, n, 2), 6),
        "params": {"log_slope": float(reg.coef_[0]), "log_intercept": float(reg.intercept_)},
        "fitted": y_pred,
    }


def _stl_decompose(values: list[float], period: int = 7) -> dict | None:
    """STL decomposition (seasonal-trend decomposition using LOESS)."""
    try:
        from statsmodels.tsa.seasonal import STL
        import numpy as np
    except ImportError:
        return None

    clean = [v if v is not None else float("nan") for v in values]
    arr = np.array(clean, dtype=float)

    # Forward-fill NaN
    mask = np.isnan(arr)
    if mask.any():
        idx = np.where(~mask, np.arange(len(arr)), 0)
        np.maximum.accumulate(idx, out=idx)
        arr = arr[idx]

    if len(arr) < period * 2:
        return None

    try:
        stl = STL(arr, period=period, robust=True)
        result = stl.fit()
        return {
            "trend": result.trend.tolist(),
            "seasonal": result.seasonal.tolist(),
            "residual": result.resid.tolist(),
            "period": period,
        }
    except Exception:
        return None


def _pelt_changepoints(values: list[float]) -> dict | None:
    """PELT change point detection."""
    try:
        import ruptures as rpt
        import numpy as np
    except ImportError:
        return None

    clean = np.array([v for v in values if v is not None], dtype=float)
    if len(clean) < 10:
        return None

    try:
        algo = rpt.Pelt(model="rbf").fit(clean)
        result = algo.predict(pen=3)
        changepoints = [int(r) for r in result[:-1]]  # last is len
        segments = []
        prev = 0
        for cp in result:
            if cp > prev:
                seg = clean[prev:cp].tolist()
                mean, std = _mean_std(seg)
                segments.append({
                    "start": int(prev),
                    "end": int(cp),
                    "mean": round(mean, 4),
                    "std": round(std, 4),
                })
            prev = cp
        return {"changepoint_indices": changepoints, "segments": segments}
    except Exception:
        return None


def analyze_trend_pro(time_series: list[dict], forecast_horizon: int = 14) -> dict:
    """Run Pro-tier trend analysis on all time series."""
    findings: list[dict] = []
    evidence: list[dict] = []

    for idx, series in enumerate(time_series):
        values_raw = series.get("values", [])
        timestamps = series.get("timestamps", [])
        metric_key = series.get("metric_key", f"metric_{idx}")
        metric_name = series.get("name", metric_key)
        unit = series.get("unit", "")

        values = [v for v in values_raw if v is not None]
        n = len(values)
        if n < 5:
            continue

        x = list(range(n))
        y = values

        # Multi-model fitting
        linear = _fit_linear(x, y)
        poly2 = _fit_polynomial(x, y, degree=2)
        exp_model = _fit_exponential(x, y)

        models = [linear, poly2, exp_model]
        # Select best model by R²_adj
        best = max(models, key=lambda m: m.get("r2_adj", 0.0))

        # STL decomposition
        stl = _stl_decompose(y)

        # PELT change points
        pelt = _pelt_changepoints(y)

        # Forecast using best model
        forecast_x = list(range(n, n + forecast_horizon))
        forecast_vals: list[float] = []
        confidence_lower: list[float] = []
        confidence_upper: list[float] = []

        if best["model"] == "linear" and best.get("params"):
            sl = best["params"]["slope"]
            ic = best["params"]["intercept"]
            forecast_vals = [sl * xi + ic for xi in forecast_x]
        elif best["model"].startswith("polynomial"):
            import numpy as np
            from sklearn.preprocessing import PolynomialFeatures
            from sklearn.linear_model import LinearRegression
            from sklearn.pipeline import make_pipeline

            degree = int(best["model"].split("_d")[1])
            X = np.array(x).reshape(-1, 1)
            Y = np.array(y)
            pipe = make_pipeline(PolynomialFeatures(degree), LinearRegression())
            pipe.fit(X, Y)
            forecast_vals = pipe.predict(np.array(forecast_x).reshape(-1, 1)).tolist()
        elif best["model"] == "exponential" and best.get("params"):
            ls = best["params"]["log_slope"]
            li = best["params"]["log_intercept"]
            forecast_vals = [math.exp(ls * xi + li) for xi in forecast_x]
        else:
            forecast_vals = [y[-1]] * forecast_horizon

        # 95% confidence band (simple residual std approximation)
        if best.get("fitted") and len(best["fitted"]) == n:
            residuals = [y[i] - best["fitted"][i] for i in range(n)]
            _, res_std = _mean_std(residuals)
            se = res_std * 1.96
            confidence_lower = [fv - se for fv in forecast_vals]
            confidence_upper = [fv + se for fv in forecast_vals]

        # Direction & slope for finding
        slope_val = _slope(y)
        direction = "stable"
        if slope_val > 0.01:
            direction = "trending_up"
        elif slope_val < -0.01:
            direction = "trending_down"

        mean_v, std_v = _mean_std(y)
        volatility = abs(std_v / mean_v) if mean_v != 0 else 0.0

        findings.append({
            "metric": metric_name,
            "metric_key": metric_key,
            "direction": direction,
            "slope": round(slope_val, 6),
            "volatility": round(volatility, 4),
            "confidence": KIND_CONFIDENCE.get(direction, "medium"),
            "best_model": best["model"],
            "r2_adj": best.get("r2_adj", 0.0),
            "changepoint_count": len(pelt.get("changepoint_indices", [])) if pelt else 0,
        })

        evidence.append({
            "metric_key": metric_key,
            "metric_name": metric_name,
            "n_points": n,
            "models": {m["model"]: {"r2_adj": m.get("r2_adj", 0.0)} for m in models},
            "stl_period": stl.get("period") if stl else None,
            "changepoints": pelt.get("changepoint_indices", []) if pelt else [],
        })

        # Build ECharts trend chart
        series["pro_models"] = models
        series["pro_stl"] = stl
        series["pro_pelt"] = pelt
        series["pro_forecast"] = forecast_vals
        series["pro_confidence_lower"] = confidence_lower
        series["pro_confidence_upper"] = confidence_upper
        series["pro_best_model"] = best["model"]

    # Build regression summary
    data_coverage = {
        "covered_metrics": len(time_series),
        "missing_metrics": 0,
        "time_coverage_pct": 100.0,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "findings": findings,
        "evidence": evidence,
        "data_coverage": data_coverage,
        "time_series": time_series,
        "generated_at": iso_now(),
        "human_review_required": True,
    }


def main() -> int:
    parser = base_parser(description="Pro-tier trend analysis")
    parser.add_argument("--input", required=True, help="Path to trend_data.json")
    parser.add_argument("--forecast-horizon", type=int, default=14)
    args = parser.parse_args()

    ok, missing = _check_dependencies()
    if not ok:
        emit_error(
            "DEPENDENCY_MISSING",
            f"Pro dependencies not installed: {', '.join(missing)}. "
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

    result = analyze_trend_pro(time_series, forecast_horizon=args.forecast_horizon)

    out_path = write_json(Path(args.output_dir), "pro_trend_analysis", result)

    print(json.dumps({
        "ok": True,
        "findings": len(result["findings"]),
        "best_models": {f["metric_key"]: f["best_model"] for f in result["findings"]},
        "output": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
