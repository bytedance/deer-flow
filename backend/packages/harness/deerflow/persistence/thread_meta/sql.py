"""SQLAlchemy-backed thread metadata repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.thread_meta.base import ThreadMetaStore
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_owner_id


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
        owner_id: str | None | _AutoSentinel = AUTO,
        display_name: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        # Auto-resolve owner_id from contextvar when AUTO; explicit None
        # creates an orphan row (used by migration scripts).
        resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.create")
        now = datetime.now(UTC)
        row = ThreadMetaRow(
            thread_id=thread_id,
            assistant_id=assistant_id,
            owner_id=resolved_owner_id,
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

    async def get(
        self,
        thread_id: str,
        *,
        owner_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.get")
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return None
            # Enforce owner filter unless explicitly bypassed (owner_id=None).
            if resolved_owner_id is not None and row.owner_id != resolved_owner_id:
                return None
            return self._row_to_dict(row)

    async def list_by_owner(self, owner_id: str, *, limit: int = 100, offset: int = 0) -> list[dict]:
        stmt = select(ThreadMetaRow).where(ThreadMetaRow.owner_id == owner_id).order_by(ThreadMetaRow.updated_at.desc()).limit(limit).offset(offset)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def check_access(self, thread_id: str, owner_id: str, *, require_existing: bool = False) -> bool:
        """Check if ``owner_id`` has access to ``thread_id``.

        Two modes — one row, two distinct semantics depending on what
        the caller is about to do:

        - ``require_existing=False`` (default, permissive):
          Returns True for: row missing (untracked legacy thread),
          ``row.owner_id`` is None (shared / pre-auth data),
          or ``row.owner_id == owner_id``. Use for **read-style**
          decorators where treating an untracked thread as accessible
          preserves backward-compat.

        - ``require_existing=True`` (strict):
          Returns True **only** when the row exists AND
          (``row.owner_id == owner_id`` OR ``row.owner_id is None``).
          Use for **destructive / mutating** decorators (DELETE, PATCH,
          state-update) so a thread that has *already been deleted*
          cannot be re-targeted by any caller — closing the
          delete-idempotence cross-user gap where the row vanishing
          made every other user appear to "own" it.
        """
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return not require_existing
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
        owner_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict]:
        """Search threads with optional metadata and status filters.

        Owner filter is enforced by default: caller must be in a user
        context. Pass ``owner_id=None`` to bypass (migration/CLI).
        """
        resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.search")
        stmt = select(ThreadMetaRow).order_by(ThreadMetaRow.updated_at.desc())
        if resolved_owner_id is not None:
            stmt = stmt.where(ThreadMetaRow.owner_id == resolved_owner_id)
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

    async def _check_ownership(self, session: AsyncSession, thread_id: str, resolved_owner_id: str | None) -> bool:
        """Return True if the row exists and is owned (or filter bypassed)."""
        if resolved_owner_id is None:
            return True  # explicit bypass
        row = await session.get(ThreadMetaRow, thread_id)
        return row is not None and row.owner_id == resolved_owner_id

    async def update_display_name(
        self,
        thread_id: str,
        display_name: str,
        *,
        owner_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        """Update the display_name (title) for a thread."""
        resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.update_display_name")
        async with self._sf() as session:
            if not await self._check_ownership(session, thread_id, resolved_owner_id):
                return
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(display_name=display_name, updated_at=datetime.now(UTC)))
            await session.commit()

    async def update_status(
        self,
        thread_id: str,
        status: str,
        *,
        owner_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.update_status")
        async with self._sf() as session:
            if not await self._check_ownership(session, thread_id, resolved_owner_id):
                return
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(status=status, updated_at=datetime.now(UTC)))
            await session.commit()

    async def update_metadata(
        self,
        thread_id: str,
        metadata: dict,
        *,
        owner_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        """Merge ``metadata`` into ``metadata_json``.

        Read-modify-write inside a single session/transaction so concurrent
        callers see consistent state. No-op if the row does not exist or
        the owner_id check fails.
        """
        resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.update_metadata")
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return
            if resolved_owner_id is not None and row.owner_id != resolved_owner_id:
                return
            merged = dict(row.metadata_json or {})
            merged.update(metadata)
            row.metadata_json = merged
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def delete(
        self,
        thread_id: str,
        *,
        owner_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        resolved_owner_id = resolve_owner_id(owner_id, method_name="ThreadMetaRepository.delete")
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return
            if resolved_owner_id is not None and row.owner_id != resolved_owner_id:
                return
            await session.delete(row)
            await session.commit()
