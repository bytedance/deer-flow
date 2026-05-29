#!/usr/bin/env python3
"""Anomaly detection in service events."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev


def main():
    parser = argparse.ArgumentParser(description="Event anomaly detection")
    parser.add_argument("--input", required=True, help="Input JSON file")
    parser.add_argument("--threshold", type=float, default=2.0, help="Anomaly threshold (std devs)")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()

    try:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        records = data.get("records", [])

        if not records:
            result = {"anomalies": [], "total": 0}
        else:
            anomalies = []

            # Group by day
            events_by_day = defaultdict(int)
            for r in records:
                event_time = r.get("event_time")
                if event_time:
                    dt = datetime.fromtimestamp(event_time / 1000.0)
                    day_key = dt.strftime("%Y-%m-%d")
                    events_by_day[day_key] += 1

            # 1. Frequency spike
            if len(events_by_day) >= 3:
                daily_counts = list(events_by_day.values())
                avg_count = mean(daily_counts)
                std_count = stdev(daily_counts) if len(daily_counts) > 1 else 0.0
                spike_threshold = avg_count + args.threshold * std_count

                for day, count in events_by_day.items():
                    if count > spike_threshold and std_count > 0:
                        deviation = (count - avg_count) / std_count
                        severity = "high" if deviation > 3.0 else "medium" if deviation > 2.0 else "low"
                        anomalies.append({
                            "anomaly_type": "frequency_spike",
                            "unit_name": None,
                            "event_name": None,
                            "description": f"事件频率突增: {day} 发生 {count} 次 (均值 {avg_count:.1f})",
                            "severity": severity,
                            "event_count": count,
                            "baseline_count": int(avg_count),
                            "deviation_ratio": round(deviation, 2),
                        })

            # 2. New event type
            if len(records) >= 10:
                baseline_size = int(len(records) * 0.7)
                baseline_events = records[:baseline_size]
                recent_events = records[baseline_size:]

                baseline_types = {r.get("event_name") for r in baseline_events if r.get("event_name")}
                seen_new = set()
                for r in recent_events:
                    event_name = r.get("event_name")
                    if event_name and event_name not in baseline_types and event_name not in seen_new:
                        anomalies.append({
                            "anomaly_type": "new_event_type",
                            "unit_name": r.get("unit_name"),
                            "event_name": event_name,
                            "description": f"新事件类型: '{event_name}' 在基线期内未出现",
                            "severity": "medium",
                            "event_count": 1,
                        })
                        seen_new.add(event_name)

            # 3. High frequency unit
            unit_counts = defaultdict(int)
            for r in records:
                unit_name = r.get("unit_name")
                if unit_name:
                    unit_counts[unit_name] += 1

            if len(unit_counts) >= 3:
                counts = list(unit_counts.values())
                median_count = median(counts)
                high_freq_threshold = median_count * 2.0

                for unit, count in unit_counts.items():
                    if count > high_freq_threshold and median_count > 0:
                        ratio = count / median_count
                        severity = "high" if ratio > 3.0 else "medium"
                        anomalies.append({
                            "anomaly_type": "high_frequency_unit",
                            "unit_name": unit,
                            "event_name": None,
                            "description": f"高频机组: '{unit}' 事件数 {count} 次 (中位数 {median_count:.1f})",
                            "severity": severity,
                            "event_count": count,
                            "baseline_count": int(median_count),
                            "deviation_ratio": round(ratio, 2),
                        })

            result = {"anomalies": anomalies, "total": len(anomalies)}

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
