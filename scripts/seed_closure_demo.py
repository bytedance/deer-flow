"""One-shot seed for closure_sla_configs + sample closure_tickets.

Idempotent on re-run: skips SLA rows that already exist for `__default__`,
and skips ticket rows whose (tenant_id, source_type, source_run_id, device_id)
key already exists.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "backend" / ".deer-flow" / "data" / "deerflow.db"


def utc_now() -> datetime:
    return datetime.utcnow()


def iso(dt: datetime) -> str:
    return dt.isoformat()


def seed_sla(con: sqlite3.Connection) -> int:
    cur = con.cursor()
    cur.execute(
        "SELECT priority FROM closure_sla_configs WHERE tenant_id = ?",
        ("__default__",),
    )
    existing = {row[0] for row in cur.fetchall()}
    defaults = [
        ("urgent", 4),
        ("important", 72),
        ("normal", 168),
        ("observe", 720),
    ]
    inserted = 0
    now = iso(utc_now())
    for priority, hours in defaults:
        if priority in existing:
            continue
        cur.execute(
            "INSERT INTO closure_sla_configs(id, tenant_id, priority, sla_hours, "
            "updated_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "__default__", priority, hours, None, now, now),
        )
        inserted += 1
    return inserted


SAMPLE_TICKETS = [
    {
        "tenant_id": "zm",
        "title": "1#磨煤机出口温度持续偏低",
        "description": "近 24h 出口温度低于工艺下限 3-5℃，疑似冷一次风门卡涩。",
        "status": "pending",
        "priority": "important",
        "severity": "high",
        "device_id": "MILL-1",
        "device_name": "1#磨煤机",
        "source_type": "diagnosis",
        "due_offset_hours": 72,
    },
    {
        "tenant_id": "zm",
        "title": "3#给水泵密封水流量异常",
        "description": "密封水流量比同型号泵低 30%，建议检修密封件。",
        "status": "assigned",
        "priority": "normal",
        "severity": "medium",
        "device_id": "FW-PUMP-3",
        "device_name": "3#给水泵",
        "source_type": "daily_report",
        "due_offset_hours": 168,
        "assignee_email": "yh@shenguyun.com",
    },
    {
        "tenant_id": "zm",
        "title": "脱硫塔浆液 pH 越限",
        "description": "pH 已连续 6h 低于 4.8，吸收效率下降，需现场加药调整。",
        "status": "in_progress",
        "priority": "urgent",
        "severity": "critical",
        "device_id": "FGD-1",
        "device_name": "1#脱硫塔",
        "source_type": "diagnosis",
        "due_offset_hours": 4,
        "assignee_email": "yh@shenguyun.com",
        "started_offset_hours": -1,
    },
    {
        "tenant_id": "zm",
        "title": "2#引风机轴承振动趋势上行（已超期）",
        "description": "30 天振动趋势上行 18%，已达预警线，需安排停机检查。",
        "status": "in_progress",
        "priority": "urgent",
        "severity": "high",
        "device_id": "ID-FAN-2",
        "device_name": "2#引风机",
        "source_type": "weekly_report",
        "due_offset_hours": -8,
        "assignee_email": "yh@shenguyun.com",
        "started_offset_hours": -20,
        "is_overdue": True,
    },
    {
        "tenant_id": "zm",
        "title": "凝结水溶氧偏高待验证",
        "description": "更换除氧器排气阀后溶氧已恢复正常，提交闭环验证。",
        "status": "pending_verification",
        "priority": "normal",
        "severity": "medium",
        "device_id": "DEAERATOR-1",
        "device_name": "除氧器",
        "source_type": "daily_report",
        "due_offset_hours": 168,
        "assignee_email": "yh@shenguyun.com",
        "started_offset_hours": -48,
        "submitted_offset_hours": -2,
    },
    {
        "tenant_id": "zm",
        "title": "4#循环泵电流异常已闭环",
        "description": "电流偏高根因为滤网堵塞，清理后恢复正常，运行稳定 48h。",
        "status": "closed",
        "priority": "normal",
        "severity": "low",
        "device_id": "CW-PUMP-4",
        "device_name": "4#循环泵",
        "source_type": "monthly_report",
        "due_offset_hours": 168,
        "assignee_email": "yh@shenguyun.com",
        "started_offset_hours": -72,
        "submitted_offset_hours": -50,
        "closed_offset_hours": -1,
    },
    {
        "tenant_id": "default",
        "title": "演示：测试设备温度异常",
        "description": "default 租户演示用整改单，可直接派单/处置/关闭。",
        "status": "pending",
        "priority": "normal",
        "severity": "medium",
        "device_id": "DEMO-DEV-1",
        "device_name": "演示设备",
        "source_type": "manual",
        "due_offset_hours": 168,
    },
]


def resolve_user_id(con: sqlite3.Connection, email: str) -> str | None:
    cur = con.cursor()
    cur.execute("SELECT id FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    return row[0] if row else None


def seed_tickets(con: sqlite3.Connection) -> int:
    cur = con.cursor()
    inserted = 0
    now = utc_now()

    for spec in SAMPLE_TICKETS:
        source_run_id = f"seed-{spec['device_id']}"
        cur.execute(
            "SELECT id FROM closure_tickets WHERE tenant_id = ? AND source_type = ? "
            "AND source_run_id = ? AND device_id = ?",
            (spec["tenant_id"], spec["source_type"], source_run_id, spec["device_id"]),
        )
        if cur.fetchone():
            continue

        ticket_id = str(uuid.uuid4())
        creator = resolve_user_id(con, "yh@shenguyun.com") or resolve_user_id(
            con, "test@example.com"
        ) or "system"
        assignee_id = (
            resolve_user_id(con, spec["assignee_email"])
            if spec.get("assignee_email")
            else None
        )

        due_at = now + timedelta(hours=spec["due_offset_hours"])
        is_overdue = bool(spec.get("is_overdue")) or (
            spec["status"] not in ("closed", "rejected") and due_at < now
        )
        assigned_at = (
            now if spec["status"] != "pending" and assignee_id is not None else None
        )
        started_at = (
            now + timedelta(hours=spec["started_offset_hours"])
            if "started_offset_hours" in spec
            else None
        )
        submitted_at = (
            now + timedelta(hours=spec["submitted_offset_hours"])
            if "submitted_offset_hours" in spec
            else None
        )
        closed_at = (
            now + timedelta(hours=spec["closed_offset_hours"])
            if "closed_offset_hours" in spec
            else None
        )

        cur.execute(
            """
            INSERT INTO closure_tickets(
                id, tenant_id, title, description, status, priority, severity,
                device_id, device_name, created_by, assignee_id, verifier_id,
                source_type, source_run_id, source_thread_id, extra_metadata,
                due_at, is_overdue, created_at, updated_at,
                assigned_at, started_at, submitted_at, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                spec["tenant_id"],
                spec["title"],
                spec["description"],
                spec["status"],
                spec["priority"],
                spec.get("severity"),
                spec["device_id"],
                spec["device_name"],
                creator,
                assignee_id,
                None,
                spec["source_type"],
                source_run_id,
                None,
                json.dumps({"seed": True}),
                iso(due_at),
                1 if is_overdue else 0,
                iso(now - timedelta(hours=24)),
                iso(now),
                iso(assigned_at) if assigned_at else None,
                iso(started_at) if started_at else None,
                iso(submitted_at) if submitted_at else None,
                iso(closed_at) if closed_at else None,
            ),
        )

        cur.execute(
            "INSERT INTO closure_ticket_events(id, ticket_id, tenant_id, action, "
            "from_status, to_status, actor_id, payload, created_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                ticket_id,
                spec["tenant_id"],
                "create",
                None,
                "pending",
                creator,
                json.dumps({"seed": True}),
                iso(now - timedelta(hours=24)),
            ),
        )

        if assigned_at:
            cur.execute(
                "INSERT INTO closure_ticket_events(id, ticket_id, tenant_id, action, "
                "from_status, to_status, actor_id, payload, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    ticket_id,
                    spec["tenant_id"],
                    "assign",
                    "pending",
                    "assigned",
                    creator,
                    json.dumps({"assignee_id": assignee_id}),
                    iso(assigned_at),
                ),
            )
        if started_at:
            cur.execute(
                "INSERT INTO closure_ticket_events(id, ticket_id, tenant_id, action, "
                "from_status, to_status, actor_id, payload, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    ticket_id,
                    spec["tenant_id"],
                    "start",
                    "assigned",
                    "in_progress",
                    assignee_id,
                    json.dumps({}),
                    iso(started_at),
                ),
            )
        if submitted_at:
            cur.execute(
                "INSERT INTO closure_ticket_events(id, ticket_id, tenant_id, action, "
                "from_status, to_status, actor_id, payload, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    ticket_id,
                    spec["tenant_id"],
                    "submit_verification",
                    "in_progress",
                    "pending_verification",
                    assignee_id,
                    json.dumps({"resolution": "已处置完成，提交验证"}),
                    iso(submitted_at),
                ),
            )
        if closed_at:
            cur.execute(
                "INSERT INTO closure_ticket_events(id, ticket_id, tenant_id, action, "
                "from_status, to_status, actor_id, payload, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    ticket_id,
                    spec["tenant_id"],
                    "verify_close",
                    "pending_verification",
                    "closed",
                    creator,
                    json.dumps({"verification_note": "验证通过"}),
                    iso(closed_at),
                ),
            )

        inserted += 1

    return inserted


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"DB not found: {DB}")
    con = sqlite3.connect(DB)
    try:
        sla_added = seed_sla(con)
        ticket_added = seed_tickets(con)
        con.commit()
    finally:
        con.close()
    print(f"sla rows inserted: {sla_added}")
    print(f"ticket rows inserted: {ticket_added}")


if __name__ == "__main__":
    main()
