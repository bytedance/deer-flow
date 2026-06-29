"""Tests for workflow frontdoor stores."""

import pytest

from deerflow.persistence.workflow import WorkflowRepository
from deerflow.runtime.workflows.store.memory import MemoryWorkflowStore


async def _make_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return WorkflowRepository(get_session_factory())


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


@pytest.mark.anyio
async def test_memory_workflow_store_create_or_get_is_idempotent():
    store = MemoryWorkflowStore()

    first, created = await store.create_or_get(
        source_type="channel",
        source="slack:T1",
        idempotency_key="m-1",
        external_message_ref="m-1",
        metadata={"attempt": 1},
    )
    second, created_again = await store.create_or_get(
        source_type="channel",
        source="slack:T1",
        idempotency_key="m-1",
        external_message_ref="m-1",
        metadata={"attempt": 2},
    )

    assert created is True
    assert created_again is False
    assert second["workflow_id"] == first["workflow_id"]
    assert second["metadata"] == {"attempt": 1}


@pytest.mark.anyio
async def test_memory_workflow_store_bind_status_and_filter():
    store = MemoryWorkflowStore()
    workflow, _ = await store.create_or_get(source_type="api", source="dashboard", user_id="alice")

    bound = await store.bind_runtime(
        workflow["workflow_id"],
        thread_id="thread-1",
        run_id="run-1",
        checkpoint_ns="",
        checkpoint_id="ckpt-1",
        status="run_created",
        metadata={"binding": "direct"},
    )
    updated = await store.update_status(workflow["workflow_id"], "running", metadata={"phase": "streaming"})

    row = await store.get(workflow["workflow_id"], user_id="alice")
    rows = await store.list(thread_id="thread-1", run_id="run-1", user_id="alice")

    assert bound is True
    assert updated is True
    assert row["status"] == "running"
    assert row["thread_id"] == "thread-1"
    assert row["run_id"] == "run-1"
    assert row["checkpoint_id"] == "ckpt-1"
    assert row["metadata"] == {"binding": "direct", "phase": "streaming"}
    assert [item["workflow_id"] for item in rows] == [workflow["workflow_id"]]


@pytest.mark.anyio
async def test_memory_workflow_store_claim_and_release_for_retry():
    store = MemoryWorkflowStore()
    workflow, _ = await store.create_or_get(source_type="api", source="dashboard", max_attempts=2)

    claimed = await store.claim_next(lease_owner="worker-1", lease_seconds=30)
    released = await store.release_for_retry(
        workflow["workflow_id"],
        status="received",
        error="transient",
        metadata={"retry": True},
    )
    claimed_again = await store.claim_next(lease_owner="worker-2", lease_seconds=30)
    exhausted = await store.release_for_retry(workflow["workflow_id"], status="received")
    should_skip = await store.claim_next(lease_owner="worker-3", lease_seconds=30)

    assert claimed["workflow_id"] == workflow["workflow_id"]
    assert claimed["lease_owner"] == "worker-1"
    assert claimed["attempt_count"] == 1
    assert released is True
    assert claimed_again["lease_owner"] == "worker-2"
    assert claimed_again["attempt_count"] == 2
    assert exhausted is True
    assert should_skip is None


@pytest.mark.anyio
async def test_memory_workflow_store_appends_events_in_order():
    store = MemoryWorkflowStore()
    workflow, _ = await store.create_or_get(workflow_id="wf-memory-events", source_type="api")

    first = await store.append_event(
        workflow["workflow_id"],
        event_type="workflow.received",
        content={"source": "dashboard"},
        metadata={"durable": True},
    )
    second = await store.append_event(
        workflow["workflow_id"],
        event_type="workflow.bound",
        thread_id="thread-1",
        run_id="run-1",
        checkpoint_ns="",
        checkpoint_id="ckpt-1",
        run_event_seq=7,
        idempotency_key="wf-memory-events:bound",
    )
    missing = await store.append_event("missing", event_type="workflow.received")
    bound_events = await store.list_events(workflow["workflow_id"], event_types=["workflow.bound"])

    assert first["seq"] == 1
    assert first["content"] == {"source": "dashboard"}
    assert first["metadata"] == {"durable": True}
    assert second["seq"] == 2
    assert second["thread_id"] == "thread-1"
    assert second["run_id"] == "run-1"
    assert second["checkpoint_ns"] == ""
    assert second["run_event_seq"] == 7
    assert second["idempotency_key"] == "wf-memory-events:bound"
    assert missing is None
    assert [event["event_type"] for event in bound_events] == ["workflow.bound"]


