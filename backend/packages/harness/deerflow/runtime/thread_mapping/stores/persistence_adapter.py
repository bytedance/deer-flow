"""Thread-mapping adapter backed by official persistence.thread_meta."""

from __future__ import annotations

import time
from typing import Any

from deerflow.persistence.thread_meta.base import ThreadMetaStore
from deerflow.runtime.thread_mapping.ns import parse_user_threads_namespace, user_id_from_search_prefix
from deerflow.runtime.thread_mapping.types import ThreadMappingItem, ThreadMappingStore


def _to_mapping_value(record: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    value = dict(metadata)
    display_name = record.get("display_name")
    if display_name:
        value.setdefault("title", display_name)
    status = record.get("status")
    if status:
        value.setdefault("status", status)
    updated_at = record.get("updated_at")
    if updated_at:
        value.setdefault("updated_at", updated_at)
    return value


class PersistenceThreadMappingStore(ThreadMappingStore):
    """Expose ``ThreadMetaStore`` through the legacy thread-mapping KV interface."""

    __slots__ = ("_thread_store",)

    def __init__(self, thread_store: ThreadMetaStore) -> None:
        self._thread_store = thread_store

    async def aget(
        self,
        namespace: tuple[str, ...],
        key: str,
        *,
        refresh_ttl: bool | None = None,
    ) -> ThreadMappingItem | None:
        _ = refresh_ttl
        uid, tid = parse_user_threads_namespace(namespace, key)
        record = await self._thread_store.get(tid, user_id=uid)
        if record is None:
            return None
        return ThreadMappingItem(tid, _to_mapping_value(record))

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Any = None,
    ) -> None:
        _ = index
        uid, tid = parse_user_threads_namespace(namespace, key)
        existing = await self._thread_store.get(tid, user_id=uid)
        title = value.get("title")
        status = value.get("status")
        metadata = dict(value)
        metadata.pop("title", None)
        metadata.pop("status", None)
        metadata.setdefault("updated_at", value.get("updated_at") or time.time())

        if existing is None:
            await self._thread_store.create(
                tid,
                user_id=uid,
                display_name=str(title).strip() if title is not None else None,
                metadata=metadata,
            )
            if status is not None:
                await self._thread_store.update_status(tid, str(status), user_id=uid)
            return

        if title is not None:
            await self._thread_store.update_display_name(tid, str(title), user_id=uid)
        if status is not None:
            await self._thread_store.update_status(tid, str(status), user_id=uid)
        await self._thread_store.update_metadata(tid, metadata, user_id=uid)

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[ThreadMappingItem]:
        _ = query, refresh_ttl
        uid = user_id_from_search_prefix(namespace_prefix)
        status = None
        metadata_filter = dict(filter or {})
        if "status" in metadata_filter:
            status = str(metadata_filter.pop("status"))
        records = await self._thread_store.search(
            metadata=metadata_filter or None,
            status=status,
            limit=limit,
            offset=offset,
            user_id=uid,
        )
        return [ThreadMappingItem(str(r["thread_id"]), _to_mapping_value(r)) for r in records]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        uid, tid = parse_user_threads_namespace(namespace, key)
        await self._thread_store.delete(tid, user_id=uid)
