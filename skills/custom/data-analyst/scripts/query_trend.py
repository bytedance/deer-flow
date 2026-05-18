"""Synthetic time-series for trend analysis (deterministic demo).

Sprint S1 enhancement — replaces the original 84-line stub with a richer
demo that matches the design contract used by the rest of the data-analyst
skill (query_daily / query_weekly / query_monthly):

- Output ``time_series[]`` per metric (NOT a dict-of-arrays) so downstream
  iteration is positional and consistent with the §13.2 evidence model.
- Each series carries ``metric_key`` / ``name`` / ``unit`` / ``aggregation`` /
  ``timestamps[]`` / ``values[]`` / ``point_count``.
- A top-level ``metadata`` block surfaces the resolved date range / total
  point count / aggregation step so the downstream transform never has to
  rederive them.
- Hourly aggregation now actually produces 24-points-per-day (the original
  stub used the same daily step for ``hourly`` / ``daily``).
- Demo data is still deterministic (same input → same output) so unit tests
  can assert exact values.

CLI:
    python query_trend.py \
        --metric-keys runtime_rate,vibration_level \
        --date-range 2026-01-01..2026-05-18 \
        --aggregation daily \
        --forecast-horizon 14 \
        --output-dir /run/abc
"""

from __future__ import annotations

import math
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    parse_csv,
    write_json,
)

# Importing this module registers DemoTrendProvider + HttpTrendProvider in the
# DataConnector registry. fetch_with_fallback() then routes based on the
# DEER_FLOW_DATA_PROVIDER env var.
import _data_provider_impls  # noqa: F401 — register-only side-effect import
from _data_providers import fetch_with_fallback


SCHEMA_VERSION = "1"

# Metric display names + units. Anything not listed gets ``metric_key`` as name
# and an empty unit — the transform layer is responsible for graceful display.
METRIC_CATALOG = {
    "runtime_rate": {"name": "运行率", "unit": "%", "amplitude": 0.05, "base": 0.92, "better_when_higher": True},
    "alarm_count": {"name": "告警数量", "unit": "条", "amplitude": 3.0, "base": 4.0, "better_when_higher": False},
    "vibration_level": {"name": "振动水平", "unit": "mm/s", "amplitude": 0.5, "base": 3.0, "better_when_higher": False},
    "bearing_temp": {"name": "轴承温度", "unit": "℃", "amplitude": 4.0, "base": 65.0, "better_when_higher": False},
    "outlet_pressure": {"name": "出口压力", "unit": "MPa", "amplitude": 0.15, "base": 1.0, "better_when_higher": True},
    "flow_rate": {"name": "流量", "unit": "m³/h", "amplitude": 20.0, "base": 120.0, "better_when_higher": True},
    "energy_consumption": {"name": "能耗", "unit": "kWh", "amplitude": 100.0, "base": 800.0, "better_when_higher": False},
}


def _metric_meta(metric_key: str) -> dict:
    return METRIC_CATALOG.get(
        metric_key,
        {
            "name": metric_key,
            "unit": "",
            "amplitude": 0.4,
            "base": 0.5,
            "better_when_higher": False,
        },
    )


def _deterministic_value(metric_key: str, step_index: int, total_steps: int, meta: dict) -> float:
    """Stable sinusoid + small linear drift; ``metric_key`` shifts the phase.

    Drift is bounded so the demo doesn't degenerate into out-of-physical-range
    values over long windows.
    """
    phase = sum(ord(c) for c in metric_key) * 0.01
    sine = math.sin(step_index * 0.3 + phase)
    drift = 0.0
    if total_steps > 0:
        # ±20% of amplitude over the full window — small but visible
        drift = (step_index / total_steps - 0.5) * meta["amplitude"] * 0.4
    value = meta["base"] + meta["amplitude"] * sine + drift
    return round(value, 4)