class TestWorkflowRepository:
    @pytest.mark.anyio
    async def test_create_or_get_and_get(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            row, created = await repo.create_or_get(
                workflow_id="wf-1",
                workflow_kind="message",
                source_type="api",
                source="dashboard",
                idempotency_key="idem-1",
                external_message_ref="msg-1",
                conversation_ref="conv-1",
                sender_ref="user-1",
                user_id="alice",
                metadata={"source": "test"},
            )

            loaded = await repo.get("wf-1", user_id="alice")

            assert created is True
            assert loaded == row
            assert loaded["workflow_id"] == "wf-1"
            assert loaded["status"] == "received"
            assert loaded["metadata"] == {"source": "test"}
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_create_or_get_is_idempotent_for_retried_writes(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            first, created = await repo.create_or_get(
                workflow_kind="message",
                source_type="channel",
                source="slack:T1",
                idempotency_key="event-1",
                metadata={"attempt": 1},
            )
            second, created_again = await repo.create_or_get(
                workflow_kind="message",
                source_type="channel",
                source="slack:T1",
                idempotency_key="event-1",
                metadata={"attempt": 2},
            )

            assert created is True
            assert created_again is False
            assert second["workflow_id"] == first["workflow_id"]
            assert second["metadata"] == {"attempt": 1}
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_idempotency_without_source_uses_blank_scope(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            first, _ = await repo.create_or_get(source_type="api", idempotency_key="same")
            second, created_again = await repo.create_or_get(source_type="api", idempotency_key="same")

            assert created_again is False
            assert second["workflow_id"] == first["workflow_id"]
            assert second["source"] == ""
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_bind_runtime_and_update_status(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            row, _ = await repo.create_or_get(workflow_id="wf-bind", source_type="api")

            bound = await repo.bind_runtime(
                row["workflow_id"],
                thread_id="thread-1",
                run_id="run-1",
                checkpoint_ns="",
                checkpoint_id="ckpt-1",
                status="run_created",
                metadata={"binding": "deterministic"},
            )
            updated = await repo.update_status(
                row["workflow_id"],
                "failed",
                error="boom",
                metadata={"recovery": "retryable"},
            )
            loaded = await repo.get(row["workflow_id"])

            assert bound is True
            assert updated is True
            assert loaded["status"] == "failed"
            assert loaded["error"] == "boom"
            assert loaded["thread_id"] == "thread-1"
            assert loaded["run_id"] == "run-1"
            assert loaded["checkpoint_ns"] == ""
            assert loaded["checkpoint_id"] == "ckpt-1"
            assert loaded["metadata"] == {
                "binding": "deterministic",
                "recovery": "retryable",
            }
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_claim_next_and_release_for_retry(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            row, _ = await repo.create_or_get(
                workflow_id="wf-claim",
                source_type="api",
                source="dashboard",
                max_attempts=2,
            )

            claimed = await repo.claim_next(lease_owner="worker-1", lease_seconds=60)
            none_while_leased = await repo.claim_next(lease_owner="worker-2", lease_seconds=60)
            released = await repo.release_for_retry(
                row["workflow_id"],
                status="received",
                error="transient",
                metadata={"retry": True},
            )
            claimed_again = await repo.claim_next(lease_owner="worker-2", lease_seconds=60)
            await repo.release_for_retry(row["workflow_id"], status="received")
            should_skip = await repo.claim_next(lease_owner="worker-3", lease_seconds=60)

            assert claimed["workflow_id"] == "wf-claim"
            assert claimed["status"] == "claimed"
            assert claimed["lease_owner"] == "worker-1"
            assert claimed["lease_expires_at"] is not None
            assert claimed["attempt_count"] == 1
            assert none_while_leased is None
            assert released is True
            assert claimed_again["lease_owner"] == "worker-2"
            assert claimed_again["attempt_count"] == 2
            assert should_skip is None
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_list_filters(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            await repo.create_or_get(
                workflow_id="wf-1",
                source_type="channel",
                source="slack",
                user_id="alice",
                thread_id="thread-1",
                run_id="run-1",
                status="running",
            )
            await repo.create_or_get(
                workflow_id="wf-2",
                source_type="channel",
                source="discord",
                user_id="alice",
                thread_id="thread-2",
                run_id="run-2",
                status="received",
            )
            await repo.create_or_get(
                workflow_id="wf-3",
                source_type="api",
                source="dashboard",
                user_id="bob",
                thread_id="thread-1",
                run_id="run-3",
                status="running",
            )

            rows = await repo.list(
                status="running",
                source_type="channel",
                source="slack",
                thread_id="thread-1",
                user_id="alice",
            )

            assert [row["workflow_id"] for row in rows] == ["wf-1"]
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_missing_updates_return_false(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            assert await repo.bind_runtime("missing", thread_id="t1") is False
            assert await repo.update_status("missing", "failed") is False
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_append_and_list_events(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            row, _ = await repo.create_or_get(workflow_id="wf-events", source_type="api")

            first = await repo.append_event(
                row["workflow_id"],
                event_type="workflow.received",
                category="lifecycle",
                content={"source": "dashboard"},
                metadata={"attempt": 1},
            )
            second = await repo.append_event(
                row["workflow_id"],
                event_type="workflow.bound",
                category="runtime",
                thread_id="thread-1",
                run_id="run-1",
                checkpoint_ns="",
                checkpoint_id="ckpt-1",
                run_event_seq=9,
                idempotency_key="wf-events:bound",
                source_event_ref="run_events:thread-1:run-1:1",
            )
            missing = await repo.append_event("missing", event_type="workflow.received")
            all_events = await repo.list_events(row["workflow_id"])
            bound_events = await repo.list_events(row["workflow_id"], event_types=["workflow.bound"])

            assert first["seq"] == 1
            assert first["content"] == {"source": "dashboard"}
            assert first["metadata"] == {"attempt": 1}
            assert second["seq"] == 2
            assert second["category"] == "runtime"
            assert second["thread_id"] == "thread-1"
            assert second["run_id"] == "run-1"
            assert second["checkpoint_ns"] == ""
            assert second["checkpoint_id"] == "ckpt-1"
            assert second["run_event_seq"] == 9
            assert second["idempotency_key"] == "wf-events:bound"
            assert second["source_event_ref"] == "run_events:thread-1:run-1:1"
            assert missing is None
            assert [event["event_type"] for event in all_events] == [
                "workflow.received",
                "workflow.bound",
            ]
            assert [event["event_type"] for event in bound_events] == ["workflow.bound"]
        finally:
            await _cleanup()
