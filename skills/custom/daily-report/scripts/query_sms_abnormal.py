#!/usr/bin/env python3
"""Query SMS abnormal list for daily report integration.

Fetches SMS /api/abnormal/list for a given date range and equipment scope,
filters by equipment IDs on the client side, and outputs a structured
JSON summary for the daily report DSL pipeline.

Authentication reuses the features-tool InsApiClient, which supports
Bearer token (INS_ACCESS_TOKEN) with username/password login fallback.

Usage:
    python query_sms_abnormal.py \
        --date 2026-06-04 \
        --type rotating_machinery \
        --equipment P-203A,K-101 \
        --output /mnt/user-data/outputs/sms_abnormal.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from _perf import get_tracer
from _report_common import SMS_SEVERITY_MAP

DEFAULT_OUTPUT_DIR = os.environ.get("DAILY_REPORT_OUTPUT_DIR", "/mnt/user-data/outputs")

# Equipment types for which SMS data is relevant
SMS_RELEVANT_TYPES = {"rotating_machinery", "all"}

# ---------------------------------------------------------------------------
# InsApiClient (features-tool) bootstrap
# ---------------------------------------------------------------------------

_ins_client = None
_ins_init_error: str | None = None


def _init_ins_client():
    """Initialize the features-tool InsApiClient (once)."""
    global _ins_client, _ins_init_error

    if _ins_client is not None or _ins_init_error is not None:
        return

    root = os.environ.get("FEATURES_TOOL_ROOT", "/mnt/skills/custom/features-tool")
    if not os.path.isdir(root):
        _ins_init_error = f"features-tool not found at {root}"
        return

    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from ins import InsApiClient, load_ins_settings

        settings = load_ins_settings()
        _ins_client = InsApiClient(settings)
    except ImportError as e:
        _ins_init_error = f"cannot import ins from {root}: {e}"
    except Exception as e:
        _ins_init_error = f"failed to initialize InsApiClient: {e}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_id(eq_id: str) -> str:
    """Normalize equipment ID for cross-system matching: strip hyphens, lowercase."""
    return eq_id.replace("-", "").replace("_", "").lower()


def _severity_label(level: int) -> str:
    """Map SMS latest_level to severity label."""
    for threshold, label in SMS_SEVERITY_MAP:
        if level >= threshold:
            return label
    return "low"


def _day_range_ms(date_str: str) -> tuple[int, int]:
    """Convert YYYY-MM-DD to (start_ms, end_ms) in UTC."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ms = int(dt.timestamp() * 1000)
    end_ms = start_ms + 24 * 60 * 60 * 1000 - 1
    return start_ms, end_ms


# ---------------------------------------------------------------------------
# SMS HTTP request (via features-tool InsApiClient)
# ---------------------------------------------------------------------------


def _request_sms(path: str, params: dict) -> dict:
    """Make a GET request to the SMS API via features-tool InsApiClient.

    Uses the InsApiClient's auth stack (Bearer token → login fallback) and
    httpx session, but parses the response directly so we don't depend on
    InS-specific ``code==200`` response conventions.
    """
    _init_ins_client()
    if _ins_client is None:
        return {"error": _ins_init_error or "InsApiClient not available"}

    return asyncio.run(_request_sms_async(path, params))


async def _request_sms_async(path: str, params: dict) -> dict:
    client = _ins_client
    str_params = {k: str(v) for k, v in params.items() if v is not None}

    try:
        token = await client.ensure_token()
        base_url = os.environ.get("SMS_BASE_URL", client.settings.base_url).rstrip("/")
        response = await client.http.get(
            f"{base_url}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}"},
            params=str_params,
        )
        if response.is_error:
            detail = response.text[:500] if response.text else ""
            return {"error": f"HTTP {response.status_code}", "detail": detail}
        return response.json()
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Core: fetch + aggregate
# ---------------------------------------------------------------------------


