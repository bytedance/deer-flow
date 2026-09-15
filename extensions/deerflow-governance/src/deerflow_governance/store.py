"""审批单与审计账本的持久化（只用 stdlib sqlite3）。

为什么审批单必须落库而不是放内存：
审批的本质是「跨进程、跨时间的人工介入」——审批的人和跑 agent 的进程不是同一个，
甚至不在同一台机器。放内存的审批系统只是个弹窗，不是审批。

审计账本是 **append-only**：只有 INSERT，没有 UPDATE/DELETE 的接口。
能被改的审计记录没有审计价值。审批单本身可以改状态（pending→approved），
但每一次状态变更都会往审计账本追加一条记录，形成不可篡改的决策链。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .contracts import AuditRecord, Ticket, TicketStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_ticket (
    ticket_id        TEXT PRIMARY KEY,
    fingerprint      TEXT NOT NULL,
    status           TEXT NOT NULL,
    tool_name        TEXT NOT NULL,
    tool_input_brief TEXT NOT NULL,
    reason           TEXT NOT NULL,
    rule_id          TEXT NOT NULL,
    risk             TEXT NOT NULL,
    thread_id        TEXT,
    run_id           TEXT,
    is_subagent      INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL,
    decided_at       REAL,
    decided_by       TEXT,
    decision_note    TEXT NOT NULL DEFAULT '',
    expires_at       REAL,
    grant_scope      TEXT NOT NULL DEFAULT 'exact'
);
CREATE INDEX IF NOT EXISTS idx_ticket_fp ON approval_ticket(fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_ticket_status ON approval_ticket(status, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    record_id   TEXT PRIMARY KEY,
    ts          REAL NOT NULL,
    kind        TEXT NOT NULL,
    tool_name   TEXT NOT NULL DEFAULT '',
    effect      TEXT NOT NULL DEFAULT '',
    rule_id     TEXT NOT NULL DEFAULT '',
    risk        TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT '',
    ticket_id   TEXT NOT NULL DEFAULT '',
    thread_id   TEXT,
    run_id      TEXT,
    user_id     TEXT,
    is_subagent INTEGER NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_thread ON audit_log(thread_id, ts);
"""


