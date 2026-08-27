"""Tests for RunRepository (SQLAlchemy-backed RunStore).

Uses a temp SQLite DB to test ORM-backed CRUD operations.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.sql import _database_wall_clock
from deerflow.runtime import CancelOutcome, RunManager, RunStatus, ThreadOperationKind
from deerflow.runtime.runs.manager import ConflictError
from deerflow.runtime.runs.store.base import RunStore


def test_postgres_lease_fence_uses_wall_clock_not_transaction_time():
    """A row-lock wait must not reuse PostgreSQL's transaction-start time."""
    statement = select(_database_wall_clock("postgresql"))
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "clock_timestamp()" in compiled
    assert "CURRENT_TIMESTAMP" not in compiled


async def _make_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return RunRepository(get_session_factory())


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


class _CustomRunStoreWithoutProgress(RunStore):
    def __init__(self):
        self.legacy_atomic_calls = 0

    async def put(self, *args, **kwargs):
        return None

    async def get(self, *args, **kwargs):
        return None

    async def list_by_thread(self, *args, **kwargs):
        return []

    async def update_status(self, *args, **kwargs):
        return None

    async def start_run(self, *args, **kwargs):
        return False

    async def delete(self, *args, **kwargs):
        return None

    async def update_model_name(self, *args, **kwargs):
        return None

    async def update_run_completion(self, *args, **kwargs):
        return None

    async def list_pending(self, *args, **kwargs):
        return []

    async def list_inflight(self, *args, **kwargs):
        return []

    async def aggregate_tokens_by_thread(self, *args, **kwargs):
        return {}

    async def update_lease(self, *args, **kwargs):
        return True

    async def list_inflight_with_expired_lease(self, *args, **kwargs):
        return []

    async def create_run_atomic(self, *args, **kwargs):
        self.legacy_atomic_calls += 1
        return {}, []

    async def claim_for_takeover(self, *args, **kwargs):
        return False


@pytest.mark.anyio
async def test_update_run_progress_defaults_to_noop_for_custom_store():
    store = _CustomRunStoreWithoutProgress()

    await store.update_run_progress("r1", total_tokens=1)


@pytest.mark.anyio
async def test_owned_completion_finalize_defaults_to_unsupported_for_custom_store():
    store = _CustomRunStoreWithoutProgress()

    result = await store.finalize_completion_if_owned_and_not_cancelled(
        "r1",
        expected_owner_worker_id="worker-1",
        status="success",
        total_tokens=1,
    )

    assert result is None


@pytest.mark.anyio
async def test_terminal_insert_defaults_to_unsupported_for_custom_store():
    store = _CustomRunStoreWithoutProgress()

    result = await store.insert_terminal_completion_if_absent(
        "r1",
        run_payload={"thread_id": "t1"},
        completion_payload={"status": "success"},
    )

    assert result is None


@pytest.mark.anyio
async def test_checkpoint_mutation_fence_defaults_to_unsupported_for_custom_store():
    store = _CustomRunStoreWithoutProgress()

    async with store.checkpoint_mutation_fence(
        "r1",
        expected_owner_worker_id="worker-1",
        lease_seconds=30,
    ) as fence:
        assert fence.acquired is False


@pytest.mark.anyio
async def test_legacy_create_run_atomic_store_remains_compatible():
    store = _CustomRunStoreWithoutProgress()

    await store.create_thread_operation_atomic(
        "r1",
        thread_id="t1",
        owner_worker_id="worker-1",
        lease_expires_at=None,
    )

    assert store.legacy_atomic_calls == 1
    with pytest.raises(NotImplementedError, match="cannot create non-run"):
        await store.create_thread_operation_atomic(
            "checkpoint-write-1",
            thread_id="t1",
            owner_worker_id="worker-1",
            lease_expires_at=None,
            operation_kind=ThreadOperationKind.checkpoint_write,
        )


