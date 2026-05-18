"""Closure-items demo data (issue tracker + actions + verification).

Sprint S4 enhancement — replaces the 62-line stub with a realistic demo that
covers all 5 closure statuses (pending / in_progress / verifying / closed /
reopened) so downstream ``closure_summary`` can exercise every code path.

Output contract:
- ``verification_period`` / ``owner_department`` echo
- ``closure_items[]``: each item has
    id / title / owner / department / created_at / due_date / closed_at
    status (5 values) / actions[] / verification_results[] / notes
- ``data_source: demo_fallback``
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    parse_csv,
    write_json,
)


SCHEMA_VERSION = "1"

VALID_STATUSES = ["pending", "in_progress", "verifying", "closed", "reopened"]


def _build_issue(idx: int, issue_id: str, today: date, department: str) -> dict:
    """Cycle through the 5 statuses so demo data always covers each path."""
    status = VALID_STATUSES[idx % len(VALID_STATUSES)]
    created = today - timedelta(days=60 - idx * 10)
    # `due_date` runs from 30 days ago to 30 days in the future depending on index
    # so the summary script's overdue-check has something to find.
    due = today + timedelta(days=(idx - 2) * 15)
    closed = (today - timedelta(days=5)) if status == "closed" else None

    actions = [
        {
            "id": f"{issue_id}-ACT-1",
            "label": "现场整改",
            "owner": "现场负责人",
            "status": "done" if status in ("closed", "verifying", "reopened") else "in_progress",
            "completed_at": (today - timedelta(days=20)).isoformat() if status in ("closed", "verifying") else None,
        },
        {
            "id": f"{issue_id}-ACT-2",
            "label": "复核验证",
            "owner": "技术部",
            "status": "done" if status == "closed" else "pending" if status == "pending" else "in_progress",
            "completed_at": closed.isoformat() if closed else None,
        },
    ]
    verifications = []
    if status in ("verifying", "closed"):
        verifications.append(
            {
                "id": f"{issue_id}-VER-1",
                "method": "现场抽查 + 数据复测",
                "executor": "QA",
                "outcome": "passed" if status == "closed" else "in_review",
                "executed_at": (today - timedelta(days=5)).isoformat(),
            }
        )
    if status == "reopened":
        verifications.append(
            {
                "id": f"{issue_id}-VER-1",
                "method": "首次验证",
                "executor": "QA",
                "outcome": "failed",
                "executed_at": (today - timedelta(days=15)).isoformat(),
                "reopen_reason": "复测振动仍超阈值",
            }
        )

    note = {
        "pending": "尚未指派现场负责人",
        "in_progress": "现场整改进行中",
        "verifying": "整改已完成，等待复核",
        "closed": "已闭环并通过复核",
        "reopened": "首次复核未通过，重新打开",
    }[status]

    return {
        "id": issue_id,
        "title": f"问题单 {issue_id}",
        "owner": "张三" if idx % 2 == 0 else "李四",
        "department": department or "运行部",
        "status": status,
        "created_at": created.isoformat(),
        "due_date": due.isoformat(),
        "closed_at": closed.isoformat() if closed else None,
        "actions": actions,
        "verification_results": verifications,
        "notes": note,
    }


def main() -> int:
    parser = base_parser("Closure-items demo data")
    parser.add_argument("--issue-ids", required=True, help="CSV of issue ids")
    parser.add_argument("--owner-department", default="")
    parser.add_argument("--verification-period", default="")
    args = parser.parse_args()

    ids = parse_csv(args.issue_ids)
    if not ids:
        return emit_error("INVALID_ISSUE_IDS", "--issue-ids cannot be empty")

    today = date.today()
    items = [_build_issue(idx, iid, today, args.owner_department) for idx, iid in enumerate(ids)]

    output = {
        "schema_version": SCHEMA_VERSION,
        "verification_period": args.verification_period,
        "owner_department": args.owner_department,
        "closure_items": items,
        "data_source": "demo_fallback",
        "_meta": {"stub": True, "generated_at": iso_now(), "as_of": today.isoformat()},
    }
    write_json(Path(args.output_dir), "closure_items", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
