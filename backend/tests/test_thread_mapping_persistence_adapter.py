"""Tests for PersistenceThreadMappingStore backed by ThreadMetaRepository."""

from __future__ import annotations

import pytest

from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.runtime.thread_mapping.stores.persistence_adapter import PersistenceThreadMappingStore


async def _make_adapter(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'thread_mapping_adapter.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    repo = ThreadMetaRepository(get_session_factory())
    return PersistenceThreadMappingStore(repo)


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


class TestPersistenceThreadMappingStore:
    @pytest.mark.anyio
    async def test_aput_and_aget_roundtrip(self, tmp_path):
        store = await _make_adapter(tmp_path)
        try:
            await store.aput(("user_threads", "alice"), "thread-1", {"title": "Alpha", "status": "idle", "kind": "chat"})

            item = await store.aget(("user_threads", "alice"), "thread-1")
            assert item is not None
            assert item.key == "thread-1"
            assert item.value["title"] == "Alpha"
            assert item.value["status"] == "idle"
            assert item.value["kind"] == "chat"
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_asearch_is_user_isolated(self, tmp_path):
        store = await _make_adapter(tmp_path)
        try:
            await store.aput(("user_threads", "alice"), "thread-a", {"title": "Alice thread", "status": "idle"})
            await store.aput(("user_threads", "bob"), "thread-b", {"title": "Bob thread", "status": "busy"})

            rows = await store.asearch(("user_threads", "alice"), limit=10)
            assert [r.key for r in rows] == ["thread-a"]
            assert rows[0].value["title"] == "Alice thread"
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_asearch_supports_status_and_metadata_filter(self, tmp_path):
        store = await _make_adapter(tmp_path)
        try:
            await store.aput(("user_threads", "alice"), "thread-a", {"title": "A", "status": "idle", "kind": "chat"})
            await store.aput(("user_threads", "alice"), "thread-b", {"title": "B", "status": "busy", "kind": "task"})

            rows = await store.asearch(("user_threads", "alice"), filter={"status": "busy", "kind": "task"}, limit=10)
            assert [r.key for r in rows] == ["thread-b"]
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_adelete_removes_mapping(self, tmp_path):
        store = await _make_adapter(tmp_path)
        try:
            await store.aput(("user_threads", "alice"), "thread-1", {"title": "Alpha"})
            assert await store.aget(("user_threads", "alice"), "thread-1") is not None

            await store.adelete(("user_threads", "alice"), "thread-1")
            assert await store.aget(("user_threads", "alice"), "thread-1") is None
        finally:
            await _cleanup()
