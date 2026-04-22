"""Tests for current run event store backends."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.run_events import JsonlRunEventStore, build_run_event_store
from app.infra.storage import AppRunEventStore, ThreadMetaStorage, ThreadMetaStoreAdapter
from deerflow.runtime.actor_context import ActorContext, bind_actor_context, reset_actor_context
from store.persistence import MappedBase


@pytest.fixture
def jsonl_store(tmp_path):
    return JsonlRunEventStore(base_dir=tmp_path / "jsonl")


async def _make_db_store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    thread_store = ThreadMetaStorage(ThreadMetaStoreAdapter(session_factory))
    return engine, thread_store, AppRunEventStore(session_factory), session_factory


class _RunEventStoreContract:
    async def _exercise_basic_contract(self, store):
        first = await store.put_batch(
            [
                {"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message", "content": "a"},
                {"thread_id": "t1", "run_id": "r1", "event_type": "ai_message", "category": "message", "content": "b"},
                {"thread_id": "t1", "run_id": "r1", "event_type": "llm_end", "category": "trace", "metadata": {"m": 1}},
            ]
        )
        assert [row["seq"] for row in first] == [1, 2, 3]

        messages = await store.list_messages("t1")
        assert [row["seq"] for row in messages] == [1, 2]
        assert messages[0]["content"] == "a"

        events = await store.list_events("t1", "r1")
        assert len(events) == 3

        by_run = await store.list_messages_by_run("t1", "r1")
        assert [row["seq"] for row in by_run] == [1, 2]
        assert await store.count_messages("t1") == 2

        deleted = await store.delete_by_run("t1", "r1")
        assert deleted == 3
        assert await store.list_messages("t1") == []


class TestJsonlRunEventStore(_RunEventStoreContract):
    @pytest.mark.anyio
    async def test_basic_contract(self, jsonl_store):
        await self._exercise_basic_contract(jsonl_store)

    @pytest.mark.anyio
    async def test_file_at_correct_path(self, tmp_path):
        store = JsonlRunEventStore(base_dir=tmp_path / "jsonl")
        await store.put_batch(
            [{"thread_id": "t1", "run_id": "r1", "event_type": "human_message", "category": "message"}]
        )
        assert (tmp_path / "jsonl" / "threads" / "t1" / "events.jsonl").exists()


class TestAppRunEventStore(_RunEventStoreContract):
    @pytest.mark.anyio
    async def test_basic_contract(self, tmp_path):
        engine, thread_store, store, _ = await _make_db_store(tmp_path)
        try:
            await thread_store.ensure_thread(thread_id="t1", user_id=None)
            await self._exercise_basic_contract(store)
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_actor_isolation_by_thread_owner(self, tmp_path):
        engine, thread_store, store, _ = await _make_db_store(tmp_path)
        try:
            token = bind_actor_context(ActorContext(user_id="user-a"))
            try:
                await thread_store.ensure_thread(thread_id="t-alpha")
                await store.put_batch(
                    [
                        {
                            "thread_id": "t-alpha",
                            "run_id": "run-a1",
                            "event_type": "human_message",
                            "category": "message",
                            "content": "private-a",
                        }
                    ]
                )
            finally:
                reset_actor_context(token)

            token = bind_actor_context(ActorContext(user_id="user-b"))
            try:
                await thread_store.ensure_thread(thread_id="t-beta")
                await store.put_batch(
                    [
                        {
                            "thread_id": "t-beta",
                            "run_id": "run-b1",
                            "event_type": "human_message",
                            "category": "message",
                            "content": "private-b",
                        }
                    ]
                )
                assert await store.list_messages("t-alpha") == []
                assert await store.list_events("t-alpha", "run-a1") == []
                assert await store.count_messages("t-alpha") == 0
                assert await store.delete_by_thread("t-alpha") == 0
            finally:
                reset_actor_context(token)

            token = bind_actor_context(ActorContext(user_id="user-a"))
            try:
                rows = await store.list_messages("t-alpha")
                assert [row["content"] for row in rows] == ["private-a"]
            finally:
                reset_actor_context(token)
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_put_batch_preserves_structured_content_metadata_and_created_at(self, tmp_path):
        engine, thread_store, store, _ = await _make_db_store(tmp_path)
        try:
            await thread_store.ensure_thread(thread_id="t1", user_id=None)
            created_at = datetime(2026, 4, 20, 8, 30, tzinfo=UTC)
            rows = await store.put_batch(
                [
                    {
                        "thread_id": "t1",
                        "run_id": "r1",
                        "event_type": "tool_end",
                        "category": "trace",
                        "content": {"type": "tool", "content": "ok"},
                        "metadata": {"tool": "search"},
                        "created_at": created_at.isoformat(),
                    }
                ]
            )

            assert rows[0]["content"] == {"type": "tool", "content": "ok"}
            assert rows[0]["metadata"]["tool"] == "search"
            assert "content_is_dict" not in rows[0]["metadata"]
            assert rows[0]["created_at"] == created_at.isoformat()
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_list_messages_supports_before_and_after_pagination(self, tmp_path):
        engine, thread_store, store, _ = await _make_db_store(tmp_path)
        try:
            await thread_store.ensure_thread(thread_id="t1", user_id=None)
            await store.put_batch(
                [
                    {
                        "thread_id": "t1",
                        "run_id": "r1",
                        "event_type": "human_message",
                        "category": "message",
                        "content": str(i),
                    }
                    for i in range(10)
                ]
            )

            before = await store.list_messages("t1", before_seq=6, limit=3)
            after = await store.list_messages("t1", after_seq=7, limit=3)

            assert [message["seq"] for message in before] == [3, 4, 5]
            assert [message["seq"] for message in after] == [8, 9, 10]
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_list_events_filters_by_run_and_event_type(self, tmp_path):
        engine, thread_store, store, _ = await _make_db_store(tmp_path)
        try:
            await thread_store.ensure_thread(thread_id="t1", user_id=None)
            await store.put_batch(
                [
                    {"thread_id": "t1", "run_id": "r1", "event_type": "llm_start", "category": "trace"},
                    {"thread_id": "t1", "run_id": "r1", "event_type": "llm_end", "category": "trace"},
                    {"thread_id": "t1", "run_id": "r2", "event_type": "llm_end", "category": "trace"},
                ]
            )

            events = await store.list_events("t1", "r1", event_types=["llm_end"])
            assert len(events) == 1
            assert events[0]["run_id"] == "r1"
            assert events[0]["event_type"] == "llm_end"
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_put_batch_denies_write_to_other_users_thread(self, tmp_path):
        engine, thread_store, store, _ = await _make_db_store(tmp_path)
        try:
            token = bind_actor_context(ActorContext(user_id="user-a"))
            try:
                await thread_store.ensure_thread(thread_id="t-alpha")
            finally:
                reset_actor_context(token)

            token = bind_actor_context(ActorContext(user_id="user-b"))
            try:
                with pytest.raises(PermissionError, match="not allowed to append events"):
                    await store.put_batch(
                        [
                            {
                                "thread_id": "t-alpha",
                                "run_id": "run-a1",
                                "event_type": "human_message",
                                "category": "message",
                                "content": "forbidden",
                            }
                        ]
                    )
            finally:
                reset_actor_context(token)
        finally:
            await engine.dispose()


class TestBuildRunEventStore:
    @pytest.mark.anyio
    async def test_db_backend(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        engine, _, _, session_factory = await _make_db_store(tmp_path)
        try:
            monkeypatch.setattr(
                "app.infra.run_events.factory.get_app_config",
                lambda: SimpleNamespace(run_events=SimpleNamespace(backend="db", jsonl_base_dir="", max_trace_content=0)),
            )
            store = build_run_event_store(session_factory)
            assert isinstance(store, AppRunEventStore)
        finally:
            await engine.dispose()

    @pytest.mark.anyio
    async def test_jsonl_backend(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        engine, _, _, session_factory = await _make_db_store(tmp_path)
        try:
            monkeypatch.setattr(
                "app.infra.run_events.factory.get_app_config",
                lambda: SimpleNamespace(
                    run_events=SimpleNamespace(
                        backend="jsonl",
                        jsonl_base_dir=str(tmp_path / "jsonl"),
                        max_trace_content=0,
                    )
                ),
            )
            store = build_run_event_store(session_factory)
            assert isinstance(store, JsonlRunEventStore)
        finally:
            await engine.dispose()