def fetch_sms_abnormal(
    date_str: str,
    equipment_ids: list[str],
    eq_type: str = "rotating_machinery",
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """Fetch SMS abnormal list and produce structured summary.

    Args:
        date_str: Report date YYYY-MM-DD.
        equipment_ids: List of equipment IDs to filter by.
        eq_type: Equipment type filter. Non-rotating types short-circuit.
        equipment_meta: Optional dict of {id: {name, area, ...}} for display names.

    Returns:
        Dict with sms_abnormal payload per the output contract.
    """
    # Short-circuit for non-rotating equipment types
    if eq_type not in SMS_RELEVANT_TYPES:
        return _empty_result(date_str, eq_type)

    start_ms, end_ms = _day_range_ms(date_str)

    user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID", "0")

    # Build search keywords from user-selected equipment labels
    search_keywords: list[str] = []
    if equipment_meta:
        search_keywords = [meta.get("name", "") for meta in equipment_meta.values() if meta.get("name")]
    search = ",".join(search_keywords) if search_keywords else ""

    print("[数据查询] 正在查询 SMS 异常数据 (query_sms_abnormal)...", file=sys.stderr)
    params: dict = {
        "currentPage": 1,
        "pageSize": 200,
        "orgId": 0,
        "userId": user_id,
        "startTime": start_ms,
        "endTime": end_ms,
    }
    if search:
        params["search"] = search
    result = _request_sms("/api/abnormal/list", params)

    if "error" in result:
        return {
            "report_date": date_str,
            "equipment_type": eq_type,
            "sms_abnormal": {"error": json.dumps(result, ensure_ascii=False)},
        }

    rows = result.get("data", result).get("rows") or []
    if not isinstance(rows, list):
        rows = []

    # Build lookup: normalized equipment ID set for filtering
    norm_ids = {_normalize_id(eid) for eid in equipment_ids} if equipment_ids else set()
    eq_names: dict[str, str] = {}
    if equipment_meta:
        eq_names = {_normalize_id(eid): meta.get("name", eid) for eid, meta in equipment_meta.items()}

    # Filter and classify
    filtered: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mac_id = str(row.get("macId", ""))
        if norm_ids and _normalize_id(mac_id) not in norm_ids:
            continue
        filtered.append(row)

    # Aggregate statistics
    total_count = len(filtered)
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}

    # Build top_events sorted by latest_level desc
    events: list[dict] = []
    for row in filtered:
        level = int(row.get("latestLevel") or 0)
        sev = _severity_label(level)
        by_severity[sev] = by_severity.get(sev, 0) + 1

        status = str(row.get("processStatus") or "未知")
        by_status[status] = by_status.get(status, 0) + 1

        mac_id = str(row.get("macId", ""))
        mac_name = str(row.get("macName", ""))
        component_name = str(row.get("componentName", ""))
        # Prefer Organize-tree name over SMS name when available
        norm_id = _normalize_id(mac_id)
        display_name = eq_names.get(norm_id, mac_name) if eq_names else mac_name

        events.append({
            "abnormal_id": str(row.get("id", "")),
            "mac_name": display_name,
            "component_name": component_name,
            "mac_id": mac_id,
            "latest_health": float(row.get("latestHealth") or 0),
            "latest_level": level,
            "serious_level": int(row.get("seriousLevel") or 0),
            "event_count": int(row.get("eventCount") or 0),
            "process_status": status,
            "run_status": str(row.get("runStatus", "")),
            "first_event_time": int(row.get("firstEventTime") or 0),
            "lastest_event_time": int(row.get("lastestEventTime") or 0),
        })

    events.sort(key=lambda e: (-e["latest_level"], -e["serious_level"]))
    for i, evt in enumerate(events, 1):
        evt["rank"] = i

    return {
        "report_date": date_str,
        "equipment_type": eq_type,
        "sms_abnormal": {
            "total_count": total_count,
            "by_severity": by_severity,
            "by_status": by_status,
            "by_type": by_type,
            "top_events": events,
        },
    }


def _empty_result(date_str: str, eq_type: str) -> dict:
    return {
        "report_date": date_str,
        "equipment_type": eq_type,
        "sms_abnormal": {
            "total_count": 0,
            "by_severity": {},
            "by_status": {},
            "by_type": {},
            "top_events": [],
        },
    }


def write_output(payload: dict, output_path: Path | None = None) -> Path:
    """Write SMS abnormal payload to JSON file."""
    out_path = output_path or Path(DEFAULT_OUTPUT_DIR) / "sms_abnormal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Query SMS abnormal list for daily report")
    parser.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    parser.add_argument(
        "--equipment",
        default="",
        help="Comma-separated equipment IDs to filter by",
    )
    parser.add_argument(
        "--equipment-names",
        dest="equipment_names",
        default="",
        help="Comma-separated equipment names aligned with --equipment (optional)",
    )
    parser.add_argument(
        "--type",
        default="rotating_machinery",
        help="Equipment type filter (default: rotating_machinery)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path (default: <DAILY_REPORT_OUTPUT_DIR>/sms_abnormal.json)",
    )
    args = parser.parse_args()

    # Validate date
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError as exc:
        print(json.dumps({"error": f"invalid --date: {exc}"}, ensure_ascii=False))
        return 0

    equipment_ids = [e.strip() for e in args.equipment.split(",") if e.strip()]
    equipment_names = [n.strip() for n in args.equipment_names.split(",") if n.strip()]
    equipment_meta = None
    if equipment_names and equipment_ids:
        equipment_meta = {
            eid: {"name": equipment_names[i] if i < len(equipment_names) else eid}
            for i, eid in enumerate(equipment_ids)
        }

    try:
        tracer = get_tracer(trace_id=os.environ.get("REPORT_RUN_ID"))
        tracer.start_span("sms_fetch")
        payload = fetch_sms_abnormal(args.date, equipment_ids, args.type, equipment_meta)
        sms_count = 0
        sms_data = payload.get("sms_abnormal") if isinstance(payload.get("sms_abnormal"), dict) else {}
        top_events = sms_data.get("top_events") if isinstance(sms_data, dict) else []
        if isinstance(top_events, list):
            sms_count = len(top_events)
        tracer.end_span(record_count=sms_count)
        out_path = write_output(payload, Path(args.output) if args.output else None)
        print(json.dumps({"output": str(out_path), "report_date": payload["report_date"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
