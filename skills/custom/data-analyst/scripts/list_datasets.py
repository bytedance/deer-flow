#!/usr/bin/env python3
"""list_datasets.py — List available datasets from the data platform.

Usage:
    python list_datasets.py [--source-type TYPE] [--search KEYWORD] [--limit N] [--parent PARENT_ID]

Output:
    JSON to stdout:
    {"datasets": [{"id": "...", "name": "...", "description": "...", ...}], "total": N}

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
    parser = argparse.ArgumentParser(description="List available datasets")
    parser.add_argument("--source-type", default=None, help="Filter by source type")
    parser.add_argument("--search", default=None, help="Search keyword")
    parser.add_argument("--limit", type=int, default=50, help="Max results")
    parser.add_argument("--parent", default=None, help="Parent ID for hierarchical sources")
    args = parser.parse_args()

    base_url = os.environ.get("DATA_PLATFORM_URL", "").rstrip("/")
    token = os.environ.get("DATA_PLATFORM_TOKEN", "")

    if not base_url:
        print(json.dumps({"datasets": [], "total": 0, "error": "DATA_PLATFORM_URL not configured"}))
        sys.exit(0)

    params = {"limit": str(args.limit)}
    if args.source_type:
        params["source_type"] = args.source_type
    if args.search:
        params["search"] = args.search
    if args.parent:
        params["parent"] = args.parent

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{base_url}/api/v1/datasets?{query_string}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        if httpx is not None:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                print(resp.text)
        else:
            result = fetch_with_urllib(url, headers, timeout=30.0)
            print(result)
    except Exception as e:
        print(json.dumps({"datasets": [], "total": 0, "error": str(e)}))
        sys.exit(0)


if __name__ == "__main__":
    main()
