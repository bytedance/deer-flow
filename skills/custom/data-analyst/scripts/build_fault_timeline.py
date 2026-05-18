"""Build a fault timeline from fault_context.

Sprint S2 enhancement — events now carry ``source_type`` / ``source_id`` so
the downstream ``diagnosis_analysis`` script can attach §13.2-compliant
evidence entries (each finding evidence must declare source_type / source_id).
"""

from __future__ import annotations

import sys
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    read_json,
    write_json,
)


SCHEMA_VERSION = "1"

# Operations samples with value above this threshold become an anomaly_point
# event for the timeline. Threshold is per-metric — keeps the demo legible.
ANOMALY_THRESHOLDS = {
    "vibration_level": 0.7,
    "bearing_temp": 70.0,
}


def main() -> int:
    parser = base_parser("Build fault timeline from context")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    try:
        ctx = read_json(Path(args.input))
    except (FileNotFoundError, ValueError) as exc:
        return emit_error("INPUT_UNREADABLE", str(exc))

    events: list[dict] = []
    for wo in ctx.get("work_orders", []) or []:
        events.append(
            {
                "t": wo.get("created_at"),
                "type": "work_order",
                "label": wo.get("title", ""),
                "source_type": "work_order",
                "source_id": wo.get("id"),
                "level": "info",
            }
        )
    for mr in ctx.get("maintenance_records", []) or []:
        events.append(
            {
                "t": mr.get("at"),
                "type": "maintenance",
                "label": mr.get("type", ""),
                "source_type": "maintenance_record",
                "source_id": mr.get("id"),
                "level": "info",
            }
        )
    for alm in ctx.get("alarms", []) or []:
        events.append(
            {
                "t": alm.get("time"),
                "type": "alarm",
                "label": f"{alm.get('level')}: {alm.get('message') or alm.get('msg')}",
                "source_type": "alarm",
                "source_id": alm.get("id"),
                "level": alm.get("level", "info"),
            }
        )
    for op in ctx.get("operations", []) or []:
        metric = op.get("metric")
        threshold = ANOMALY_THRESHOLDS.get(metric)
        if threshold is None:
            continue
        value = op.get("value")
        if isinstance(value, (int, float)) and float(value) >= threshold:
            events.append(
                {
                    "t": op.get("t"),
                    "type": "anomaly_point",
                    "label": f"{metric}={value}",
                    "source_type": "timeseries",
                    "source_id": op.get("id", ""),
                    "level": "warning",
                }
            )

    events.sort(key=lambda e: e.get("t") or "")

    output = {
        "schema_version": SCHEMA_VERSION,
        "fault_time": ctx.get("fault_time"),
        "equipment_id": ctx.get("equipment_id"),
        "timeline": events,
        "event_count": len(events),
        "_meta": {"stub": True, "generated_at": iso_now()},
    }
    write_json(Path(args.output_dir), "fault_timeline", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
