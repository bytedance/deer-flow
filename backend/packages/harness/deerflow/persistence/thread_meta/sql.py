"""SQLAlchemy-backed thread metadata repository."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from deerflow.persistence.json_compat import json_match
from deerflow.persistence.thread_meta.base import THREAD_PINNED_METADATA_KEY, InvalidMetadataFilterError, ThreadMetaStore
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_iso

logger = logging.getLogger(__name__)


class ThreadMetaRepository(ThreadMetaStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ThreadMetaRow) -> dict[str, Any]:
        d = row.to_dict()
        d["metadata"] = d.pop("metadata_json", None) or {}
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                # SQLite drops tzinfo despite ``DateTime(timezone=True)``;
                # ``coerce_iso`` normalizes naive values as UTC so the wire format always carries tz.
                d[key] = coerce_iso(val)
        return d

    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
        display_name: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        # Auto-resolve user_id from contextvar when AUTO; explicit None
        # creates an orphan row (used by migration scripts).
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.create")
        now = datetime.now(UTC)
        row = ThreadMetaRow(
            thread_id=thread_id,
            assistant_id=assistant_id,
            user_id=resolved_user_id,
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
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> dict | None:
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.get")
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return None
            # Enforce owner filter unless explicitly bypassed (user_id=None).
            if resolved_user_id is not None and row.user_id != resolved_user_id:
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
        async with self._sf() as session:
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
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Search threads with optional metadata and status filters.

        Owner filter is enforced by default: caller must be in a user
        context. Pass ``user_id=None`` to bypass (migration/CLI).
        """
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.search")
        pinned_order = case(
            (json_match(ThreadMetaRow.metadata_json, THREAD_PINNED_METADATA_KEY, True), 1),
            else_=0,
        )
        stmt = select(ThreadMetaRow).order_by(
            pinned_order.desc(),
            ThreadMetaRow.updated_at.desc(),
            ThreadMetaRow.thread_id.desc(),
        )
        if resolved_user_id is not None:
            stmt = stmt.where(ThreadMetaRow.user_id == resolved_user_id)
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

        stmt = stmt.limit(limit).offset(offset)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def _check_ownership(self, session: AsyncSession, thread_id: str, resolved_user_id: str | None) -> bool:
        """Return True if the row exists and is owned (or filter bypassed)."""
        if resolved_user_id is None:
            return True  # explicit bypass
        row = await session.get(ThreadMetaRow, thread_id)
        return row is not None and row.user_id == resolved_user_id

    async def update_display_name(
        self,
        thread_id: str,
        display_name: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        """Update the display_name (title) for a thread."""
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.update_display_name")
        async with self._sf() as session:
            if not await self._check_ownership(session, thread_id, resolved_user_id):
                return
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(display_name=display_name, updated_at=datetime.now(UTC)))
            await session.commit()

    async def update_status(
        self,
        thread_id: str,
        status: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.update_status")
        async with self._sf() as session:
            if not await self._check_ownership(session, thread_id, resolved_user_id):
                return
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(status=status, updated_at=datetime.now(UTC)))
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
        async with self._sf() as session:
            if session.get_bind().dialect.name == "sqlite":
                # A deferred SQLite transaction does not reserve the writer
                # until the UPDATE, which is too late for a read-modify-write
                # merge. BEGIN IMMEDIATE serializes writers before the read,
                # including writers in other processes using the same file.
                await session.execute(text("BEGIN IMMEDIATE"))
                row = await session.get(ThreadMetaRow, thread_id)
            else:
                result = await session.execute(select(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).with_for_update())
                row = result.scalar_one_or_none()
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
        async with self._sf() as session:
            if not await self._check_ownership(session, thread_id, resolved_user_id):
                return
            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == thread_id).values(user_id=owner_user_id, updated_at=datetime.now(UTC)))
            await session.commit()

    async def delete(
        self,
        thread_id: str,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        resolved_user_id = resolve_user_id(user_id, method_name="ThreadMetaRepository.delete")
        async with self._sf() as session:
            row = await session.get(ThreadMetaRow, thread_id)
            if row is None:
                return
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return
            await session.delete(row)
            await session.commit()
