"""Short approval transactions, independent of an active Agent event loop."""

from __future__ import annotations

import asyncio
import copy
import time

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from deerflow.persistence.tool_approvals.model import ToolApprovalRow


class ApprovalConflict(ValueError):
    pass


class ApprovalStore:
    """SQL when configured, memory for deliberately ephemeral deployments.

    Decisions use compare-and-set so concurrent browser tabs cannot replace an
    accepted answer. Every read and write requires the full owner/thread scope.
    """

    def __init__(self, session_factory=None):
        self.sf = session_factory
        self.rows: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    async def create(self, row: dict) -> None:
        row = copy.deepcopy(row)
        if self.sf is None:
            async with self.lock:
                existing = self.rows.get(row["request_id"])
                if existing is None:
                    self.rows[row["request_id"]] = row
                    return
        else:
            async with self.sf() as session:
                session.add(ToolApprovalRow(**row))
                try:
                    await session.commit()
                    return
                except IntegrityError:
                    await session.rollback()
            existing = await self.get(row["request_id"], scope=(row["user_id"], row["thread_id"], row["incarnation"]))
        if existing is None or any(existing[key] != row[key] for key in ("user_id", "thread_id", "incarnation", "fingerprint", "kind")):
            raise ApprovalConflict("Approval identity changed")

    @staticmethod
    def _scope(scope):
        owner, thread, incarnation = scope
        return (ToolApprovalRow.user_id == owner, ToolApprovalRow.thread_id == thread, ToolApprovalRow.incarnation == incarnation)

    @staticmethod
    def _matches(row, scope):
        return tuple(row[key] for key in ("user_id", "thread_id", "incarnation")) == tuple(scope)

    async def get(self, request_id: str, *, scope) -> dict | None:
        if self.sf is None:
            row = self.rows.get(request_id)
            return copy.deepcopy(row) if row is not None and self._matches(row, scope) else None
        async with self.sf() as session:
            row = await session.scalar(select(ToolApprovalRow).where(ToolApprovalRow.request_id == request_id, *self._scope(scope)))
            return row.to_dict() if row else None

    async def list(self, *, scope, status: str | None = None, grants=False, limit=64) -> list[dict]:
        if self.sf is None:
            rows = [copy.deepcopy(row) for row in self.rows.values() if self._matches(row, scope)]
            rows = [row for row in rows if (status is None or row["status"] == status) and (not grants or (row["decision"] == "approve_thread" and row["status"] == "consumed"))]
            return sorted(rows, key=lambda row: row["created_at"], reverse=True)[:limit]
        stmt = select(ToolApprovalRow).where(*self._scope(scope))
        if status:
            stmt = stmt.where(ToolApprovalRow.status == status)
        if grants:
            stmt = stmt.where(ToolApprovalRow.decision == "approve_thread", ToolApprovalRow.status == "consumed")
        async with self.sf() as session:
            rows = (await session.scalars(stmt.order_by(ToolApprovalRow.created_at.desc()).limit(limit))).all()
            return [row.to_dict() for row in rows]

    async def has_grant(self, fingerprint, *, scope) -> bool:
        if self.sf is None:
            return any(self._matches(row, scope) and row["fingerprint"] == fingerprint and row["decision"] == "approve_thread" and row["status"] == "consumed" for row in self.rows.values())
        async with self.sf() as session:
            return bool(
                await session.scalar(select(ToolApprovalRow.request_id).where(*self._scope(scope), ToolApprovalRow.fingerprint == fingerprint, ToolApprovalRow.decision == "approve_thread", ToolApprovalRow.status == "consumed").limit(1))
            )

    async def decide(self, request_id, response, *, scope, fingerprint) -> None:
        """Idempotent for the identical answer; conflicting answers are rejected."""
        now = time.time()
        if self.sf is None:
            async with self.lock:
                row = self.rows.get(request_id)
                if row is not None and self._matches(row, scope) and row["fingerprint"] == fingerprint and row["status"] == "pending" and (row["expires_at"] is None or row["expires_at"] > now):
                    row.update(status="decided", response=copy.deepcopy(response))
                    return
        else:
            async with self.sf() as session:
                result = await session.execute(
                    update(ToolApprovalRow)
                    .where(
                        *self._scope(scope),
                        ToolApprovalRow.request_id == request_id,
                        ToolApprovalRow.fingerprint == fingerprint,
                        ToolApprovalRow.status == "pending",
                        (ToolApprovalRow.expires_at.is_(None) | (ToolApprovalRow.expires_at > now)),
                    )
                    .values(status="decided", response=copy.deepcopy(response))
                )
                await session.commit()
                if result.rowcount == 1:
                    return
        row = await self.get(request_id, scope=scope)
        if row is None or row["fingerprint"] != fingerprint or row["status"] not in ("decided", "consumed") or row["response"] != response:
            raise ApprovalConflict("Approval expired, was cancelled, or already has a different answer")

    async def finish(self, request_id, *, scope, decision, response=None) -> None:
        if self.sf is None:
            async with self.lock:
                row = self.rows.get(request_id)
                if row is None or not self._matches(row, scope) or row["status"] not in ("pending", "decided", "consumed"):
                    raise ApprovalConflict("Approval is no longer active")
                row.update(status="consumed", decision=decision, response=copy.deepcopy(response) if response is not None else row["response"])
            return
        values = {"status": "consumed", "decision": decision}
        if response is not None:
            values["response"] = copy.deepcopy(response)
        async with self.sf() as session:
            result = await session.execute(update(ToolApprovalRow).where(*self._scope(scope), ToolApprovalRow.request_id == request_id, ToolApprovalRow.status.in_(("pending", "decided", "consumed"))).values(**values))
            await session.commit()
            if result.rowcount != 1:
                raise ApprovalConflict("Approval is no longer active")

    async def cancel_run(self, run_id, *, scope):
        if self.sf is None:
            async with self.lock:
                for row in self.rows.values():
                    if self._matches(row, scope) and row["run_id"] == run_id and row["kind"] == "live" and row["status"] in ("pending", "decided"):
                        row["status"] = "cancelled"
            return
        async with self.sf() as session:
            await session.execute(update(ToolApprovalRow).where(*self._scope(scope), ToolApprovalRow.run_id == run_id, ToolApprovalRow.kind == "live", ToolApprovalRow.status.in_(("pending", "decided"))).values(status="cancelled"))
            await session.commit()

    async def cancel_request(self, request_id, *, scope):
        if self.sf is None:
            async with self.lock:
                row = self.rows.get(request_id)
                if row is not None and self._matches(row, scope) and row["status"] in ("pending", "decided"):
                    row["status"] = "cancelled"
            return
        async with self.sf() as session:
            await session.execute(update(ToolApprovalRow).where(*self._scope(scope), ToolApprovalRow.request_id == request_id, ToolApprovalRow.status.in_(("pending", "decided"))).values(status="cancelled"))
            await session.commit()

    async def revoke(self, *, scope):
        if self.sf is None:
            async with self.lock:
                for row in self.rows.values():
                    if self._matches(row, scope) and row["decision"] == "approve_thread":
                        row["status"] = "revoked"
            return
        async with self.sf() as session:
            await session.execute(update(ToolApprovalRow).where(*self._scope(scope), ToolApprovalRow.decision == "approve_thread").values(status="revoked"))
            await session.commit()

    async def delete_thread(self, thread_id, *, user_id):
        if self.sf is None:
            async with self.lock:
                self.rows = {key: row for key, row in self.rows.items() if row["thread_id"] != thread_id or row["user_id"] != user_id}
            return
        async with self.sf() as session:
            await session.execute(delete(ToolApprovalRow).where(ToolApprovalRow.thread_id == thread_id, ToolApprovalRow.user_id == user_id))
            await session.commit()
