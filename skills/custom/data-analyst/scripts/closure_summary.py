"""Closure summary — factual report (no §13.2 evidence chain needed).

Sprint S4 enhancement — consumes ``closure_items.json`` and produces a
fact-only summary: aggregate counts, completion_rate, risk checks, and a
conclusion. Distinct from interpretive reports (trend / diagnosis /
failure-analysis): no findings/evidence/confidence/human_review_required
contract here.

Output:
- overall_status: {level, summary, total, closed_count, pending_count, completion_rate}
- status_distribution: count per status
- unclosed_items: grouped by status
- risk_items: overdue items + reopened items
- closure_conclusion: mechanically generated
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    read_json,
    write_json,
)


SCHEMA_VERSION = "1"

ALL_STATUSES = ["pending", "in_progress", "verifying", "closed", "reopened"]


def _classify_risks(items: list[dict], today_iso: str) -> list[dict]:
    """Two risk categories:
    - overdue: due_date < today AND status != closed
    - reopened: status == reopened (first-time verification failed)
    """
    risks: list[dict] = []
    for it in items:
        due = it.get("due_date")
        status = it.get("status")
        if due and due < today_iso and status != "closed":
            risks.append(
                {
                    "id": it["id"],
                    "kind": "overdue",
                    "status": status,
                    "due_date": due,
                    "owner": it.get("owner"),
                    "department": it.get("department"),
                    "note": f"已逾期且未闭环（当前状态 {status}）",
                }
            )
        if status == "reopened":
            risks.append(
                {
                    "id": it["id"],
                    "kind": "reopened",
                    "status": status,
                    "due_date": due,
                    "owner": it.get("owner"),
                    "department": it.get("department"),
                    "note": "首次复核未通过，重新打开",
                }
            )
    return risks


def _conclusion(
    total: int, closed: int, completion_rate: float, risks: list[dict], period: str
) -> str:
    if total == 0:
        return "未提供问题单，无法生成闭环结论。"
    parts: list[str] = []
    period_clause = f"（验证周期：{period}）" if period else ""
    parts.append(f"共 {total} 项问题单{period_clause}，已闭环 {closed} 项，完成率 {completion_rate:.0%}。")
    overdue = [r for r in risks if r["kind"] == "overdue"]
    reopened = [r for r in risks if r["kind"] == "reopened"]
    if overdue:
        parts.append(f"发现 {len(overdue)} 项逾期未闭，需立即跟进。")
    if reopened:
        parts.append(f"{len(reopened)} 项被重新打开，建议复盘整改方案。")
    if not overdue and not reopened:
        parts.append("当前无风险项，可按计划推进。")
    return "".join(parts)


def main() -> int:
    parser = base_parser("Closure summary (factual report)")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    try:
        raw = read_json(Path(args.input))
    except (FileNotFoundError, ValueError) as exc:
        return emit_error("INPUT_UNREADABLE", str(exc))

    # Support both new field name (closure_items) and legacy (issues)
    items = raw.get("closure_items") or raw.get("issues") or []
    today_iso = date.today().isoformat()

    # Status distribution — always populate all 5 keys so the table is stable
    distribution = {status: 0 for status in ALL_STATUSES}
    for it in items:
        status = it.get("status", "pending")
        distribution[status] = distribution.get(status, 0) + 1

    total = len(items)
    closed = distribution.get("closed", 0)
    completion_rate = round(closed / total, 4) if total > 0 else 0.0
    unclosed_count = total - closed

    # Unclosed items: grouped by status (everything except closed)
    unclosed_items: list[dict] = [
        {
            "id": it["id"],
            "title": it.get("title"),
            "status": it.get("status"),
            "owner": it.get("owner"),
            "department": it.get("department"),
            "due_date": it.get("due_date"),
            "notes": it.get("notes"),
        }
        for it in items
        if it.get("status") != "closed"
    ]

    risks = _classify_risks(items, today_iso)
    conclusion = _conclusion(total, closed, completion_rate, risks, raw.get("verification_period", ""))

    # Overall level: critical if reopened items exist, warning if overdue, good otherwise
    if any(r["kind"] == "reopened" for r in risks):
        level = "critical"
    elif any(r["kind"] == "overdue" for r in risks):
        level = "warning"
    else:
        level = "good"

    overall_status = {
        "level": level,
        "summary": (
            f"共 {total} 项问题单，闭环 {closed} 项（{completion_rate:.0%}），未闭项 {unclosed_count} 项，风险项 {len(risks)} 项。"
        )[:80],
        "total": total,
        "closed_count": closed,
        "unclosed_count": unclosed_count,
        "completion_rate": completion_rate,
    }

    output = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "verification_period": raw.get("verification_period", ""),
            "owner_department": raw.get("owner_department", ""),
            "as_of": today_iso,
            "data_source": raw.get("data_source"),
        },
        "overall_status": overall_status,
        "status_distribution": [
            {"status": status, "count": distribution[status]}
            for status in ALL_STATUSES
        ],
        "unclosed_items": unclosed_items,
        "risk_items": risks,
        "closure_conclusion": conclusion,
        "_meta": {"stub": True, "generated_at": iso_now()},
    }
    write_json(Path(args.output_dir), "closure_summary", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
