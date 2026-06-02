#!/usr/bin/env python3
"""Fetch monitoring trend / waveform data from InS for abnormal judgment.

Usage:
    python query_monitoring.py trend --point-id <gpid> --start <ms> --end <ms> --factory-id <id> [--output <path>]
    python query_monitoring.py waveform --point-id <gpid> --time <ms> --factory-id <id> [--output <path>]
    python query_monitoring.py batch --input /mnt/user-data/outputs/abnormal_detail.json [--output <path>]

Environment:
    INS_BASE_URL           — InS base URL (default: http://182.92.187.198)
    INS_ACCESS_TOKEN       — Bearer token (injected by Deer Flow runtime)
    INS_REFRESH_TOKEN      — Refresh token for auto-renewal on 401 (injected by Deer Flow runtime)
    DEER_FLOW_GATEWAY_URL  — Deer Flow Gateway URL for token refresh (default: http://localhost:8001)

When INS_REFRESH_TOKEN is available, HTTP 401 responses trigger an automatic
token refresh via ``POST /api/auth/ins-base/refresh`` on the Deer Flow Gateway.
On success the new token is used for a single retry.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

INS_BASE = os.environ.get("INS_BASE_URL", "http://182.92.187.198")
GATEWAY_URL = os.environ.get("DEER_FLOW_GATEWAY_URL", "http://localhost:8001")
REFRESH_TOKEN = os.environ.get("INS_REFRESH_TOKEN", "")

# Mutable token — _try_refresh_token() updates it in-place on successful refresh.
_token = os.environ.get("INS_ACCESS_TOKEN", "")

# 8K rotating machinery — must match InsApiClient in features-tool
TREND_PATH = "/ins-os-view/sg8kData/getTrendDataHis"
WAVEFORM_PATH = "/ins-os-view/sg8kData/getWaveDataHis"

FEATURES = "pp_value,rms,1x,2x,remain_freq,speed,gap"
INCLUDE_FILTER = "history,startstop,blackbox,alarm"


def _try_refresh_token() -> bool:
    """Attempt to refresh the access token via Deer Flow Gateway.

    Calls ``POST /api/auth/ins-base/refresh`` with the stored refresh token.
    On success, updates the module-level ``_token`` and returns True.

    Returns:
        True if the token was successfully refreshed.
    """
    if not REFRESH_TOKEN:
        print("[query_monitoring] no INS_REFRESH_TOKEN available, cannot refresh", file=sys.stderr)
        return False

    refresh_url = f"{GATEWAY_URL}/api/auth/ins-base/refresh"
    body = json.dumps({"refresh_token": REFRESH_TOKEN}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    print(f"[query_monitoring] attempting token refresh via {refresh_url}", file=sys.stderr)
    req = urllib.request.Request(refresh_url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")[:500]
        print(f"[query_monitoring] token refresh HTTP {e.code}: {body_text}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[query_monitoring] token refresh error: {e}", file=sys.stderr)
        return False

    new_token = data.get("token") or data.get("access_token")
    if not new_token or not isinstance(new_token, str) or not new_token.strip():
        print(f"[query_monitoring] token refresh response missing token: {data}", file=sys.stderr)
        return False

    global _token
    _token = new_token.strip()
    print("[query_monitoring] token refreshed successfully", file=sys.stderr)
    return True


def _get(path: str, params: dict) -> dict:
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    url = f"{INS_BASE}{path}?{qs}"

    def _do_request() -> dict:
        headers = {"Accept": "application/json"}
        if _token:
            headers["Authorization"] = f"Bearer {_token}"

        print(f"[query_monitoring] GET {url}", file=sys.stderr)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                print(f"[query_monitoring] response: {len(raw)} bytes", file=sys.stderr)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            print(f"[query_monitoring] HTTP {e.code}: {body}", file=sys.stderr)
            return {"error": f"HTTP {e.code}", "detail": body, "status_code": e.code}
        except Exception as e:
            print(f"[query_monitoring] error: {e}", file=sys.stderr)
            return {"error": str(e)}

    result = _do_request()

    # Auto-refresh on 401 when a refresh token is available.
    if isinstance(result, dict) and result.get("status_code") == 401:
        if _try_refresh_token():
            print("[query_monitoring] retrying request with refreshed token", file=sys.stderr)
            result = _do_request()

    return result


def _extract_trend_summary(raw: dict, point_id: str) -> dict:
    """Extract compact summary from 8K trend response.

    8K API returns multiple formats:
    - {"code":200, "data": {"<gpid>": {"values": {"pp_value": [...], ...}}}}
    - {"code":200, "data": [{"<gpid>": {"values": {...}}}, ...]}
    - {"code":200, "data": {"<gpid>": {"trendData": {"dataArr": [...]}}}}
    """
    data = raw.get("data", {})
    if isinstance(data, list):
        # List format: find entry matching point_id
        point_data = {}
        for entry in data:
            if isinstance(entry, dict):
                if point_id in entry:
                    point_data = entry[point_id]
                    break
                # Fallback: use first entry's first key
                if not point_data:
                    for k in entry:
                        if not k.startswith("_"):
                            point_data = entry[k]
                            break
        if not point_data:
            return {"point_id": point_id, "points": [], "error": "no matching data in list"}
    elif isinstance(data, dict):
        point_data = data.get(point_id, {})
        if not point_data:
            # Try first key as fallback
            keys = [k for k in data if not k.startswith("_")]
            if keys:
                point_data = data.get(keys[0], {})
    else:
        return {"point_id": point_id, "points": [], "error": f"unexpected data type: {type(data).__name__}"}

    if not point_data:
        return {"point_id": point_id, "points": [], "error": "no data for point"}

    # 8K format: {"<gpid>": {"values": {"pp_value": [...], "rms": [...]}}}
    values = point_data.get("values", {})
    if isinstance(values, dict) and values:
        result = {"point_id": point_id}
        for feat, arr in values.items():
            if isinstance(arr, list) and len(arr) > 0:
                nums = [v for v in arr if isinstance(v, (int, float))]
                if nums:
                    result[feat] = {
                        "count": len(nums),
                        "min": round(min(nums), 4),
                        "max": round(max(nums), 4),
                        "avg": round(sum(nums) / len(nums), 4),
                        "first": nums[0],
                        "last": nums[-1],
                    }
        if len(result) > 1:
            return result

    # Alternative 8K format: trendData.dataArr
    trend_data = point_data.get("trendData", {})
    data_arr = trend_data.get("dataArr", [])
    if data_arr:
        vals = []
        for item in data_arr:
            if isinstance(item, dict):
                v = item.get("value") or item.get("v")
                if isinstance(v, (int, float)):
                    vals.append(v)
                elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], (int, float)):
                    vals.append(v[0])
        if vals:
            return {
                "point_id": point_id,
                "count": len(vals),
                "min": round(min(vals), 4),
                "max": round(max(vals), 4),
                "avg": round(sum(vals) / len(vals), 4),
                "first": vals[0],
                "last": vals[-1],
            }

    return {"point_id": point_id, "points": [], "error": "unknown response format"}


def cmd_trend(args):
    params = {
        "gpids": args.point_id,
        "startTime": args.start,
        "endTime": args.end,
        "density": "high",
        "typeList": FEATURES,
        "includeFilter": INCLUDE_FILTER,
        "factoryId": args.factory_id,
    }
    result = _get(TREND_PATH, params)
    if "error" not in result:
        result = _extract_trend_summary(result, args.point_id)
    _output(result, args.output)


def cmd_waveform(args):
    params = {
        "gpids": args.point_id,
        "timepoint": args.time,
        "factoryId": args.factory_id,
    }
    result = _get(WAVEFORM_PATH, params)
    _output(result, args.output)


def cmd_batch(args):
    """Read abnormal_detail.json, fetch trend for every event point, merge results."""
    with open(args.input, encoding="utf-8") as f:
        raw = json.load(f)

    detail = raw.get("data", raw) if isinstance(raw, dict) else raw

    queries: list[dict] = []
    seen = set()
    for evt in detail.get("events", []):
        jp = evt.get("jumpParams", {}) or {}
        fid = str(jp.get("factoryId", ""))
        t_start = jp.get("startTime", 0)
        t_end = jp.get("endTime", 0)
        if not t_start or not t_end:
            et = evt.get("time", 0)
            t_start = et - 2 * 3600 * 1000
            t_end = et + 2 * 3600 * 1000
        for pt in jp.get("points", []):
            pid = str(pt.get("pointId", ""))
            if not pid:
                continue
            key = (pid, fid)
            if key in seen:
                continue
            seen.add(key)
            queries.append({
                "point_id": pid,
                "point_name": pt.get("pointName", ""),
                "value_type": pt.get("valueType", ""),
                "factory_id": fid,
                "start": t_start,
                "end": t_end,
            })

    results = []
    for q in queries:
        print(f"[query_monitoring] batch: {q['point_name']} ({q['point_id']}) start={q['start']} end={q['end']}", file=sys.stderr)
        params = {
            "gpids": q["point_id"],
            "startTime": q["start"],
            "endTime": q["end"],
            "density": "high",
            "typeList": FEATURES,
            "includeFilter": INCLUDE_FILTER,
            "factoryId": q["factory_id"],
        }
        raw = _get(TREND_PATH, params)
        summary = _extract_trend_summary(raw, q["point_id"]) if "error" not in raw else raw
        if isinstance(summary, dict):
            summary["point_name"] = q["point_name"]
            summary["value_type"] = q["value_type"]
            summary["time_range"] = {"start": q["start"], "end": q["end"]}
        results.append(summary)

    _output({"trends": results}, args.output)


def _output(data: dict, out_path: str = ""):
    json_text = json.dumps(data, ensure_ascii=False, indent=2)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json_text)
        print(f"[query_monitoring] written to {out_path}", file=sys.stderr)
    print(json_text)


def main():
    p = argparse.ArgumentParser(description="Fetch InS monitoring data for abnormal judgment")
    sub = p.add_subparsers(dest="cmd")

    t = sub.add_parser("trend", help="Fetch trend data for a single point")
    t.add_argument("--point-id", required=True)
    t.add_argument("--start", required=True, help="Start time (ms)")
    t.add_argument("--end", required=True, help="End time (ms)")
    t.add_argument("--factory-id", required=True)
    t.add_argument("--output", default="")

    w = sub.add_parser("waveform", help="Fetch waveform data for a single point")
    w.add_argument("--point-id", required=True)
    w.add_argument("--time", required=True, help="Timestamp (ms)")
    w.add_argument("--factory-id", required=True)
    w.add_argument("--output", default="")

    b = sub.add_parser("batch", help="Batch fetch trend for all points in abnormal_detail.json")
    b.add_argument("--input", required=True, help="Path to abnormal_detail.json")
    b.add_argument("--output", default="")

    args = p.parse_args()

    if args.cmd == "trend":
        cmd_trend(args)
    elif args.cmd == "waveform":
        cmd_waveform(args)
    elif args.cmd == "batch":
        cmd_batch(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
