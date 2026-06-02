#!/usr/bin/env python3
"""Fetch SMS abnormal detail directly from the SMS API.

Usage:
    python query_abnormal_detail.py --abnormal-id <id> [--mac-id <id>] [--component-id <id>] [--output <path>]

The SMS /api/abnormal/detail endpoint does NOT return mac_id / component_id.
Pass them from the list-side data so they are merged into the output for downstream use.

Environment:
    INS_BASE_URL          — SMS/InS base URL (default: http://182.92.187.198)
    INS_ACCESS_TOKEN      — Bearer token for SMS authentication
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

SMS_BASE = os.environ.get("INS_BASE_URL", "http://182.92.187.198")
TOKEN = os.environ.get("INS_ACCESS_TOKEN", "")


def _request(path: str, params: dict) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
    url = f"{SMS_BASE}{path}?{qs}"
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        return {"error": f"HTTP {e.code}", "detail": body, "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


def main():
    p = argparse.ArgumentParser(description="Fetch SMS abnormal detail")
    p.add_argument("--abnormal-id", required=True, help="Abnormal event ID")
    p.add_argument("--mac-id", default="", help="Equipment ID (merged into output)")
    p.add_argument("--component-id", default="", help="Sub-device ID (merged into output)")
    p.add_argument("--output", default="", help="Write JSON to file instead of stdout")
    args = p.parse_args()

    params = {"abnormalId": args.abnormal_id}
    print(f"[query_abnormal_detail] requesting: path=/api/abnormal/detail params={params}", file=sys.stderr)
    print(f"[query_abnormal_detail] merge: mac_id={args.mac_id!r} component_id={args.component_id!r}", file=sys.stderr)

    result = _request("/api/abnormal/detail", params)

    # Merge mac_id / component_id from CLI (SMS detail API does not return them)
    if isinstance(result, dict) and "error" not in result:
        if args.mac_id:
            result["mac_id"] = args.mac_id
        if args.component_id:
            result["component_id"] = args.component_id

    json_text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        out_path = args.output
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json_text)
        print(f"Written to {out_path}", file=sys.stderr)

    print(json_text)


if __name__ == "__main__":
    main()