def _enumerate_steps(start: date, end: date, aggregation: str) -> list[str]:
    """Return a list of ISO-formatted timestamps for the given window."""
    timestamps: list[str] = []
    if aggregation == "hourly":
        cursor = datetime.combine(start, time.min)
        stop = datetime.combine(end, time(23))
        while cursor <= stop:
            timestamps.append(cursor.isoformat(timespec="seconds"))
            cursor += timedelta(hours=1)
    elif aggregation == "daily":
        cursor = start
        while cursor <= end:
            timestamps.append(cursor.isoformat())
            cursor += timedelta(days=1)
    elif aggregation == "weekly":
        cursor = start
        while cursor <= end:
            timestamps.append(cursor.isoformat())
            cursor += timedelta(days=7)
    else:
        raise ValueError(f"unsupported aggregation: {aggregation}")
    return timestamps


def _build_series(metric_key: str, timestamps: list[str]) -> dict:
    meta = _metric_meta(metric_key)
    total = len(timestamps)
    values = [_deterministic_value(metric_key, i, total, meta) for i in range(total)]
    return {
        "metric_key": metric_key,
        "name": meta["name"],
        "unit": meta["unit"],
        "timestamps": timestamps,
        "values": values,
        "point_count": total,
        "better_when_higher": meta["better_when_higher"],
    }


def main() -> int:
    parser = base_parser("Synthetic time-series for trend analysis")
    parser.add_argument("--metric-keys", required=True, help="CSV of metric keys")
    parser.add_argument("--date-range", required=True, help="YYYY-MM-DD..YYYY-MM-DD")
    parser.add_argument(
        "--aggregation",
        default="daily",
        choices=["hourly", "daily", "weekly"],
    )
    parser.add_argument("--forecast-horizon", type=int, default=7)
    args = parser.parse_args()

    metrics = parse_csv(args.metric_keys)
    if not metrics:
        return emit_error("INVALID_METRICS", "--metric-keys must contain at least one key")

    try:
        start_str, end_str = args.date_range.split("..", 1)
        start = date.fromisoformat(start_str.strip())
        end = date.fromisoformat(end_str.strip())
    except (ValueError, AttributeError) as exc:
        return emit_error("INVALID_DATE_RANGE", f"date_range must be 'YYYY-MM-DD..YYYY-MM-DD': {exc}")
    if end < start:
        return emit_error("INVALID_DATE_RANGE", "end date is before start date")
    if not (0 <= args.forecast_horizon <= 90):
        return emit_error("INVALID_FORECAST_HORIZON", "forecast_horizon must be in [0, 90]")

    timestamps = _enumerate_steps(start, end, args.aggregation)
    if not timestamps:
        return emit_error("EMPTY_WINDOW", "date_range produced no sample points")

    # Route through the DataConnector abstraction: HttpTrendProvider when
    # ``DEER_FLOW_DATA_PROVIDER=http`` + ``DEERFLOW_TREND_URL`` are set,
    # otherwise DemoTrendProvider. fetch_with_fallback handles graceful
    # degradation when the HTTP path fails.
    result = fetch_with_fallback(
        source="trend",
        fetch_args={
            "metric_keys": metrics,
            "date_range": (start.isoformat(), end.isoformat()),
            "aggregation": args.aggregation,
            "forecast_horizon": args.forecast_horizon,
        },
    )
    time_series = result.data.get("time_series") or []
    total_points = sum(s.get("point_count", len(s.get("values") or [])) for s in time_series)

    output = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "date_range": [start.isoformat(), end.isoformat()],
            "aggregation": args.aggregation,
            "forecast_horizon": args.forecast_horizon,
            "requested_metric_keys": metrics,
            "data_source": result.data_source,
        },
        "time_series": time_series,
        "summary": {
            "metric_count": len(time_series),
            "total_points": total_points,
            "first_timestamp": timestamps[0],
            "last_timestamp": timestamps[-1],
        },
        "_meta": {"stub": True, "generated_at": iso_now(), "provider_notes": result.notes},
    }

    write_json(Path(args.output_dir), "trend_data", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
