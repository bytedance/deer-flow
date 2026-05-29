#!/usr/bin/env python3
"""Query service event details from Xiaoshouyi CRM."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from xsy_client import XsyClient


def main():
    parser = argparse.ArgumentParser(description="Query service events")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--unit-name", help="Filter by unit name")
    parser.add_argument("--event-name", help="Filter by event name")
    parser.add_argument("--limit", type=int, default=500, help="Max records")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()

    try:
        client = XsyClient()
        records = client.query_service_events(
            start_date=args.start_date,
            end_date=args.end_date,
            unit_name=args.unit_name,
            event_name=args.event_name,
            limit=args.limit,
        )

        transformed = []
        for r in records:
            transformed.append({
                "id": str(r.get("id", "")),
                "unit_name": r.get("customItem4__c"),
                "event_name": r.get("customItem6__c"),
                "event_time": r.get("customItem8__c"),
            })

        result = {
            "records": transformed,
            "total": len(transformed),
            "query": {
                "start_date": args.start_date,
                "end_date": args.end_date,
                "unit_name": args.unit_name,
                "event_name": args.event_name,
                "limit": args.limit,
            },
        }

        output_json = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(output_json, encoding="utf-8")
        else:
            print(output_json)

    except Exception as e:
        error_result = {"error": str(e), "records": [], "total": 0}
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
