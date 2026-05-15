from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEER_FLOW_CONFIG_PATH", str(Path(__file__).resolve().parents[2] / "config.example.yaml"))

from store.persistence import create_persistence_from_database_config
from store.repositories import (
    FeedbackCreate,
    InvalidMetadataFilterError,
    RunCreate,
    RunEventCreate,
    ThreadMetaCreate,
    build_feedback_repository,
    build_run_event_repository,
    build_run_repository,
    build_thread_meta_repository,
)


async def _make_persistence(tmp_path):
    persistence = await create_persistence_from_database_config(
        SimpleNamespace(
            backend="sqlite",
            sqlite_dir=str(tmp_path),
            echo_sql=False,
            pool_size=5,
        )
    )
    await persistence.setup()
    return persistence


@pytest.mark.anyio
async def test_storage_run_repository_filters_and_aggregates(tmp_path):
    persistence = await _make_persistence(tmp_path)
    old = datetime.now(UTC) - timedelta(hours=1)
    newer = datetime.now(UTC)
    try:
        async with persistence.session_factory() as session:
            repo = build_run_repository(session)
            await repo.create_run(
                RunCreate(
                    run_id="run-old",
                    thread_id="thread-1",
                    user_id="alice",
                    status="pending",
                    model_name="model-a",
                    metadata={"kind": "draft"},
                    kwargs={"temperature": 0.2},
                    created_time=old,
                )
            )
            await repo.create_run(
                RunCreate(
                    run_id="run-new",
                    thread_id="thread-1",
                    user_id="bob",
                    status="running",
                    model_name="model-b",
                    error="queued",
                    created_time=newer,
                )
            )
            await repo.create_run(RunCreate(run_id="run-other", thread_id="thread-2", status="running"))
            await repo.update_run_completion(
                "run-old",
                status="success",
                total_input_tokens=7,
                total_output_tokens=3,
                total_tokens=10,
                llm_call_count=1,
                lead_agent_tokens=8,
                subagent_tokens=2,
                first_human_message="hello",
                last_ai_message="world",
            )
            await repo.update_run_completion(
                "run-new",
                status="error",
                total_tokens=5,
                middleware_tokens=5,
                error="failed",
            )
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_run_repository(session)
            fetched = await repo.get_run("run-old")
            assert fetched is not None
            assert fetched.metadata == {"kind": "draft"}
            assert fetched.kwargs == {"temperature": 0.2}
            assert fetched.first_human_message == "hello"
            assert fetched.last_ai_message == "world"

            all_thread_runs = await repo.list_runs_by_thread("thread-1")
            assert [run.run_id for run in all_thread_runs] == ["run-new", "run-old"]
            alice_runs = await repo.list_runs_by_thread("thread-1", user_id="alice")
            assert [run.run_id for run in alice_runs] == ["run-old"]

            pending = await repo.list_pending(before=datetime.now(UTC).isoformat())
            assert [run.run_id for run in pending] == []

            agg = await repo.aggregate_tokens_by_thread("thread-1")
            assert agg["total_tokens"] == 15
            assert agg["total_input_tokens"] == 7
            assert agg["total_output_tokens"] == 3
            assert agg["total_runs"] == 2
            assert agg["by_model"] == {
                "model-a": {"tokens": 10, "runs": 1},
                "model-b": {"tokens": 5, "runs": 1},
            }
            assert agg["by_caller"] == {"lead_agent": 8, "subagent": 2, "middleware": 5}
    finally:
        await persistence.aclose()


