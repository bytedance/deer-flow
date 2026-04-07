"""In-memory ThreadMetaStore backed by LangGraph BaseStore.

Used when database.backend=memory. Delegates to the LangGraph Store's
``("threads",)`` namespace — the same namespace used by the Gateway
router for thread records.
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.store.base import BaseStore

from deerflow.persistence.thread_meta.base import ThreadMetaStore

THREADS_NS: tuple[str, ...] = ("threads",)


class MemoryThreadMetaStore(ThreadMetaStore):
    def __init__(self, store: BaseStore) -> None:
        self._store = store

    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        owner_id: str | None = None,
        display_name: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        now = time.time()
        record: dict[str, Any] = {
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "owner_id": owner_id,
            "display_name": display_name,
            "status": "idle",
            "metadata": metadata or {},
            "values": {},
            "created_at": now,
            "updated_at": now,
        }
        await self._store.aput(THREADS_NS, thread_id, record)
        return record

    async def get(self, thread_id: str) -> dict | None:
        item = await self._store.aget(THREADS_NS, thread_id)
        return item.value if item is not None else None

    async def search(
        self,
        *,
        metadata: dict | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        filter_dict: dict[str, Any] = {}
        if metadata:
            filter_dict.update(metadata)
        if status:
            filter_dict["status"] = status

        items = await self._store.asearch(
            THREADS_NS,
            filter=filter_dict or None,
            limit=limit,
            offset=offset,
        )
        return [self._item_to_dict(item) for item in items]

    async def update_display_name(self, thread_id: str, display_name: str) -> None:
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return
        record = dict(item.value)
        record["display_name"] = display_name
        record["updated_at"] = time.time()
        await self._store.aput(THREADS_NS, thread_id, record)

    async def update_status(self, thread_id: str, status: str) -> None:
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return
        record = dict(item.value)
        record["status"] = status
        record["updated_at"] = time.time()
        await self._store.aput(THREADS_NS, thread_id, record)

    async def update_metadata(self, thread_id: str, metadata: dict) -> None:
        """Merge ``metadata`` into the in-memory record. No-op if absent."""
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return
        record = dict(item.value)
        merged = dict(record.get("metadata") or {})
        merged.update(metadata)
        record["metadata"] = merged
        record["updated_at"] = time.time()
        await self._store.aput(THREADS_NS, thread_id, record)

    async def delete(self, thread_id: str) -> None:
        await self._store.adelete(THREADS_NS, thread_id)

    @staticmethod
    def _item_to_dict(item) -> dict[str, Any]:
        """Convert a Store SearchItem to the dict format expected by callers."""
        val = item.value
        return {
            "thread_id": item.key,
            "assistant_id": val.get("assistant_id"),
            "owner_id": val.get("owner_id"),
            "display_name": val.get("display_name"),
            "status": val.get("status", "idle"),
            "metadata": val.get("metadata", {}),
            "created_at": str(val.get("created_at", "")),
            "updated_at": str(val.get("updated_at", "")),
        }
