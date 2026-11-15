"""In-memory ThreadMetaStore backed by LangGraph BaseStore.

Used when database.backend=memory. Delegates to the LangGraph Store's
``("threads",)`` namespace — the same namespace used by the Gateway
router for thread records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.store.base import BaseStore

from deerflow.persistence.json_compat import json_value_matches
from deerflow.persistence.thread_meta.base import (
    PROJECT_FILTER_UNSET,
    THREAD_ARCHIVED_METADATA_KEY,
    THREAD_INCOGNITO_ENDED_METADATA_KEY,
    THREAD_INCOGNITO_EXPIRED_STATUS,
    THREAD_PINNED_METADATA_KEY,
    ThreadMetaStore,
    ThreadOwnershipConflictError,
    _as_utc,
    _ProjectFilterUnset,
)
from deerflow.runtime.keyed_lock import AsyncKeyedLockTable
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id
from deerflow.utils.time import coerce_iso, now_iso

THREADS_NS: tuple[str, ...] = ("threads",)
SEARCH_PAGE_SIZE = 500


class MemoryThreadMetaStore(ThreadMetaStore):
    def __init__(self, store: BaseStore) -> None:
        self._store = store
        self._thread_locks = AsyncKeyedLockTable[str]()

    async def _get_owned_record(
        self,
        thread_id: str,
        user_id: str | None | _AutoSentinel,
        method_name: str,
    ) -> dict | None:
        """Fetch a record and verify ownership. Returns a mutable copy, or None."""
        resolved = resolve_user_id(user_id, method_name=method_name)
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return None
        record = dict(item.value)
        if resolved is not None and record.get("user_id") != resolved:
            return None
        return record

    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
        display_name: str | None = None,
        metadata: dict | None = None,
        project_id: str | None = None,
        incognito: bool = False,
        expires_at: datetime | None = None,
    ) -> dict:
        # Memory mode has no projects backend in Phase 1. Fail closed exactly
        # like the SQL store does for a missing/foreign/archived project: a
        # create carrying ``project_id`` raises ``ProjectNotAssignableError``
        # (the router maps it to 404) instead of silently persisting an
        # unassigned thread that a run would then proceed under. Mirrors
        # ``set_project`` below, which already reports rejection.
        if project_id is not None:
            from deerflow.persistence.projects import ProjectNotAssignableError

            raise ProjectNotAssignableError(project_id)
        resolved_user_id = resolve_user_id(user_id, method_name="MemoryThreadMetaStore.create")
        async with self._thread_locks.hold(thread_id):
            existing = await self._store.aget(THREADS_NS, thread_id)
            if existing is not None and resolved_user_id is not None and existing.value.get("user_id") != resolved_user_id:
                raise ThreadOwnershipConflictError(thread_id)
            now = now_iso()
            record: dict[str, Any] = {
                "thread_id": thread_id,
                "incarnation": (existing.value.get("incarnation") if existing is not None else None) or uuid.uuid4().hex,
                "assistant_id": assistant_id,
                "user_id": resolved_user_id,
                "display_name": display_name,
                "status": "idle",
                "metadata": metadata or {},
                "values": {},
                "incognito": incognito,
                "expires_at": coerce_iso(expires_at) if expires_at is not None else None,
                "created_at": now,
                "updated_at": now,
            }
            await self._store.aput(THREADS_NS, thread_id, record)
            return record

    async def claim_unowned(self, thread_id: str, owner: str) -> bool:
        async with self._thread_locks.hold(thread_id):
            item = await self._store.aget(THREADS_NS, thread_id)
            if item is None or item.value.get("user_id") is not None:
                return False
            record = dict(item.value)
            record["user_id"] = owner
            await self._store.aput(THREADS_NS, thread_id, record)
            return True

    async def set_project(self, thread_id: str, project_id: str | None, *, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        # Memory mode has no projects backend in Phase 1: membership moves
        # are unsupported and always report rejection.
        return False

    async def get(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        return await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.get")

    async def search(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        query: str | None = None,
        status: str | None = None,
        archived: bool | None = None,
        project_id: str | None | _ProjectFilterUnset = PROJECT_FILTER_UNSET,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Search threads by materializing matches, then sorting in Python.

        The memory backend loads all matching rows in chunks before slicing so
        it can mirror SQL's pinned-first ordering. Use the SQL store for
        scalable paginated I/O.
        """
        resolved_user_id = resolve_user_id(user_id, method_name="MemoryThreadMetaStore.search")
        if not isinstance(project_id, _ProjectFilterUnset) and project_id is not None:
            # Memory mode has no projects backend: no thread can be a member.
            return []
        filter_dict: dict[str, Any] = {}
        if status:
            filter_dict["status"] = status
        if resolved_user_id is not None:
            filter_dict["user_id"] = resolved_user_id

        items = []
        search_offset = 0
        while True:
            page = await self._store.asearch(
                THREADS_NS,
                filter=filter_dict or None,
                limit=SEARCH_PAGE_SIZE,
                offset=search_offset,
            )
            if not page:
                break
            items.extend(page)
            if len(page) < SEARCH_PAGE_SIZE:
                break
            search_offset += len(page)

        records = [record for record in (self._item_to_dict(item) for item in items) if record.get("incognito") is not True]
        if metadata:
            records = [record for record in records if isinstance(record.get("metadata"), dict) and all(json_value_matches(record["metadata"], key, value) for key, value in metadata.items())]
        if archived is not None:
            records = [record for record in records if ((record.get("metadata") or {}).get(THREAD_ARCHIVED_METADATA_KEY) is True) == archived]
        if query and query.strip():
            needle = query.strip().casefold()
            records = [record for record in records if needle in (record.get("display_name") or "").casefold()]
        records.sort(key=self._sort_key, reverse=True)
        return records[offset : offset + limit]

    async def check_access(self, thread_id: str, user_id: str, *, require_existing: bool = False) -> bool:
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return not require_existing
        value = item.value
        # An expired incognito thread resolves for nobody: the owner's view of
        # it ends when its deadline passes, even before the sweep purges data.
        if value.get("incognito") is True:
            deadline = _as_utc(value.get("expires_at"))
            if value.get("status") == THREAD_INCOGNITO_EXPIRED_STATUS or (deadline is not None and deadline <= datetime.now(UTC)):
                return False
        record_user_id = value.get("user_id")
        if record_user_id is None:
            return True
        return record_user_id == user_id

    async def update_display_name(
        self,
        thread_id: str,
        display_name: str,
        *,
        remove_metadata_keys: tuple[str, ...] = (),
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_display_name")
            if record is None:
                return
            record["display_name"] = display_name
            metadata = dict(record.get("metadata") or {})
            for key in remove_metadata_keys:
                metadata.pop(key, None)
            record["metadata"] = metadata
            record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def update_status(self, thread_id: str, status: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_status")
            if record is None:
                return
            record["status"] = status
            record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def update_metadata(self, thread_id: str, metadata: dict, *, touch: bool = True, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_metadata")
            if record is None:
                return
            merged = dict(record.get("metadata") or {})
            merged.update(metadata)
            record["metadata"] = merged
            if touch:
                record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def update_owner(self, thread_id: str, owner_user_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.update_owner")
            if record is None:
                return
            record["user_id"] = owner_user_id
            record["updated_at"] = now_iso()
            await self._store.aput(THREADS_NS, thread_id, record)

    async def delete(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.delete")
            if record is None:
                return
            await self._store.adelete(THREADS_NS, thread_id)

    # ------------------------------------------------------------------
    # Incognito lifetime
    # ------------------------------------------------------------------

    async def _all_records(self) -> list[dict[str, Any]]:
        """Page the whole thread namespace; the sweep runs unscoped."""
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self._store.asearch(THREADS_NS, limit=SEARCH_PAGE_SIZE, offset=offset)
            if not page:
                break
            records.extend(self._item_to_dict(item) for item in page)
            if len(page) < SEARCH_PAGE_SIZE:
                break
            offset += len(page)
        return records

    async def list_due_incognito(self, *, now: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
        moment = now or datetime.now(UTC)
        due = []
        for record in await self._all_records():
            if record.get("incognito") is not True:
                continue
            deadline = _as_utc(record.get("expires_at"))
            if deadline is not None and deadline <= moment:
                due.append(record)
        due.sort(key=lambda record: str(record.get("expires_at") or ""))
        return due[:limit]

    async def renew_incognito(
        self,
        thread_id: str,
        *,
        idle_ttl: timedelta,
        max_lifetime: timedelta,
        now: datetime | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        moment = now or datetime.now(UTC)
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.renew_incognito")
            if record is None or record.get("incognito") is not True or record.get("status") == THREAD_INCOGNITO_EXPIRED_STATUS:
                return False
            if (record.get("metadata") or {}).get(THREAD_INCOGNITO_ENDED_METADATA_KEY) is True:
                return False
            created = _as_utc(record.get("created_at")) or moment
            record["expires_at"] = coerce_iso(min(moment + idle_ttl, created + max_lifetime))
            await self._store.aput(THREADS_NS, thread_id, record)
            return True

    async def end_incognito(self, thread_id: str, *, grace: timedelta, now: datetime | None = None, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        moment = now or datetime.now(UTC)
        async with self._thread_locks.hold(thread_id):
            record = await self._get_owned_record(thread_id, user_id, "MemoryThreadMetaStore.end_incognito")
            if record is None or record.get("incognito") is not True or record.get("status") == THREAD_INCOGNITO_EXPIRED_STATUS:
                return False
            metadata = dict(record.get("metadata") or {})
            metadata[THREAD_INCOGNITO_ENDED_METADATA_KEY] = True
            record["metadata"] = metadata
            record["expires_at"] = coerce_iso(moment + grace)
            await self._store.aput(THREADS_NS, thread_id, record)
            return True

    async def begin_incognito_expiry(self, thread_id: str) -> bool:
        async with self._thread_locks.hold(thread_id):
            item = await self._store.aget(THREADS_NS, thread_id)
            if item is None or item.value.get("incognito") is not True:
                return False
            record = dict(item.value)
            record["status"] = THREAD_INCOGNITO_EXPIRED_STATUS
            record["display_name"] = None
            record["metadata"] = {}
            await self._store.aput(THREADS_NS, thread_id, record)
            return True

    async def finish_incognito_expiry(self, thread_id: str) -> None:
        async with self._thread_locks.hold(thread_id):
            item = await self._store.aget(THREADS_NS, thread_id)
            if item is None:
                return
            record = dict(item.value)
            record["expires_at"] = None
            await self._store.aput(THREADS_NS, thread_id, record)

    @staticmethod
    def _item_to_dict(item) -> dict[str, Any]:
        """Convert a Store SearchItem to the dict format expected by callers."""
        val = item.value
        return {
            "thread_id": item.key,
            "incarnation": val.get("incarnation"),
            "assistant_id": val.get("assistant_id"),
            "user_id": val.get("user_id"),
            "display_name": val.get("display_name"),
            "status": val.get("status", "idle"),
            "metadata": val.get("metadata", {}),
            "incognito": val.get("incognito") is True,
            "expires_at": val.get("expires_at"),
            # ``coerce_iso`` heals legacy unix-second values written by
            # earlier Gateway versions that called ``str(time.time())``.
            "created_at": coerce_iso(val.get("created_at", "")),
            "updated_at": coerce_iso(val.get("updated_at", "")),
        }

    @staticmethod
    def _sort_key(record: dict[str, Any]) -> tuple[bool, str, str]:
        metadata = record.get("metadata")
        pinned = isinstance(metadata, dict) and metadata.get(THREAD_PINNED_METADATA_KEY) is True
        return (pinned, str(record.get("updated_at") or ""), str(record.get("thread_id") or ""))