class GovernanceStore:
    def __init__(self, db_path: str | Path, *, jsonl_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 审计同时写一份 JSONL：SQLite 便于查询，JSONL 便于外部日志系统采集与离线归档
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------- 审批单 ----------------

    def create_ticket(self, ticket: Ticket) -> Ticket:
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO approval_ticket
                   (ticket_id, fingerprint, status, tool_name, tool_input_brief, reason, rule_id, risk,
                    thread_id, run_id, is_subagent, created_at, decided_at, decided_by, decision_note,
                    expires_at, grant_scope)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ticket.ticket_id, ticket.fingerprint, ticket.status.value, ticket.tool_name,
                    ticket.tool_input_brief, ticket.reason, ticket.rule_id, ticket.risk,
                    ticket.thread_id, ticket.run_id, int(ticket.is_subagent), ticket.created_at,
                    ticket.decided_at, ticket.decided_by, ticket.decision_note, ticket.expires_at,
                    ticket.grant_scope,
                ),
            )
        return ticket

    def _row_to_ticket(self, row: sqlite3.Row) -> Ticket:
        return Ticket(
            ticket_id=row["ticket_id"], fingerprint=row["fingerprint"], status=TicketStatus(row["status"]),
            tool_name=row["tool_name"], tool_input_brief=row["tool_input_brief"], reason=row["reason"],
            rule_id=row["rule_id"], risk=row["risk"], thread_id=row["thread_id"], run_id=row["run_id"],
            is_subagent=bool(row["is_subagent"]), created_at=row["created_at"], decided_at=row["decided_at"],
            decided_by=row["decided_by"], decision_note=row["decision_note"], expires_at=row["expires_at"],
            grant_scope=row["grant_scope"],
        )

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM approval_ticket WHERE ticket_id=?", (ticket_id,)).fetchone()
        return self._row_to_ticket(row) if row else None

    def find_by_fingerprint(self, fingerprint: str) -> Ticket | None:
        """查这个指纹上最新的一张单。

        排序刻意用 created_at DESC：同一指纹可能被批过又被撤销再重申，
        永远以最新一次人工决定为准，而不是「曾经批过就一直有效」。
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM approval_ticket WHERE fingerprint=? ORDER BY created_at DESC LIMIT 1",
                (fingerprint,),
            ).fetchone()
        return self._row_to_ticket(row) if row else None

    def decide(self, ticket_id: str, *, approved: bool, by: str, note: str = "", now: float | None = None) -> Ticket | None:
        now = now if now is not None else time.time()
        status = TicketStatus.APPROVED if approved else TicketStatus.DENIED
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """UPDATE approval_ticket SET status=?, decided_at=?, decided_by=?, decision_note=?
                   WHERE ticket_id=? AND status=?""",
                (status.value, now, by, note, ticket_id, TicketStatus.PENDING.value),
            )
            if cur.rowcount == 0:
                return None  # 不存在，或已经被裁决过 —— 不允许二次裁决
        ticket = self.get_ticket(ticket_id)
        if ticket:
            self.append_audit(
                AuditRecord.new(
                    "ticket_decided", tool_name=ticket.tool_name, effect=status.value, rule_id=ticket.rule_id,
                    risk=ticket.risk, fingerprint=ticket.fingerprint, ticket_id=ticket.ticket_id,
                    thread_id=ticket.thread_id, run_id=ticket.run_id, is_subagent=ticket.is_subagent,
                    detail={"decided_by": by, "note": note, "grant_scope": ticket.grant_scope},
                )
            )
        return ticket

    def list_tickets(self, *, status: TicketStatus | None = None, limit: int = 50) -> list[Ticket]:
        sql = "SELECT * FROM approval_ticket"
        params: tuple = ()
        if status is not None:
            sql += " WHERE status=?"
            params = (status.value,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        return [self._row_to_ticket(r) for r in rows]

    def expire_stale(self, *, now: float | None = None) -> int:
        """把过期的已批准单标记为 expired。由 CLI 或定时任务调用。"""
        now = now if now is not None else time.time()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE approval_ticket SET status=? WHERE status=? AND expires_at IS NOT NULL AND expires_at < ?",
                (TicketStatus.EXPIRED.value, TicketStatus.APPROVED.value, now),
            )
            return cur.rowcount

    # ---------------- 审计 ----------------

    def append_audit(self, record: AuditRecord) -> None:
        """只追加。本类刻意不提供审计记录的 update/delete 接口。"""
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO audit_log
                   (record_id, ts, kind, tool_name, effect, rule_id, risk, fingerprint, ticket_id,
                    thread_id, run_id, user_id, is_subagent, detail)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.record_id, record.ts, record.kind, record.tool_name, record.effect,
                    record.rule_id, record.risk, record.fingerprint, record.ticket_id, record.thread_id,
                    record.run_id, record.user_id, int(record.is_subagent),
                    json.dumps(record.detail, ensure_ascii=False, default=str),
                ),
            )
        if self.jsonl_path:
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False, default=str) + "\n")

    def audit_tail(self, *, limit: int = 50, thread_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM audit_log"
        params: tuple = ()
        if thread_id:
            sql += " WHERE thread_id=?"
            params = (thread_id,)
        sql += " ORDER BY ts DESC LIMIT ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"] or "{}")
            out.append(d)
        return out

    def stats(self) -> dict:
        """真实统计。没有数据就返回 0 / None，不编造。"""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM audit_log WHERE kind='policy_decision'").fetchone()["c"]
            if total == 0:
                return {"decisions": 0, "allow": 0, "ask": 0, "deny": 0, "pending_tickets": 0, "approval_rate": None}
            by_effect = {r["effect"]: r["c"] for r in conn.execute("SELECT effect, COUNT(*) c FROM audit_log WHERE kind='policy_decision' GROUP BY effect")}
            pending = conn.execute("SELECT COUNT(*) c FROM approval_ticket WHERE status='pending'").fetchone()["c"]
            decided = conn.execute("SELECT status, COUNT(*) c FROM approval_ticket WHERE status IN ('approved','denied') GROUP BY status").fetchall()
            decided_map = {r["status"]: r["c"] for r in decided}
            total_decided = sum(decided_map.values())
        return {
            "decisions": total,
            "allow": by_effect.get("allow", 0),
            "ask": by_effect.get("ask", 0),
            "deny": by_effect.get("deny", 0),
            "pending_tickets": pending,
            "approval_rate": round(decided_map.get("approved", 0) / total_decided, 4) if total_decided else None,
        }
