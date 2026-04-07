"""Tests for FeedbackRepository and follow-up association.

Uses temp SQLite DB for ORM tests.
"""

import pytest

from deerflow.persistence.feedback import FeedbackRepository


async def _make_feedback_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return FeedbackRepository(get_session_factory())


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


# -- FeedbackRepository --


class TestFeedbackRepository:
    @pytest.mark.anyio
    async def test_create_positive(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1)
        assert record["feedback_id"]
        assert record["rating"] == 1
        assert record["run_id"] == "r1"
        assert record["thread_id"] == "t1"
        assert "created_at" in record
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_negative_with_comment(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(
            run_id="r1",
            thread_id="t1",
            rating=-1,
            comment="Response was inaccurate",
        )
        assert record["rating"] == -1
        assert record["comment"] == "Response was inaccurate"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_message_id(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1, message_id="msg-42")
        assert record["message_id"] == "msg-42"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_owner(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        record = await repo.create(run_id="r1", thread_id="t1", rating=1, owner_id="user-1")
        assert record["owner_id"] == "user-1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_invalid_rating_zero(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.create(run_id="r1", thread_id="t1", rating=0)
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_invalid_rating_five(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        with pytest.raises(ValueError):
            await repo.create(run_id="r1", thread_id="t1", rating=5)
        await _cleanup()

    @pytest.mark.anyio
    async def test_get(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        created = await repo.create(run_id="r1", thread_id="t1", rating=1)
        fetched = await repo.get(created["feedback_id"])
        assert fetched is not None
        assert fetched["feedback_id"] == created["feedback_id"]
        assert fetched["rating"] == 1
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_nonexistent(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        assert await repo.get("nonexistent") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_run(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1)
        await repo.create(run_id="r1", thread_id="t1", rating=-1)
        await repo.create(run_id="r2", thread_id="t1", rating=1)
        results = await repo.list_by_run("t1", "r1")
        assert len(results) == 2
        assert all(r["run_id"] == "r1" for r in results)
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1)
        await repo.create(run_id="r2", thread_id="t1", rating=-1)
        await repo.create(run_id="r3", thread_id="t2", rating=1)
        results = await repo.list_by_thread("t1")
        assert len(results) == 2
        assert all(r["thread_id"] == "t1" for r in results)
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        created = await repo.create(run_id="r1", thread_id="t1", rating=1)
        deleted = await repo.delete(created["feedback_id"])
        assert deleted is True
        assert await repo.get(created["feedback_id"]) is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_nonexistent(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        deleted = await repo.delete("nonexistent")
        assert deleted is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_by_run(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        await repo.create(run_id="r1", thread_id="t1", rating=1)
        await repo.create(run_id="r1", thread_id="t1", rating=1)
        await repo.create(run_id="r1", thread_id="t1", rating=-1)
        stats = await repo.aggregate_by_run("t1", "r1")
        assert stats["total"] == 3
        assert stats["positive"] == 2
        assert stats["negative"] == 1
        assert stats["run_id"] == "r1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_empty(self, tmp_path):
        repo = await _make_feedback_repo(tmp_path)
        stats = await repo.aggregate_by_run("t1", "r1")
        assert stats["total"] == 0
        assert stats["positive"] == 0
        assert stats["negative"] == 0
        await _cleanup()


# -- Follow-up association --


class TestFollowUpAssociation:
    @pytest.mark.anyio
    async def test_run_records_follow_up_via_memory_store(self):
        """MemoryRunStore stores follow_up_to_run_id in kwargs."""
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        await store.put("r1", thread_id="t1", status="success")
        # MemoryRunStore doesn't have follow_up_to_run_id as a top-level param,
        # but it can be passed via metadata
        await store.put("r2", thread_id="t1", metadata={"follow_up_to_run_id": "r1"})
        run = await store.get("r2")
        assert run["metadata"]["follow_up_to_run_id"] == "r1"

    @pytest.mark.anyio
    async def test_human_message_has_follow_up_metadata(self):
        """human_message event metadata includes follow_up_to_run_id."""
        from deerflow.runtime.events.store.memory import MemoryRunEventStore

        event_store = MemoryRunEventStore()
        await event_store.put(
            thread_id="t1",
            run_id="r2",
            event_type="human_message",
            category="message",
            content="Tell me more about that",
            metadata={"follow_up_to_run_id": "r1"},
        )
        messages = await event_store.list_messages("t1")
        assert messages[0]["metadata"]["follow_up_to_run_id"] == "r1"

    @pytest.mark.anyio
    async def test_follow_up_auto_detection_logic(self):
        """Simulate the auto-detection: latest successful run becomes follow_up_to."""
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        store = MemoryRunStore()
        await store.put("r1", thread_id="t1", status="success")
        await store.put("r2", thread_id="t1", status="error")

        # Auto-detect: list_by_thread returns newest first
        recent = await store.list_by_thread("t1", limit=1)
        follow_up = None
        if recent and recent[0].get("status") == "success":
            follow_up = recent[0]["run_id"]
        # r2 (error) is newest, so no follow_up detected
        assert follow_up is None

        # Now add a successful run
        await store.put("r3", thread_id="t1", status="success")
        recent = await store.list_by_thread("t1", limit=1)
        follow_up = None
        if recent and recent[0].get("status") == "success":
            follow_up = recent[0]["run_id"]
        assert follow_up == "r3"
