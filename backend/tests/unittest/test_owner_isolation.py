"""Cross-user isolation tests for current app-owned storage adapters.

These tests exercise isolation by binding different ``ActorContext``
values around the app-layer storage adapters. The safety property is:

  data written under user A is not visible to user B through the same
  adapter surface unless a call explicitly opts out with ``user_id=None``.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.storage import AppRunEventStore, FeedbackStoreAdapter, RunStoreAdapter, ThreadMetaStorage, ThreadMetaStoreAdapter
from deerflow.runtime.actor_context import AUTO, ActorContext, bind_actor_context, reset_actor_context
from store.persistence import MappedBase


USER_A = "user-a"
USER_B = "user-b"


async def _make_components(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'isolation.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    thread_store = ThreadMetaStorage(ThreadMetaStoreAdapter(session_factory))
    return (
        engine,
        thread_store,
        RunStoreAdapter(session_factory),
        FeedbackStoreAdapter(session_factory),
        AppRunEventStore(session_factory),
    )


@contextmanager
def _as_user(user_id: str):
    token = bind_actor_context(ActorContext(user_id=user_id))
    try:
        yield
    finally:
        reset_actor_context(token)


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_thread_meta_cross_user_isolation(tmp_path):
    engine, thread_store, _, _, _ = await _make_components(tmp_path)
    try:
        with _as_user(USER_A):
            await thread_store.ensure_thread(thread_id="t-alpha")
        with _as_user(USER_B):
            await thread_store.ensure_thread(thread_id="t-beta")

        with _as_user(USER_A):
            assert (await thread_store.get_thread("t-alpha")) is not None
            assert await thread_store.get_thread("t-beta") is None
            rows = await thread_store.search_threads()
            assert [row.thread_id for row in rows] == ["t-alpha"]

        with _as_user(USER_B):
            assert (await thread_store.get_thread("t-beta")) is not None
            assert await thread_store.get_thread("t-alpha") is None
            rows = await thread_store.search_threads()
            assert [row.thread_id for row in rows] == ["t-beta"]
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_runs_cross_user_isolation(tmp_path):
    engine, thread_store, run_store, _, _ = await _make_components(tmp_path)
    try:
        with _as_user(USER_A):
            await thread_store.ensure_thread(thread_id="t-alpha")
            await run_store.create("run-a1", "t-alpha")
            await run_store.create("run-a2", "t-alpha")

        with _as_user(USER_B):
            await thread_store.ensure_thread(thread_id="t-beta")
            await run_store.create("run-b1", "t-beta")

        with _as_user(USER_A):
            assert (await run_store.get("run-a1")) is not None
            assert await run_store.get("run-b1") is None
            rows = await run_store.list_by_thread("t-alpha")
            assert {row["run_id"] for row in rows} == {"run-a1", "run-a2"}
            assert await run_store.list_by_thread("t-beta") == []

        with _as_user(USER_B):
            assert await run_store.get("run-a1") is None
            rows = await run_store.list_by_thread("t-beta")
            assert [row["run_id"] for row in rows] == ["run-b1"]
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_run_events_cross_user_isolation(tmp_path):
    engine, thread_store, _, _, event_store = await _make_components(tmp_path)
    try:
        with _as_user(USER_A):
            await thread_store.ensure_thread(thread_id="t-alpha")
            await event_store.put_batch(
                [
                    {
                        "thread_id": "t-alpha",
                        "run_id": "run-a1",
                        "event_type": "human_message",
                        "category": "message",
                        "content": "User A private question",
                    },
                    {
                        "thread_id": "t-alpha",
                        "run_id": "run-a1",
                        "event_type": "ai_message",
                        "category": "message",
                        "content": "User A private answer",
                    },
                ]
            )

        with _as_user(USER_B):
            await thread_store.ensure_thread(thread_id="t-beta")
            await event_store.put_batch(
                [
                    {
                        "thread_id": "t-beta",
                        "run_id": "run-b1",
                        "event_type": "human_message",
                        "category": "message",
                        "content": "User B private question",
                    }
                ]
            )

        with _as_user(USER_A):
            msgs = await event_store.list_messages("t-alpha")
            contents = [msg["content"] for msg in msgs]
            assert "User A private question" in contents
            assert "User A private answer" in contents
            assert "User B private question" not in contents
            assert await event_store.list_messages("t-beta") == []
            assert await event_store.list_events("t-beta", "run-b1") == []
            assert await event_store.count_messages("t-beta") == 0

        with _as_user(USER_B):
            msgs = await event_store.list_messages("t-beta")
            contents = [msg["content"] for msg in msgs]
            assert "User B private question" in contents
            assert "User A private question" not in contents
            assert await event_store.count_messages("t-alpha") == 0
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_feedback_cross_user_isolation(tmp_path):
    engine, thread_store, _, feedback_store, _ = await _make_components(tmp_path)
    try:
        with _as_user(USER_A):
            await thread_store.ensure_thread(thread_id="t-alpha")
            a_feedback = await feedback_store.create(
                run_id="run-a1",
                thread_id="t-alpha",
                rating=1,
                user_id=USER_A,
                comment="A liked this",
            )

        with _as_user(USER_B):
            await thread_store.ensure_thread(thread_id="t-beta")
            b_feedback = await feedback_store.create(
                run_id="run-b1",
                thread_id="t-beta",
                rating=-1,
                user_id=USER_B,
                comment="B disliked this",
            )

        with _as_user(USER_A):
            assert (await feedback_store.get(a_feedback["feedback_id"])) is not None
            assert await feedback_store.get(b_feedback["feedback_id"]) is not None
            assert await feedback_store.list_by_run("t-beta", "run-b1", user_id=USER_A) == []

        with _as_user(USER_B):
            assert await feedback_store.list_by_run("t-alpha", "run-a1", user_id=USER_B) == []
            rows = await feedback_store.list_by_run("t-beta", "run-b1", user_id=USER_B)
            assert len(rows) == 1
            assert rows[0]["comment"] == "B disliked this"
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_repository_without_context_raises(tmp_path):
    engine, thread_store, _, _, _ = await _make_components(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="no actor context is set"):
            await thread_store.search_threads(user_id=AUTO)
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_explicit_none_bypasses_filter(tmp_path):
    engine, thread_store, _, _, _ = await _make_components(tmp_path)
    try:
        with _as_user(USER_A):
            await thread_store.ensure_thread(thread_id="t-alpha")
        with _as_user(USER_B):
            await thread_store.ensure_thread(thread_id="t-beta")

        rows = await thread_store.search_threads(user_id=None)
        assert {row.thread_id for row in rows} == {"t-alpha", "t-beta"}
        assert await thread_store.get_thread("t-alpha", user_id=None) is not None
        assert await thread_store.get_thread("t-beta", user_id=None) is not None
    finally:
        await engine.dispose()
