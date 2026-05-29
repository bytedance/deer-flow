#!/usr/bin/env python3
"""Statistical analysis of outbound data."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean


def main():
    parser = argparse.ArgumentParser(description="Outbound statistics")
    parser.add_argument("--input", required=True, help="Input JSON file")
    parser.add_argument("--group-by", choices=["spec_model", "day", "week", "month"], help="Group by")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()

    try:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        records = data.get("records", [])

        if not records:
            result = {
                "total_records": 0,
                "total_quantity": 0.0,
                "avg_quantity": 0.0,
                "min_quantity": 0.0,
                "max_quantity": 0.0,
                "by_spec_model": {},
                "by_period": {},
            }
        else:
            quantities = [r["quantity"] for r in records]

            by_spec_model = {}
            if args.group_by in ("spec_model", None):
                spec_groups = defaultdict(float)
                for r in records:
                    key = r.get("spec_model") or "unknown"
                    spec_groups[key] += r["quantity"]
                by_spec_model = dict(spec_groups)

            by_period = {}
            if args.group_by in ("day", "week", "month"):
                period_groups = defaultdict(float)
                for r in records:
                    created_at = r.get("created_at")
                    if created_at:
                        dt = datetime.fromtimestamp(created_at / 1000.0)
                        if args.group_by == "day":
                            key = dt.strftime("%Y-%m-%d")
                        elif args.group_by == "week":
                            key = dt.strftime("%Y-W%U")
                        else:
                            key = dt.strftime("%Y-%m")
                        period_groups[key] += r["quantity"]
                by_period = dict(sorted(period_groups.items()))

            result = {
                "total_records": len(records),
                "total_quantity": sum(quantities),
                "avg_quantity": mean(quantities),
                "min_quantity": min(quantities),
                "max_quantity": max(quantities),
                "by_spec_model": by_spec_model,
                "by_period": by_period,
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