@pytest.mark.anyio
async def test_storage_thread_meta_repository_search_update_delete(tmp_path):
    persistence = await _make_persistence(tmp_path)
    try:
        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            await repo.create_thread_meta(
                ThreadMetaCreate(
                    thread_id="thread-1",
                    assistant_id="agent-a",
                    user_id="alice",
                    display_name="Initial",
                    status="idle",
                    metadata={"topic": "finance", "region": "cn"},
                )
            )
            await repo.create_thread_meta(
                ThreadMetaCreate(
                    thread_id="thread-2",
                    assistant_id="agent-b",
                    user_id="bob",
                    status="running",
                    metadata={"topic": "legal"},
                )
            )
            await repo.update_thread_meta(
                "thread-1",
                display_name="Updated",
                status="running",
                metadata={"topic": "finance", "region": "us"},
            )
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            fetched = await repo.get_thread_meta("thread-1")
            assert fetched is not None
            assert fetched.display_name == "Updated"
            assert fetched.status == "running"
            assert fetched.metadata == {"topic": "finance", "region": "us"}

            by_metadata = await repo.search_threads(metadata={"topic": "finance"}, user_id="alice")
            assert [thread.thread_id for thread in by_metadata] == ["thread-1"]
            by_assistant = await repo.search_threads(assistant_id="agent-b")
            assert [thread.thread_id for thread in by_assistant] == ["thread-2"]

            await repo.delete_thread("thread-1")
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            assert await repo.get_thread_meta("thread-1") is None
    finally:
        await persistence.aclose()


@pytest.mark.anyio
async def test_storage_thread_meta_metadata_filters_are_type_safe(tmp_path):
    persistence = await _make_persistence(tmp_path)
    try:
        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            await repo.create_thread_meta(ThreadMetaCreate(thread_id="bool-true", metadata={"value": True}))
            await repo.create_thread_meta(ThreadMetaCreate(thread_id="bool-false", metadata={"value": False}))
            await repo.create_thread_meta(ThreadMetaCreate(thread_id="int-one", metadata={"value": 1}))
            await repo.create_thread_meta(ThreadMetaCreate(thread_id="null-value", metadata={"value": None}))
            await repo.create_thread_meta(ThreadMetaCreate(thread_id="missing-value", metadata={"other": "x"}))
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            assert [row.thread_id for row in await repo.search_threads(metadata={"value": True})] == ["bool-true"]
            assert [row.thread_id for row in await repo.search_threads(metadata={"value": False})] == ["bool-false"]
            assert [row.thread_id for row in await repo.search_threads(metadata={"value": 1})] == ["int-one"]
            assert [row.thread_id for row in await repo.search_threads(metadata={"value": None})] == ["null-value"]
    finally:
        await persistence.aclose()


@pytest.mark.anyio
async def test_storage_thread_meta_metadata_filters_paginate_after_sql_match(tmp_path):
    persistence = await _make_persistence(tmp_path)
    try:
        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            for index in range(30):
                metadata = {"target": "yes"} if index % 3 == 0 else {"target": "no"}
                await repo.create_thread_meta(ThreadMetaCreate(thread_id=f"thread-{index:02d}", metadata=metadata))
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            first_page = await repo.search_threads(metadata={"target": "yes"}, limit=3, offset=0)
            second_page = await repo.search_threads(metadata={"target": "yes"}, limit=3, offset=3)
            last_page = await repo.search_threads(metadata={"target": "yes"}, limit=3, offset=9)

        assert len(first_page) == 3
        assert len(second_page) == 3
        assert len(last_page) == 1
        assert {row.thread_id for row in first_page}.isdisjoint({row.thread_id for row in second_page})
    finally:
        await persistence.aclose()


@pytest.mark.anyio
async def test_storage_thread_meta_metadata_filter_rejects_invalid_entries(tmp_path):
    persistence = await _make_persistence(tmp_path)
    try:
        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            await repo.create_thread_meta(ThreadMetaCreate(thread_id="thread-1", metadata={"env": "prod"}))
            await repo.create_thread_meta(ThreadMetaCreate(thread_id="thread-2", metadata={"env": "staging"}))
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_thread_meta_repository(session)
            partial = await repo.search_threads(metadata={"env": "prod", "bad;key": "ignored"})
            assert [row.thread_id for row in partial] == ["thread-1"]

            with pytest.raises(InvalidMetadataFilterError, match="rejected"):
                await repo.search_threads(metadata={"bad;key": "x"})
            with pytest.raises(InvalidMetadataFilterError, match="rejected"):
                await repo.search_threads(metadata={"env": ["prod", "staging"]})
    finally:
        await persistence.aclose()


