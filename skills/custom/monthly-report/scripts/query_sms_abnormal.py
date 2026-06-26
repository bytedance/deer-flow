#!/usr/bin/env python3
"""Query SMS abnormal list for monthly report integration.

Fetches SMS /api/abnormal/list for a full calendar month and equipment scope,
filters by equipment IDs on the client side, and outputs a structured
JSON summary for the monthly report DSL pipeline.

Uses pagination (loops over pages) to handle months that may exceed the
default pageSize of 500 records.

Authentication reuses the features-tool InsApiClient, which supports
Bearer token (INS_ACCESS_TOKEN) with username/password login fallback.

Usage:
    python query_sms_abnormal.py \
        --report-month 2026-06 \
        --type rotating_machinery \
        --equipment P-203A,K-101 \
        --output /mnt/user-data/outputs/sms_abnormal.json
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from _report_common import SMS_SEVERITY_MAP

DEFAULT_OUTPUT_DIR = os.environ.get(
    "MONTHLY_REPORT_OUTPUT_DIR",
    os.environ.get(
        "WEEKLY_REPORT_OUTPUT_DIR",
        os.environ.get("DAILY_REPORT_OUTPUT_DIR", "/mnt/user-data/outputs"),
    ),
)

SMS_RELEVANT_TYPES = {"rotating_machinery", "all"}

PAGE_SIZE = 500
MAX_PAGES = 20

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


def _month_range_ms(report_month: str) -> tuple[int, int]:
    """Convert YYYY-MM to (start_ms, end_ms) covering the full calendar month in UTC."""
    year, month = map(int, report_month.split("-"))
    _, day_count = calendar.monthrange(year, month)
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year, month, day_count, 23, 59, 59, 999000, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


# ---------------------------------------------------------------------------
# SMS HTTP request (via features-tool InsApiClient)
# ---------------------------------------------------------------------------


def _request_sms(path: str, params: dict) -> dict:
    """Make a GET request to the SMS API via features-tool InsApiClient."""
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


def _fetch_all_pages(path: str, base_params: dict) -> list[dict]:
    """Fetch all pages from the SMS API, up to MAX_PAGES."""
    all_rows: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        params = {**base_params, "currentPage": page}
        result = _request_sms(path, params)
        if "error" in result:
            break
        data = result.get("data", result)
        rows = data.get("rows") if isinstance(data, dict) else []
        if not rows or not isinstance(rows, list):
            break
        all_rows.extend(rows)
        if len(rows) < base_params.get("pageSize", PAGE_SIZE):
            break
    return all_rows


# ---------------------------------------------------------------------------
# Core: fetch + aggregate
# ---------------------------------------------------------------------------


def fetch_sms_abnormal(
    report_month: str,
    equipment_ids: list[str],
    eq_type: str = "rotating_machinery",
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """Fetch SMS abnormal list for a calendar month and produce structured summary.

    Args:
        report_month: Report month YYYY-MM.
        equipment_ids: List of equipment IDs to filter by.
        eq_type: Equipment type filter. Non-rotating types short-circuit.
        equipment_meta: Optional dict of {id: {name, area, ...}} for display names.

    Returns:
        Dict with sms_abnormal payload per the output contract.
    """
    if eq_type not in SMS_RELEVANT_TYPES:
        return _empty_result(report_month, eq_type)

    start_ms, end_ms = _month_range_ms(report_month)

    user_id = os.environ.get("DEER_FLOW_EFFECTIVE_USER_ID", "0")

    search_keywords: list[str] = []
    if equipment_meta:
        search_keywords = [meta.get("name", "") for meta in equipment_meta.values() if meta.get("name")]
    search = ",".join(search_keywords) if search_keywords else ""

    print("[数据查询] 正在查询 SMS 异常数据 (monthly query_sms_abnormal)...", file=sys.stderr)
    base_params: dict = {
        "pageSize": PAGE_SIZE,
        "orgId": 0,
        "userId": user_id,
        "startTime": start_ms,
        "endTime": end_ms,
    }
    if search:
        base_params["search"] = search

    rows = _fetch_all_pages("/api/abnormal/list", base_params)

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

    total_count = len(filtered)
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}

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
        "report_month": report_month,
        "equipment_type": eq_type,
        "sms_abnormal": {
            "total_count": total_count,
            "by_severity": by_severity,
            "by_status": by_status,
            "by_type": by_type,
            "top_events": events,
        },
    }


def _empty_result(report_month: str, eq_type: str) -> dict:
    return {
        "report_month": report_month,
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
    out_path = output_path or Path(DEFAULT_OUTPUT_DIR) / "sms_abnormal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Query SMS abnormal list for monthly report")
    parser.add_argument("--report-month", required=True, help="Report month YYYY-MM")
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
        help="Output JSON path (default: <MONTHLY_REPORT_OUTPUT_DIR>/sms_abnormal.json)",
    )
    args = parser.parse_args()

    # Validate report-month format
    try:
        year, month = map(int, args.report_month.split("-"))
        if not (2000 <= year <= 2100) or not (1 <= month <= 12):
            raise ValueError("out of range")
    except (ValueError, TypeError):
        print(json.dumps({"error": f"invalid --report-month: {args.report_month} (expected YYYY-MM)"}, ensure_ascii=False))
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
        payload = fetch_sms_abnormal(args.report_month, equipment_ids, args.type, equipment_meta)
        out_path = write_output(payload, Path(args.output) if args.output else None)
        print(json.dumps({"output": str(out_path), "report_month": payload["report_month"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    sys.exit(main())
