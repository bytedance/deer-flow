"""Inspection records demo data.

Sprint S5 enhancement — replaces the 51-line stub with deterministic demo
records that cover all 3 severity tiers (low / medium / high / critical),
attach inspector + per-record attachments, and respect ``--severity-min``
filtering.

Output contract (``inspection_data.json``):
- ``inspection_date`` / ``route`` / ``area`` / ``severity_min`` echo
- ``records[]``: each with id / time / route / area / equipment / inspector /
  status (normal/warning/critical) / severity (low/medium/high/critical) /
  description / attachments[] (refs into the top-level attachments list)
- ``attachments[]`` (top-level): id / type (photo/note) / ref / summary
- ``data_source: demo_fallback``
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    write_json,
)


SCHEMA_VERSION = "1"

VALID_SEVERITY_MIN = {"low", "medium", "high"}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Demo records anchored to mid-day so timestamps fall inside a reasonable shift.
DEMO_RECORDS = [
    {
        "equipment": "P-001",
        "inspector": "张三",
        "status": "normal",
        "severity": "low",
        "description": "运行参数稳定，未发现异常",
        "attachment_refs": [],
    },
    {
        "equipment": "P-002",
        "inspector": "李四",
        "status": "warning",
        "severity": "medium",
        "description": "出口压力略有波动，需关注",
        "attachment_refs": ["ATT-002"],
    },
    {
        "equipment": "P-003",
        "inspector": "王五",
        "status": "warning",
        "severity": "high",
        "description": "振动持续超阈值，建议停机检查",
        "attachment_refs": ["ATT-003", "ATT-004"],
    },
    {
        "equipment": "RM-101",
        "inspector": "赵六",
        "status": "critical",
        "severity": "critical",
        "description": "联轴器异响，疑似对中漂移",
        "attachment_refs": ["ATT-005"],
    },
    {
        "equipment": "RM-102",
        "inspector": "张三",
        "status": "normal",
        "severity": "low",
        "description": "巡检通过，未发现异常",
        "attachment_refs": [],
    },
    {
        "equipment": "HE-201",
        "inspector": "孙七",
        "status": "warning",
        "severity": "medium",
        "description": "保温层局部脱落",
        "attachment_refs": ["ATT-006"],
    },
]

DEMO_ATTACHMENTS = [
    {"id": "ATT-001", "type": "photo", "ref": "/attachments/insp-001.jpg", "summary": "P-001 前轴承端外观"},
    {"id": "ATT-002", "type": "photo", "ref": "/attachments/insp-002.jpg", "summary": "P-002 出口压力表读数"},
    {"id": "ATT-003", "type": "photo", "ref": "/attachments/insp-003.jpg", "summary": "P-003 振动测点照片"},
    {"id": "ATT-004", "type": "note", "ref": "", "summary": "P-003 持续 30 分钟超阈值，已通知值班长"},
    {"id": "ATT-005", "type": "note", "ref": "", "summary": "RM-101 联轴器异响明显，建议立即停机"},
    {"id": "ATT-006", "type": "photo", "ref": "/attachments/insp-006.jpg", "summary": "HE-201 保温层照片"},
]


def main() -> int:
    parser = base_parser("Inspection records demo data")
    parser.add_argument("--inspection-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--route", default="")
    parser.add_argument("--area", default="")
    parser.add_argument("--severity-min", default="low")
    args = parser.parse_args()

    if args.severity_min not in VALID_SEVERITY_MIN:
        return emit_error(
            "INVALID_SEVERITY",
            f"severity_min must be one of {sorted(VALID_SEVERITY_MIN)}, got {args.severity_min!r}",
        )
    try:
        inspection_day = date.fromisoformat(args.inspection_date)
    except ValueError as exc:
        return emit_error("INVALID_INSPECTION_DATE", str(exc))

    min_rank = SEVERITY_RANK[args.severity_min]
    base_dt = datetime.combine(inspection_day, datetime.min.time()) + timedelta(hours=8)

    records: list[dict] = []
    used_attachment_ids: set[str] = set()
    for idx, template in enumerate(DEMO_RECORDS):
        if SEVERITY_RANK[template["severity"]] < min_rank:
            continue
        record_dt = base_dt + timedelta(minutes=idx * 27)
        record_id = f"INSP-{inspection_day.strftime('%Y%m%d')}-{idx + 1:03d}"
        record_attachments = template["attachment_refs"]
        used_attachment_ids.update(record_attachments)
        records.append(
            {
                "id": record_id,
                "time": record_dt.isoformat(timespec="seconds"),
                "route": args.route,
                "area": args.area,
                "equipment": template["equipment"],
                "inspector": template["inspector"],
                "status": template["status"],
                "severity": template["severity"],
                "description": template["description"],
                "attachment_refs": record_attachments,
            }
        )

    # Filter attachments to those actually referenced by surviving records.
    attachments = [att for att in DEMO_ATTACHMENTS if att["id"] in used_attachment_ids]

    output = {
        "schema_version": SCHEMA_VERSION,
        "inspection_date": args.inspection_date,
        "route": args.route,
        "area": args.area,
        "severity_min": args.severity_min,
        "data_source": "demo_fallback",
        "records": records,
        "attachments": attachments,
        "_meta": {"stub": True, "generated_at": iso_now()},
    }
    write_json(Path(args.output_dir), "inspection_data", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
