"""SQLAlchemy-backed project repositories.

Ownership discipline mirrors ``ThreadMetaRepository``: every method resolves
the caller via ``resolve_user_id(..., AUTO)`` and filters by ``user_id``;
a foreign project/document is indistinguishable from a missing one (callers
map ``None``/``False`` to 404). ``delete`` runs the membership-clearing
transaction from RFC v2 §5.1 plus the Phase-2 shelf-trash statement (§8.1):
every active ``project_documents`` row is moved to trash — with a
``trash_origin`` snapshot — inside the same transaction and row lock, so a
deleted project never leaves an active shelf row behind. No filesystem work
happens in either repository: shelf bytes are immutable, hash-qualified, and
owned by the document row's exclusive namespace, so trash and project delete
are pure row transitions.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.file_io import await_drained
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)

ProjectStatus = Literal["active", "archived"]


class ProjectNotAssignableError(ValueError):
    """Raised when a thread cannot be assigned to a project.

    The project is missing, foreign to the caller, or archived — the
    atomicity rules (RFC v2 §5.2) make these indistinguishable inside the
    mutating statement, so callers get one signal and map it to 404 (explicit
    API) or a dropped key (run admission).
    """


class ProjectRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        *,
        name: str,
        instructions: str = "",
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.create")
        now = datetime.now(UTC)
        row = ProjectRow(
            id=uuid.uuid4().hex,
            user_id=resolved_user_id,
            name=name,
            instructions=instructions,
            presentation=presentation or {},
            status="active",
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.get")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            return self._row_to_dict(row)

    async def list(
        self,
        *,
        status: ProjectStatus | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.list")
        stmt = select(ProjectRow).order_by(ProjectRow.created_at.asc(), ProjectRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectRow.user_id == resolved_user_id)
        if status is not None:
            stmt = stmt.where(ProjectRow.status == status)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def patch(
        self,
        project_id: str,
        *,
        name: str | None = None,
        instructions: str | None = None,
        presentation: dict | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.patch")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return None
            if name is not None:
                row.name = name
            if instructions is not None:
                row.instructions = instructions
            if presentation is not None:
                row.presentation = presentation
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def set_status(
        self,
        project_id: str,
        status: ProjectStatus,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        """Idempotent status flip; returns the current row or None (missing/foreign)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.set_status")
        async with self._sf() as session:
            row = await session.get(ProjectRow, project_id)
            if row is None or (resolved_user_id is not None and row.user_id != resolved_user_id):
                return None
            row.status = status
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def delete(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Delete a project and clear membership in one transaction (no filesystem work).

        Returns True when the project row was deleted; False when missing/foreign.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectRepository.delete")
        async with self._sf() as session:
            async with session.begin():
                # Lock the project row before touching it (FOR UPDATE on
                # Postgres; the clause renders nothing on SQLite). Membership
                # assignment (ThreadMetaRepository.set_project/create) takes
                # the same row lock before writing ``project_id``, so an
                # assigner either commits first and has its membership cleared
                # below, or blocks until this transaction commits and then
                # re-reads the row as gone — no dangling ``threads_meta.project_id``
                # (RFC v2 §14.14). Missing/foreign rows keep the False result.
                lock_stmt = select(ProjectRow).where(ProjectRow.id == project_id)
                if resolved_user_id is not None:
                    lock_stmt = lock_stmt.where(ProjectRow.user_id == resolved_user_id)
                locked = (await session.execute(lock_stmt.with_for_update())).scalar_one_or_none()
                if locked is None:
                    return False
                # §8.1 statement 2: every active shelf row moves to trash in
                # the same transaction and lock — never an active row pointing
                # at a deleted project. No filesystem work.
                await ProjectDocumentRepository.trash_all_for_project(session, project_id, project_name=locked.name, user_id=resolved_user_id)
                if resolved_user_id is not None:
                    await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.project_id == project_id, ThreadMetaRow.user_id == resolved_user_id).values(project_id=None, updated_at=ThreadMetaRow.__table__.c.updated_at))
                    result = await session.execute(sa_delete(ProjectRow).where(ProjectRow.id == project_id, ProjectRow.user_id == resolved_user_id))
                else:
                    await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.project_id == project_id).values(project_id=None, updated_at=ThreadMetaRow.__table__.c.updated_at))
                    result = await session.execute(sa_delete(ProjectRow).where(ProjectRow.id == project_id))
            return result.rowcount > 0


