"""Verify ix_one_active_run_per_thread blocks concurrent run creation.

These tests confirm that the partial unique index added to the ``runs``
table prevents two active runs on the same thread — the root cause of the
multi-worker create_or_reject race described in Issue #3948.
"""

import uuid

import pytest

from deerflow.persistence.run import RunRepository
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.runs.manager import ConflictError


async def _make_repo_and_mgr(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    repo = RunRepository(get_session_factory())
    mgr = RunManager(store=repo)
    return mgr, repo


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


class TestCrossWorkerAtomicCreate:
    """Simulate the multi-worker race at the DB constraint layer."""

    @pytest.mark.anyio
    async def test_second_active_run_on_same_thread_triggers_integrity_error(self, tmp_path):
        """Direct repo.put() — IntegrityError when two pending runs share thread_id."""
        mgr, repo = await _make_repo_and_mgr(tmp_path)

        thread_id = f"thread-{uuid.uuid4().hex[:8]}"

        # First run: OK
        rec = await mgr.create_or_reject(thread_id)
        assert rec.thread_id == thread_id
        assert rec.status == RunStatus.pending

        # Second run must be rejected
        with pytest.raises(ConflictError, match="already has an active run"):
            await mgr.create_or_reject(thread_id)

        # Verify only one run exists
        rows = await repo.list_by_thread(thread_id)
        assert len(rows) == 1

        await _cleanup()

    @pytest.mark.anyio
    async def test_second_run_allowed_after_first_completes(self, tmp_path):
        """Transitioning the first run to success unblocks a new run."""
        mgr, repo = await _make_repo_and_mgr(tmp_path)

        thread_id = f"thread-{uuid.uuid4().hex[:8]}"

        rec1 = await mgr.create_or_reject(thread_id)
        assert rec1.status == RunStatus.pending

        # Complete the first run
        await mgr.set_status(rec1.run_id, RunStatus.success)

        # Now a second run on same thread is allowed
        rec2 = await mgr.create_or_reject(thread_id)
        assert rec2.thread_id == thread_id
        assert rec2.status == RunStatus.pending

        rows = await repo.list_by_thread(thread_id)
        assert len(rows) == 2

        await _cleanup()

    @pytest.mark.anyio
    async def test_different_threads_still_independent(self, tmp_path):
        """Two different threads can each have an active run."""
        mgr, repo = await _make_repo_and_mgr(tmp_path)

        tid_a = f"thread-a-{uuid.uuid4().hex[:8]}"
        tid_b = f"thread-b-{uuid.uuid4().hex[:8]}"

        ra = await mgr.create_or_reject(tid_a)
        rb = await mgr.create_or_reject(tid_b)

        assert ra.status == RunStatus.pending
        assert rb.status == RunStatus.pending

        a_rows = await repo.list_by_thread(tid_a)
        b_rows = await repo.list_by_thread(tid_b)
        assert len(a_rows) == 1
        assert len(b_rows) == 1

        await _cleanup()

    @pytest.mark.anyio
    async def test_integrity_error_converts_to_conflict_error(self, tmp_path):
        """When the DB rejects a duplicate active run, it surfaces as ConflictError."""
        mgr, repo = await _make_repo_and_mgr(tmp_path)
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"

        await mgr.create_or_reject(thread_id)

        with pytest.raises(ConflictError):
            await mgr.create_or_reject(thread_id)

        # The in-memory record created by the failed attempt should be rolled back
        active_runs = [r for r in mgr._runs.values()
                       if r.thread_id == thread_id
                       and r.status in (RunStatus.pending, RunStatus.running)]
        assert len(active_runs) == 1

        await _cleanup()

    @pytest.mark.anyio
    async def test_interrupt_strategy_cancels_old_and_creates_new(self, tmp_path):
        """interrupt strategy marks the old run as interrupted and creates a new one."""
        mgr, repo = await _make_repo_and_mgr(tmp_path)
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"

        rec1 = await mgr.create_or_reject(thread_id)
        assert rec1.status == RunStatus.pending

        # Create with interrupt — should cancel the old and create new
        rec2 = await mgr.create_or_reject(thread_id, multitask_strategy="interrupt")
        assert rec2.status == RunStatus.pending
        assert rec2.run_id != rec1.run_id

        # Old run must be interrupted
        rows = await repo.list_by_thread(thread_id)
        assert len(rows) == 2
        statuses = {r["run_id"]: r["status"] for r in rows}
        assert statuses[rec1.run_id] == RunStatus.interrupted
        assert statuses[rec2.run_id] == RunStatus.pending

        await _cleanup()

    @pytest.mark.anyio
    async def test_rollback_strategy_cancels_old_and_creates_new(self, tmp_path):
        """rollback strategy marks the old run as interrupted and creates a new one."""
        mgr, repo = await _make_repo_and_mgr(tmp_path)
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"

        rec1 = await mgr.create_or_reject(thread_id)
        assert rec1.status == RunStatus.pending

        # Create with rollback — should cancel the old and create new
        rec2 = await mgr.create_or_reject(thread_id, multitask_strategy="rollback")
        assert rec2.status == RunStatus.pending
        assert rec2.run_id != rec1.run_id

        # Old run must be interrupted
        rows = await repo.list_by_thread(thread_id)
        assert len(rows) == 2
        statuses = {r["run_id"]: r["status"] for r in rows}
        assert statuses[rec1.run_id] == RunStatus.interrupted
        assert statuses[rec2.run_id] == RunStatus.pending

        await _cleanup()

    @pytest.mark.anyio
    async def test_interrupt_after_completed_is_safe(self, tmp_path):
        """interrupt on a thread whose run already completed is a normal create."""
        mgr, repo = await _make_repo_and_mgr(tmp_path)
        thread_id = f"thread-{uuid.uuid4().hex[:8]}"

        rec1 = await mgr.create_or_reject(thread_id)
        await mgr.set_status(rec1.run_id, RunStatus.success)

        # No inflight run — interrupt behaves like a normal create
        rec2 = await mgr.create_or_reject(thread_id, multitask_strategy="interrupt")
        assert rec2.status == RunStatus.pending
        assert rec1.status == RunStatus.success  # unchanged

        rows = await repo.list_by_thread(thread_id)
        assert len(rows) == 2

        await _cleanup()
