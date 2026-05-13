#!/usr/bin/env python3
"""preview_dataset.py — Preview schema and sample rows of a dataset.

Usage:
    python preview_dataset.py --dataset-id ID [--rows N]

Output:
    JSON to stdout:
    {"dataset_id": "...", "columns": [{"name": "...", "type": "...", ...}], "sample_rows": [...], "total_rows": N}

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


def fetch_with_urllib(url: str, headers: dict, timeout: float) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Preview dataset schema and sample data")
    parser.add_argument("--dataset-id", required=True, help="Dataset identifier")
    parser.add_argument("--rows", type=int, default=5, help="Number of sample rows")
    args = parser.parse_args()

    base_url = os.environ.get("DATA_PLATFORM_URL", "").rstrip("/")
    token = os.environ.get("DATA_PLATFORM_TOKEN", "")

    if not base_url:
        print(json.dumps({"dataset_id": args.dataset_id, "columns": [], "sample_rows": [], "error": "DATA_PLATFORM_URL not configured"}))
        sys.exit(0)

    url = f"{base_url}/api/v1/datasets/{args.dataset_id}/preview?rows={args.rows}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        if httpx is not None:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                result = resp.text
        else:
            result = fetch_with_urllib(url, headers, timeout=30.0)

        output = json.loads(result)
        output["dataset_id"] = args.dataset_id
        print(json.dumps(output, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"dataset_id": args.dataset_id, "columns": [], "sample_rows": [], "error": str(e)}))
        sys.exit(0)


if __name__ == "__main__":
    main()
