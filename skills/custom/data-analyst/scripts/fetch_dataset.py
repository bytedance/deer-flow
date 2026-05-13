#!/usr/bin/env python3
"""fetch_dataset.py — Fetch data from a specific dataset.

Usage:
    python fetch_dataset.py --dataset-id ID [--format json|csv] [--limit N] [--offset N]

Output:
    JSON to stdout:
    {"dataset_id": "...", "columns": [...], "data": [...], "total": N}

Environment:
    DATA_PLATFORM_URL — Base URL of the data platform API
    DATA_PLATFORM_TOKEN — Bearer token for authentication (optional)
"""

import argparse
import json
import os
import sys

try:
    import httpx
except ImportError:
    import urllib.request
    import urllib.error
    httpx = None


def fetch_with_urllib(url: str, headers: dict, body: bytes, timeout: float) -> str:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Fetch dataset data")
    parser.add_argument("--dataset-id", required=True, help="Dataset identifier")
    parser.add_argument("--format", default="json", choices=["json", "csv"], help="Output format")
    parser.add_argument("--limit", type=int, default=1000, help="Max rows to fetch")
    parser.add_argument("--offset", type=int, default=0, help="Row offset for pagination")
    args = parser.parse_args()

    base_url = os.environ.get("DATA_PLATFORM_URL", "").rstrip("/")
    token = os.environ.get("DATA_PLATFORM_TOKEN", "")

    if not base_url:
        print(json.dumps({"data": [], "error": "DATA_PLATFORM_URL not configured"}))
        sys.exit(0)

    url = f"{base_url}/api/v1/datasets/query"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "dataset_id": args.dataset_id,
        "format": args.format,
        "limit": args.limit,
        "offset": args.offset,
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        if httpx is not None:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, headers=headers, content=body)
                resp.raise_for_status()
                result = resp.text
        else:
            result = fetch_with_urllib(url, headers, body, timeout=60.0)

        output = json.loads(result)
        output["dataset_id"] = args.dataset_id
        print(json.dumps(output, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"dataset_id": args.dataset_id, "data": [], "error": str(e)}))
        sys.exit(0)


if __name__ == "__main__":
    main()
