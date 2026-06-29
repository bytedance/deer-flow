"""In-memory workflow store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from deerflow.runtime.workflows.store.base import WorkflowStore


class MemoryWorkflowStore(WorkflowStore):
    """In-memory WorkflowStore for development and tests."""

    def __init__(self) -> None:
        self._workflows: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _idempotency_tuple(source_type: str, source: str | None, idempotency_key: str | None) -> tuple[str, str, str] | None:
        if not idempotency_key:
            return None
        return (source_type, source or "", idempotency_key)

    async def create_or_get(
        self,
        *,
        workflow_kind: str = "message",
        source_type: str = "api",
        source: str | None = None,
        idempotency_key: str | None = None,
        external_message_ref: str | None = None,
        conversation_ref: str | None = None,
        thread_ref: str | None = None,
        sender_ref: str | None = None,
        user_id: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        checkpoint_ns: str | None = None,
        checkpoint_id: str | None = None,
        status: str = "received",
        max_attempts: int = 1,
        metadata: dict[str, Any] | None = None,
        workflow_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        idem = self._idempotency_tuple(source_type, source, idempotency_key)
        if idempotency_key and source is None:
            source = ""
        if idem is not None:
            existing_id = self._idempotency.get(idem)
            if existing_id is not None:
                return dict(self._workflows[existing_id]), False

        now = self._now()
        workflow_id = workflow_id or str(uuid.uuid4())
        row = {
            "workflow_id": workflow_id,
            "workflow_kind": workflow_kind,
            "source_type": source_type,
            "source": source,
            "idempotency_key": idempotency_key,
            "external_message_ref": external_message_ref,
            "conversation_ref": conversation_ref,
            "thread_ref": thread_ref,
            "sender_ref": sender_ref,
            "user_id": user_id,
            "thread_id": thread_id,
            "run_id": run_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "status": status,
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "next_attempt_at": None,
            "lease_owner": None,
            "lease_expires_at": None,
            "error": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        self._workflows[workflow_id] = row
        if idem is not None:
            self._idempotency[idem] = workflow_id
        self._events.setdefault(workflow_id, [])
        return dict(row), True

    async def claim_next(
        self,
        *,
        lease_owner: str,
        lease_seconds: int = 300,
        statuses: tuple[str, ...] = ("received", "bound"),
        status_on_claim: str = "claimed",
    ) -> dict[str, Any] | None:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease_expires_at = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        candidates = sorted(self._workflows.values(), key=lambda row: row["created_at"])
        for row in candidates:
            if row.get("status") not in statuses:
                continue
            if int(row.get("attempt_count") or 0) >= int(row.get("max_attempts") or 1):
                continue
            next_attempt_at = row.get("next_attempt_at")
            if next_attempt_at and next_attempt_at > now:
                continue
            lease_expires = row.get("lease_expires_at")
            if row.get("lease_owner") and lease_expires and lease_expires > now:
                continue
            row["lease_owner"] = lease_owner
            row["lease_expires_at"] = lease_expires_at
            row["attempt_count"] = int(row.get("attempt_count") or 0) + 1
            row["status"] = status_on_claim
            row["updated_at"] = now
            return dict(row)
        return None

    async def get(self, workflow_id: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        row = self._workflows.get(workflow_id)
        if row is None:
            return None
        if user_id is not None and row.get("user_id") != user_id:
            return None
        return dict(row)

    async def update_status(
        self,
        workflow_id: str,
        status: str,
        *,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        row = self._workflows.get(workflow_id)
        if row is None:
            return False
        row["status"] = status
        if error is not None:
            row["error"] = error
        if metadata:
            row["metadata"] = {**(row.get("metadata") or {}), **metadata}
        row["updated_at"] = self._now()
        return True

    async def bind_runtime(
        self,
        workflow_id: str,
        *,
        thread_id: str | None = None,
        run_id: str | None = None,
        checkpoint_ns: str | None = None,
        checkpoint_id: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        row = self._workflows.get(workflow_id)
        if row is None:
            return False
        updates = {
            "thread_id": thread_id,
            "run_id": run_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "status": status,
        }
        for key, value in updates.items():
            if value is not None:
                row[key] = value
        if metadata:
            row["metadata"] = {**(row.get("metadata") or {}), **metadata}
        row["updated_at"] = self._now()
        return True

    async def release_for_retry(
        self,
        workflow_id: str,
        *,
        next_attempt_at: str | None = None,
        status: str = "received",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        row = self._workflows.get(workflow_id)
        if row is None:
            return False
        row["lease_owner"] = None
        row["lease_expires_at"] = None
        row["next_attempt_at"] = next_attempt_at
        row["status"] = status
        if error is not None:
            row["error"] = error
        if metadata:
            row["metadata"] = {**(row.get("metadata") or {}), **metadata}
        row["updated_at"] = self._now()
        return True

    async def append_event(
        self,
        workflow_id: str,
        *,
        event_type: str,
        category: str = "lifecycle",
        content: Any | None = None,
        metadata: dict[str, Any] | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        checkpoint_ns: str | None = None,
        checkpoint_id: str | None = None,
        run_event_seq: int | None = None,
        idempotency_key: str | None = None,
        source_event_ref: str | None = None,
        workflow_event_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any] | None:
        if workflow_id not in self._workflows:
            return None
        events = self._events.setdefault(workflow_id, [])
        row = {
            "workflow_event_id": workflow_event_id or str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "seq": len(events) + 1,
            "event_type": event_type,
            "category": category,
            "thread_id": thread_id,
            "run_id": run_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "run_event_seq": run_event_seq,
            "idempotency_key": idempotency_key,
            "source_event_ref": source_event_ref,
            "content": content,
            "metadata": metadata or {},
            "created_at": created_at or self._now(),
        }
        events.append(row)
        return dict(row)

    async def list_events(
        self,
        workflow_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        events = list(self._events.get(workflow_id, []))
        if event_types is not None:
            wanted = set(event_types)
            events = [event for event in events if event["event_type"] in wanted]
        return [dict(event) for event in events[:limit]]

    async def list(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        source: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = list(self._workflows.values())
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        if source_type is not None:
            rows = [row for row in rows if row.get("source_type") == source_type]
        if source is not None:
            rows = [row for row in rows if row.get("source") == source]
        if thread_id is not None:
            rows = [row for row in rows if row.get("thread_id") == thread_id]
        if run_id is not None:
            rows = [row for row in rows if row.get("run_id") == run_id]
        if user_id is not None:
            rows = [row for row in rows if row.get("user_id") == user_id]
        rows.sort(key=lambda row: row["created_at"], reverse=True)
        return [dict(row) for row in rows[:limit]]
