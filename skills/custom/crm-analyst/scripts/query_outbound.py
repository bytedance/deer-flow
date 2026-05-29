#!/usr/bin/env python3
"""Query product outbound details from Xiaoshouyi CRM."""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from xsy_client import XsyClient


def main():
    parser = argparse.ArgumentParser(description="Query outbound details")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--spec-model", help="Filter by spec model")
    parser.add_argument("--min-qty", type=float, help="Minimum quantity")
    parser.add_argument("--max-qty", type=float, help="Maximum quantity")
    parser.add_argument("--limit", type=int, default=500, help="Max records")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()

    try:
        client = XsyClient()
        records = client.query_outbound(
            start_date=args.start_date,
            end_date=args.end_date,
            spec_model=args.spec_model,
            limit=args.limit,
        )

        # Transform to canonical format
        transformed = []
        for r in records:
            transformed.append({
                "id": str(r.get("id", "")),
                "quantity": float(r.get("customItem3__c", 0)),
                "spec_model": r.get("customItem5__c"),
                "created_at": r.get("createdAt"),
            })

        result = {
            "records": transformed,
            "total": len(transformed),
            "query": {
                "start_date": args.start_date,
                "end_date": args.end_date,
                "spec_model": args.spec_model,
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
