"""Contract tests for the FeedbackRepository port.

Every implementation (SQL adapter, in-memory fake) runs the same suite, so
port semantics and implementations cannot drift apart. The in-memory fake
lives in ``feedback_fakes`` because service-level tests reuse it as a fast
zero-IO double.
"""

import pytest
from feedback_fakes import InMemoryFeedbackRepository

from deerflow.domain.feedback import Feedback
from deerflow.domain.feedback.ports import FeedbackRepository


class FeedbackRepositoryContract:
    """Shared port-semantics suite; subclasses provide a ``repo`` fixture."""

    @pytest.mark.anyio
    async def test_satisfies_port(self, repo):
        assert isinstance(repo, FeedbackRepository)

    @pytest.mark.anyio
    async def test_save_creates(self, repo):
        fb = await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=1, user_id="u1"))
        assert fb.feedback_id
        assert fb.rating == 1
        assert fb.created_at.tzinfo is not None

    @pytest.mark.anyio
    async def test_save_updates_keeping_identity(self, repo):
        first = await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=1, user_id="u1"))
        second = await repo.save(
            Feedback.create(
                run_id="r1",
                thread_id="t1",
                rating=-1,
                user_id="u1",
                comment="changed my mind",
                tags=["incorrect", "slow"],
            )
        )
        assert second.feedback_id == first.feedback_id
        assert second.rating == -1
        assert second.comment == "changed my mind"
        assert second.tags == ("incorrect", "slow")

    @pytest.mark.anyio
    async def test_save_different_users_separate(self, repo):
        a = await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=1, user_id="u1"))
        b = await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=-1, user_id="u2"))
        assert a.feedback_id != b.feedback_id

    @pytest.mark.anyio
    async def test_latest_per_run_in_thread_scopes_thread_and_owner(self, repo):
        await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=1, user_id="u1"))
        await repo.save(Feedback.create(run_id="r2", thread_id="t1", rating=-1, user_id="u1"))
        await repo.save(Feedback.create(run_id="r3", thread_id="t2", rating=1, user_id="u1"))
        await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=-1, user_id="u2"))

        grouped = await repo.latest_per_run_in_thread("t1", user_id="u1")

        assert set(grouped) == {"r1", "r2"}
        assert grouped["r1"].rating == 1
        assert grouped["r2"].rating == -1

    @pytest.mark.anyio
    async def test_latest_per_run_in_thread_empty(self, repo):
        assert await repo.latest_per_run_in_thread("t1", user_id="u1") == {}

    @pytest.mark.anyio
    async def test_latest_for_runs_scopes_selection(self, repo):
        await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=1, user_id="u1"))
        await repo.save(Feedback.create(run_id="r2", thread_id="t1", rating=-1, user_id="u1"))
        await repo.save(Feedback.create(run_id="r3", thread_id="t1", rating=1, user_id="u1"))

        grouped = await repo.latest_for_runs("t1", {"r1", "r2"}, user_id="u1")

        assert set(grouped) == {"r1", "r2"}

    @pytest.mark.anyio
    async def test_latest_for_runs_empty_set(self, repo):
        assert await repo.latest_for_runs("t1", set(), user_id="u1") == {}

    @pytest.mark.anyio
    async def test_remove_for_run(self, repo):
        await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=1, user_id="u1"))
        assert await repo.remove_for_run("t1", "r1", user_id="u1") is True
        assert await repo.latest_per_run_in_thread("t1", user_id="u1") == {}

    @pytest.mark.anyio
    async def test_remove_for_run_nonexistent(self, repo):
        assert await repo.remove_for_run("t1", "r1", user_id="u1") is False

    @pytest.mark.anyio
    async def test_remove_for_run_other_user_denied(self, repo):
        await repo.save(Feedback.create(run_id="r1", thread_id="t1", rating=1, user_id="u1"))
        assert await repo.remove_for_run("t1", "r1", user_id="u2") is False
        assert set(await repo.latest_per_run_in_thread("t1", user_id="u1")) == {"r1"}


class TestSqlFeedbackRepository(FeedbackRepositoryContract):
    @pytest.fixture
    async def repo(self, tmp_path):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        import deerflow.persistence.feedback.model  # noqa: F401  (register FeedbackRow)
        from app.infra.persistence.feedback import SqlFeedbackRepository
        from deerflow.persistence.base import Base

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield SqlFeedbackRepository(async_sessionmaker(engine, expire_on_commit=False))
        await engine.dispose()


class TestInMemoryFeedbackRepository(FeedbackRepositoryContract):
    @pytest.fixture
    def repo(self):
        return InMemoryFeedbackRepository()


# -- Follow-up association (unrelated to the feedback repository) --


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