class TestRunRepository:
    @pytest.mark.anyio
    async def test_put_and_get(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="pending")
        row = await repo.get("r1")
        assert row is not None
        assert row["run_id"] == "r1"
        assert row["thread_id"] == "t1"
        assert row["status"] == "pending"
        await _cleanup()

    @pytest.mark.anyio
    async def test_checkpoint_mutation_fence_requires_live_owner_and_renews_lease(self, tmp_path):
        repo = await _make_repo(tmp_path)
        original_expiry = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.put(
            "r-fence",
            thread_id="t-fence",
            status="running",
            owner_worker_id="worker-a",
            lease_expires_at=original_expiry,
        )

        async with repo.checkpoint_mutation_fence(
            "r-fence",
            expected_owner_worker_id="worker-a",
            lease_seconds=120,
        ) as fence:
            assert fence.acquired is True

        stored = await repo.get("r-fence")
        assert stored is not None
        assert fence.lease_expires_at is not None
        assert stored["lease_expires_at"] == fence.lease_expires_at
        assert datetime.fromisoformat(stored["lease_expires_at"]) > datetime.now(UTC) + timedelta(seconds=110)

        async with repo.checkpoint_mutation_fence(
            "r-fence",
            expected_owner_worker_id="worker-b",
            lease_seconds=120,
        ) as fence:
            assert fence.acquired is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_put_is_idempotent_for_retried_writes(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", assistant_id="old-agent", status="pending")

        await repo.put("r1", thread_id="t1", assistant_id="new-agent", status="running", error="retry")

        row = await repo.get("r1")
        assert row["assistant_id"] == "new-agent"
        assert row["status"] == "running"
        assert row["error"] == "retry"
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_missing_returns_none(self, tmp_path):
        repo = await _make_repo(tmp_path)
        assert await repo.get("nope") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        updated = await repo.update_status("r1", "running")
        row = await repo.get("r1")
        assert updated is True
        assert row["status"] == "running"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status_returns_false_for_missing_row(self, tmp_path):
        repo = await _make_repo(tmp_path)
        updated = await repo.update_status("missing", "error", error="lost")
        assert updated is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_start_run_only_updates_pending_rows(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("pending-run", thread_id="t1", status="pending")
        await repo.put("cancelled-run", thread_id="t2", status="pending")
        await repo.update_status("cancelled-run", "interrupted")

        assert await repo.start_run("pending-run") is True
        assert await repo.start_run("cancelled-run") is False

        pending_row = await repo.get("pending-run")
        cancelled_row = await repo.get("cancelled-run")
        assert pending_row["status"] == "running"
        assert cancelled_row["status"] == "interrupted"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status_with_error(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.update_status("r1", "error", error="boom")
        row = await repo.get("r1")
        assert row["status"] == "error"
        assert row["error"] == "boom"
        await _cleanup()

    @pytest.mark.anyio
    async def test_generic_writes_do_not_replace_interrupted_terminal_row(
        self,
        tmp_path,
    ):
        repo = await _make_repo(tmp_path)
        try:
            await repo.put("r1", thread_id="t1", status="interrupted")

            assert await repo.update_status("r1", "success") is False
            assert await repo.update_status("r1", "error", error="late error") is False
            assert (
                await repo.update_run_completion(
                    "r1",
                    status="error",
                    total_tokens=99,
                )
                is False
            )

            row = await repo.get("r1")
            assert row is not None
            assert row["status"] == "interrupted"
            assert row["error"] is None
            assert row["total_tokens"] == 0
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="success")
        await repo.put("r2", thread_id="t1", status="pending")
        await repo.put("r3", thread_id="t2", status="pending")
        rows = await repo.list_by_thread("t1")
        assert len(rows) == 2
        assert all(r["thread_id"] == "t1" for r in rows)
        await _cleanup()

    @pytest.mark.anyio
    async def test_run_history_excludes_internal_thread_operations(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="success")
        await repo.put(
            "checkpoint-write-1",
            thread_id="t1",
            status="error",
            operation_kind=ThreadOperationKind.checkpoint_write,
        )

        rows = await repo.list_by_thread("t1")

        assert [row["run_id"] for row in rows] == ["r1"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_owner_filter(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", user_id="alice", status="success")
        await repo.put("r2", thread_id="t1", user_id="bob", status="pending")
        rows = await repo.list_by_thread("t1", user_id="alice")
        assert len(rows) == 1
        assert rows[0]["user_id"] == "alice"
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        await repo.delete("r1")
        assert await repo.get("r1") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_noop(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.delete("nope")  # should not raise
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_pending(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="pending")
        await repo.put("r2", thread_id="t2", status="running")
        await repo.put("r3", thread_id="t3", status="pending")
        pending = await repo.list_pending()
        assert len(pending) == 2
        assert all(r["status"] == "pending" for r in pending)
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_inflight_returns_pending_and_running_before_cutoff(self, tmp_path):
        repo = await _make_repo(tmp_path)
        # Each thread can hold at most one pending/running row (partial unique
        # index ``uq_runs_thread_active``), so spread the inflight rows across
        # distinct threads to exercise the before-cutoff filter.
        await repo.put("pending-old", thread_id="t1", status="pending", created_at="2026-01-01T00:00:00+00:00")
        await repo.put("running-old", thread_id="t2", status="running", created_at="2026-01-01T00:00:01+00:00")
        await repo.put("success-old", thread_id="t3", status="success", created_at="2026-01-01T00:00:02+00:00")
        await repo.put("pending-new", thread_id="t4", status="pending", created_at="2026-01-01T00:00:03+00:00")

        inflight = await repo.list_inflight(before="2026-01-01T00:00:02+00:00")

        assert [row["run_id"] for row in inflight] == ["pending-old", "running-old"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        updated = await repo.update_run_completion(
            "r1",
            status="success",
            total_input_tokens=100,
            total_output_tokens=50,
            total_tokens=150,
            llm_call_count=2,
            lead_agent_tokens=120,
            subagent_tokens=20,
            middleware_tokens=10,
            message_count=3,
            last_ai_message="The answer is 42",
            first_human_message="What is the meaning?",
            stop_reason="token_capped",
        )
        row = await repo.get("r1")
        assert updated is True
        assert row["status"] == "success"
        assert row["total_tokens"] == 150
        assert row["llm_call_count"] == 2
        assert row["lead_agent_tokens"] == 120
        assert row["message_count"] == 3
        assert row["last_ai_message"] == "The answer is 42"
        assert row["first_human_message"] == "What is the meaning?"
        assert row["stop_reason"] == "token_capped"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion_returns_false_for_missing_row(self, tmp_path):
        repo = await _make_repo(tmp_path)
        updated = await repo.update_run_completion("missing", status="error", total_tokens=1)
        assert updated is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion_does_not_replace_terminal_status(self, tmp_path):
        """Late completion data cannot rewrite a peer's terminal outcome."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_status("r1", "error", error="peer takeover")

        updated = await repo.update_run_completion("r1", status="success", total_tokens=1)

        row = await repo.get("r1")
        assert updated is False
        assert row["status"] == "error"
        assert row["error"] == "peer takeover"
        await _cleanup()

    @pytest.mark.anyio
    async def test_finalize_completion_if_owned_and_not_cancelled(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put(
            "owned",
            thread_id="owned-thread",
            status="running",
            owner_worker_id="worker-local",
        )
        await repo.put(
            "peer-owned",
            thread_id="peer-thread",
            status="running",
            owner_worker_id="worker-peer",
        )
        await repo.put(
            "cancelled",
            thread_id="cancelled-thread",
            status="running",
            owner_worker_id="worker-local",
        )
        assert await repo.request_cancel("cancelled", action="rollback") == "rollback"

        finalized = await repo.finalize_completion_if_owned_and_not_cancelled(
            "owned",
            expected_owner_worker_id="worker-local",
            status="success",
            total_input_tokens=10,
            total_output_tokens=5,
            total_tokens=15,
            token_usage_by_model={"model-a": {"input_tokens": 10, "output_tokens": 5}},
            message_count=2,
            stop_reason="completed",
        )
        peer_miss = await repo.finalize_completion_if_owned_and_not_cancelled(
            "peer-owned",
            expected_owner_worker_id="worker-local",
            status="success",
            total_tokens=99,
        )
        cancel_miss = await repo.finalize_completion_if_owned_and_not_cancelled(
            "cancelled",
            expected_owner_worker_id="worker-local",
            status="success",
            total_tokens=99,
        )

        owned = await repo.get("owned")
        peer_owned = await repo.get("peer-owned")
        cancelled = await repo.get("cancelled")
        assert finalized is not None
        assert finalized.finalized is True
        assert finalized.durable_write_confirmed is True
        assert owned["status"] == "success"
        assert owned["total_input_tokens"] == 10
        assert owned["total_output_tokens"] == 5
        assert owned["total_tokens"] == 15
        assert owned["token_usage_by_model"] == {"model-a": {"input_tokens": 10, "output_tokens": 5}}
        assert owned["message_count"] == 2
        assert owned["stop_reason"] == "completed"
        assert peer_miss is not None
        assert peer_miss.finalized is False
        assert peer_owned["status"] == "running"
        assert peer_owned["total_tokens"] == 0
        assert cancel_miss is not None
        assert cancel_miss.finalized is False
        assert cancel_miss.cancel_action == "rollback"
        assert cancelled["status"] == "running"
        assert cancelled["total_tokens"] == 0
        await _cleanup()

    @pytest.mark.anyio
    async def test_owner_terminal_cas_requires_live_lease_only_for_active_row(
        self,
        tmp_path,
    ):
        repo = await _make_repo(tmp_path)
        expired = "2000-01-01T00:00:00+00:00"
        try:
            await repo.put(
                "expired-active",
                thread_id="active-thread",
                status="running",
                owner_worker_id="worker-local",
                lease_expires_at=expired,
            )
            await repo.put(
                "expired-terminal",
                thread_id="terminal-thread",
                status="success",
                owner_worker_id="worker-local",
                lease_expires_at=expired,
            )

            stale_active = await repo.finalize_completion_if_owned_and_not_cancelled(
                "expired-active",
                expected_owner_worker_id="worker-local",
                status="success",
                total_tokens=99,
                require_unexpired_lease=True,
            )
            terminal_repair = await repo.finalize_completion_if_owned_and_not_cancelled(
                "expired-terminal",
                expected_owner_worker_id="worker-local",
                status="success",
                total_tokens=17,
                require_unexpired_lease=True,
            )

            active = await repo.get("expired-active")
            terminal = await repo.get("expired-terminal")
            assert stale_active.finalized is False
            assert active is not None
            assert active["status"] == "running"
            assert active["total_tokens"] == 0
            assert terminal_repair.finalized is True
            assert terminal_repair.durable_write_confirmed is True
            assert terminal is not None
            assert terminal["status"] == "success"
            assert terminal["total_tokens"] == 17
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_cancelled_and_same_terminal_owner_cas_persist_full_snapshot(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            await repo.put(
                "cancelled-owned",
                thread_id="cancelled-owned-thread",
                status="running",
                owner_worker_id="worker-local",
            )
            assert await repo.request_cancel("cancelled-owned", action="interrupt") == "interrupt"

            cancelled = await repo.finalize_cancelled_completion_if_owned(
                "cancelled-owned",
                expected_owner_worker_id="worker-local",
                expected_cancel_action="interrupt",
                status="interrupted",
                total_input_tokens=20,
                total_output_tokens=10,
                total_tokens=30,
                llm_call_count=2,
                lead_agent_tokens=21,
                subagent_tokens=7,
                middleware_tokens=2,
                token_usage_by_model={
                    "model-a": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                    }
                },
                message_count=3,
                last_ai_message="partial",
                first_human_message="start",
                stop_reason="cancelled",
            )
            same_terminal = await repo.finalize_completion_if_owned_and_not_cancelled(
                "cancelled-owned",
                expected_owner_worker_id="worker-local",
                status="interrupted",
                total_input_tokens=25,
                total_output_tokens=10,
                total_tokens=35,
                llm_call_count=3,
                lead_agent_tokens=26,
                subagent_tokens=7,
                middleware_tokens=2,
                token_usage_by_model={
                    "model-a": {
                        "input_tokens": 25,
                        "output_tokens": 10,
                        "total_tokens": 35,
                    }
                },
                message_count=4,
                last_ai_message="final partial",
                first_human_message="start",
                stop_reason="cancelled",
            )

            row = await repo.get("cancelled-owned")
            assert cancelled is not None
            assert cancelled.finalized is True
            assert same_terminal is not None
            assert same_terminal.finalized is True
            assert row is not None
            assert row["status"] == "interrupted"
            assert row["cancel_action"] == "interrupt"
            assert row["owner_worker_id"] == "worker-local"
            assert row["total_input_tokens"] == 25
            assert row["total_output_tokens"] == 10
            assert row["total_tokens"] == 35
            assert row["llm_call_count"] == 3
            assert row["lead_agent_tokens"] == 26
            assert row["subagent_tokens"] == 7
            assert row["middleware_tokens"] == 2
            assert row["token_usage_by_model"] == {
                "model-a": {
                    "input_tokens": 25,
                    "output_tokens": 10,
                    "total_tokens": 35,
                }
            }
            assert row["message_count"] == 4
            assert row["last_ai_message"] == "final partial"
            assert row["first_human_message"] == "start"
            assert row["stop_reason"] == "cancelled"

            await repo.put(
                "rollback-owned",
                thread_id="rollback-owned-thread",
                status="running",
                owner_worker_id="worker-local",
            )
            assert await repo.request_cancel("rollback-owned", action="rollback") == "rollback"
            assert await repo.update_status(
                "rollback-owned",
                "interrupted",
            )
            rollback = await repo.finalize_cancelled_completion_if_owned(
                "rollback-owned",
                expected_owner_worker_id="worker-local",
                expected_cancel_action="rollback",
                status="error",
                total_tokens=19,
                message_count=2,
                error="Rolled back by user",
            )
            rollback_row = await repo.get("rollback-owned")
            assert rollback is not None
            assert rollback.finalized is True
            assert rollback_row is not None
            assert rollback_row["status"] == "error"
            assert rollback_row["cancel_action"] == "rollback"
            assert rollback_row["owner_worker_id"] == "worker-local"
            assert rollback_row["error"] == "Rolled back by user"
            assert rollback_row["total_tokens"] == 19
            assert rollback_row["message_count"] == 2

            await repo.put(
                "local-rollback-owned",
                thread_id="local-rollback-owned-thread",
                status="running",
                owner_worker_id="worker-local",
            )
            assert await repo.update_status(
                "local-rollback-owned",
                "interrupted",
            )
            local_rollback = await repo.finalize_completion_if_owned_and_not_cancelled(
                "local-rollback-owned",
                expected_owner_worker_id="worker-local",
                status="error",
                total_tokens=11,
                error="Rolled back by user",
            )
            local_rollback_row = await repo.get("local-rollback-owned")
            assert local_rollback is not None
            assert local_rollback.finalized is True
            assert local_rollback_row is not None
            assert local_rollback_row["status"] == "error"
            assert local_rollback_row.get("cancel_action") is None
            assert local_rollback_row["owner_worker_id"] == "worker-local"
            assert local_rollback_row["error"] == "Rolled back by user"
            assert local_rollback_row["total_tokens"] == 11
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_insert_terminal_completion_if_absent_never_overwrites(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            run_payload = {
                "thread_id": "terminal-thread",
                "status": "success",
                "operation_kind": "run",
                "multitask_strategy": "reject",
                "metadata": {"source": "local"},
                "kwargs": {},
                "owner_worker_id": "worker-local",
            }
            completion_payload = {
                "status": "success",
                "total_tokens": 17,
                "message_count": 2,
                "last_ai_message": "done",
                "stop_reason": "completed",
            }

            inserted = await repo.insert_terminal_completion_if_absent(
                "terminal-new",
                run_payload=run_payload,
                completion_payload=completion_payload,
            )
            await repo.put(
                "terminal-conflict",
                thread_id="peer-thread",
                status="running",
                owner_worker_id="worker-peer",
            )
            conflict = await repo.insert_terminal_completion_if_absent(
                "terminal-conflict",
                run_payload=run_payload,
                completion_payload=completion_payload,
            )

            created = await repo.get("terminal-new")
            peer = await repo.get("terminal-conflict")
            assert inserted is True
            assert created is not None
            assert created["status"] == "success"
            assert created["total_tokens"] == 17
            assert created["message_count"] == 2
            assert created["last_ai_message"] == "done"
            assert created["stop_reason"] == "completed"
            assert conflict is False
            assert peer is not None
            assert peer["status"] == "running"
            assert peer["owner_worker_id"] == "worker-peer"
            assert peer["total_tokens"] == 0
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_terminal_eviction_repairs_full_sql_snapshot_without_zeroing_or_chasing_truncation(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            manager = RunManager(store=repo, worker_id="worker-local")
            record = await manager.create("thread-sql-completion-repair")
            long_last = "a" * 2200
            long_first = "h" * 2300
            await manager.set_status(
                record.run_id,
                RunStatus.success,
                stop_reason="completed",
                persist=False,
            )
            record.total_input_tokens = 100
            record.total_output_tokens = 50
            record.total_tokens = 151
            record.llm_call_count = 2
            record.lead_agent_tokens = 120
            record.subagent_tokens = 20
            record.middleware_tokens = 10
            record.token_usage_by_model = {"model-a": {"input_tokens": 100, "output_tokens": 50}}
            record.message_count = 3
            record.last_ai_message = long_last
            record.first_human_message = long_first

            assert await manager._evict_if_durable_terminal(record.run_id) is True

            stored = await repo.get(record.run_id)
            assert stored is not None
            assert stored["status"] == RunStatus.success.value
            assert stored["total_input_tokens"] == 100
            assert stored["total_output_tokens"] == 50
            assert stored["total_tokens"] == 151
            assert stored["llm_call_count"] == 2
            assert stored["lead_agent_tokens"] == 120
            assert stored["subagent_tokens"] == 20
            assert stored["middleware_tokens"] == 10
            assert stored["token_usage_by_model"] == {"model-a": {"input_tokens": 100, "output_tokens": 50}}
            assert stored["message_count"] == 3
            assert stored["last_ai_message"] == long_last[:2000]
            assert stored["first_human_message"] == long_first[:2000]
            assert stored["stop_reason"] == "completed"
            assert record.run_id not in manager._runs
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_manager_completion_does_not_overwrite_sql_peer_takeover(self, tmp_path):
        repo = await _make_repo(tmp_path)
        try:
            manager = RunManager(store=repo, worker_id="worker-local")
            record = await manager.create("thread-sql-peer-takeover")
            await manager.set_status(
                record.run_id,
                RunStatus.error,
                error="local worker failed",
                stop_reason="tool_capped",
                persist=False,
            )
            assert await repo.claim_for_takeover(
                record.run_id,
                grace_seconds=0,
                error="peer lease takeover",
                stop_reason="orphan_recovered",
            )

            await manager.update_run_completion(
                record.run_id,
                status=RunStatus.error.value,
                total_tokens=99,
                message_count=7,
            )

            stored = await repo.get(record.run_id)
            assert stored is not None
            assert stored["status"] == RunStatus.error.value
            assert stored["error"] == "peer lease takeover"
            assert stored["stop_reason"] == "orphan_recovered"
            assert stored["owner_worker_id"] is None
            assert stored["lease_expires_at"] is None
            assert stored["total_tokens"] == 0
            assert stored["message_count"] == 0
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_metadata_preserved(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", metadata={"key": "value"})
        row = await repo.get("r1")
        assert row["metadata"] == {"key": "value"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_kwargs_with_non_serializable(self, tmp_path):
        """kwargs containing non-JSON-serializable objects should be safely handled."""
        repo = await _make_repo(tmp_path)

        class Dummy:
            pass

        await repo.put("r1", thread_id="t1", kwargs={"obj": Dummy()})
        row = await repo.get("r1")
        assert "obj" in row["kwargs"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_completion_preserves_existing_fields(self, tmp_path):
        """update_run_completion does not overwrite thread_id or assistant_id."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", assistant_id="agent1", status="running")
        await repo.update_run_completion("r1", status="success", total_tokens=100)
        row = await repo.get("r1")
        assert row["thread_id"] == "t1"
        assert row["assistant_id"] == "agent1"
        assert row["total_tokens"] == 100
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_progress_keeps_status_running(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_run_progress(
            "r1",
            total_input_tokens=40,
            total_output_tokens=10,
            total_tokens=50,
            llm_call_count=1,
            message_count=2,
            last_ai_message="partial answer",
        )
        row = await repo.get("r1")
        assert row["status"] == "running"
        assert row["total_tokens"] == 50
        assert row["llm_call_count"] == 1
        assert row["message_count"] == 2
        assert row["last_ai_message"] == "partial answer"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_progress_preserves_omitted_fields(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_run_progress(
            "r1",
            total_input_tokens=40,
            total_output_tokens=10,
            total_tokens=50,
            llm_call_count=1,
            lead_agent_tokens=30,
            subagent_tokens=20,
            message_count=2,
        )

        await repo.update_run_progress("r1", total_tokens=60, last_ai_message="updated")

        row = await repo.get("r1")
        assert row["total_input_tokens"] == 40
        assert row["total_output_tokens"] == 10
        assert row["total_tokens"] == 60
        assert row["llm_call_count"] == 1
        assert row["lead_agent_tokens"] == 30
        assert row["subagent_tokens"] == 20
        assert row["message_count"] == 2
        assert row["last_ai_message"] == "updated"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_run_progress_skips_terminal_runs(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="running")
        await repo.update_run_completion("r1", status="success", total_tokens=100, llm_call_count=1)

        await repo.update_run_progress("r1", total_tokens=200, llm_call_count=2)

        row = await repo.get("r1")
        assert row["status"] == "success"
        assert row["total_tokens"] == 100
        assert row["llm_call_count"] == 1
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_counts_completed_runs_only(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("success-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "success-run",
            status="success",
            total_input_tokens=70,
            total_output_tokens=30,
            total_tokens=100,
            lead_agent_tokens=80,
            subagent_tokens=15,
            middleware_tokens=5,
        )
        await repo.put("error-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "error-run",
            status="error",
            total_input_tokens=20,
            total_output_tokens=30,
            total_tokens=50,
            lead_agent_tokens=40,
            subagent_tokens=10,
        )
        await repo.put("running-run", thread_id="t1", status="running")
        await repo.update_run_completion(
            "running-run",
            status="running",
            total_input_tokens=900,
            total_output_tokens=99,
            total_tokens=999,
            lead_agent_tokens=999,
        )
        await repo.put("other-thread-run", thread_id="t2", status="running")
        await repo.update_run_completion(
            "other-thread-run",
            status="success",
            total_tokens=888,
            lead_agent_tokens=888,
        )

        agg = await repo.aggregate_tokens_by_thread("t1")

        assert agg["total_tokens"] == 150
        assert agg["total_input_tokens"] == 90
        assert agg["total_output_tokens"] == 60
        assert agg["total_runs"] == 2
        assert agg["by_model"] == {"unknown": {"tokens": 150, "runs": 2}}
        assert agg["by_caller"] == {
            "lead_agent": 120,
            "subagent": 25,
            "middleware": 5,
        }
        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_can_include_active_runs(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("success-run", thread_id="t1", status="running")
        await repo.update_run_completion("success-run", status="success", total_tokens=100, lead_agent_tokens=100)
        await repo.put("running-run", thread_id="t1", status="running")
        await repo.update_run_progress("running-run", total_tokens=25, lead_agent_tokens=20, subagent_tokens=5)

        without_active = await repo.aggregate_tokens_by_thread("t1")
        with_active = await repo.aggregate_tokens_by_thread("t1", include_active=True)

        assert without_active["total_tokens"] == 100
        assert without_active["total_runs"] == 1
        assert with_active["total_tokens"] == 125
        assert with_active["total_runs"] == 2
        assert with_active["by_caller"] == {
            "lead_agent": 120,
            "subagent": 5,
            "middleware": 0,
        }
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_ordered_desc(self, tmp_path):
        """list_by_thread returns newest first."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", status="success", created_at="2024-01-01T00:00:00+00:00")
        await repo.put("r2", thread_id="t1", status="pending", created_at="2024-01-02T00:00:00+00:00")
        rows = await repo.list_by_thread("t1")
        assert rows[0]["run_id"] == "r2"
        assert rows[1]["run_id"] == "r1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_list_by_thread_limit(self, tmp_path):
        repo = await _make_repo(tmp_path)
        # Only one row can be pending/running per thread; mark earlier ones
        # terminal so the partial unique index still holds.
        for i in range(4):
            await repo.put(f"r{i}", thread_id="t1", status="success")
        await repo.put("r4", thread_id="t1", status="pending")
        rows = await repo.list_by_thread("t1", limit=2)
        assert len(rows) == 2
        await _cleanup()

    @pytest.mark.anyio
    async def test_owner_none_returns_all(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", user_id="alice", status="success")
        await repo.put("r2", thread_id="t1", user_id="bob", status="pending")
        rows = await repo.list_by_thread("t1", user_id=None)
        assert len(rows) == 2
        await _cleanup()

    @pytest.mark.anyio
    async def test_model_name_persistence(self, tmp_path):
        """RunRepository should persist, normalize, and truncate model_name correctly via SQL."""
        from deerflow.persistence.engine import get_session_factory, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        repo = RunRepository(get_session_factory())

        await repo.put("run-1", thread_id="thread-1", model_name="gpt-4o", status="success")
        row = await repo.get("run-1")
        assert row is not None
        assert row["model_name"] == "gpt-4o"

        long_name = "a" * 200
        await repo.put("run-2", thread_id="thread-1", model_name=long_name, status="success")
        row2 = await repo.get("run-2")
        assert row2["model_name"] == "a" * 128

        await repo.put("run-3", thread_id="thread-1", model_name=123, status="success")
        row3 = await repo.get("run-3")
        assert row3["model_name"] == "123"

        await repo.put("run-4", thread_id="thread-1", model_name=None, status="pending")
        row4 = await repo.get("run-4")
        assert row4["model_name"] is None

        await _cleanup()

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_returns_zeros_when_no_rows(self):
        """Empty thread aggregates to all-zero totals, no model buckets, and a
        single query — replaces the older test that pinned the now-removed
        ``GROUP BY coalesce(model_name)`` shape (issue #3645 reduces by_model
        in Python from each row's per-model JSON column instead)."""
        captured = []

        class FakeResult:
            def all(self):
                return []

        class FakeSession:
            async def execute(self, stmt):
                captured.append(stmt)
                return FakeResult()

        class FakeSessionContext:
            async def __aenter__(self):
                return FakeSession()

            async def __aexit__(self, exc_type, exc, tb):
                return None

        repo = RunRepository(lambda: FakeSessionContext())

        agg = await repo.aggregate_tokens_by_thread("t1")
        assert agg == {
            "total_tokens": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_runs": 0,
            "by_model": {},
            "by_caller": {"lead_agent": 0, "subagent": 0, "middleware": 0},
        }
        assert len(captured) == 1

    @pytest.mark.anyio
    async def test_aggregate_tokens_by_thread_compiles_on_postgres_dialect(self):
        """Compile-smoke the new SELECT on the postgres dialect.

        The project ships both SQLite and Postgres backends. The new aggregation
        projects ``RunRow.token_usage_by_model`` (a JSON column) directly into
        the row set instead of grouping on a scalar, so the SQL needs to compile
        cleanly under PG's JSON/JSONB binding too. Pins:
          * the JSON column is selected by name (PG would otherwise need a
            ``::jsonb`` cast or coalesce around it)
          * there is no GROUP BY / aggregate function left (the per-model
            reduction now happens in Python — see issue #3645)
        """

        captured = []

        class FakeResult:
            def all(self):
                return []

        class FakeSession:
            async def execute(self, stmt):
                captured.append(stmt)
                return FakeResult()

        class FakeSessionContext:
            async def __aenter__(self):
                return FakeSession()

            async def __aexit__(self, exc_type, exc, tb):
                return None

        repo = RunRepository(lambda: FakeSessionContext())
        await repo.aggregate_tokens_by_thread("t1")

        compiled = str(captured[0].compile(dialect=postgresql.dialect()))
        assert "token_usage_by_model" in compiled
        assert "GROUP BY" not in compiled.upper()

    @pytest.mark.anyio
    async def test_run_manager_hydrates_store_only_run_from_sql(self, tmp_path):
        """RunManager should hydrate historical runs from SQL-backed store."""
        repo = await _make_repo(tmp_path)
        await repo.put(
            "sql-store-only",
            thread_id="thread-1",
            assistant_id="lead_agent",
            status="success",
            metadata={"source": "sql"},
            kwargs={"input": "value"},
            model_name="model-a",
        )
        manager = RunManager(store=repo)

        record = await manager.get("sql-store-only")
        rows = await manager.list_by_thread("thread-1")

        assert record is not None
        assert record.run_id == "sql-store-only"
        assert record.status == RunStatus.success
        assert record.metadata == {"source": "sql"}
        assert record.kwargs == {"input": "value"}
        assert record.model_name == "model-a"
        assert [run.run_id for run in rows] == ["sql-store-only"]
        await _cleanup()

    @pytest.mark.anyio
    async def test_run_manager_cancel_persists_interrupted_status_to_sql(self, tmp_path):
        """RunManager.cancel should write interrupted status to SQL-backed store."""
        repo = await _make_repo(tmp_path)
        manager = RunManager(store=repo)
        record = await manager.create("thread-1")
        await manager.set_status(record.run_id, RunStatus.running)

        cancelled = await manager.cancel(record.run_id)
        row = await repo.get(record.run_id)

        assert cancelled == CancelOutcome.cancelled
        assert row is not None
        assert row["status"] == "interrupted"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_model_name(self, tmp_path):
        """RunRepository.update_model_name should update model_name for existing run."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", model_name="initial-model")
        await repo.update_model_name("r1", "updated-model")
        row = await repo.get("r1")
        assert row["model_name"] == "updated-model"
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_model_name_normalizes_value(self, tmp_path):
        """RunRepository.update_model_name should normalize and truncate model_name."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1")
        long_name = "a" * 200
        await repo.update_model_name("r1", long_name)
        row = await repo.get("r1")
        assert row["model_name"] == "a" * 128
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_model_name_to_none(self, tmp_path):
        """RunRepository.update_model_name should allow setting model_name to None."""
        repo = await _make_repo(tmp_path)
        await repo.put("r1", thread_id="t1", model_name="initial-model")
        await repo.update_model_name("r1", None)
        row = await repo.get("r1")
        assert row["model_name"] is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_run_manager_update_model_name_persists_to_sql(self, tmp_path):
        """RunManager.update_model_name should persist to SQL-backed store without integrity error."""
        repo = await _make_repo(tmp_path)
        manager = RunManager(store=repo)
        record = await manager.create("thread-1")

        await manager.update_model_name(record.run_id, "gpt-4o")

        row = await repo.get(record.run_id)
        assert row is not None
        assert row["model_name"] == "gpt-4o"
        await _cleanup()

    @pytest.mark.anyio
    async def test_run_manager_update_model_name_twice(self, tmp_path):
        """RunManager.update_model_name should support multiple updates."""
        repo = await _make_repo(tmp_path)
        manager = RunManager(store=repo)
        record = await manager.create("thread-1")

        await manager.update_model_name(record.run_id, "model-1")
        await manager.update_model_name(record.run_id, "model-2")

        row = await repo.get(record.run_id)
        assert row["model_name"] == "model-2"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_thread_operation_atomic_rejects_unique_violation(self, tmp_path):
        """reject path against a real SQLite-backed store must surface as ConflictError, not raw IntegrityError.

        The partial unique index ``uq_runs_thread_active`` is created by
        ``Base.metadata.create_all`` on SQLite too. Every other atomic-create
        test in the suite uses ``MemoryRunStore``, which raises ConflictError
        directly and never exercises the manager's
        ``_is_unique_violation``-based conversion. This test is the load-bearing
        coverage for that branch on a real DB: pre-insert an active run on
        thread T, then attempt a reject-strategy create for the same thread,
        and assert ConflictError (HTTP 409) — not a leaking IntegrityError
        (HTTP 500).
        """
        from datetime import UTC, datetime, timedelta

        from deerflow.config.run_ownership_config import RunOwnershipConfig

        repo = await _make_repo(tmp_path)
        manager = RunManager(
            store=repo,
            run_ownership_config=RunOwnershipConfig(
                lease_seconds=30,
                grace_seconds=10,
                heartbeat_enabled=False,
            ),
        )

        # Pre-insert an active run on thread T directly through the store so
        # the partial unique index has something to enforce on the second insert.
        lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.create_thread_operation_atomic(
            "run-A",
            thread_id="thread-T",
            owner_worker_id="worker-A",
            lease_expires_at=lease,
            multitask_strategy="reject",
            created_at=datetime.now(UTC).isoformat(),
        )

        # Second reject-strategy create against the same thread must convert the
        # underlying IntegrityError into ConflictError via ``_is_unique_violation``.
        with pytest.raises(ConflictError, match="already has an active run"):
            await manager.create_or_reject(
                "thread-T",
                multitask_strategy="reject",
            )

        await _cleanup()

    @pytest.mark.anyio
    async def test_run_admission_reuses_process_wide_idempotency_key(self, tmp_path):
        repo = await _make_repo(tmp_path)
        ownership = RunOwnershipConfig(
            lease_seconds=30,
            grace_seconds=10,
            heartbeat_enabled=True,
        )
        first_manager = RunManager(
            store=repo,
            worker_id="worker-a",
            run_ownership_config=ownership,
        )
        second_manager = RunManager(
            store=repo,
            worker_id="worker-b",
            run_ownership_config=ownership,
        )

        first = await first_manager.create_or_reject(
            "thread-T",
            user_id="test-user-autouse",
            idempotency_key="mcp-task:task-1:1:0",
        )
        await first_manager.try_start(first.run_id)
        reused = await second_manager.create_or_reject(
            "thread-T",
            user_id="test-user-autouse",
            idempotency_key="mcp-task:task-1:1:0",
        )

        assert reused.run_id == first.run_id
        assert reused.idempotency_reused is True
        assert reused.store_only is True
        assert reused.run_id not in second_manager._runs
        assert len(await repo.list_by_thread("thread-T", user_id="test-user-autouse")) == 1

        outcome = await second_manager.cancel(reused.run_id, action="rollback")
        stored = await repo.get(first.run_id, user_id="test-user-autouse")
        assert outcome == CancelOutcome.requested
        assert stored is not None
        assert stored["status"] == RunStatus.running.value
        assert stored["owner_worker_id"] == "worker-a"
        assert stored["cancel_action"] == "rollback"

        await first_manager._renew_leases()
        assert first.abort_event.is_set() is True
        assert first.abort_action == "rollback"
        await _cleanup()

    @pytest.mark.anyio
    async def test_checkpoint_write_reservation_blocks_interrupt_run_on_sql_store(self, tmp_path):
        """An interrupt-strategy run cannot displace a durable checkpoint writer."""
        repo = await _make_repo(tmp_path)
        compaction_worker = RunManager(store=repo, worker_id="worker-a")
        run_worker = RunManager(store=repo, worker_id="worker-b")

        async with compaction_worker.reserve_thread_operation("thread-T", kind=ThreadOperationKind.checkpoint_write):
            with pytest.raises(ConflictError, match="checkpoint write"):
                await run_worker.create_or_reject("thread-T", multitask_strategy="interrupt")

        assert await repo.list_by_thread("thread-T") == []
        admitted = await run_worker.create_or_reject("thread-T")
        assert admitted.status == RunStatus.pending
        await _cleanup()

    @pytest.mark.anyio
    async def test_reservation_release_uses_record_user_without_ambient_context(self, tmp_path):
        """Release must not depend on the request ContextVar still being set."""
        repo = await _make_repo(tmp_path)
        manager = RunManager(store=repo)

        async with manager.reserve_thread_operation(
            "thread-T",
            kind=ThreadOperationKind.checkpoint_write,
            user_id="reservation-owner",
        ):
            inflight = await repo.list_inflight()
            assert len(inflight) == 1
            assert inflight[0]["user_id"] == "reservation-owner"

        assert await repo.list_inflight() == []
        await _cleanup()

    @pytest.mark.anyio
    async def test_interrupt_reclaims_expired_checkpoint_write_reservation_on_sql_store(self, tmp_path):
        """An expired durable checkpoint writer is immediately reclaimable."""
        repo = await _make_repo(tmp_path)
        expired = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
        await repo.put(
            "checkpoint-write-1",
            thread_id="thread-T",
            status="pending",
            operation_kind=ThreadOperationKind.checkpoint_write,
            owner_worker_id="dead-worker",
            lease_expires_at=expired,
            created_at=expired,
        )
        manager = RunManager(store=repo, worker_id="worker-b")

        admitted = await manager.create_or_reject("thread-T", multitask_strategy="interrupt")

        assert admitted.status == RunStatus.pending
        stale = await repo.get("checkpoint-write-1")
        assert stale is not None
        assert stale["status"] == "interrupted"
        assert stale["owner_worker_id"] == "worker-b"
        await _cleanup()

    @pytest.mark.anyio
    async def test_is_unique_violation_detects_real_sqlite_integrity_error(self, tmp_path):
        """``_is_unique_violation`` must return True for a real SQLite IntegrityError.

        SQLite raises ``UNIQUE constraint failed: runs.uq_runs_thread_active``
        which contains "unique" but neither "violat" nor "duplicate" — the
        previous substring-only heuristic returned False on SQLite, leaking the
        raw IntegrityError. This test triggers a real violation against the
        partial unique index and feeds the resulting SQLAlchemy IntegrityError
        (with the wrapped sqlite3.IntegrityError on ``.orig``) through the
        detector to assert True.
        """
        import sqlite3

        from sqlalchemy.exc import IntegrityError

        from deerflow.runtime.runs.manager import _is_unique_violation

        repo = await _make_repo(tmp_path)

        # First insert succeeds; second collides on the partial unique index.
        await repo.put("first", thread_id="thread-T", status="pending")
        with pytest.raises(IntegrityError) as exc_info:
            await repo.put("second", thread_id="thread-T", status="pending")

        # The wrapped driver exception must be a sqlite3 IntegrityError carrying
        # SQLITE_CONSTRAINT_UNIQUE. Walk the chain so we assert on the actual
        # driver-level signal, not the SQLAlchemy wrapper.
        driver = exc_info.value.orig
        assert isinstance(driver, sqlite3.IntegrityError)
        assert driver.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE

        # The detector must return True regardless of message phrasing.
        assert _is_unique_violation(exc_info.value) is True

        await _cleanup()

    @pytest.mark.anyio
    async def test_is_unique_violation_does_not_misclassify_application_exception(self):
        """Message fallbacks must not fire on non-IntegrityError exceptions.

        A ``ValueError`` / ``RuntimeError`` whose ``str()`` happens to
        contain ``"duplicate key"`` or ``"unique" + "violat"`` substrings
        must NOT be classified as a unique violation — that would silently
        mask real application bugs as HTTP 409 conflicts instead of 500.
        Pre-fix the substring-only fallback fired regardless of exception
        type. The fix gates the fallback on
        ``isinstance(current, (SAIntegrityError, sqlite3.IntegrityError))``.
        """
        from deerflow.runtime.runs.manager import _is_unique_violation

        assert _is_unique_violation(ValueError("duplicate key in input data: 'email'")) is False
        assert _is_unique_violation(RuntimeError("unique violat detected in config")) is False
        assert _is_unique_violation(Exception("unique constraint failed (in a unit test mock)")) is False

    @pytest.mark.anyio
    async def test_is_unique_violation_detects_psycopg3_sqlstate(self):
        """psycopg3 exposes the error code via ``sqlstate``, not ``pgcode``.

        On Postgres (the only supported multi-worker backend), psycopg3's
        ``sqlstate=23505`` must be detected as a unique violation without
        falling through to the message-substring fallback.
        """
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        from deerflow.runtime.runs.manager import _is_unique_violation

        # Simulate psycopg3's sqlstate attribute on a wrapped IntegrityError
        dbapi_err = Exception()
        dbapi_err.sqlstate = "23505"  # psycopg3 uses sqlstate

        sa_err = SAIntegrityError(
            "duplicate key value violates unique constraint",
            params=None,
            orig=dbapi_err,
        )

        assert _is_unique_violation(sa_err) is True

    @pytest.mark.anyio
    async def test_create_thread_operation_atomic_tolerates_tz_naive_lease_on_sqlite(self, tmp_path):
        """Interrupt path must not raise TypeError comparing naive vs aware datetimes.

        SQLite drops tzinfo on read despite ``DateTime(timezone=True)`` (see
        the comment in ``RunRepository._row_to_dict``). The interrupt branch
        of ``create_thread_operation_atomic`` compares ``row.lease_expires_at`` against
        the aware ``cutoff = datetime.now(UTC) - ...`` in Python. Under
        default config (heartbeat disabled) leases are always NULL so the
        ``is not None`` check short-circuits, but there is no guard against
        ``heartbeat_enabled=true`` on SQLite — a naive lease would raise
        ``TypeError: can't compare offset-naive and offset-aware datetimes``
        and surface as an opaque 500.

        Pre-fix this test fails with TypeError; post-fix it raises
        ConflictError (the live other-worker run blocks the interrupt).
        """
        from datetime import UTC, datetime, timedelta

        repo = await _make_repo(tmp_path)

        # Seed an active run owned by another worker with a still-valid lease.
        # The lease value is stored as ISO; SQLite reads it back as a tz-naive
        # datetime — exactly the shape that triggered the bug.
        valid_lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.create_thread_operation_atomic(
            "valid-lease-run",
            thread_id="thread-T",
            owner_worker_id="other-worker",
            lease_expires_at=valid_lease,
            multitask_strategy="reject",
            created_at=datetime.now(UTC).isoformat(),
        )

        # The interrupt path must surface a clean ConflictError, not a
        # TypeError from the naive-vs-aware comparison.
        with pytest.raises(ConflictError, match="another worker"):
            await repo.create_thread_operation_atomic(
                "run-new",
                thread_id="thread-T",
                owner_worker_id="w1",
                lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                multitask_strategy="interrupt",
                created_at=datetime.now(UTC).isoformat(),
            )

        await _cleanup()

    # ------------------------------------------------------------------
    # claim_for_takeover SQL path
    # ------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_claim_for_takeover_succeeds_with_expired_lease(self, tmp_path):
        repo = await _make_repo(tmp_path)
        grace = 10
        expired = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
        await repo.put("run-1", thread_id="t1", status="running", owner_worker_id="w-a", lease_expires_at=expired, created_at=datetime.now(UTC).isoformat())
        assert await repo.request_cancel("run-1", action="rollback") == "rollback"

        ok = await repo.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
        assert ok is True

        row = await repo.get("run-1")
        assert row["status"] == "error"
        assert row["error"] == "claimed"
        assert row["owner_worker_id"] is None
        assert row["lease_expires_at"] is None
        assert row["cancel_action"] == "rollback"

        stale_owner = await repo.finalize_completion_if_owned_and_not_cancelled(
            "run-1",
            expected_owner_worker_id="w-a",
            status="error",
            total_tokens=99,
        )
        assert stale_owner is not None
        assert stale_owner.finalized is False
        assert stale_owner.cancel_action is None
        row = await repo.get("run-1")
        assert row["error"] == "claimed"
        assert row["total_tokens"] == 0
        await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_fails_on_valid_lease(self, tmp_path):
        repo = await _make_repo(tmp_path)
        grace = 10
        valid = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.put("run-1", thread_id="t1", status="running", owner_worker_id="w-a", lease_expires_at=valid, created_at=datetime.now(UTC).isoformat())

        ok = await repo.claim_for_takeover("run-1", grace_seconds=grace, error="claimed")
        assert ok is False

        row = await repo.get("run-1")
        assert row["status"] == "running"
        await _cleanup()

    @pytest.mark.anyio
    async def test_request_cancel_is_returned_by_owner_lease_renewal(self, tmp_path):
        """The SQL store must atomically carry the first cancel action to the owner."""
        repo = await _make_repo(tmp_path)
        lease = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        await repo.put(
            "run-1",
            thread_id="t1",
            status="running",
            owner_worker_id="worker-a",
            lease_expires_at=lease,
        )

        assert await repo.request_cancel("run-1", action="rollback") == "rollback"
        assert await repo.request_cancel("run-1", action="interrupt") == "rollback"

        renewal = await repo.renew_lease(
            "run-1",
            owner_worker_id="worker-a",
            lease_expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        )

        assert renewal.renewed is True
        assert renewal.cancel_action == "rollback"
        row = await repo.get("run-1")
        assert row["cancel_action"] == "rollback"
        assert row["cancel_requested_at"] is not None
        await _cleanup()

    @pytest.mark.anyio
    async def test_request_cancel_rejects_terminal_run(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("run-1", thread_id="t1", status="success")

        assert await repo.request_cancel("run-1", action="interrupt") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_cancel_request_wins_before_owner_completion(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put(
            "run-1",
            thread_id="t1",
            status="running",
            owner_worker_id="worker-a",
        )

        assert await repo.request_cancel("run-1", action="rollback") == "rollback"
        result = await repo.finalize_if_not_cancelled(
            "run-1",
            status="success",
        )

        assert result.finalized is False
        assert result.cancel_action == "rollback"
        assert (await repo.get("run-1"))["status"] == "running"
        await _cleanup()

    @pytest.mark.anyio
    async def test_owner_completion_wins_before_cancel_request(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put(
            "run-1",
            thread_id="t1",
            status="running",
            owner_worker_id="worker-a",
        )

        result = await repo.finalize_if_not_cancelled(
            "run-1",
            status="success",
        )

        assert result.finalized is True
        assert result.durable_write_confirmed is True
        assert await repo.request_cancel("run-1", action="rollback") is None
        assert (await repo.get("run-1"))["status"] == "success"
        await _cleanup()

    @pytest.mark.anyio
    async def test_reconciliation_skips_run_renewed_after_scan(self, tmp_path):
        """The SQL takeover CAS must reject a candidate renewed after its scan."""
        repo = await _make_repo(tmp_path)
        grace = 10
        run_id = "renewed-after-scan"
        owner_worker_id = "worker-alive"
        try:
            await repo.put(
                run_id,
                thread_id="t1",
                status="running",
                owner_worker_id=owner_worker_id,
                lease_expires_at=(datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat(),
                created_at=(datetime.now(UTC) - timedelta(seconds=120)).isoformat(),
            )
            original_scan = repo.list_inflight_with_expired_lease

            async def scan_then_renew(*, before=None, grace_seconds=10):
                rows = await original_scan(before=before, grace_seconds=grace_seconds)
                renewed = await repo.update_lease(
                    run_id,
                    owner_worker_id=owner_worker_id,
                    lease_expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
                )
                assert renewed is True
                return rows

            repo.list_inflight_with_expired_lease = scan_then_renew
            manager = RunManager(store=repo)

            recovered = await manager.reconcile_orphaned_inflight_runs(error="orphaned")

            row = await repo.get(run_id)
            assert recovered == []
            assert row is not None
            assert row["status"] == "running"
            assert datetime.fromisoformat(row["lease_expires_at"]) > datetime.now(UTC)
        finally:
            await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_succeeds_with_null_lease(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("run-null", thread_id="t1", status="running", created_at=datetime.now(UTC).isoformat())

        ok = await repo.claim_for_takeover("run-null", grace_seconds=10, error="claimed")
        assert ok is True

        row = await repo.get("run-null")
        assert row["status"] == "error"
        await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_fails_on_terminal_row(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.put("run-done", thread_id="t1", status="success", created_at=datetime.now(UTC).isoformat())

        ok = await repo.claim_for_takeover("run-done", grace_seconds=10, error="claimed")
        assert ok is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_claim_for_takeover_nonexistent_run(self, tmp_path):
        repo = await _make_repo(tmp_path)
        ok = await repo.claim_for_takeover("no-such-run", grace_seconds=10, error="claimed")
        assert ok is False
        await _cleanup()
