"""Time-series for trend analysis — InS-backed via the DataConnector registry.

Uses the DataConnector abstraction: ``InsTrendProvider`` calls the InS
platform through ``_ins_provider.fetch_trend_series_payload``. Any failure
raises ``HttpProviderError`` which propagates as
``{"error": "HttpProviderError: ..."}`` in the script's JSON output —
there is no demo fallback for trend data.

CLI:
    python query_trend.py \
        --metric-keys runtime_rate,vibration_level \
        --date-range 2026-01-01..2026-05-18 \
        --aggregation daily \
        --forecast-horizon 14 \
        --equipment P-001,P-002 \
        --include-alarms \
        --include-events \
        --output-dir /run/abc
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from _report_common import detect_equipment_type, load_sibling_module
from _stub_helpers import base_parser, emit_error, iso_now, parse_csv, write_json


SCHEMA_VERSION = "1"

# Agent-friendly aliases that normalise to _KPI_FEATURE_MAP keys before the
# provider sees them. Keeps the CLI surface tolerant of natural-language input.
TREND_METRIC_ALIASES: dict[str, str] = {
    "temperature": "bearing_temp",
    "pressure": "outlet_pressure",
    "vibration": "vibration_level",
}


def main() -> int:
    parser = base_parser("Time-series query for trend analysis")
    parser.add_argument("--metric-keys", required=True, help="CSV of metric keys")
    parser.add_argument("--date-range", required=True, help="YYYY-MM-DD..YYYY-MM-DD")
    parser.add_argument(
        "--aggregation",
        default="daily",
        choices=["hourly", "daily", "weekly"],
    )
    parser.add_argument("--forecast-horizon", type=int, default=7)
    parser.add_argument(
        "--equipment",
        default="",
        help="CSV of equipment IDs (enables per-equipment alarm/event context)",
    )
    parser.add_argument(
        "--include-alarms",
        action="store_true",
        help="Include alarm records within the date range",
    )
    parser.add_argument(
        "--include-events",
        action="store_true",
        help="Include event records within the date range",
    )
    args = parser.parse_args()

    metrics = [TREND_METRIC_ALIASES.get(m, m) for m in parse_csv(args.metric_keys)]
    if not metrics:
        return emit_error("INVALID_METRICS", "--metric-keys must contain at least one key")

    equipment_ids = parse_csv(args.equipment)

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

    # Derive eq_type from the org tree so per-type KPI mappings (e.g. pump →
    # 2K bearing_temp) apply. Mirrors query_daily.py lines 253-256.
    eq_type = "all"
    if equipment_ids:
        detected = detect_equipment_type(equipment_ids)
        if detected != "all":
            eq_type = detected

    dp = load_sibling_module("_data_providers")
    load_sibling_module("_data_provider_impls")
    try:
        provider = dp.get_provider("trend")
    except KeyError as exc:
        return emit_error("PROVIDER_UNAVAILABLE", f"trend provider not registered: {exc}")

    from _data_providers import HttpProviderError

    try:
        result = provider.fetch(
            metric_keys=metrics,
            date_range=(start.isoformat(), end.isoformat()),
            aggregation=args.aggregation,
            forecast_horizon=args.forecast_horizon,
            equipment_ids=equipment_ids or None,
            include_alarms=args.include_alarms,
            include_events=args.include_events,
            eq_type=eq_type,
        )
    except HttpProviderError as exc:
        return emit_error("HTTP_PROVIDER_ERROR", str(exc))

    time_series = result.data.get("time_series") or []
    total_points = sum(s.get("point_count", len(s.get("values") or [])) for s in time_series)

    output = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "date_range": [start.isoformat(), end.isoformat()],
            "aggregation": args.aggregation,
            "forecast_horizon": args.forecast_horizon,
            "requested_metric_keys": metrics,
            "equipment_ids": equipment_ids,
            "include_alarms": args.include_alarms,
            "include_events": args.include_events,
            "data_source": result.data_source,
            "eq_type": eq_type,
        },
        "time_series": time_series,
        "summary": {
            "metric_count": len(time_series),
            "total_points": total_points,
        },
        "_meta": {"generated_at": iso_now(), "provider_notes": result.notes},
    }

    if args.include_alarms:
        output["alarms"] = result.data.get("alarms") or []
    if args.include_events:
        output["events"] = result.data.get("events") or []

    write_json(Path(args.output_dir), "trend_data", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