@pytest.mark.anyio
async def test_storage_feedback_repository_lists_and_deletes(tmp_path):
    persistence = await _make_persistence(tmp_path)
    try:
        async with persistence.session_factory() as session:
            repo = build_feedback_repository(session)
            first = await repo.create_feedback(
                FeedbackCreate(
                    feedback_id="fb-1",
                    run_id="run-1",
                    thread_id="thread-1",
                    rating=1,
                    user_id="alice",
                    message_id="msg-1",
                    comment="good",
                )
            )
            second = await repo.create_feedback(
                FeedbackCreate(
                    feedback_id="fb-2",
                    run_id="run-1",
                    thread_id="thread-1",
                    rating=-1,
                    user_id="bob",
                )
            )
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_feedback_repository(session)
            assert await repo.get_feedback(first.feedback_id) == first
            assert [item.feedback_id for item in await repo.list_feedback_by_run("run-1")] == [
                second.feedback_id,
                first.feedback_id,
            ]
            assert {item.feedback_id for item in await repo.list_feedback_by_thread("thread-1")} == {
                "fb-1",
                "fb-2",
            }
            assert await repo.delete_feedback("fb-1") is True
            assert await repo.delete_feedback("missing") is False
            with pytest.raises(ValueError, match="rating must be"):
                await repo.create_feedback(
                    FeedbackCreate(
                        feedback_id="fb-bad",
                        run_id="run-1",
                        thread_id="thread-1",
                        rating=0,
                    )
                )
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_feedback_repository(session)
            assert await repo.get_feedback("fb-1") is None
    finally:
        await persistence.aclose()


@pytest.mark.anyio
async def test_storage_run_event_repository_sequences_paginates_and_deletes(tmp_path):
    persistence = await _make_persistence(tmp_path)
    try:
        async with persistence.session_factory() as session:
            repo = build_run_event_repository(session)
            rows = await repo.append_batch(
                [
                    RunEventCreate(
                        thread_id="thread-1",
                        run_id="run-1",
                        user_id="alice",
                        event_type="message",
                        category="message",
                        content={"role": "user", "content": "hello"},
                        metadata={"source": "input"},
                    ),
                    RunEventCreate(
                        thread_id="thread-1",
                        run_id="run-1",
                        event_type="tool",
                        category="debug",
                        content="tool-call",
                    ),
                    RunEventCreate(
                        thread_id="thread-1",
                        run_id="run-2",
                        event_type="message",
                        category="message",
                        content="second",
                    ),
                    RunEventCreate(
                        thread_id="thread-2",
                        run_id="run-3",
                        event_type="message",
                        category="message",
                        content="other-thread",
                    ),
                ]
            )
            await session.commit()

        assert [row.thread_id for row in rows] == ["thread-1", "thread-1", "thread-1", "thread-2"]
        assert [row.seq for row in rows] == sorted(row.seq for row in rows)
        assert rows[1].seq == rows[0].seq + 1
        assert rows[2].seq == rows[1].seq + 1
        assert rows[0].content == {"role": "user", "content": "hello"}
        assert rows[0].metadata == {"source": "input", "content_is_json": True}

        async with persistence.session_factory() as session:
            repo = build_run_event_repository(session)
            messages = await repo.list_messages("thread-1", limit=2)
            assert [event.seq for event in messages] == [rows[0].seq, rows[2].seq]
            assert await repo.count_messages("thread-1") == 2

            after = await repo.list_messages_by_run("thread-1", "run-1", after_seq=0, limit=5)
            assert [event.seq for event in after] == [rows[0].seq]
            before = await repo.list_messages("thread-1", before_seq=rows[2].seq, limit=5)
            assert [event.seq for event in before] == [rows[0].seq]

            events = await repo.list_events("thread-1", "run-1", event_types=["tool"])
            assert [event.content for event in events] == ["tool-call"]

            assert await repo.delete_by_run("thread-1", "run-1") == 2
            assert await repo.delete_by_thread("thread-2") == 1
            await session.commit()

        async with persistence.session_factory() as session:
            repo = build_run_event_repository(session)
            remaining = await repo.list_events("thread-1", "run-2")
            assert [event.seq for event in remaining] == [rows[2].seq]
            assert await repo.count_messages("thread-2") == 0

            later = await repo.append_batch(
                [
                    RunEventCreate(
                        thread_id="thread-1",
                        run_id="run-4",
                        event_type="message",
                        category="message",
                        content="after-delete",
                    )
                ]
            )
            assert later[0].seq > rows[2].seq
    finally:
        await persistence.aclose()
