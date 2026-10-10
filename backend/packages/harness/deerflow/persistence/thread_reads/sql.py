"""SQL repository for per-user thread read state.

A thread is **unread** for a user while one of that user's server-originated
runs in it (``runs.origin_kind IS NOT NULL``) changed after the user last
opened it. "Last opened" is ``thread_read_markers.seen_change_seq``: the
highest ``runs.change_seq`` of the user's runs in that thread when they read
it. The run-change clock is database-global and monotonic, so the marker
works across workers and devices and never depends on wall-clock time.

``thread_read_versions`` is a per-user counter raised in the same transaction
whenever a marker actually moves forward. The activity feed returns it, so
another device notices a read even when no run changed.

Every method takes an explicit ``user_id`` string (never ``None`` or the
``AUTO`` sentinel): the router resolves the caller once.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.run.model import RunRow
from deerflow.persistence.thread_reads.model import ThreadReadMarkerRow, ThreadReadVersionRow


def _insert_for(session: AsyncSession):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert
    if dialect == "sqlite":
        return sqlite_insert
    raise ValueError(f"Unsupported thread read database dialect: {dialect}")


class ThreadReadRepository:
    """Persistence facade for ``thread_read_markers`` and ``thread_read_versions``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def mark_read(self, *, user_id: str, thread_id: str) -> int:
        """Mark the thread read up to the user's newest run change; returns the stored position.

        One transaction. The marker only ever moves forward (concurrent reads
        from several devices keep the maximum), and a read that changes
        nothing writes nothing: no marker update and no ``read_version``
        bump, so other tabs and devices do not refetch. A thread without any
        run of this user has nothing to read and gets no marker.
        """
        async with self._sf() as session:
            insert = _insert_for(session)
            seen = int(
                await session.scalar(
                    select(func.coalesce(func.max(RunRow.change_seq), 0)).where(
                        RunRow.thread_id == thread_id,
                        RunRow.user_id == user_id,
                    )
                )
                or 0
            )
            raised = None
            if seen > 0:
                stmt = insert(ThreadReadMarkerRow).values(
                    user_id=user_id,
                    thread_id=thread_id,
                    seen_change_seq=seen,
                    updated_at=datetime.now(UTC),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[ThreadReadMarkerRow.user_id, ThreadReadMarkerRow.thread_id],
                    set_={"seen_change_seq": stmt.excluded.seen_change_seq, "updated_at": stmt.excluded.updated_at},
                    where=ThreadReadMarkerRow.seen_change_seq < stmt.excluded.seen_change_seq,
                ).returning(ThreadReadMarkerRow.seen_change_seq)
                raised = (await session.execute(stmt)).scalar_one_or_none()
            if raised is not None:
                version = insert(ThreadReadVersionRow).values(user_id=user_id, version=1)
                version = version.on_conflict_do_update(
                    index_elements=[ThreadReadVersionRow.user_id],
                    set_={"version": ThreadReadVersionRow.version + 1},
                )
                await session.execute(version)
                await session.commit()
                return int(raised)
            stored = await session.scalar(
                select(ThreadReadMarkerRow.seen_change_seq).where(
                    ThreadReadMarkerRow.user_id == user_id,
                    ThreadReadMarkerRow.thread_id == thread_id,
                )
            )
            await session.rollback()
            return int(stored) if stored is not None else seen

    async def unread_thread_ids(self, *, user_id: str, thread_ids: Sequence[str]) -> set[str]:
        """The subset of ``thread_ids`` that are unread for ``user_id``.

        Only the viewer's own server-originated agent runs count: their own
        interactive runs, legacy rows (``origin_kind`` NULL) and other users'
        runs in a shared thread never make a thread unread.
        """
        ids = list(dict.fromkeys(thread_ids))
        if not ids:
            return set()
        stmt = (
            select(RunRow.thread_id)
            .distinct()
            .select_from(RunRow)
            .outerjoin(
                ThreadReadMarkerRow,
                and_(ThreadReadMarkerRow.user_id == user_id, ThreadReadMarkerRow.thread_id == RunRow.thread_id),
            )
            .where(
                RunRow.thread_id.in_(ids),
                RunRow.user_id == user_id,
                RunRow.operation_kind == "run",
                RunRow.origin_kind.is_not(None),
                RunRow.change_seq > func.coalesce(ThreadReadMarkerRow.seen_change_seq, 0),
            )
        )
        async with self._sf() as session:
            return {str(thread_id) for thread_id in (await session.execute(stmt)).scalars()}

    async def read_version(self, *, user_id: str) -> int:
        """The user's read clock; 0 when they never marked anything read."""
        async with self._sf() as session:
            version = await session.scalar(select(ThreadReadVersionRow.version).where(ThreadReadVersionRow.user_id == user_id))
        return int(version or 0)

    async def delete_by_thread(self, thread_id: str) -> None:
        """Drop every user's marker for a deleted thread."""
        async with self._sf() as session:
            await session.execute(delete(ThreadReadMarkerRow).where(ThreadReadMarkerRow.thread_id == thread_id))
            await session.commit()
