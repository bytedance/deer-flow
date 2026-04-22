"""Tests for current feedback storage adapters and follow-up association."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.storage import AppRunEventStore, FeedbackStoreAdapter, RunStoreAdapter
from store.persistence import MappedBase


async def _make_feedback_repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    class _FeedbackRepoCompat:
        def __init__(self, session_factory):
            self._repo = FeedbackStoreAdapter(session_factory)

        async def create(self, **kwargs):
            return await self._repo.create(
                run_id=kwargs["run_id"],
                thread_id=kwargs["thread_id"],
                rating=kwargs["rating"],
                owner_id=kwargs.get("owner_id"),
                user_id=kwargs.get("user_id"),
                message_id=kwargs.get("message_id"),
                comment=kwargs.get("comment"),
            )

        async def get(self, feedback_id):
            return await self._repo.get(feedback_id)

        async def list_by_run(self, thread_id, run_id, user_id=None, limit=100):
            rows = await self._repo.list_by_run(thread_id, run_id, user_id=user_id, limit=limit)
            return rows

        async def list_by_thread(self, thread_id, limit=100):
            return await self._repo.list_by_thread(thread_id, limit=limit)

        async def delete(self, feedback_id):
            return await self._repo.delete(feedback_id)

        async def aggregate_by_run(self, thread_id, run_id):
            return await self._repo.aggregate_by_run(thread_id, run_id)

        async def upsert(self, **kwargs):
            return await self._repo.upsert(
                run_id=kwargs["run_id"],
                thread_id=kwargs["thread_id"],
                rating=kwargs["rating"],
                user_id=kwargs.get("user_id"),
                comment=kwargs.get("comment"),
            )

        async def delete_by_run(self, *, thread_id, run_id, user_id):
            return await self._repo.delete_by_run(thread_id=thread_id, run_id=run_id, user_id=user_id)

        async def list_by_thread_grouped(self, thread_id, user_id):
            return await self._repo.list_by_thread_grouped(thread_id, user_id=user_id)

    return engine, session_factory, _FeedbackRepoCompat(session_factory)


# -- FeedbackRepository --


class TestFeedbackRepository:
    @pytest.mark.anyio
    async def test_create_positive(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1)
        assert record["feedback_id"]
        assert record["rating"] == 1
        assert record["run_id"] == "r1"
        assert record["thread_id"] == "t1"
        assert "created_at" in record
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_negative_with_comment(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(
            run_id="r1",
            thread_id="t1",
            rating=-1,
            comment="Response was inaccurate",
        )
        assert record["rating"] == -1
        assert record["comment"] == "Response was inaccurate"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_with_message_id(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1, message_id="msg-42")
        assert record["message_id"] == "msg-42"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_with_owner(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-1")
        assert record["user_id"] == "user-1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_uses_owner_id_fallback(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1, owner_id="owner-1")
        assert record["user_id"] == "owner-1"
        assert record["owner_id"] == "owner-1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_invalid_rating_zero(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.create(run_id="r1", thread_id="t1", rating=0)
        await engine.dispose()

    @pytest.mark.anyio
    async def test_create_invalid_rating_five(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.create(run_id="r1", thread_id="t1", rating=5)
        await engine.dispose()

    @pytest.mark.anyio
    async def test_get(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        created = await repo.create(run_id="r1", thread_id="t1", rating=1)
        fetched = await repo.get(created["feedback_id"])
        assert fetched is not None
        assert fetched["feedback_id"] == created["feedback_id"]
        assert fetched["rating"] == 1
        await engine.dispose()

    @pytest.mark.anyio
    async def test_get_nonexistent(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        assert await repo.get("nonexistent") is None
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_run(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-1")
        await repo.create(run_id="r1", thread_id="t1", rating=-1, user_id="user-2")
        await repo.create(run_id="r2", thread_id="t1", rating=1, user_id="user-1")
        results = await repo.list_by_run("t1", "r1", user_id=None)
        assert len(results) == 2
        assert all(r["run_id"] == "r1" for r in results)
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_run_filters_thread_even_with_same_run_id(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-1")
        await repo.create(run_id="r1", thread_id="t2", rating=-1, user_id="user-2")
        results = await repo.list_by_run("t1", "r1", user_id=None)
        assert len(results) == 1
        assert results[0]["thread_id"] == "t1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_run_respects_limit(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        await repo.create(run_id="r1", thread_id="t1", rating=-1, user_id="u2")
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="u3")
        results = await repo.list_by_run("t1", "r1", user_id=None, limit=2)
        assert len(results) == 2
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1)
        await repo.create(run_id="r2", thread_id="t1", rating=-1)
        await repo.create(run_id="r3", thread_id="t2", rating=1)
        results = await repo.list_by_thread("t1")
        assert len(results) == 2
        assert all(r["thread_id"] == "t1" for r in results)
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread_respects_limit(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1)
        await repo.create(run_id="r2", thread_id="t1", rating=-1)
        await repo.create(run_id="r3", thread_id="t1", rating=1)
        results = await repo.list_by_thread("t1", limit=2)
        assert len(results) == 2
        await engine.dispose()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        created = await repo.create(run_id="r1", thread_id="t1", rating=1)
        deleted = await repo.delete(created["feedback_id"])
        assert deleted is True
        assert await repo.get(created["feedback_id"]) is None
        await engine.dispose()

    @pytest.mark.anyio
    async def test_delete_nonexistent(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        deleted = await repo.delete("nonexistent")
        assert deleted is False
        await engine.dispose()

    @pytest.mark.anyio
    async def test_aggregate_by_run(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-1")
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="user-2")
        await repo.create(run_id="r1", thread_id="t1", rating=-1, user_id="user-3")
        stats = await repo.aggregate_by_run("t1", "r1")
        assert stats["total"] == 3
        assert stats["positive"] == 2
        assert stats["negative"] == 1
        assert stats["run_id"] == "r1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_aggregate_empty(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        stats = await repo.aggregate_by_run("t1", "r1")
        assert stats["total"] == 0
        assert stats["positive"] == 0
        assert stats["negative"] == 0
        await engine.dispose()

    @pytest.mark.anyio
    async def test_upsert_creates_new(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        record = await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        assert record["rating"] == 1
        assert record["feedback_id"]
        assert record["user_id"] == "u1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_upsert_updates_existing(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        first = await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        second = await repo.upsert(run_id="r1", thread_id="t1", rating=-1, user_id="u1", comment="changed my mind")
        assert second["feedback_id"] == first["feedback_id"]
        assert second["rating"] == -1
        assert second["comment"] == "changed my mind"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_upsert_different_users_separate(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        r1 = await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        r2 = await repo.upsert(run_id="r1", thread_id="t1", rating=-1, user_id="u2")
        assert r1["feedback_id"] != r2["feedback_id"]
        assert r1["rating"] == 1
        assert r2["rating"] == -1
        await engine.dispose()

    @pytest.mark.anyio
    async def test_upsert_invalid_rating(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.upsert(run_id="r1", thread_id="t1", rating=0, user_id="u1")
        await engine.dispose()

    @pytest.mark.anyio
    async def test_delete_by_run(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        deleted = await repo.delete_by_run(thread_id="t1", run_id="r1", user_id="u1")
        assert deleted is True
        results = await repo.list_by_run("t1", "r1", user_id="u1")
        assert len(results) == 0
        await engine.dispose()

    @pytest.mark.anyio
    async def test_delete_by_run_nonexistent(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        deleted = await repo.delete_by_run(thread_id="t1", run_id="r1", user_id="u1")
        assert deleted is False
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread_grouped(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.upsert(run_id="r1", thread_id="t1", rating=1, user_id="u1")
        await repo.upsert(run_id="r2", thread_id="t1", rating=-1, user_id="u1")
        await repo.upsert(run_id="r3", thread_id="t2", rating=1, user_id="u1")
        grouped = await repo.list_by_thread_grouped("t1", user_id="u1")
        assert "r1" in grouped
        assert "r2" in grouped
        assert "r3" not in grouped
        assert grouped["r1"]["rating"] == 1
        assert grouped["r2"]["rating"] == -1
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread_grouped_filters_by_user_when_same_run_id_exists(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1, user_id="u1", comment="mine")
        await repo.create(run_id="r1", thread_id="t1", rating=-1, user_id="u2", comment="other")
        grouped = await repo.list_by_thread_grouped("t1", user_id="u1")
        assert grouped["r1"]["user_id"] == "u1"
        assert grouped["r1"]["comment"] == "mine"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_list_by_thread_grouped_empty(self, tmp_path):
        engine, _, repo = await _make_feedback_repo(tmp_path)
        grouped = await repo.list_by_thread_grouped("t1", user_id="u1")
        assert grouped == {}
        await engine.dispose()


# -- Follow-up association --


class TestFollowUpAssociation:
    @pytest.mark.anyio
    async def test_run_records_follow_up_via_memory_store(self):
        """RunStoreAdapter persists follow_up_to_run_id as a first-class field."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(MappedBase.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        store = RunStoreAdapter(session_factory)
        await store.create("r1", thread_id="t1", status="success")
        await store.create("r2", thread_id="t1", follow_up_to_run_id="r1")
        run = await store.get("r2")
        assert run is not None
        assert run["follow_up_to_run_id"] == "r1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_human_message_has_follow_up_metadata(self):
        """AppRunEventStore preserves follow_up_to_run_id in message metadata."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(MappedBase.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        event_store = AppRunEventStore(session_factory)
        await event_store.put_batch([
            {
                "thread_id": "t1",
                "run_id": "r2",
                "event_type": "human_message",
                "category": "message",
                "content": "Tell me more about that",
                "metadata": {"follow_up_to_run_id": "r1"},
            }
        ])
        messages = await event_store.list_messages("t1")
        assert messages[0]["metadata"]["follow_up_to_run_id"] == "r1"
        await engine.dispose()

    @pytest.mark.anyio
    async def test_follow_up_auto_detection_logic(self):
        """Simulate the auto-detection: latest successful run becomes follow_up_to."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(MappedBase.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        store = RunStoreAdapter(session_factory)
        await store.create("r1", thread_id="t1", status="success")
        await store.create("r2", thread_id="t1", status="error")

        # Auto-detect: list_by_thread returns newest first
        recent = await store.list_by_thread("t1", limit=1)
        follow_up = None
        if recent and recent[0].get("status") == "success":
            follow_up = recent[0]["run_id"]
        # r2 (error) is newest, so no follow_up detected
        assert follow_up is None

        # Now add a successful run
        await store.create("r3", thread_id="t1", status="success")
        recent = await store.list_by_thread("t1", limit=1)
        follow_up = None
        if recent and recent[0].get("status") == "success":
            follow_up = recent[0]["run_id"]
        assert follow_up == "r3"
        await engine.dispose()
