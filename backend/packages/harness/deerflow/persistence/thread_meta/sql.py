"""SQLAlchemy-backed thread metadata repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.thread_meta.base import ThreadMetaStore
from deerflow.persistence.thread_meta.model import ThreadMetaRow


class ThreadMetaRepository(ThreadMetaStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ThreadMetaRow) -> dict[str, Any]:
        d = row.to_dict()
        d["metadata"] = d.pop("metadata_json", {})
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        owner_id: str | None = None,
        display_name: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        row = ThreadMetaRow(
            thread_id=thread_id,
            assistant_id=assistant_id,
            owner_id=owner_id,
            display_name=display_name,
            metadata_json=metadata or {},
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, thread_id: str) -> dict | None:
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            return self._row_to_dict(row) if row else None

    async def list_by_owner(self, owner_id: str, *, limit: int = 100, offset: int = 0) -> list[dict]:
        stmt = select(ThreadMetaRow).where(ThreadMetaRow.owner_id == owner_id).order_by(ThreadMetaRow.updated_at.desc()).limit(limit).offset(offset)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def check_access(self, thread_id: str, owner_id: str) -> bool:
        """Check if owner_id has access to thread_id.

        Returns True if: row doesn't exist (untracked thread), owner_id
        is None on the row (shared thread), or owner_id matches.
        """
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return True
            if row.owner_id is None:
                return True
            return row.owner_id == owner_id

    async def search(
        self,
        *,
        metadata: dict | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Search threads with optional metadata and status filters."""
        stmt = select(ThreadMetaRow).order_by(ThreadMetaRow.updated_at.desc())
        if status:
            stmt = stmt.where(ThreadMetaRow.status == status)

        if metadata:
            # When metadata filter is active, fetch a larger window and filter
            # in Python. TODO(Phase 2): use JSON DB operators (Postgres @>,
            # SQLite json_extract) for server-side filtering.
            stmt = stmt.limit(limit * 5 + offset)
            async with self._sf() as session:
                result = await session.execute(stmt)
                rows = [self._row_to_dict(r) for r in result.scalars()]
            rows = [r for r in rows if all(r.get("metadata", {}).get(k) == v for k, v in metadata.items())]
            return rows[offset : offset + limit]
        else:
            stmt = stmt.limit(limit).offset(offset)
            async with self._sf() as session:
                result = await session.execute(stmt)
                return [self._row_to_dict(r) for r in result.scalars()]

    async def update_display_name(self, thread_id: str, display_name: str) -> None:
        """Update the display_name (title) for a thread."""
        async with self._sf() as session:
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(display_name=display_name, updated_at=datetime.now(UTC)))
            await session.commit()

    async def update_status(self, thread_id: str, status: str) -> None:
        async with self._sf() as session:
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(status=status, updated_at=datetime.now(UTC)))
            await session.commit()

    async def update_metadata(self, thread_id: str, metadata: dict) -> None:
        """Merge ``metadata`` into ``metadata_json``.

        Read-modify-write inside a single session/transaction so concurrent
        callers see consistent state. No-op if the row does not exist.
        """
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return
            merged = dict(row.metadata_json or {})
            merged.update(metadata)
            row.metadata_json = merged
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def delete(self, thread_id: str) -> None:
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is not None:
                await session.delete(row)
                await session.commit()
