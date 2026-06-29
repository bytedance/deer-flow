"""SQLAlchemy-backed workflow store implementation."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.workflow.model import WorkflowEventRow, WorkflowRow
from deerflow.runtime.workflows.store.base import WorkflowStore
from deerflow.utils.time import coerce_iso


class WorkflowRepository(WorkflowStore):
    """SQL-backed durable workflow envelope repository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _safe_json(obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: WorkflowRepository._safe_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [WorkflowRepository._safe_json(v) for v in obj]
        if hasattr(obj, "model_dump"):
            try:
                return obj.model_dump()
            except Exception:
                pass
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)

    @staticmethod
    def _row_to_dict(row: WorkflowRow) -> dict[str, Any]:
        d = row.to_dict()
        d["metadata"] = d.pop("metadata_json", {})
        for key in ("created_at", "updated_at", "next_attempt_at", "lease_expires_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    @staticmethod
    def _event_row_to_dict(row: WorkflowEventRow) -> dict[str, Any]:
        d = row.to_dict()
        d["content"] = d.pop("content_json", None)
        d["metadata"] = d.pop("metadata_json", {})
        val = d.get("created_at")
        if isinstance(val, datetime):
            d["created_at"] = coerce_iso(val)
        return d

    @staticmethod
    def _coerce_datetime(value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    @staticmethod
    def _normalize_source(source: str | None) -> str | None:
        if source is None:
            return None
        normalized = str(source).strip()
        return normalized[:128] if normalized else None

    @staticmethod
    def _normalize_idempotency_key(idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        normalized = str(idempotency_key).strip()
        return normalized[:256] if normalized else None

    async def _find_by_idempotency(
        self,
        *,
        source_type: str,
        source: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        stmt = select(WorkflowRow).where(
            WorkflowRow.source_type == source_type,
            WorkflowRow.source == source,
            WorkflowRow.idempotency_key == idempotency_key,
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return self._row_to_dict(row) if row is not None else None

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
        source = self._normalize_source(source)
        idempotency_key = self._normalize_idempotency_key(idempotency_key)
        if idempotency_key and source is None:
            source = ""
        existing = await self._find_by_idempotency(
            source_type=source_type,
            source=source,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing, False

        now = datetime.now(UTC)
        row = WorkflowRow(
            workflow_id=workflow_id or str(uuid.uuid4()),
            workflow_kind=workflow_kind,
            source_type=source_type,
            source=source,
            idempotency_key=idempotency_key,
            external_message_ref=external_message_ref,
            conversation_ref=conversation_ref,
            thread_ref=thread_ref,
            sender_ref=sender_ref,
            user_id=user_id,
            thread_id=thread_id,
            run_id=run_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
            status=status,
            attempt_count=0,
            max_attempts=max(1, int(max_attempts)),
            metadata_json=self._safe_json(metadata) or {},
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self._find_by_idempotency(
                    source_type=source_type,
                    source=source,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return existing, False
                raise
            return self._row_to_dict(row), True

    async def claim_next(
        self,
        *,
        lease_owner: str,
        lease_seconds: int = 300,
        statuses: tuple[str, ...] = ("received", "bound"),
        status_on_claim: str = "claimed",
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        stmt = (
            select(WorkflowRow)
            .where(
                WorkflowRow.status.in_(statuses),
                WorkflowRow.attempt_count < WorkflowRow.max_attempts,
                or_(WorkflowRow.next_attempt_at.is_(None), WorkflowRow.next_attempt_at <= now),
                or_(WorkflowRow.lease_expires_at.is_(None), WorkflowRow.lease_expires_at <= now),
            )
            .order_by(WorkflowRow.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            async with session.begin():
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row is None:
                    return None
                row.lease_owner = lease_owner
                row.lease_expires_at = lease_expires_at
                row.attempt_count = (row.attempt_count or 0) + 1
                row.status = status_on_claim
                row.updated_at = now
            return self._row_to_dict(row)

    async def get(self, workflow_id: str, *, user_id: str | None = None) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(WorkflowRow, workflow_id)
            if row is None:
                return None
            if user_id is not None and row.user_id != user_id:
                return None
            return self._row_to_dict(row)

    async def update_status(
        self,
        workflow_id: str,
        status: str,
        *,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        values: dict[str, Any] = {"status": status, "updated_at": datetime.now(UTC)}
        if error is not None:
            values["error"] = error
        async with self._sf() as session:
            row = await session.get(WorkflowRow, workflow_id)
            if row is None:
                return False
            if metadata:
                values["metadata_json"] = {**(row.metadata_json or {}), **(self._safe_json(metadata) or {})}
            await session.execute(update(WorkflowRow).where(WorkflowRow.workflow_id == workflow_id).values(**values))
            await session.commit()
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
        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        optional = {
            "thread_id": thread_id,
            "run_id": run_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "status": status,
        }
        for key, value in optional.items():
            if value is not None:
                values[key] = value
        async with self._sf() as session:
            row = await session.get(WorkflowRow, workflow_id)
            if row is None:
                return False
            if metadata:
                values["metadata_json"] = {**(row.metadata_json or {}), **(self._safe_json(metadata) or {})}
            await session.execute(update(WorkflowRow).where(WorkflowRow.workflow_id == workflow_id).values(**values))
            await session.commit()
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
        values: dict[str, Any] = {
            "lease_owner": None,
            "lease_expires_at": None,
            "next_attempt_at": self._coerce_datetime(next_attempt_at),
            "status": status,
            "updated_at": datetime.now(UTC),
        }
        if error is not None:
            values["error"] = error
        async with self._sf() as session:
            row = await session.get(WorkflowRow, workflow_id)
            if row is None:
                return False
            if metadata:
                values["metadata_json"] = {**(row.metadata_json or {}), **(self._safe_json(metadata) or {})}
            await session.execute(update(WorkflowRow).where(WorkflowRow.workflow_id == workflow_id).values(**values))
            await session.commit()
            return True

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
        stmt = select(WorkflowRow)
        if status is not None:
            stmt = stmt.where(WorkflowRow.status == status)
        if source_type is not None:
            stmt = stmt.where(WorkflowRow.source_type == source_type)
        if source is not None:
            stmt = stmt.where(WorkflowRow.source == self._normalize_source(source))
        if thread_id is not None:
            stmt = stmt.where(WorkflowRow.thread_id == thread_id)
        if run_id is not None:
            stmt = stmt.where(WorkflowRow.run_id == run_id)
        if user_id is not None:
            stmt = stmt.where(WorkflowRow.user_id == user_id)
        stmt = stmt.order_by(WorkflowRow.created_at.desc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

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
        created_at: str | datetime | None = None,
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            async with session.begin():
                workflow = await session.get(WorkflowRow, workflow_id)
                if workflow is None:
                    return None
                max_seq_stmt = select(func.max(WorkflowEventRow.seq)).where(WorkflowEventRow.workflow_id == workflow_id)
                max_seq = (await session.execute(max_seq_stmt)).scalar_one()
                row = WorkflowEventRow(
                    workflow_event_id=workflow_event_id or str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    seq=(max_seq or 0) + 1,
                    event_type=event_type,
                    category=category,
                    thread_id=thread_id,
                    run_id=run_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    run_event_seq=run_event_seq,
                    idempotency_key=self._normalize_idempotency_key(idempotency_key),
                    source_event_ref=source_event_ref,
                    content_json=self._safe_json(content),
                    metadata_json=self._safe_json(metadata) or {},
                    created_at=self._coerce_datetime(created_at) or datetime.now(UTC),
                )
                session.add(row)
            return self._event_row_to_dict(row)

    async def list_events(
        self,
        workflow_id: str,
        *,
        event_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        stmt = select(WorkflowEventRow).where(WorkflowEventRow.workflow_id == workflow_id)
        if event_types:
            stmt = stmt.where(WorkflowEventRow.event_type.in_(event_types))
        stmt = stmt.order_by(WorkflowEventRow.seq.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._event_row_to_dict(row) for row in result.scalars()]
