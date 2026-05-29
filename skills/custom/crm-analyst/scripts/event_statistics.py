#!/usr/bin/env python3
"""Statistical analysis of service events."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median


def main():
    parser = argparse.ArgumentParser(description="Service event statistics")
    parser.add_argument("--input", required=True, help="Input JSON file")
    parser.add_argument("--group-by", choices=["device_name", "name", "event_category", "work_order_type", "day", "week", "month"], help="Group by")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()

    try:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        records = data.get("records", [])

        if not records:
            result = {
                "total_records": 0,
                "by_unit": {},
                "by_event_type": {},
                "by_period": {},
                "frequency_per_unit": {},
            }
        else:
            unit_counts = defaultdict(int)
            for r in records:
                key = r.get("device_name") or r.get("name") or "unknown"
                unit_counts[key] += 1
            by_unit = dict(unit_counts)

            by_event_type = {}
            if args.group_by in ("event_category", "name", "work_order_type", None):
                event_groups = defaultdict(int)
                for r in records:
                    key = r.get("event_category") or r.get("name") or "unknown"
                    event_groups[key] += 1
                by_event_type = dict(event_groups)

            by_period = {}
            if args.group_by in ("day", "week", "month"):
                period_groups = defaultdict(int)
                for r in records:
                    event_time = r.get("fault_time") or r.get("created_at")
                    if event_time:
                        dt = datetime.fromtimestamp(event_time / 1000.0)
                        if args.group_by == "day":
                            key = dt.strftime("%Y-%m-%d")
                        elif args.group_by == "week":
                            key = dt.strftime("%Y-W%U")
                        else:
                            key = dt.strftime("%Y-%m")
                        period_groups[key] += 1
                by_period = dict(sorted(period_groups.items()))

            frequency_per_unit = {}
            times = [r["fault_time"] for r in records if r.get("fault_time")]
            if len(times) >= 2:
                min_time = min(times)
                max_time = max(times)
                span_days = max((max_time - min_time) / 1000.0 / 86400.0, 1.0)
                for unit, count in unit_counts.items():
                    frequency_per_unit[unit] = count / span_days

            result = {
                "total_records": len(records),
                "by_unit": by_unit,
                "by_event_type": by_event_type,
                "by_period": by_period,
                "frequency_per_unit": frequency_per_unit,
            }

        output_json = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(output_json, encoding="utf-8")
        else:
            print(output_json)

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
