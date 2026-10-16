"""SQLAlchemy-backed RunStore implementation.

Each method acquires and releases its own short-lived session.
Run status updates happen from background workers that may live
minutes -- we don't hold connections across long execution.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.authz.workspace import WorkspaceContext, get_current_workspace
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.workspaces.run_control import NativeRunStopTarget, create_execution_lifetime, execution_lifetime, pending_execution_barrier, pending_run_stop, revocation_run_stop
from deerflow.persistence.workspaces.scope import resolve_resource_scope
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.runtime.run_origin import origin_kind_of
from deerflow.runtime.runs.store.base import (
    LeaseRenewal,
    RunIdempotencyConflict,
    RunStore,
    StatusFinalization,
    canonical_run_created_at,
    normalize_run_created_at_iso,
)
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_iso


def _lease_expired_or_null(lease_col, cutoff: datetime):
    """SQLAlchemy filter: True when the lease is NULL or has expired past *cutoff*."""
    return or_(lease_col.is_(None), lease_col < cutoff)


def _origin_kind(operation_kind: str, metadata: Any) -> str | None:
    """Denormalized ``runs.origin_kind``: the server-owned origin of an agent run.

    Thread operations (checkpoint writes, deletes) never carry one, and a run
    without a well-formed ``deerflow_origin`` stays NULL (interactive/legacy).
    """
    return origin_kind_of(metadata) if operation_kind == "run" else None


class RunRepository(RunStore):
    supports_workspace_reads = True
    supports_workspace_admission = True

    async def find_by_idempotency_key(self, key: str, *, user_id: str, thread_id: str) -> dict[str, Any] | None:
        """Owner-scoped recovery of an admission whose acknowledgement was lost."""
        async with self._sf() as session:
            row = await session.scalar(self._read_scope(select(RunRow).where(RunRow.idempotency_key == key, RunRow.thread_id == thread_id), user_id, require_run_incarnation=True))
            return self._row_to_dict(row) if row is not None else None

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, workspace_required=False) -> None:
        self._sf = session_factory
        self._workspace_required = workspace_required
        self.workspace_scope_required = bool(workspace_required)

    def _read_scope(self, stmt, user_id, *, thread_incarnation=None, require_run_incarnation=False):
        context = resolve_resource_scope(None, user_id, required=self._workspace_required)
        if user_id is not None:
            stmt = stmt.where(RunRow.user_id == user_id)
        if context is not None:
            # Filter before cursors, limits or reduction. A matching run alone
            # cannot authorize an incompatible or missing private thread parent.
            parent_query = ThreadMetaRepository._owned_scope(select(ThreadMetaRow.thread_id).where(ThreadMetaRow.thread_id == RunRow.thread_id), user_id, context)
            if thread_incarnation is not None:
                parent_query = parent_query.where(ThreadMetaRow.incarnation == thread_incarnation)
            if require_run_incarnation:
                parent_query = parent_query.where(ThreadMetaRow.incarnation == RunRow.thread_incarnation)
            parent = parent_query.correlate(RunRow).exists()
            stmt = stmt.where(RunRow.workspace_id == context.workspace_id, parent)
        return stmt

    async def can_observe_private_run(self, run_id, *, thread_id, incarnation, user_id, token_version, system_role, oauth_provider, oauth_id):
        """One read-only SQL fence for a captured browser observer capability."""
        resolve_resource_scope(None, user_id, required=True)
        if not incarnation:
            raise WorkspaceAccessDenied("observer requires captured thread identity")
        principal = (
            select(UserRow.id)
            .where(UserRow.id == user_id, UserRow.token_version == token_version, UserRow.needs_setup.is_(False), UserRow.system_role == system_role, UserRow.oauth_provider == oauth_provider, UserRow.oauth_id == oauth_id)
            .exists()
        )
        stmt = self._read_scope(select(RunRow.run_id).where(RunRow.run_id == run_id, RunRow.thread_id == thread_id, RunRow.operation_kind == "run", principal), user_id, thread_incarnation=incarnation)
        async with self._sf() as session:
            return await session.scalar(stmt) is not None

    @staticmethod
    async def _next_change_seq(session: AsyncSession) -> int:
        dialect = session.bind.dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:  # pragma: no cover - configured databases are SQLite/Postgres
            raise RuntimeError(f"unsupported run-change clock dialect: {dialect}")
        await session.execute(insert(RunChangeClockRow).values(id=1, value=0).on_conflict_do_nothing(index_elements=[RunChangeClockRow.id]))
        value = await session.scalar(update(RunChangeClockRow).where(RunChangeClockRow.id == 1).values(value=RunChangeClockRow.value + 1).returning(RunChangeClockRow.value))
        if value is None:
            raise RuntimeError("run-change clock did not return a position")
        return int(value)

    @staticmethod
    def _normalize_model_name(model_name: str | None) -> str | None:
        """Normalize model_name for storage: strip whitespace, truncate to 128 chars."""
        if model_name is None:
            return None
        if not isinstance(model_name, str):
            model_name = str(model_name)
        normalized = model_name.strip()
        if len(normalized) > 128:
            normalized = normalized[:128]
        return normalized

    @staticmethod
    def _safe_json(obj: Any) -> Any:
        """Ensure obj is JSON-serializable. Falls back to model_dump() or str()."""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: RunRepository._safe_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [RunRepository._safe_json(v) for v in obj]
        if hasattr(obj, "model_dump"):
            try:
                return obj.model_dump()
            except Exception:
                pass
        if hasattr(obj, "dict"):
            try:
                return obj.dict()
            except Exception:
                pass
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)

    @staticmethod
    def _row_to_dict(row: RunRow) -> dict[str, Any]:
        d = row.to_dict()
        # Remap JSON columns to match RunStore interface
        d["metadata"] = d.pop("metadata_json", {})
        d["kwargs"] = d.pop("kwargs_json", {})
        # Convert datetime to ISO string for consistency with MemoryRunStore.
        # SQLite drops tzinfo on read despite ``DateTime(timezone=True)`` —
        # ``coerce_iso`` normalizes naive datetimes as UTC.
        for key in ("created_at", "updated_at", "lease_expires_at", "cancel_requested_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def put(
        self,
        run_id,
        *,
        thread_id,
        assistant_id=None,
        user_id: str | None | _AutoSentinel = AUTO,
        model_name: str | None = None,
        status="pending",
        operation_kind: str = "run",
        multitask_strategy="reject",
        metadata=None,
        kwargs=None,
        error=None,
        stop_reason: str | None = None,
        goal_verdict: dict[str, Any] | None = None,
        created_at=None,
        follow_up_to_run_id=None,
        owner_worker_id: str | None = None,
        lease_expires_at: str | None = None,
        idempotency_key: str | None = None,
    ):
        """Insert or update a run row.

        ``RunManager`` retries ``put`` after transient SQLite failures.  Making
        this operation idempotent prevents a successful-but-unacknowledged first
        commit from turning the retry into a primary-key failure.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.put")
        if resolve_resource_scope(None, resolved_user_id, required=self._workspace_required) is not None:
            raise WorkspaceAccessDenied("workspace Run upserts require scoped lifecycle integration")
        now = datetime.now(UTC)
        created = datetime.fromisoformat(created_at) if created_at else now
        lease_dt = datetime.fromisoformat(lease_expires_at) if lease_expires_at else None
        values = {
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "user_id": resolved_user_id,
            "model_name": self._normalize_model_name(model_name),
            "status": status,
            "operation_kind": operation_kind,
            "multitask_strategy": multitask_strategy,
            "metadata_json": self._safe_json(metadata) or {},
            "kwargs_json": self._safe_json(kwargs) or {},
            "error": error,
            "stop_reason": stop_reason,
            "goal_verdict": self._safe_json(goal_verdict),
            "follow_up_to_run_id": follow_up_to_run_id,
            "owner_worker_id": owner_worker_id,
            "lease_expires_at": lease_dt,
            "idempotency_key": idempotency_key,
            "origin_kind": _origin_kind(operation_kind, metadata),
            "updated_at": now,
        }
        async with self._sf() as session:
            values["change_seq"] = await self._next_change_seq(session)
            row = await session.get(RunRow, run_id)
            if row is not None and row.workspace_id is not None:
                raise WorkspaceAccessDenied("legacy upsert cannot mutate a workspace Run")
            if row is None:
                session.add(RunRow(run_id=run_id, created_at=created, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            await session.commit()

    async def get(
        self,
        run_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.get")
        async with self._sf() as session:
            row = await session.scalar(self._read_scope(select(RunRow).where(RunRow.run_id == run_id), resolved_user_id))
            return self._row_to_dict(row) if row is not None else None

    async def list_changed(
        self,
        *,
        after_change_seq: int,
        after_run_id: str,
        user_id: str | None | _AutoSentinel = AUTO,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.list_changed")
        stmt = select(RunRow).where(
            RunRow.operation_kind == "run",
            or_(
                RunRow.change_seq > after_change_seq,
                and_(RunRow.change_seq == after_change_seq, RunRow.run_id > after_run_id),
            ),
        )
        stmt = self._read_scope(stmt, resolved_user_id)
        stmt = stmt.order_by(RunRow.change_seq.asc(), RunRow.run_id.asc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def latest_change(self, *, user_id: str) -> tuple[int, str] | None:
        """The caller's newest run-change position ``(change_seq, run_id)``, or ``None``.

        Seeds the activity feed cursor: one backward seek on
        ``ix_runs_user_change_seq``. ``user_id`` is always an explicit owner id.
        """
        stmt = self._read_scope(select(RunRow.change_seq, RunRow.run_id), user_id).order_by(RunRow.change_seq.desc(), RunRow.run_id.desc()).limit(1)
        async with self._sf() as session:
            row = (await session.execute(stmt)).first()
        return (int(row.change_seq), str(row.run_id)) if row is not None else None

    async def list_by_thread(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
        limit=100,
        before_created_at: str | None = None,
        before_run_id: str | None = None,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.list_by_thread")
        stmt = select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind == "run")
        stmt = self._read_scope(stmt, resolved_user_id)
        if before_created_at and before_run_id:
            cursor_dt = datetime.fromisoformat(normalize_run_created_at_iso(before_created_at))
            if cursor_dt.tzinfo is None:
                cursor_dt = cursor_dt.replace(tzinfo=UTC)
            else:
                cursor_dt = cursor_dt.astimezone(UTC)
            stmt = stmt.where(
                or_(
                    RunRow.created_at < cursor_dt,
                    and_(RunRow.created_at == cursor_dt, RunRow.run_id < before_run_id),
                )
            )
        # Keyset pages filter on (created_at, run_id) after thread_id. Existing
        # indexes are (thread_id) and (thread_id, status), so each page still
        # sorts matching rows. A covering (thread_id, created_at, run_id) index
        # is a follow-up if deep paging shows up in profiles.
        stmt = stmt.order_by(RunRow.created_at.desc(), RunRow.run_id.desc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_by_thread_created_at(self, thread_id, *, user_id, created_at):
        timestamp = datetime.fromisoformat(canonical_run_created_at(created_at))
        async with self._sf() as session:
            result = await session.execute(self._read_scope(select(RunRow).where(RunRow.thread_id == thread_id, RunRow.created_at == timestamp), user_id))
            return [self._row_to_dict(row) for row in result.scalars()]

    async def list_successful_regenerate_sources(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.list_successful_regenerate_sources")
        source = RunRow.metadata_json["regenerate_from_run_id"].as_string()
        stmt = select(source).where(
            RunRow.thread_id == thread_id,
            RunRow.operation_kind == "run",
            RunRow.status == "success",
            source.is_not(None),
            source != "",
        )
        stmt = self._read_scope(stmt, resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {value for value in result.scalars() if isinstance(value, str) and value}

    async def list_edit_regenerate_runs(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.list_edit_regenerate_runs")
        replay_kind = RunRow.metadata_json["replay_kind"].as_string()
        source = RunRow.metadata_json["regenerate_from_run_id"].as_string()
        stmt = select(RunRow).where(
            RunRow.thread_id == thread_id,
            replay_kind == "edit",
            source.is_not(None),
            source != "",
        )
        stmt = self._read_scope(stmt, resolved_user_id)
        stmt = stmt.order_by(RunRow.created_at.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]

    async def get_many_by_thread(
        self,
        thread_id,
        run_ids,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.get_many_by_thread")
        stmt = select(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind == "run", RunRow.run_id.in_(run_ids))
        stmt = self._read_scope(stmt, resolved_user_id)
        if not run_ids:
            return {}
        async with self._sf() as session:
            result = await session.execute(stmt)
            return {row.run_id: self._row_to_dict(row) for row in result.scalars()}

    async def update_status(self, run_id, status, *, error=None, stop_reason=None, goal_verdict=None, worker_target=None) -> bool:
        values: dict[str, Any] = {"status": status, "updated_at": datetime.now(UTC)}
        if error is not None:
            values["error"] = error
        if stop_reason is not None:
            values["stop_reason"] = stop_reason
        if goal_verdict is not None:
            values["goal_verdict"] = self._safe_json(goal_verdict)
        # Guard: only transition rows that are still active. ``interrupted`` is
        # included because the rollback path goes ``running → interrupted``
        # (cancel acknowledged) then ``interrupted → error`` (task finalize).
        # ``error`` and ``success`` remain locked so a peer's takeover (or a
        # completed run) cannot be overwritten by a late writer.
        async with self._sf() as session:
            values["change_seq"], scope = await self._worker_write_scope(session, run_id, worker_target)
            result = await session.execute(update(RunRow).where(RunRow.run_id == run_id, *scope, RunRow.status.in_(("pending", "running", "interrupted"))).values(**values))
            await session.commit()
            return result.rowcount != 0

    async def _pending_transition_scope(self, session, run_id, *, user_id, thread_id, thread_incarnation, workspace_context):
        context = resolve_resource_scope(workspace_context, user_id, required=self._workspace_required)
        if context is None:
            return await self._next_change_seq(session), [RunRow.workspace_id.is_(None)]
        if not isinstance(thread_id, str) or not isinstance(thread_incarnation, str) or not thread_incarnation:
            raise WorkspaceAccessDenied("pending Run transition requires captured parent identity")
        parent = await ThreadMetaRepository(self._sf)._locked_row(session, thread_id, user_id, context)
        if parent is None or parent.incarnation != thread_incarnation:
            raise WorkspaceAccessDenied("pending Run parent identity changed")
        # Keep workspace -> actor -> parent -> clock -> Run lock order.
        change_seq = await self._next_change_seq(session)
        row = await session.scalar(select(RunRow).where(RunRow.run_id == run_id).with_for_update())
        if row is None or row.workspace_id != context.workspace_id or row.user_id != user_id or row.thread_id != thread_id or row.thread_incarnation != thread_incarnation or row.operation_kind != "run":
            raise WorkspaceAccessDenied("pending Run identity is unavailable")
        try:
            captured = WorkspaceContext(**row.workspace_context_json)
        except (TypeError, ValueError):
            raise WorkspaceAccessDenied("pending Run workspace snapshot is invalid") from None
        if captured != context:
            raise WorkspaceAccessDenied("pending Run workspace authorization changed")
        try:
            await execution_lifetime(session, NativeRunStopTarget.from_row(row))
        except ValueError as exc:
            raise WorkspaceAccessDenied("pending Run lifetime is unavailable") from exc
        return change_seq, [RunRow.workspace_id == context.workspace_id, RunRow.user_id == user_id, RunRow.thread_id == thread_id, RunRow.thread_incarnation == thread_incarnation]

    async def lock_worker_effect(self, session, target: NativeRunStopTarget, *, change_clock=False):
        """Lock captured execution authority in the caller's short transaction."""
        if type(target) is not NativeRunStopTarget:
            raise WorkspaceAccessDenied("worker effect requires captured native Run identity")
        parent = await ThreadMetaRepository(self._sf)._locked_row(session, target.thread_id, target.user_id, target.workspace_context)
        if parent is None or parent.incarnation != target.thread_incarnation:
            raise WorkspaceAccessDenied("worker effect parent changed")
        sequence = await self._next_change_seq(session) if change_clock else None
        row = await session.scalar(select(RunRow).where(RunRow.run_id == target.run_id).with_for_update())
        try:
            if row is None or NativeRunStopTarget.from_row(row) != target or row.operation_kind != "run":
                raise ValueError("worker effect Run differs")
            await execution_lifetime(session, target)
        except ValueError as exc:
            raise WorkspaceAccessDenied("worker effect execution changed") from exc
        if await session.scalar(select(pending_run_stop(run_id=target.run_id))):
            raise WorkspaceAccessDenied("worker effect stop is pending")
        lease = row.lease_expires_at
        if lease is not None and lease.tzinfo is None:
            lease = lease.replace(tzinfo=UTC)
        if row.status not in ("running", "success", "error", "timeout", "interrupted") or row.cancel_action is not None or lease is None or lease <= datetime.now(UTC):
            raise WorkspaceAccessDenied("worker effect execution is no longer live")
        return row, sequence

    async def _worker_write_scope(self, session, run_id, target, *, change_clock=True):
        if target is None:
            if self._workspace_required or get_current_workspace() is not None:
                raise WorkspaceAccessDenied("workspace worker write requires captured execution identity")
            return (await self._next_change_seq(session) if change_clock else None), [RunRow.workspace_id.is_(None)]
        if type(target) is not NativeRunStopTarget or target.run_id != run_id:
            raise WorkspaceAccessDenied("worker write Run differs from captured identity")
        _, sequence = await self.lock_worker_effect(session, target, change_clock=change_clock)
        return sequence, [RunRow.workspace_id == target.workspace_id]

    async def check_worker_invocation(self, target):
        """Authorize admission only; release all SQL locks before handler IO."""
        async with self._sf() as session:
            await self.lock_worker_effect(session, target)
            await session.commit()

    async def commit_worker_io(self, target: NativeRunStopTarget, *, commit):
        """Drain prepared native checkpoint/queue IO, never graph/model/tool work.

        This serializes authority, not a distributed checkpoint transaction.
        Cleanup and rollback after withdrawal need separate control authority.
        """
        from deerflow.utils.file_io import await_drained

        async with self._sf() as session:
            await self.lock_worker_effect(session, target)
            result = await await_drained(commit())
            await session.commit()
            return result

    async def commit_worker_checkpoint(self, target: NativeRunStopTarget, *, commit):
        return await self.commit_worker_io(target, commit=commit)

    async def signal_worker_stream_end(self, target, *, signal):
        from deerflow.persistence.workspaces.run_control import signal_owned_stream_end

        return await signal_owned_stream_end(self._sf, target, signal=signal)

    async def cleanup_worker_stream(self, target, *, cleanup):
        from deerflow.persistence.workspaces.run_control import signal_owned_stream_end

        return await signal_owned_stream_end(self._sf, target, signal=cleanup, closed_only=True)

    async def start_run(self, run_id: str, *, owner_worker_id: str | None = None, user_id: str | None = None, thread_id: str | None = None, thread_incarnation: str | None = None, workspace_context: WorkspaceContext | None = None) -> bool:
        """Start only a still-pending run; cancelled rows must not be resurrected."""
        async with self._sf() as session:
            change_seq, scope_conditions = await self._pending_transition_scope(session, run_id, user_id=user_id, thread_id=thread_id, thread_incarnation=thread_incarnation, workspace_context=workspace_context)
            result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    *scope_conditions,
                    RunRow.status == "pending",
                    RunRow.cancel_action.is_(None),
                    *([RunRow.owner_worker_id == owner_worker_id] if owner_worker_id is not None else []),
                )
                .values(status="running", updated_at=datetime.now(UTC), change_seq=change_seq)
            )
            await session.commit()
            return result.rowcount != 0

    async def finish_dispatch_pending(self, run_id: str, *, owner_worker_id: str, error: str | None = None) -> bool:
        """Terminalize a queued dispatch admission only before worker adoption.

        The dispatch host must first fence its job against claim/start. The
        pending owner CAS makes adoption and this terminal commit exclusive.
        """
        async with self._sf() as session:
            conditions = [RunRow.run_id == run_id, RunRow.owner_worker_id == owner_worker_id, RunRow.status == "pending"]
            if error is None:
                conditions.append(RunRow.cancel_action.is_not(None))
            else:
                conditions.append(RunRow.cancel_action.is_(None))
            change_seq = await self._next_change_seq(session)
            result = await session.execute(update(RunRow).where(*conditions).values(status="error" if error else "interrupted", error=error, updated_at=datetime.now(UTC), change_seq=change_seq))
            await session.commit()
            return result.rowcount != 0

    async def transfer_pending(
        self, run_id: str, *, thread_id: str, user_id: str | None, expected_owner_worker_id: str, owner_worker_id: str, lease_expires_at: str | None, workspace_context: WorkspaceContext | None = None, thread_incarnation: str | None = None
    ) -> bool:
        """Transfer only the exact uncancelled admission; keep its identity and payload."""
        async with self._sf() as session:
            change_seq, scope_conditions = await self._pending_transition_scope(session, run_id, user_id=user_id, thread_id=thread_id, thread_incarnation=thread_incarnation, workspace_context=workspace_context)
            result = await session.execute(
                update(RunRow)
                .where(*scope_conditions, RunRow.run_id == run_id, RunRow.thread_id == thread_id, RunRow.user_id == user_id, RunRow.status == "pending", RunRow.cancel_action.is_(None), RunRow.owner_worker_id == expected_owner_worker_id)
                .values(owner_worker_id=owner_worker_id, lease_expires_at=datetime.fromisoformat(lease_expires_at) if lease_expires_at else None, updated_at=datetime.now(UTC), change_seq=change_seq)
            )
            if result.rowcount:
                row = await session.get(RunRow, run_id)
            if result.rowcount and row.workspace_id is not None:
                # transfer_pending has already changed the row owner under the
                # native workspace/clock/Run locks; rebind only this same lifetime.
                target = NativeRunStopTarget.from_row(row)
                previous = NativeRunStopTarget(**{**{name: getattr(target, name) for name in target.__dataclass_fields__}, "owner_worker_id": expected_owner_worker_id})
                lifetime = await execution_lifetime(session, previous)
                lifetime.payload = {**lifetime.payload, "owner_worker_id": owner_worker_id}
            await session.commit()
            return result.rowcount != 0

    async def update_model_name(self, run_id, model_name, *, worker_target=None):
        async with self._sf() as session:
            change_seq, scope = await self._worker_write_scope(session, run_id, worker_target)
            await session.execute(
                update(RunRow)
                .where(RunRow.run_id == run_id, *scope)
                .values(
                    model_name=self._normalize_model_name(model_name),
                    updated_at=datetime.now(UTC),
                    change_seq=change_seq,
                )
            )
            await session.commit()

    async def delete(
        self,
        run_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.delete")
        async with self._sf() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                return
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return
            await session.delete(row)
            await session.commit()

    async def delete_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> int:
        """Delete a thread's historical runs, keeping internal operation rows.

        Only ``operation_kind == "run"`` rows are removed. The same table holds
        durable thread-operation reservations (checkpoint writes, artifact
        writes, branches and thread deletions) that their own release path owns
        through ``delete_thread_operation``; deleting the reservation currently
        protecting a thread deletion would drop the cross-worker exclusion in
        the middle of that request.

        The bulk delete deliberately does not bump the run-change clock, matching
        the single-row :meth:`delete` and keeping thread cleanup away from
        ``run_change_clock`` (#5516). ``user_id`` follows the same three-state
        convention as the rest of this repository: ``AUTO`` reads the request
        context (raising when there is none), an explicit id scopes the delete,
        and ``None`` skips the owner filter for migration/CLI callers.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.delete_by_thread")

        conditions = [
            RunRow.thread_id == thread_id,
            RunRow.operation_kind == "run",
        ]
        if resolved_user_id is not None:
            conditions.append(RunRow.user_id == resolved_user_id)

        async with self._sf() as session:
            count = await session.scalar(select(func.count()).select_from(RunRow).where(*conditions)) or 0
            if count:
                await session.execute(delete(RunRow).where(*conditions))
            await session.commit()
            return count

    async def delete_thread_operation(self, run_id: str, *, user_id: str | None, workspace_context=None, owner_worker_id: str | None = None) -> None:
        """Release only the captured reservation, even after live revocation.

        This cleanup grants no content read or new work. A scoped caller must
        supply the admitting worker, and cannot delete normal agent runs.
        """
        context = resolve_resource_scope(workspace_context, user_id, required=self._workspace_required)
        conditions = [RunRow.run_id == run_id, RunRow.operation_kind != "run"]
        if user_id is not None:
            conditions.append(RunRow.user_id == user_id)
        if context is not None:
            if not owner_worker_id:
                raise WorkspaceAccessDenied("reservation cleanup requires its captured worker")
            conditions.extend((RunRow.workspace_id == context.workspace_id, RunRow.owner_worker_id == owner_worker_id))
        async with self._sf() as session:
            await session.execute(delete(RunRow).where(*conditions))
            await session.commit()

    async def list_pending(self, *, before=None):
        if before is None:
            before_dt = datetime.now(UTC)
        elif isinstance(before, datetime):
            before_dt = before
        else:
            before_dt = datetime.fromisoformat(before)
        stmt = select(RunRow).where(RunRow.operation_kind == "run", RunRow.status == "pending", RunRow.created_at <= before_dt).order_by(RunRow.created_at.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def list_inflight(self, *, before=None):
        """Return persisted active runs for startup recovery."""
        if before is None:
            before_dt = datetime.now(UTC)
        elif isinstance(before, datetime):
            before_dt = before
        else:
            before_dt = datetime.fromisoformat(before)
        stmt = (
            select(RunRow)
            .where(
                RunRow.status.in_(("pending", "running")),
                RunRow.created_at <= before_dt,
                RunRow.workspace_id.is_(None),
            )
            .order_by(RunRow.created_at.asc())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def update_run_completion(
        self,
        run_id: str,
        *,
        status: str,
        worker_target=None,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_tokens: int = 0,
        llm_call_count: int = 0,
        lead_agent_tokens: int = 0,
        subagent_tokens: int = 0,
        middleware_tokens: int = 0,
        token_usage_by_model: dict[str, dict[str, int]] | None = None,
        message_count: int = 0,
        last_ai_message: str | None = None,
        first_human_message: str | None = None,
        error: str | None = None,
        goal_verdict: dict[str, Any] | None = None,
    ) -> bool:
        """Update status + token usage + convenience fields on run completion.

        Returns ``False`` when the row is missing or already has a conflicting
        terminal outcome.
        """
        values: dict[str, Any] = {
            "status": status,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "llm_call_count": llm_call_count,
            "lead_agent_tokens": lead_agent_tokens,
            "subagent_tokens": subagent_tokens,
            "middleware_tokens": middleware_tokens,
            "token_usage_by_model": self._safe_json(token_usage_by_model) or {},
            "message_count": message_count,
            "updated_at": datetime.now(UTC),
        }
        if last_ai_message is not None:
            values["last_ai_message"] = last_ai_message[:2000]
        if first_human_message is not None:
            values["first_human_message"] = first_human_message[:2000]
        if error is not None:
            values["error"] = error
        if goal_verdict is not None:
            values["goal_verdict"] = self._safe_json(goal_verdict)
        allowed_sources = ["pending", "running"]
        if status not in allowed_sources:
            allowed_sources.append(status)
        if status == "error" and "interrupted" not in allowed_sources:
            allowed_sources.append("interrupted")
        async with self._sf() as session:
            values["change_seq"], scope = await self._worker_write_scope(session, run_id, worker_target)
            result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    *scope,
                    RunRow.status.in_(tuple(allowed_sources)),
                )
                .values(**values)
            )
            await session.commit()
            return result.rowcount != 0

    async def update_run_progress(
        self,
        run_id: str,
        *,
        worker_target=None,
        total_input_tokens: int | None = None,
        total_output_tokens: int | None = None,
        total_tokens: int | None = None,
        llm_call_count: int | None = None,
        lead_agent_tokens: int | None = None,
        subagent_tokens: int | None = None,
        middleware_tokens: int | None = None,
        token_usage_by_model: dict[str, dict[str, int]] | None = None,
        message_count: int | None = None,
        last_ai_message: str | None = None,
        first_human_message: str | None = None,
    ) -> None:
        """Update token usage + convenience fields while a run is still active."""
        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        optional_counters = {
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "llm_call_count": llm_call_count,
            "lead_agent_tokens": lead_agent_tokens,
            "subagent_tokens": subagent_tokens,
            "middleware_tokens": middleware_tokens,
            "message_count": message_count,
        }
        for key, value in optional_counters.items():
            if value is not None:
                values[key] = value
        if token_usage_by_model is not None:
            values["token_usage_by_model"] = self._safe_json(token_usage_by_model) or {}
        if last_ai_message is not None:
            values["last_ai_message"] = last_ai_message[:2000]
        if first_human_message is not None:
            values["first_human_message"] = first_human_message[:2000]
        async with self._sf() as session:
            _, scope = await self._worker_write_scope(session, run_id, worker_target, change_clock=False)
            await session.execute(update(RunRow).where(RunRow.run_id == run_id, *scope, RunRow.status == "running").values(**values))
            await session.commit()

    async def aggregate_tokens_by_thread(
        self,
        thread_id: str,
        *,
        include_active: bool = False,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict[str, Any]:
        """Aggregate token usage for a thread.

        ``by_model`` is reduced in Python from each row's ``token_usage_by_model``
        JSON column so subagent / middleware tokens land on the model that
        actually produced them (issue #3645). Rows written before that column
        existed fall back to ``RunRow.model_name`` + ``RunRow.total_tokens``,
        preserving the legacy lead-only behavior instead of dropping the data.

        Headline totals (``total_tokens``, ``total_input_tokens``,
        ``total_output_tokens``) and the ``by_caller`` bucket are summed from
        their own columns and are therefore unaffected by the JSON column being
        empty.
        """
        statuses = ("success", "error", "running") if include_active else ("success", "error")
        _completed = RunRow.status.in_(statuses)
        _thread = RunRow.thread_id == thread_id
        _run_operation = RunRow.operation_kind == "run"
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.aggregate_tokens_by_thread")

        stmt = select(
            RunRow.model_name,
            RunRow.total_tokens,
            RunRow.total_input_tokens,
            RunRow.total_output_tokens,
            RunRow.lead_agent_tokens,
            RunRow.subagent_tokens,
            RunRow.middleware_tokens,
            RunRow.token_usage_by_model,
        ).where(_thread, _run_operation, _completed)
        stmt = self._read_scope(stmt, resolved_user_id)

        async with self._sf() as session:
            rows = (await session.execute(stmt)).all()

        total_tokens = total_input = total_output = total_runs = 0
        lead_agent = subagent = middleware = 0
        by_model: dict[str, dict] = {}
        for r in rows:
            total_runs += 1
            total_tokens += r.total_tokens
            total_input += r.total_input_tokens
            total_output += r.total_output_tokens
            lead_agent += r.lead_agent_tokens
            subagent += r.subagent_tokens
            middleware += r.middleware_tokens

            # ``or {}`` covers rows written before ``token_usage_by_model``
            # existed (the column is NULL on a manual ALTER ADD COLUMN without
            # backfill); fresh rows always carry the journal-produced dict.
            usage_by_model = r.token_usage_by_model or {}
            if usage_by_model:
                for model, usage in usage_by_model.items():
                    entry = by_model.setdefault(model, {"tokens": 0, "runs": 0})
                    entry["tokens"] += usage.get("total_tokens", 0)
                    entry["runs"] += 1
            else:
                model = r.model_name or "unknown"
                entry = by_model.setdefault(model, {"tokens": 0, "runs": 0})
                entry["tokens"] += r.total_tokens
                entry["runs"] += 1

        return {
            "total_tokens": total_tokens,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_runs": total_runs,
            "by_model": by_model,
            "by_caller": {
                "lead_agent": lead_agent,
                "subagent": subagent,
                "middleware": middleware,
            },
        }

    # ------------------------------------------------------------------
    # Multi-worker run ownership methods
    # ------------------------------------------------------------------

    async def update_lease(
        self,
        run_id: str,
        *,
        owner_worker_id: str,
        lease_expires_at: str,
    ) -> bool:
        lease_dt = datetime.fromisoformat(lease_expires_at)
        values: dict[str, Any] = {
            "owner_worker_id": owner_worker_id,
            "lease_expires_at": lease_dt,
            "updated_at": datetime.now(UTC),
        }
        async with self._sf() as session:
            result = await session.execute(update(RunRow).where(RunRow.run_id == run_id, RunRow.workspace_id.is_(None), RunRow.owner_worker_id == owner_worker_id, RunRow.status.in_(("pending", "running"))).values(**values))
            await session.commit()
            return result.rowcount != 0

    async def renew_lease(self, run_id: str, *, owner_worker_id: str, lease_expires_at: str) -> LeaseRenewal:
        lease_dt = datetime.fromisoformat(lease_expires_at)
        now = datetime.now(UTC)
        async with self._sf() as session:
            if session.get_bind().dialect.name == "sqlite":
                await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.scalar(select(RunRow).where(RunRow.run_id == run_id).with_for_update())
            if row is None or row.owner_worker_id != owner_worker_id:
                return LeaseRenewal(renewed=False)
            if row.workspace_id is not None:
                try:
                    await execution_lifetime(session, NativeRunStopTarget.from_row(row))
                except ValueError:
                    return LeaseRenewal(renewed=False)
                old_deadline = row.lease_expires_at
                if old_deadline is None or (old_deadline.replace(tzinfo=UTC) if old_deadline.tzinfo is None else old_deadline) <= now:
                    return LeaseRenewal(renewed=False)
            elif self._workspace_required or row.status not in ("pending", "running"):
                return LeaseRenewal(renewed=False)
            stopping = bool(await session.scalar(select(pending_run_stop(run_id=row.run_id, workspace_id=row.workspace_id)))) if row.workspace_id is not None else False
            revoked = bool(await session.scalar(select(revocation_run_stop(run_id=row.run_id, workspace_id=row.workspace_id)))) if stopping else False
            row.lease_expires_at, row.updated_at = lease_dt, now
            native_no_start = row.workspace_id is not None and row.status == "pending" and row.cancel_action == "rollback"
            action = "interrupt" if revoked or native_no_start else row.cancel_action
            await session.commit()
            return LeaseRenewal(renewed=True, cancel_action=action, workspace_stop_requested=stopping)

    async def mark_worker_interrupted(self, target):
        from deerflow.persistence.workspaces.run_control import mark_owner_interrupted

        return await mark_owner_interrupted(self._sf, target)

    async def confirm_workspace_execution(self, target):
        from deerflow.persistence.workspaces.run_control import confirm_local_execution

        return await confirm_local_execution(self._sf, target)

    async def confirm_workspace_run_stop(self, target, *, evidence):
        from deerflow.persistence.workspaces.run_control import confirm_local_run_stop

        return await confirm_local_run_stop(self._sf, target, evidence=evidence)

    async def request_cancel(self, run_id: str, *, action: str) -> str | None:
        """Atomically persist the first cancellation action on an active run."""
        if action not in ("interrupt", "rollback"):
            raise ValueError(f"Unsupported cancellation action: {action}")
        current = get_current_workspace()
        if self._workspace_required or current is not None:
            context = resolve_resource_scope(None, current.actor_user_id if current is not None else None, required=True)
            async with self._sf() as session:
                locator = await session.scalar(select(RunRow).where(RunRow.run_id == run_id, RunRow.workspace_id == context.workspace_id, RunRow.user_id == context.actor_user_id))
                if locator is None:
                    return None
                located = (locator.thread_id, locator.thread_incarnation, locator.created_at)
                parent = await ThreadMetaRepository(self._sf)._locked_row(session, located[0], context.actor_user_id, context)
                if parent is None or parent.incarnation != located[1]:
                    raise WorkspaceAccessDenied("cancel Run private parent changed")
                sequence = await self._next_change_seq(session)
                row = await session.scalar(select(RunRow).where(RunRow.run_id == run_id).with_for_update().execution_options(populate_existing=True))
                if row is None or row.workspace_id != context.workspace_id or row.user_id != context.actor_user_id or (row.thread_id, row.thread_incarnation, row.created_at) != located or row.operation_kind != "run":
                    raise WorkspaceAccessDenied("cancel Run identity changed while locking")
                target = NativeRunStopTarget.from_row(row)
                try:
                    await execution_lifetime(session, target)
                except ValueError:
                    return None
                if action == "rollback" and row.status != "pending":
                    raise WorkspaceAccessDenied("workspace checkpoint rollback requires its publication fence")
                from deerflow.persistence.workspaces.run_control import enqueue_run_stop

                now = datetime.now(UTC)
                row.cancel_action = row.cancel_action or action
                await enqueue_run_stop(session, row, reason="user", now=now, invalid_identity=target.workspace_context.membership_version > context.membership_version or target.workspace_context.policy_version > context.policy_version)
                row.updated_at, row.change_seq = now, sequence
                await session.commit()
                return row.cancel_action
        now = datetime.now(UTC)
        async with self._sf() as session:
            change_seq = await self._next_change_seq(session)
            result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.workspace_id.is_(None),
                    RunRow.status.in_(("pending", "running")),
                )
                .values(
                    cancel_action=case(
                        (RunRow.cancel_action.is_(None), action),
                        else_=RunRow.cancel_action,
                    ),
                    cancel_requested_at=case(
                        (RunRow.cancel_requested_at.is_(None), now),
                        else_=RunRow.cancel_requested_at,
                    ),
                    updated_at=now,
                    change_seq=change_seq,
                )
                .returning(RunRow.cancel_action)
            )
            row = result.first()
            await session.commit()
        return row.cancel_action if row is not None else None

    async def finalize_if_not_cancelled(
        self,
        run_id: str,
        *,
        status: str,
        worker_target=None,
        error: str | None = None,
        stop_reason: str | None = None,
        goal_verdict: dict[str, Any] | None = None,
    ) -> StatusFinalization:
        """Atomically let completion win only before cancellation."""
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(UTC),
        }
        if error is not None:
            values["error"] = error
        if stop_reason is not None:
            values["stop_reason"] = stop_reason
        if goal_verdict is not None:
            values["goal_verdict"] = self._safe_json(goal_verdict)

        async with self._sf() as session:
            values["change_seq"], scope = await self._worker_write_scope(session, run_id, worker_target)
            result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    *scope,
                    RunRow.status.in_(("pending", "running")),
                    RunRow.cancel_action.is_(None),
                )
                .values(**values)
                .returning(RunRow.run_id)
            )
            if result.first() is not None:
                await session.commit()
                return StatusFinalization(finalized=True)

            current = await session.execute(select(case((revocation_run_stop(run_id=RunRow.run_id, workspace_id=RunRow.workspace_id), "interrupt"), else_=RunRow.cancel_action)).where(RunRow.run_id == run_id, *scope))
            cancel_action = current.scalar_one_or_none()
            await session.commit()
            return StatusFinalization(
                finalized=False,
                cancel_action=cancel_action,
            )

    async def claim_for_takeover(
        self,
        run_id: str,
        *,
        grace_seconds: int,
        error: str,
        stop_reason: str | None = None,
    ) -> bool:
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
        values: dict[str, Any] = {
            "status": "error",
            "error": error,
            "updated_at": datetime.now(UTC),
        }
        if stop_reason is not None:
            values["stop_reason"] = stop_reason
        async with self._sf() as session:
            values["change_seq"] = await self._next_change_seq(session)
            result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.status.in_(("pending", "running")),
                    _lease_expired_or_null(RunRow.lease_expires_at, cutoff),
                    RunRow.workspace_id.is_(None),
                )
                .values(**values)
            )
            await session.commit()
            return result.rowcount != 0

    async def list_inflight_with_expired_lease(
        self,
        *,
        before: str | None = None,
        grace_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        if before is None:
            before_dt = datetime.now(UTC)
        elif isinstance(before, datetime):
            before_dt = before
        else:
            before_dt = datetime.fromisoformat(before)
        cutoff = datetime.now(UTC) - timedelta(seconds=grace_seconds)
        stmt = (
            select(RunRow)
            .where(
                RunRow.status.in_(("pending", "running")),
                RunRow.created_at <= before_dt,
                RunRow.workspace_id.is_(None),
                _lease_expired_or_null(RunRow.lease_expires_at, cutoff),
            )
            .order_by(RunRow.created_at.asc())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def create_thread_operation_atomic(
        self,
        run_id: str,
        *,
        thread_id: str,
        owner_worker_id: str,
        lease_expires_at: str | None,
        operation_kind: str = "run",
        multitask_strategy: str = "reject",
        assistant_id: str | None = None,
        user_id: str | None = None,
        model_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        created_at: str | None = None,
        grace_seconds: int = 10,
        idempotency_key: str | None = None,
        workspace_context: WorkspaceContext | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Atomically create a run with cross-process thread-uniqueness.

        - For ``reject``: INSERT, let the partial unique index enforce
          single-active-run. Returns ``(row_dict, [])`` on success, raises
          ``IntegrityError`` on conflict.
        - For ``interrupt`` / ``rollback``: SELECT FOR UPDATE inflight
          rows for the thread, cancel them (unless their lease is still valid),
          then INSERT the new row — all in one transaction. Returns
          ``(row_dict, claimed_row_dicts)``.

        Returns:
            Tuple of ``(new_run_dict, claimed_run_dicts)``.
        """
        from deerflow.runtime.runs.manager import ConflictError

        resolved_user_id = resolve_user_id(user_id or AUTO, method_name="RunRepository.create_thread_operation_atomic")
        context = resolve_resource_scope(workspace_context, resolved_user_id, required=self._workspace_required)
        if context is not None and multitask_strategy != "reject":
            raise WorkspaceAccessDenied("workspace interrupt admission requires lifecycle integration")
        now = datetime.now(UTC)
        created = datetime.fromisoformat(created_at) if created_at else now
        lease_dt = datetime.fromisoformat(lease_expires_at) if lease_expires_at else None
        cutoff = now - timedelta(seconds=grace_seconds)

        values = {
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "user_id": resolved_user_id,
            "model_name": self._normalize_model_name(model_name),
            "status": "pending",
            "operation_kind": operation_kind,
            "multitask_strategy": multitask_strategy,
            "metadata_json": self._safe_json(metadata) or {},
            "kwargs_json": self._safe_json(kwargs) or {},
            "owner_worker_id": owner_worker_id,
            "lease_expires_at": lease_dt,
            "idempotency_key": idempotency_key,
            "origin_kind": _origin_kind(operation_kind, metadata),
            "created_at": created,
            "updated_at": now,
        }

        if context is not None:
            values["workspace_id"] = context.workspace_id
        async with self._sf() as session:
            if context is not None:
                # Short admission only: workspace -> actor -> private thread,
                # then the existing global clock -> Run row order. No checkpoint
                # or model IO is held under this database transaction.
                thread = await ThreadMetaRepository(self._sf)._locked_row(session, thread_id, resolved_user_id, context, include_deleting=operation_kind == "delete")
                if thread is None or not thread.incarnation:
                    raise WorkspaceAccessDenied("private thread is unavailable")
                values["workspace_context_json"] = asdict(context)
                values["thread_incarnation"] = thread.incarnation
                if await session.scalar(select(pending_execution_barrier(workspace_id=context.workspace_id, user_id=resolved_user_id, thread_id=thread_id))):
                    raise ConflictError("Thread has native execution cleanup awaiting confirmation")
            # Keep the global clock -> run-row lock order used by every other
            # mutator. One position covers this atomic set of changes; run_id
            # provides deterministic ordering within the position.
            change_seq = await self._next_change_seq(session)
            claimed: list[dict[str, Any]] = []

            if multitask_strategy in ("interrupt", "rollback"):
                stmt = (
                    select(RunRow)
                    .where(
                        RunRow.thread_id == thread_id,
                        RunRow.status.in_(("pending", "running")),
                    )
                    .with_for_update()
                )
                result = await session.execute(stmt)
                for row in result.scalars():
                    lease_expired = False
                    if row.lease_expires_at is not None:
                        # SQLite drops tzinfo on read despite
                        # ``DateTime(timezone=True)`` (see ``_row_to_dict``).
                        # Treat naive values as UTC — same convention as
                        # ``coerce_iso`` — so the Python-side comparison
                        # against the aware ``cutoff`` does not raise
                        # ``TypeError: can't compare offset-naive and
                        # offset-aware datetimes`` when heartbeat is enabled
                        # on SQLite.
                        row_lease = row.lease_expires_at
                        if row_lease.tzinfo is None:
                            row_lease = row_lease.replace(tzinfo=UTC)
                        lease_expired = row_lease < cutoff
                        if row_lease >= cutoff and row.owner_worker_id != owner_worker_id:
                            # Live run owned by another worker — we cannot
                            # interrupt it and the partial unique index would
                            # reject our INSERT anyway. Surface as
                            # ConflictError so the caller gets a clean signal
                            # instead of a retry loop on IntegrityError.
                            raise ConflictError(f"Thread {thread_id} already has an active run owned by another worker")
                    if row.operation_kind != "run" and not lease_expired:
                        raise ConflictError(f"Thread {thread_id} has an active checkpoint write")
                    row.status = "interrupted"
                    row.error = "Cancelled by newer run"
                    row.owner_worker_id = owner_worker_id
                    row.updated_at = now
                    row.change_seq = change_seq
                    claimed.append(self._row_to_dict(row))

            values["change_seq"] = change_seq
            session.add(RunRow(run_id=run_id, **values))
            try:
                await session.flush()
                if context is not None and operation_kind == "run":
                    await create_execution_lifetime(session, await session.get(RunRow, run_id))
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                if idempotency_key is not None:
                    query = select(RunRow).where(RunRow.idempotency_key == idempotency_key)
                    if context is not None:
                        query = self._read_scope(query.where(RunRow.thread_id == thread_id, RunRow.operation_kind == operation_kind), resolved_user_id, require_run_incarnation=True)
                    existing = (await session.execute(query)).scalar_one_or_none()
                    if existing is not None:
                        raise RunIdempotencyConflict(self._row_to_dict(existing)) from exc
                    if context is not None:
                        # A global key collision must not return another space's
                        # payload or identifiers, even when acknowledgement was lost.
                        raise WorkspaceAccessDenied("reservation conflict is unavailable") from None
                raise

            new_row = await session.get(RunRow, run_id)
            return self._row_to_dict(new_row), claimed
