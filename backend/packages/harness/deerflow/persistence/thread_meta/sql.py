"""SQLAlchemy-backed thread metadata repository."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, column, or_, select, table, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from deerflow.persistence.json_compat import json_match
from deerflow.persistence.thread_meta.base import PROJECT_FILTER_UNSET, THREAD_ARCHIVED_METADATA_KEY, THREAD_PINNED_METADATA_KEY, THREAD_PROJECT_METADATA_KEY, InvalidMetadataFilterError, ThreadMetaStore, _ProjectFilterUnset
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.workspaces.scope import live_workspace_predicate, lock_resource_scope, resolve_resource_scope
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.file_io import await_drained
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class ThreadMetaRepository(ThreadMetaStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, workspace_required: bool = False) -> None:
        self._sf = session_factory
        self._workspace_required = workspace_required

    def _scope(self, user_id, *, integrated=True):
        context = resolve_resource_scope(None, user_id, required=self._workspace_required)
        if context is not None and not integrated:
            raise WorkspaceAccessDenied("thread ownership maintenance is unavailable in workspace scope")
        return context

    @staticmethod
    def _owned_scope(stmt, user_id, context, *, include_deleting=False):
        if user_id is not None:
            stmt = stmt.where(ThreadMetaRow.user_id == user_id)
        if context is not None:
            if not include_deleting:
                stmt = stmt.where(ThreadMetaRow.status != "deleting")
            from deerflow.persistence.projects.model import ProjectRow

            parent = select(ProjectRow.id).where(ProjectRow.id == ThreadMetaRow.project_id, ProjectRow.workspace_id == context.workspace_id).correlate(ThreadMetaRow).exists()
            stmt = stmt.where(ThreadMetaRow.workspace_id == context.workspace_id, live_workspace_predicate(context), or_(ThreadMetaRow.project_id.is_(None), parent))
        return stmt

    @staticmethod
    async def _begin_write(session, context):
        if context is not None:
            await lock_resource_scope(session, context)
        elif session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))

    async def _locked_row(self, session, thread_id, user_id, context, *, include_deleting=False):
        await self._begin_write(session, context)
        return await session.scalar(self._owned_scope(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id), user_id, context, include_deleting=include_deleting).with_for_update())

    @staticmethod
    async def _project_available(session, project_id, user_id, context):
        from deerflow.persistence.projects.model import ProjectRow
        from deerflow.persistence.projects.sql import ProjectRepository

        stmt = select(ProjectRow.id).where(ProjectRow.id == project_id, ProjectRow.status == "active")
        stmt = ProjectRepository._owned_scope(stmt, user_id, context)
        return await session.scalar(stmt.with_for_update()) is not None

    @staticmethod
    def _row_to_dict(row: ThreadMetaRow) -> dict[str, Any]:
        d = row.to_dict()
        d["metadata"] = dict(d.pop("metadata_json", None) or {})
        project_id = d.pop("project_id", None)
        if project_id is not None:
            d["metadata"][THREAD_PROJECT_METADATA_KEY] = project_id
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                # SQLite drops tzinfo despite ``DateTime(timezone=True)``;
                # ``coerce_iso`` normalizes naive values as UTC so the wire format always carries tz.
                d[key] = coerce_iso(val)
        return d

    async def publish_under_live_lock[T](self, thread_id: str, *, publish: Callable[[], Awaitable[T]], incarnation: str | None = None, user_id: str | None | _AutoSentinel = AUTO) -> T:
        """Fence a short file publication; never hold this over model/network work."""
        owner = resolve_user_id(user_id, method_name="ThreadMetaRepository.publish_under_live_lock")
        context = self._scope(owner)
        async with self._sf() as session:
            row = await self._locked_row(session, thread_id, owner, context)
            if row is None or (context is not None and (not incarnation or row.incarnation != incarnation)):
                raise WorkspaceAccessDenied("thread publication identity is unavailable")
            result = await await_drained(publish())
            await session.commit()
            return result

    async def commit_checkpoint_under_live_lock[T](self, thread_id: str, *, incarnation: str, commit: Callable[[], Awaitable[T]], user_id: str | None | _AutoSentinel = AUTO) -> T:
        """Fence only prepared native checkpoint IO, never graph/model/tool setup.

        The caller must hold its durable non-run reservation. Metadata and
        checkpoint storage need not share a transaction; the live SQL locks
        serialize authorization/lifecycle changes across the drained write.
        This does not make two databases an atomic transaction.
        """
        owner = resolve_user_id(user_id, method_name="ThreadMetaRepository.commit_checkpoint_under_live_lock")
        context = self._scope(owner)
        if context is None or not incarnation:
            raise WorkspaceAccessDenied("checkpoint commit requires private thread identity")
        async with self._sf() as session:
            row = await self._locked_row(session, thread_id, owner, context)
            if row is None or row.incarnation != incarnation:
                raise WorkspaceAccessDenied("checkpoint thread changed before commit")
            result = await await_drained(commit())
            await session.commit()
            return result

    async def publish_branch_from_private_source(
        self,
        source_thread_id: str,
        source_incarnation: str,
        new_thread_id: str,
        *,
        publish: Callable[[], Awaitable[Any]],
        assistant_id: str | None = None,
        display_name: str | None = None,
        metadata: dict | None = None,
        project_id: str | None = None,
    ) -> dict:
        """Publish prepared native checkpoints and branch metadata under source fencing.

        Graph assembly and file staging precede this short transaction. The
        caller owns the source's durable branch reservation. Metadata becomes
        visible only after checkpoint IO succeeds; cross-store crash atomicity
        is not implied, and uncertain commits must not trigger file deletion.
        """
        from deerflow.persistence.projects import ProjectNotAssignableError

        owner = resolve_user_id(AUTO, method_name="ThreadMetaRepository.publish_branch_from_private_source")
        context = self._scope(owner)
        if context is None or not source_incarnation or new_thread_id == source_thread_id:
            raise WorkspaceAccessDenied("branch publication requires private source identity")
        now = datetime.now(UTC)
        async with self._sf() as session:
            source = await self._locked_row(session, source_thread_id, owner, context)
            if source is None or source.incarnation != source_incarnation:
                raise WorkspaceAccessDenied("branch source changed before publication")
            if project_id is not None and (source.project_id != project_id or not await self._project_available(session, project_id, owner, context)):
                raise ProjectNotAssignableError(project_id)
            row = ThreadMetaRow(
                thread_id=new_thread_id,
                incarnation=uuid.uuid4().hex,
                assistant_id=assistant_id,
                user_id=owner,
                workspace_id=context.workspace_id,
                project_id=project_id,
                display_name=display_name,
                status="idle",
                metadata_json=metadata or {},
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            await await_drained(publish())
            result = self._row_to_dict(row)
            await session.commit()
            return result

    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
        display_name: str | None = None,
        metadata: dict | None = None,
        project_id: str | None = None,
    ) -> dict:
        # Auto-resolve user_id from contextvar when AUTO; explicit None
        # creates an orphan row (used by migration scripts).
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.create")
        context = self._scope(resolved_user_id)
        now = datetime.now(UTC)
        async with self._sf() as session:
            await self._begin_write(session, context)
            if project_id is not None:
                from deerflow.persistence.projects import ProjectNotAssignableError

                if not await self._project_available(session, project_id, resolved_user_id, context):
                    raise ProjectNotAssignableError(project_id)
            row = ThreadMetaRow(
                thread_id=thread_id,
                incarnation=uuid.uuid4().hex,
                assistant_id=assistant_id,
                user_id=resolved_user_id,
                workspace_id=context.workspace_id if context is not None else None,
                display_name=display_name,
                status="idle",
                metadata_json=metadata or {},
                project_id=project_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def claim_unowned(self, thread_id: str, owner: str) -> bool:
        self._scope(owner, integrated=False)
        claim_target = table(
            ThreadMetaRow.__tablename__,
            column(ThreadMetaRow.thread_id.key),
            column(ThreadMetaRow.user_id.key),
        )
        async with self._sf() as session:
            result = await session.execute(
                update(claim_target)
                .where(
                    claim_target.c.thread_id == thread_id,
                    claim_target.c.user_id.is_(None),
                )
                .values(user_id=owner)
            )
            await session.commit()
            return result.rowcount > 0

    async def set_project(
        self,
        thread_id: str,
        project_id: str | None,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.set_project")
        context = self._scope(resolved_user_id)
        async with self._sf() as session:
            await self._begin_write(session, context)
            if project_id is not None and not await self._project_available(session, project_id, resolved_user_id, context):
                return False
            stmt = (
                update(ThreadMetaRow)
                .where(ThreadMetaRow.thread_id == thread_id)
                .values(
                    project_id=project_id,
                    # Explicit self-assignment: satisfies the column so the
                    # ``onupdate`` hook does not bump recency (pin precedent, G5).
                    updated_at=ThreadMetaRow.__table__.c.updated_at,
                )
            )
            stmt = self._owned_scope(stmt, resolved_user_id, context)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def get(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.get")
        context = self._scope(resolved_user_id)
        async with self._sf() as session:
            row = await session.scalar(self._owned_scope(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id), resolved_user_id, context))
            if row is None:
                return None
            return self._row_to_dict(row)

    async def check_access(self, thread_id: str, user_id: str, *, require_existing: bool = False) -> bool:
        """Check if ``user_id`` has access to ``thread_id``.

        Two modes — one row, two distinct semantics depending on what
        the caller is about to do:

        - ``require_existing=False`` (default, permissive):
          Returns True for: row missing (untracked legacy thread),
          ``row.user_id`` is None (shared / pre-auth data),
          or ``row.user_id == user_id``. Use for **read-style**
          decorators where treating an untracked thread as accessible
          preserves backward-compat.

        - ``require_existing=True`` (strict):
          Returns True **only** when the row exists AND
          (``row.user_id == user_id`` OR ``row.user_id is None``).
          Use for **destructive / mutating** decorators (DELETE, PATCH,
          state-update) so a thread that has *already been deleted*
          cannot be re-targeted by any caller — closing the
          delete-idempotence cross-user gap where the row vanishing
          made every other user appear to "own" it.
        """
        context = self._scope(user_id)
        async with self._sf() as session:
            if context is not None:
                return await session.scalar(self._owned_scope(select(ThreadMetaRow.thread_id).where(ThreadMetaRow.thread_id == thread_id), user_id, context)) is not None
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return not require_existing
            if row.user_id is None:
                return True
            return row.user_id == user_id

    async def search(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        archived: bool | None = None,
        project_id: str | None | _ProjectFilterUnset = PROJECT_FILTER_UNSET,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Search threads with optional metadata and status filters.

        Owner filter is enforced by default: caller must be in a user
        context. Pass ``user_id=None`` to bypass (migration/CLI).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.search")
        context = self._scope(resolved_user_id)
        pinned_order = case(
            (json_match(ThreadMetaRow.metadata_json, THREAD_PINNED_METADATA_KEY, True), 1),
            else_=0,
        )
        stmt = select(ThreadMetaRow).order_by(
            pinned_order.desc(),
            ThreadMetaRow.updated_at.desc(),
            ThreadMetaRow.thread_id.desc(),
        )
        stmt = self._owned_scope(stmt, resolved_user_id, context)
        if status:
            stmt = stmt.where(ThreadMetaRow.status == status)

        if metadata:
            applied = 0
            for key, value in metadata.items():
                try:
                    stmt = stmt.where(json_match(ThreadMetaRow.metadata_json, key, value))
                    applied += 1
                except (ValueError, TypeError) as exc:
                    logger.warning("Skipping metadata filter key %s: %s", ascii(key), exc)
            if applied == 0:
                # Comma-separated plain string (no list repr / nested
                # quoting) so the 400 detail surfaced by the Gateway is
                # easy for clients to read. Sorted for determinism.
                rejected_keys = ", ".join(sorted(str(k) for k in metadata))
                raise InvalidMetadataFilterError(f"All metadata filter keys were rejected as unsafe: {rejected_keys}")

        if archived is not None:
            # CASE handles missing/JSON-null keys and non-boolean legacy values
            # identically on SQLite and Postgres, including for the active view.
            archive_flag = case((json_match(ThreadMetaRow.metadata_json, THREAD_ARCHIVED_METADATA_KEY, True), 1), else_=0)
            stmt = stmt.where(archive_flag == int(archived))
        if not isinstance(project_id, _ProjectFilterUnset):
            if project_id is None:
                stmt = stmt.where(ThreadMetaRow.project_id.is_(None))
            else:
                stmt = stmt.where(ThreadMetaRow.project_id == project_id)

        stmt = stmt.limit(limit).offset(offset)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def update_display_name(
        self,
        thread_id: str,
        display_name: str,
        *,
        remove_metadata_keys: tuple[str, ...] = (),
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        """Update the display name and remove caller-selected stale metadata atomically."""
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.update_display_name")
        context = self._scope(resolved_user_id)
        async with self._sf() as session:
            row = await self._locked_row(session, thread_id, resolved_user_id, context)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return
            row.display_name = display_name
            metadata = dict(row.metadata_json or {})
            for key in remove_metadata_keys:
                metadata.pop(key, None)
            row.metadata_json = metadata
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def update_status(
        self,
        thread_id: str,
        status: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.update_status")
        context = self._scope(resolved_user_id)
        async with self._sf() as session:
            row = await self._locked_row(session, thread_id, resolved_user_id, context)
            if row is None:
                return
            row.status = status
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def update_metadata(
        self,
        thread_id: str,
        metadata: dict,
        *,
        touch: bool = True,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        """Merge ``metadata`` into ``metadata_json``.

        The row is locked before the read-modify-write merge so concurrent
        callers cannot replace each other's keys. SQLite acquires its write
        transaction before reading; databases with row-level locking use
        ``SELECT ... FOR UPDATE``. No-op if the row does not exist or the
        user_id check fails.

        ``touch`` refreshes ``updated_at`` (default); pass ``touch=False`` to
        preserve recency ordering for metadata-only changes such as pin/unpin.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.update_metadata")
        context = self._scope(resolved_user_id)
        async with self._sf() as session:
            row = await self._locked_row(session, thread_id, resolved_user_id, context)
            if row is None:
                return
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return
            merged = dict(row.metadata_json or {})
            merged.update(metadata)
            row.metadata_json = merged
            if touch:
                row.updated_at = datetime.now(UTC)
            else:
                # ``updated_at`` has an ``onupdate`` hook that fires on any row
                # UPDATE unless the column has an explicit SET value. Mark the
                # current value dirty so SQLAlchemy emits it in SET, skips the
                # hook, and preserves recency ordering.
                flag_modified(row, "updated_at")
            await session.commit()

    async def update_owner(
        self,
        thread_id: str,
        owner_user_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        """Move a thread metadata row to ``owner_user_id``."""
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.update_owner")
        context = self._scope(resolved_user_id, integrated=False)
        async with self._sf() as session:
            row = await self._locked_row(session, thread_id, resolved_user_id, context)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return
            row.user_id = owner_user_id
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def delete(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.delete")
        context = self._scope(resolved_user_id)
        async with self._sf() as session:
            row = await self._locked_row(session, thread_id, resolved_user_id, context)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return
            await session.delete(row)
            await session.commit()