class ProjectDocumentRepository:
    """Project shelf documents: hash-qualified rows with a recoverable trash tier.

    Every read filters ``trashed_at IS NULL`` unless explicitly asked
    otherwise — trashed rows are invisible to the shelf index, the tools, and
    the listing APIs. Writes follow the Phase-1 lock idiom: SQLite takes the
    write lock up front (``BEGIN IMMEDIATE``), Postgres relies on
    ``SELECT … FOR UPDATE`` on the ``projects`` row; existence/ownership/
    status validation happens inside the mutating transaction, never as a
    separate check-then-act read (Phase-2 spec §6.3, §15.5).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ProjectDocumentRow) -> dict[str, Any]:
        d = row.to_dict()
        for key in ("created_at", "updated_at", "trashed_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = coerce_iso(val)
        return d

    @staticmethod
    async def _begin_immediate_if_sqlite(session: AsyncSession) -> None:
        if session.get_bind().dialect.name == "sqlite":
            # Read-then-write transaction: take the write lock up front
            # (ThreadMetaRepository precedent) so a concurrent writer cannot
            # interleave between the project lock and the mutation.
            await session.execute(text("BEGIN IMMEDIATE"))

    @staticmethod
    async def _lock_active_project(session: AsyncSession, project_id: str, resolved_user_id: str | None) -> ProjectRow | None:
        """Lock the owned ``status='active'`` project row inside the transaction."""
        stmt = select(ProjectRow).where(ProjectRow.id == project_id, ProjectRow.status == "active")
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectRow.user_id == resolved_user_id)
        return (await session.execute(stmt.with_for_update())).scalar_one_or_none()

    async def insert_active(
        self,
        project_id: str,
        *,
        document_id: str,
        name: str,
        relpath: str,
        sha256: str,
        size_bytes: int,
        source_thread_id: str | None = None,
        source_kind: str | None = None,
        source_name: str | None = None,
        place_file: Callable[[], Awaitable[None]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        """Insert one shelf row under the active-project lock, or return the dedup hit.

        One transaction (§6.3 shelf insert): lock the owned active project row
        (``None`` when missing/foreign/archived), dedup-``SELECT`` among active
        ``(project_id, sha256)`` rows, and on a miss invoke *place_file* — the
        atomic staging→final rename into this document's exclusive namespace —
        **before** the ``INSERT`` (file-before-row, §10.3): a crash leaves an
        unreferenced file the sweep collects, never a visible row without
        bytes. A dedup hit skips placement and returns the existing row — the
        first writer's name and provenance win (§10.9); callers recognize the
        hit by ``row["id"] != document_id``.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.insert_active")
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            if await self._lock_active_project(session, project_id, resolved_user_id) is None:
                await session.rollback()
                return None
            dedup_stmt = select(ProjectDocumentRow).where(
                ProjectDocumentRow.project_id == project_id,
                ProjectDocumentRow.sha256 == sha256,
                ProjectDocumentRow.trashed_at.is_(None),
            )
            if resolved_user_id is not None:
                dedup_stmt = dedup_stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            existing = (await session.execute(dedup_stmt)).scalars().first()
            if existing is not None:
                await session.commit()
                return self._row_to_dict(existing)
            if place_file is not None:
                # Drained: cancellation waits for the placement worker instead of
                # releasing the project lock over in-flight filesystem work.
                await await_drained(place_file())
            now = datetime.now(UTC)
            row = ProjectDocumentRow(
                id=document_id,
                project_id=project_id,
                user_id=resolved_user_id,
                name=name,
                stored_relpath=relpath,
                sha256=sha256,
                size_bytes=size_bytes,
                source_thread_id=source_thread_id,
                source_kind=source_kind,
                source_name=source_name,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def find_active_by_sha256(self, project_id: str, sha256: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Return the active row with this content address, or ``None`` (dedup probe)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.find_active_by_sha256")
        stmt = select(ProjectDocumentRow).where(
            ProjectDocumentRow.project_id == project_id,
            ProjectDocumentRow.sha256 == sha256,
            ProjectDocumentRow.trashed_at.is_(None),
        )
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return self._row_to_dict(row) if row is not None else None

    async def list_active(self, project_id: str, *, limit: int, offset: int, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Active shelf rows in index order: ``updated_at DESC, id ASC`` (§10.10)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_active")
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None)).order_by(ProjectDocumentRow.updated_at.desc(), ProjectDocumentRow.id.asc()).limit(limit).offset(offset)
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def count_active(self, project_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> int:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.count_active")
        stmt = select(func.count()).select_from(ProjectDocumentRow).where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            return int((await session.execute(stmt)).scalar_one())

    async def shelf_snapshot(self, project_id: str, *, limit: int, user_id: str | None | _AutoSentinel = AUTO) -> tuple[list[dict], int]:
        """Return ``(rows, total)`` for the pinned shelf index in one round trip.

        ``rows`` are the first ``limit`` active rows in ``updated_at DESC,
        id ASC`` order against the same database snapshot as ``total``; the
        caller (§7.1 step 2) fetches ``shelf_index_max_entries + 1`` and uses
        the extra row only to decide truncation — it is never rendered.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.shelf_snapshot")
        stmt = (
            select(ProjectDocumentRow, func.count().over().label("total"))
            .where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
            .order_by(ProjectDocumentRow.updated_at.desc(), ProjectDocumentRow.id.asc())
            .limit(limit)
        )
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            pairs = result.all()
            rows = [self._row_to_dict(row) for row, _total in pairs]
            total = int(pairs[0][1]) if pairs else 0
            return rows, total

    async def get(self, document_id: str, *, include_trashed: bool = False, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        """Return one owned row, or ``None`` (missing/foreign; trashed unless included)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.get")
        async with self._sf() as session:
            row = await session.get(ProjectDocumentRow, document_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            if row.trashed_at is not None and not include_trashed:
                return None
            return self._row_to_dict(row)

    async def trash(self, document_id: str, *, project_id: str | None = None, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Move one owned document to trash; ``False`` ⇒ 404 (§6.3 trash).

        Locks the owned **active** project row first — an archived shelf
        rejects this write (§8.4) — then the owned document row in the same
        transaction, and applies the guarded ``UPDATE … WHERE project_id =
        :pid AND trashed_at IS NULL``. ``False`` covers every failure shape
        (missing/foreign document, missing/foreign/archived project, already
        trashed) so the route never leaks existence.

        *project_id* is the caller's expected project (the route's URL
        project): when given, both the unlocked probe and the locked re-read
        require the row to belong to it — a document of a sibling project is
        indistinguishable from missing, and the guarded ``UPDATE`` predicates
        on the expected id. When omitted, the document's own project is used.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.trash")
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            # Route to the owning project: the authoritative validation is the
            # locked re-read below, so this unlocked probe leaks nothing.
            probe = await session.get(ProjectDocumentRow, document_id)
            if probe is None or (project_id is not None and probe.project_id != project_id) or (resolved_user_id is not None and probe.user_id != resolved_user_id):
                await session.rollback()
                return False
            expected_project_id = project_id if project_id is not None else probe.project_id
            locked_project = await self._lock_active_project(session, expected_project_id, resolved_user_id)
            if locked_project is None:
                await session.rollback()
                return False
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if locked is None or locked.project_id != expected_project_id or (resolved_user_id is not None and locked.user_id != resolved_user_id):
                await session.rollback()
                return False
            stmt = (
                update(ProjectDocumentRow)
                .where(
                    ProjectDocumentRow.id == document_id,
                    ProjectDocumentRow.project_id == expected_project_id,
                    ProjectDocumentRow.trashed_at.is_(None),
                )
                .values(
                    trashed_at=datetime.now(UTC),
                    trash_origin={"project_id": locked_project.id, "project_name": locked_project.name},
                )
            )
            if resolved_user_id is not None:
                stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    @staticmethod
    async def trash_all_for_project(session: AsyncSession, project_id: str, *, project_name: str, user_id: str | None) -> int:
        """Trash every active shelf row of a project inside the caller's transaction.

        §8.1 statement 2: runs under the same project row lock
        ``ProjectRepository.delete`` already holds, so a concurrent shelf
        insert either commits first (and is trashed here) or blocks and then
        finds no active project — never an active row pointing at a deleted
        project. No filesystem work: rows snapshot ``{project_id,
        project_name}`` before the project row disappears.
        """
        stmt = (
            update(ProjectDocumentRow)
            .where(ProjectDocumentRow.project_id == project_id, ProjectDocumentRow.trashed_at.is_(None))
            .values(
                trashed_at=datetime.now(UTC),
                trash_origin={"project_id": project_id, "project_name": project_name},
            )
        )
        if user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == user_id)
        result = await session.execute(stmt)
        return int(result.rowcount or 0)

    async def stage_live_copy[T](
        self,
        document_id: str,
        *,
        project_id: str,
        stage: Callable[[dict[str, Any]], Awaitable[T]],
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[dict[str, Any], T] | None:
        """Run *stage* while holding the owned LIVE document row's lock (§7.3 item 3).

        Attach-to-thread reads a stable source copy serialized against purge
        and trash: this takes the document row lock inside one transaction
        (``BEGIN IMMEDIATE`` on SQLite, ``SELECT … FOR UPDATE`` elsewhere),
        validates ownership, shelf membership and liveness (``trashed_at IS
        NULL`` — an archived source project stays readable, §8.4), then
        invokes *stage* with the row dict and commits. A concurrent purge
        either commits first (the locked re-read finds the row gone/trashed
        and this returns ``None``) or blocks until the copy finishes — never
        a partially copied source. Only the document lock is taken, so no
        lock-ordering hazard exists against purge's project→document order
        (§6.3). The staged copy is the caller's responsibility once the lock
        is released.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.stage_live_copy")
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if locked is None or locked.project_id != project_id or locked.trashed_at is not None or (resolved_user_id is not None and locked.user_id != resolved_user_id):
                await session.rollback()
                return None
            row = self._row_to_dict(locked)
            # Drained: the lock is never released over an in-flight staging copy.
            staged = await await_drained(stage(row))
            await session.commit()
            return row, staged

    async def convert_under_live_lock[T](
        self,
        document_id: str,
        *,
        project_id: str,
        convert: Callable[[dict[str, Any]], Awaitable[T]],
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[dict[str, Any], T] | None:
        """Run *convert* while holding the owned LIVE document row's lock (§6.3).

        Lazy conversion publishes ``derived/converted.md`` serialized against
        trash and purge: this takes the document row lock inside one
        transaction (``BEGIN IMMEDIATE`` on SQLite, ``SELECT … FOR UPDATE``
        elsewhere), revalidates ownership, shelf membership and active state
        (``trashed_at IS NULL``) AFTER locking, then invokes *convert* — the
        offloaded convert-to-temp + atomic ``os.replace`` publish — and
        commits. A concurrent trash/purge either commits first (the locked
        re-read finds the row gone/trashed and this returns ``None`` without
        invoking *convert*, so nothing is published) or blocks until the
        publish commits — a derived file is never published after purge
        removed the original (§6.3 lock order, §13). Only the document lock
        is taken, so no lock-ordering hazard exists against trash's
        project→document order. ``None`` means missing/foreign/trashed; the
        caller maps it to its not-on-the-shelf / ``content_missing``
        semantics.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.convert_under_live_lock")
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).with_for_update())).scalar_one_or_none()
            if locked is None or locked.project_id != project_id or locked.trashed_at is not None or (resolved_user_id is not None and locked.user_id != resolved_user_id):
                await session.rollback()
                return None
            row = self._row_to_dict(locked)
            # Drained: a cancelled conversion finishes its worker (and any
            # publish) before the document lock unwinds (§6.3).
            result = await await_drained(convert(row))
            await session.commit()
            return row, result

    async def list_trashed(self, *, limit: int, offset: int, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Trashed rows, most recently trashed first (trash listing, §6.5)."""
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_trashed")
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None)).order_by(ProjectDocumentRow.trashed_at.desc(), ProjectDocumentRow.id.asc()).limit(limit).offset(offset)
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def count_trashed(self, *, user_id: str | None | _AutoSentinel = AUTO) -> int:
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.count_trashed")
        stmt = select(func.count()).select_from(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None))
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            return int((await session.execute(stmt)).scalar_one())

    async def list_all_for_sweep(self, *, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Every row — active and trashed — for retention-sweep reconciliation.

        The sweep (§8.3) needs the full row set of the swept user(s): any row
        protects its entire original/derived namespace from orphan collection
        (even after restore re-pointed it to another project), and row-side
        reconciliation detects missing/size-mismatched content without
        deleting anything.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.list_all_for_sweep")
        stmt = select(ProjectDocumentRow).order_by(ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def restore(
        self,
        document_id: str,
        *,
        target_project_id: str,
        check_content: Callable[[dict[str, Any]], Awaitable[bool]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> tuple[Literal["restored", "merged", "not_found", "no_target", "content_missing"], dict | None]:
        """Restore one trashed row into an active target project (§6.3/§8.2).

        One transaction: lock the target active owned project row first
        (``None`` ⇒ ``no_target``: missing/foreign/archived are
        indistinguishable), then lock the source and any merge-candidate rows
        in ID order. Source ownership and ``trashed_at IS NOT NULL`` are
        revalidated after locking (missing/already-restored/purged ⇒
        ``not_found``). Before either outcome, *check_content* verifies the
        original's existence/size under the source lock — and, for a merge,
        the surviving target's content under its lock; a failure yields
        ``content_missing`` and leaves the source trashed (§8.3). Merge: the
        target already has an active row with the same ``sha256``, so the
        trash row is deleted and the surviving row returned; the caller
        unlinks the discarded source namespace best-effort AFTER commit.
        Otherwise the row is re-pointed (``project_id`` = target, trash
        fields cleared) with NO file moves — ``stored_relpath`` is
        projects-root-relative, so the bytes stay valid (§10.6).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.restore")
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            locked_project = await self._lock_active_project(session, target_project_id, resolved_user_id)
            if locked_project is None:
                await session.rollback()
                return "no_target", None
            # Identify the source and any merge candidates before locking.
            # This unlocked probe only chooses WHICH rows to lock; every
            # validation below re-reads the locked rows.
            probe = (await session.execute(select(ProjectDocumentRow.id, ProjectDocumentRow.sha256, ProjectDocumentRow.trashed_at).where(ProjectDocumentRow.id == document_id))).first()
            if probe is None:
                await session.rollback()
                return "not_found", None
            lock_ids = [document_id]
            if probe.trashed_at is not None:
                candidates = await session.execute(
                    select(ProjectDocumentRow.id).where(
                        ProjectDocumentRow.project_id == target_project_id,
                        ProjectDocumentRow.sha256 == probe.sha256,
                        ProjectDocumentRow.trashed_at.is_(None),
                        ProjectDocumentRow.id != document_id,
                    )
                )
                lock_ids.extend(row[0] for row in candidates.all())
            locked_rows = (await session.execute(select(ProjectDocumentRow).where(ProjectDocumentRow.id.in_(lock_ids)).order_by(ProjectDocumentRow.id.asc()).with_for_update())).scalars().all()
            by_id = {row.id: row for row in locked_rows}
            source = by_id.get(document_id)
            # Revalidate under the lock: ownership + still trashed.
            if source is None or source.trashed_at is None or (resolved_user_id is not None and source.user_id != resolved_user_id):
                await session.rollback()
                return "not_found", None
            if check_content is not None and not await await_drained(check_content(self._row_to_dict(source))):
                # Missing/size-mismatched bytes: leave the row trashed (§8.3).
                await session.rollback()
                return "content_missing", None
            surviving = next(
                (row for row in locked_rows if row.id != document_id and row.project_id == target_project_id and row.sha256 == source.sha256 and row.trashed_at is None and (resolved_user_id is None or row.user_id == resolved_user_id)),
                None,
            )
            if surviving is not None:
                if check_content is not None and not await await_drained(check_content(self._row_to_dict(surviving))):
                    await session.rollback()
                    return "content_missing", None
                # Merge: the target already serves these bytes; delete the
                # trash row (guarded) and report the surviving row. No file
                # mutation inside the transaction — the discarded namespace
                # cleanup follows commit (§8.2).
                result = await session.execute(sa_delete(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id, ProjectDocumentRow.trashed_at.is_not(None)))
                await session.commit()
                if result.rowcount == 0:
                    return "not_found", None
                return "merged", self._row_to_dict(surviving)
            # Re-point: no file moves (§10.6). The document row lock held
            # since the revalidation above serializes this against purge.
            source.project_id = target_project_id
            source.trashed_at = None
            source.trash_origin = None
            await session.commit()
            await session.refresh(source)
            return "restored", self._row_to_dict(source)

    async def purge_candidates(self, retention_days: int, *, now: datetime | None = None, user_id: str | None | _AutoSentinel = AUTO) -> list[dict]:
        """Trashed rows at or past the retention window, oldest first (§8.3).

        A row trashed exactly ``retention_days`` ago is eligible — the window
        has fully passed. The sweep revalidates each candidate's trash
        timestamp and the cutoff under the purge lock before removing
        anything (§6.1).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.purge_candidates")
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.trashed_at.is_not(None), ProjectDocumentRow.trashed_at <= cutoff).order_by(ProjectDocumentRow.trashed_at.asc(), ProjectDocumentRow.id.asc())
        if resolved_user_id is not None:
            stmt = stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def purge(
        self,
        document_id: str,
        *,
        retention_cutoff: datetime | None = None,
        expected_trashed_at: datetime | str | None = None,
        remove_files: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        """Permanently delete one trashed row and its bytes (§6.3/§8.3).

        One database transaction holds the owned document-row lock
        continuously across trashed-state revalidation, *remove_files*
        (unlink of the original and ``derived/converted.md``), row deletion
        and commit — restore cannot pass its source-row lock meanwhile.
        Purge acquires only its document lock and never later waits on a
        project lock (§6.3 lock order). Retention callers pass
        ``expected_trashed_at`` + ``retention_cutoff`` from their candidate
        selection; both are revalidated under the lock, so a row restored
        and later re-trashed is NOT purged on its former expiry. Manual
        purge passes neither and only requires the row to be trashed now.
        ``FileNotFoundError`` inside *remove_files* counts as already
        removed; any other error rolls the transaction back and leaves a
        retryable trashed row. ``False`` ⇒ 404 (missing, foreign, not
        trashed, or no longer matching the retention selection). No public
        unguarded row deletion exists.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ProjectDocumentRepository.purge")
        async with self._sf() as session:
            await self._begin_immediate_if_sqlite(session)
            lock_stmt = select(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id)
            if resolved_user_id is not None:
                lock_stmt = lock_stmt.where(ProjectDocumentRow.user_id == resolved_user_id)
            locked = (await session.execute(lock_stmt.with_for_update())).scalar_one_or_none()
            if locked is None or locked.trashed_at is None:
                await session.rollback()
                return False
            if expected_trashed_at is not None and coerce_iso(locked.trashed_at) != coerce_iso(expected_trashed_at):
                # Restored and re-trashed since candidate selection: the
                # former expiry no longer applies (§6.1).
                await session.rollback()
                return False
            if retention_cutoff is not None:
                trashed_at = locked.trashed_at
                if trashed_at.tzinfo is None:
                    trashed_at = trashed_at.replace(tzinfo=UTC)
                if trashed_at > retention_cutoff:
                    await session.rollback()
                    return False
            if remove_files is not None:
                try:
                    # Drained: cancellation waits for the unlink worker, so the
                    # row lock is released only after the filesystem work finished.
                    await await_drained(remove_files(self._row_to_dict(locked)))
                except Exception:
                    # Filesystem work is not rollbackable, but the row is:
                    # keep the trashed row so the purge stays retryable (§8.3).
                    await session.rollback()
                    raise
            result = await session.execute(sa_delete(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id, ProjectDocumentRow.trashed_at.is_not(None)))
            await session.commit()
            return result.rowcount > 0
