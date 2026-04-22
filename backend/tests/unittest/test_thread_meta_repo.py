"""Tests for current thread metadata storage adapters."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.storage import ThreadMetaStorage, ThreadMetaStoreAdapter
from deerflow.runtime.actor_context import ActorContext, bind_actor_context, reset_actor_context
from store.persistence import MappedBase


async def _make_store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, ThreadMetaStorage(ThreadMetaStoreAdapter(session_factory))


class TestThreadMetaStorage:
    @pytest.mark.anyio
    async def test_create_and_get(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        thread = await store.ensure_thread(thread_id="t1", user_id=None)
        assert thread.thread_id == "t1"
        assert thread.status == "idle"
        fetched = await store.get_thread("t1", user_id=None)
        assert fetched is not None
        assert fetched.thread_id == "t1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_with_assistant_id(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        thread = await store.ensure_thread(thread_id="t1", assistant_id="agent1", user_id=None)
        assert thread.assistant_id == "agent1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_with_owner(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        token = bind_actor_context(ActorContext(user_id="user1"))
        try:
            thread = await store.ensure_thread(thread_id="t1")
            assert thread.user_id == "user1"
        finally:
            reset_actor_context(token)
            await engine.dispose()

    @pytest.mark.anyio
    async def test_create_with_metadata(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        thread = await store.ensure_thread(thread_id="t1", metadata={"key": "value"}, user_id=None)
        assert thread.metadata == {"key": "value"}
        await engine.dispose()

    @pytest.mark.anyio
    async def test_ensure_thread_is_idempotent(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        try:
            first = await store.ensure_thread(thread_id="t1", user_id=None)
            second = await store.ensure_thread(thread_id="t1", user_id=None)
            assert second.thread_id == first.thread_id
            rows = await store.search_threads(user_id=None)
            assert [row.thread_id for row in rows] == ["t1"]
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_get_nonexistent(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        assert await store.get_thread("missing", user_id=None) is None
        await engine.dispose()

    @pytest.mark.anyio
    async def test_cross_user_get_is_filtered(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        token = bind_actor_context(ActorContext(user_id="user1"))
        try:
            await store.ensure_thread(thread_id="t1")
        finally:
            reset_actor_context(token)

        token = bind_actor_context(ActorContext(user_id="user2"))
        try:
            assert await store.get_thread("t1") is None
        finally:
            reset_actor_context(token)
            await engine.dispose()

    @pytest.mark.anyio
    async def test_shared_thread_visible_to_anyone_with_explicit_none(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        await store.ensure_thread(thread_id="t1", user_id=None)
        token = bind_actor_context(ActorContext(user_id="user2"))
        try:
            assert await store.get_thread("t1", user_id=None) is not None
        finally:
            reset_actor_context(token)
            await engine.dispose()

    @pytest.mark.anyio
    @pytest.mark.no_auto_user
    async def test_auto_user_id_requires_actor_context(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        try:
            await store.ensure_thread(thread_id="t1", user_id="alice")
            with pytest.raises(RuntimeError, match="no actor context is set"):
                await store.search_threads()
            with pytest.raises(RuntimeError, match="no actor context is set"):
                await store.get_thread("t1")
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_sync_thread_status(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        await store.ensure_thread(thread_id="t1", user_id=None)
        await store.sync_thread_status(thread_id="t1", status="busy")
        thread = await store.get_thread("t1", user_id=None)
        assert thread is not None
        assert thread.status == "busy"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_sync_thread_assistant_id(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        await store.ensure_thread(thread_id="t1", user_id=None)
        await store.sync_thread_assistant_id(thread_id="t1", assistant_id="lead_agent")
        thread = await store.get_thread("t1", user_id=None)
        assert thread is not None
        assert thread.assistant_id == "lead_agent"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_sync_thread_metadata_replaces(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        await store.ensure_thread(thread_id="t1", metadata={"a": 1}, user_id=None)
        await store.sync_thread_metadata(thread_id="t1", metadata={"b": 2})
        thread = await store.get_thread("t1", user_id=None)
        assert thread is not None
        assert thread.metadata == {"b": 2}
        await engine.dispose()

    @pytest.mark.anyio
    async def test_delete_thread(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        await store.ensure_thread(thread_id="t1", user_id=None)
        await store.delete_thread("t1")
        assert await store.get_thread("t1", user_id=None) is None
        await engine.dispose()

    @pytest.mark.anyio
    async def test_search_threads_filters_by_actor(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        token = bind_actor_context(ActorContext(user_id="user1"))
        try:
            await store.ensure_thread(thread_id="t1")
        finally:
            reset_actor_context(token)

        token = bind_actor_context(ActorContext(user_id="user2"))
        try:
            await store.ensure_thread(thread_id="t2")
        finally:
            reset_actor_context(token)

        token = bind_actor_context(ActorContext(user_id="user1"))
        try:
            rows = await store.search_threads()
            assert [row.thread_id for row in rows] == ["t1"]
        finally:
            reset_actor_context(token)
            await engine.dispose()

    @pytest.mark.anyio
    async def test_search_threads_strips_blank_filters(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        try:
            await store.ensure_thread(thread_id="t1", assistant_id="agent1", user_id=None)
            rows = await store.search_threads(status="   ", assistant_id="   ", user_id=None)
            assert [row.thread_id for row in rows] == ["t1"]
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_ensure_thread_running_creates_and_updates(self, tmp_path):
        engine, store = await _make_store(tmp_path)
        try:
            created = await store.ensure_thread_running(thread_id="t1", assistant_id="agent1", metadata={"a": 1})
            assert created is not None
            assert created.thread_id == "t1"
            assert created.status == "running"

            await store.sync_thread_status(thread_id="t1", status="idle")
            updated = await store.ensure_thread_running(thread_id="t1")
            assert updated is not None
            assert updated.status == "running"
        finally:
            await engine.dispose()
