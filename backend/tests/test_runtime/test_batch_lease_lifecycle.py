"""Real database regressions for durable batch lease generations and setup."""

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow, SubagentBatchRow
from deerflow.subagents import batch_service as service_module
from deerflow.subagents.batch_service import SubagentBatchService


class SubagentStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"

    @property
    def is_terminal(self):
        return self is SubagentStatus.COMPLETED


@pytest_asyncio.fixture
async def repository(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        yield SubagentBatchRepository(get_session_factory())
    finally:
        await close_engine()


async def create_batch(repository, *, count=1, max_attempts=3):
    return await repository.create_batch(
        batch_id="batch-lease-test",
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        submission_key="run-1:call-1",
        title="Lease recovery",
        subagent_type="general-purpose",
        items=[{"key": f"record-{i}", "prompt": f"Process {i}"} for i in range(count)],
        max_live_items=count,
        max_running_items=1,
        max_attempts=max_attempts,
        execution_spec={"subagent_config": {"name": "general-purpose", "description": "test", "system_prompt": "Work carefully."}},
    )


async def row_snapshot(repository, item_id):
    async with repository._sf() as session:
        item = await session.get(SubagentBatchItemRow, item_id)
        return {c.name: getattr(item, c.name) for c in item.__table__.columns}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["renew", "running", "finalize", "requeue"])
@pytest.mark.parametrize("peer_action", ["reclaim", "cancel"])
async def test_in_flight_old_acknowledgement_cannot_change_reclaimed_row(repository, monkeypatch, operation, peer_action):
    await create_batch(repository)
    now = datetime.now(UTC)
    first = (await repository.claim_items(now=now, lease_owner="old-claim", lease_seconds=10, limit=1))[0]
    item_id = first["id"]
    paused, release = asyncio.Event(), asyncio.Event()
    original = AsyncSession.execute
    old_task = None

    async def execute(session, statement, *args, **kwargs):
        result = await original(session, statement, *args, **kwargs)
        if asyncio.current_task() is old_task and not paused.is_set() and getattr(statement, "is_select", False) and "subagent_batch_items" in str(statement) and len(statement.selected_columns) > 1:
            # Pause after the old operation's actual database read, not before
            # it starts. SQLite ignores SELECT FOR UPDATE; a peer can reclaim.
            paused.set()
            await release.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute)

    async def acknowledge():
        stamp = now + timedelta(seconds=1)  # Within the OLD lease; expiry must not mask a missing fence.
        if operation == "renew":
            return await repository.renew_item_lease(item_id, lease_owner="old-claim", lease_seconds=10, now=stamp)
        if operation == "running":
            return await repository.mark_item_running(item_id, lease_owner="old-claim", now=stamp)
        if operation == "requeue":
            return await repository.requeue_item_after_admission_failure(item_id, lease_owner="old-claim", error="stale rejection", now=stamp)
        return await repository.finalize_item(
            item_id,
            lease_owner="old-claim",
            succeeded=True,
            result="stale result",
            result_preview="stale result",
            result_truncated=False,
            error=None,
            stop_reason=None,
            token_usage={"total_tokens": 99},
            model_name="old-model",
            completed_at=stamp,
        )

    old_task = asyncio.create_task(acknowledge())
    try:
        await asyncio.wait_for(paused.wait(), 3)
        if peer_action == "reclaim":
            replacement = await repository.claim_items(now=now + timedelta(seconds=11), lease_owner="new-claim", lease_seconds=10, limit=1)
            assert replacement[0]["id"] == item_id and replacement[0]["attempt"] == 2
        else:
            await repository.cancel_batch("batch-lease-test", user_id="user-1")
        expected = await row_snapshot(repository, item_id)
    finally:
        release.set()
        outcome = await asyncio.wait_for(old_task, 3)
    assert outcome == ({"valid": False, "cancel_requested": peer_action == "cancel"} if operation == "renew" else False)
    assert await row_snapshot(repository, item_id) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["pending", "queued"])
@pytest.mark.parametrize("peer_action", ["claim", "cancel", "pause"])
async def test_stale_claim_pass_preserves_peer_claim_or_control(repository, monkeypatch, phase, peer_action):
    await create_batch(repository)
    now = datetime.now(UTC)
    item_id = (await repository.list_items("batch-lease-test", user_id="user-1"))[0]["id"]
    if phase == "queued":
        # Promote without claiming so the paused pass has not acquired SQLite's
        # writer lock before its runnable-item read.
        assert await repository.claim_items(now=now, lease_owner="seed", lease_seconds=10, limit=1, exclude_item_ids=(item_id,)) == []
    paused, release = asyncio.Event(), asyncio.Event()
    original = AsyncSession.execute
    stale = None

    async def execute(session, statement, *args, **kwargs):
        result = await original(session, statement, *args, **kwargs)
        if asyncio.current_task() is stale and not paused.is_set() and getattr(statement, "is_select", False) and "subagent_batch_items.status =" in str(statement) and len(statement.selected_columns) > 1:
            if phase in statement.compile().params.values():
                paused.set()
                await release.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute)
    stale = asyncio.create_task(repository.claim_items(now=now, lease_owner="stale-claim", lease_seconds=10, limit=1))
    try:
        await asyncio.wait_for(paused.wait(), 3)
        if peer_action == "claim":
            peer = await repository.claim_items(now=now + timedelta(seconds=1), lease_owner="peer-claim", lease_seconds=10, limit=1)
            assert len(peer) == 1 and peer[0]["attempt"] == 1
        elif peer_action == "cancel":
            await repository.cancel_batch("batch-lease-test", user_id="user-1")
        else:
            await repository.pause_batch("batch-lease-test", user_id="user-1")
        expected = await row_snapshot(repository, item_id)
        expected_batch = await repository.get_batch("batch-lease-test", user_id="user-1")
    finally:
        release.set()
        claimed = await asyncio.wait_for(stale, 3)
    assert claimed == [], "a stale read must not grant ownership over the peer's claim or control"
    assert await row_snapshot(repository, item_id) == expected
    assert await repository.get_batch("batch-lease-test", user_id="user-1") == expected_batch


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "wrong_owner", "item_cancelled", "batch_cancelled", "owned"])
async def test_renewal_reports_only_explicit_cancellation(repository, case):
    await create_batch(repository)
    now = datetime.now(UTC)
    item = (await repository.claim_items(now=now, lease_owner="claim", lease_seconds=10, limit=1))[0]
    if case in ("item_cancelled", "batch_cancelled"):
        async with repository._sf() as session:
            if case == "item_cancelled":
                (await session.get(SubagentBatchItemRow, item["id"])).cancel_requested_at = now
            else:
                (await session.get(SubagentBatchRow, "batch-lease-test")).status = "cancelled"
            await session.commit()
    outcome = await repository.renew_item_lease("missing" if case == "missing" else item["id"], lease_owner="peer" if case == "wrong_owner" else "claim", lease_seconds=10, now=now)
    assert outcome == {"valid": case == "owned", "cancel_requested": case in ("item_cancelled", "batch_cancelled")}


@pytest.mark.asyncio
async def test_execution_requires_an_explicit_claim_owner(repository):
    service = make_service(repository)
    with pytest.raises(TypeError, match="lease_owner"):
        await service._execute_item({"id": "missing"})


def setup_executor(monkeypatch, started, release):
    launched = []
    monkeypatch.setattr(service_module, "SubagentStatus", SubagentStatus)

    def assemble(**_kwargs):
        started.set()
        assert release.wait(10), "test must release the real assembly worker"
        return []

    class Executor:
        def __init__(self, **_kwargs):
            pass

        def execute_async(self, _prompt, task_id=None):
            launched.append(task_id)
            return "execution-1"

    result = SimpleNamespace(status=SubagentStatus.COMPLETED, result="correct source result", error=None, stop_reason=None, token_usage_records=None, ai_messages=[])
    monkeypatch.setattr("deerflow.tools.get_available_tools", assemble)
    monkeypatch.setattr(service_module, "resolve_subagent_model_name", lambda *_a, **_kw: "test-model")
    monkeypatch.setattr(service_module, "SubagentExecutor", Executor)
    monkeypatch.setattr(service_module, "get_background_task_result", lambda _id: result)
    monkeypatch.setattr(service_module, "cleanup_background_task", lambda _id: None)
    return launched


def make_service(repository):
    return SubagentBatchService(repository=repository, config=SubagentBatchesConfig(lease_seconds=10), runtime_config=SubagentRuntimeConfig(max_running=3), app_config=SimpleNamespace())


@pytest.mark.asyncio
async def test_scheduler_does_not_reclaim_its_still_initializing_item(repository, monkeypatch):
    await create_batch(repository, max_attempts=1)
    started, release = threading.Event(), threading.Event()
    launched = setup_executor(monkeypatch, started, release)
    service = make_service(repository)
    now = datetime.now(UTC)
    await service.run_once(now=now)
    tasks = list(service._executions.values())
    try:
        assert await asyncio.to_thread(started.wait, 3)
        # Advance the scheduler's logical claim clock past its lease, while a
        # real assembly-pool worker still owns initialization. No private lock
        # is held or manufactured by the test.
        await service.run_once(now=now + timedelta(seconds=11))
        item = (await repository.list_items("batch-lease-test", user_id="user-1"))[0]
        assert item["status"] == "leased", "live initialization must not exhaust its retry budget"
        assert item["attempt"] == 1
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 3)
    assert len(launched) == 1
    item = (await repository.list_items("batch-lease-test", user_id="user-1", include_result=True))[0]
    assert item["status"] == "succeeded" and item["result"] == "correct source result"


@pytest.mark.asyncio
async def test_initialization_keeps_renewing_for_other_workers(repository, monkeypatch):
    await create_batch(repository)
    started, release = threading.Event(), threading.Event()
    setup_executor(monkeypatch, started, release)
    service = make_service(repository)
    renewals, twice = [], asyncio.Event()
    original = repository.renew_item_lease

    async def renew(*args, **kwargs):
        result = await original(*args, **kwargs)
        renewals.append(kwargs["now"])
        if len(renewals) >= 2:
            twice.set()
        return result

    monkeypatch.setattr(repository, "renew_item_lease", renew)
    now = datetime.now(UTC)
    await service.run_once(now=now)
    tasks = list(service._executions.values())
    try:
        assert await asyncio.to_thread(started.wait, 3)
        try:
            await asyncio.wait_for(twice.wait(), 5)
        except TimeoutError:
            pytest.fail("a blocked tool assembly received no periodic lease heartbeat")
        # Just beyond the first renewal's expiry, but before the second one's.
        peer_time = renewals[0] + timedelta(seconds=10, milliseconds=1)
        assert await repository.claim_items(now=peer_time, lease_owner="peer", lease_seconds=10, limit=1) == []
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 3)


@pytest.mark.asyncio
async def test_each_scheduler_claim_has_a_fresh_ownership_generation(repository, monkeypatch):
    await create_batch(repository, count=2)
    started, release = threading.Event(), threading.Event()
    release.set()
    setup_executor(monkeypatch, started, release)
    service = make_service(repository)
    owners = []
    original = repository.claim_items

    async def claim(**kwargs):
        owners.append(kwargs["lease_owner"])
        return await original(**kwargs)

    monkeypatch.setattr(repository, "claim_items", claim)
    for _ in range(2):
        await service.run_once(now=datetime.now(UTC))
        await asyncio.gather(*list(service._executions.values()))
        await asyncio.sleep(0)  # Deliver the normal task-registry done callbacks.
    assert len(owners) == len(set(owners)) == 2, "worker identity must not be reused as a claim-generation fence"
    assert all(len(owner) <= 128 for owner in owners)
    items = await repository.list_items("batch-lease-test", user_id="user-1", include_result=True)
    assert [item["status"] for item in items] == ["succeeded", "succeeded"]
    assert all("lease_owner" not in item for item in items)


@pytest.mark.asyncio
async def test_recovery_does_not_overwrite_a_renewal_after_its_expiry_read(repository, monkeypatch):
    await create_batch(repository)
    now = datetime.now(UTC)
    item = (await repository.claim_items(now=now, lease_owner="live-worker", lease_seconds=10, limit=1))[0]
    paused, release = asyncio.Event(), asyncio.Event()
    original = AsyncSession.execute
    recovery = None

    async def execute(session, statement, *args, **kwargs):
        result = await original(session, statement, *args, **kwargs)
        if asyncio.current_task() is recovery and not paused.is_set() and getattr(statement, "is_select", False) and "lease_expires_at <" in str(statement):
            paused.set()
            await release.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute)
    recovery = asyncio.create_task(repository.claim_items(now=now + timedelta(seconds=11), lease_owner="recoverer", lease_seconds=10, limit=1))
    try:
        await asyncio.wait_for(paused.wait(), 3)
        assert (await repository.renew_item_lease(item["id"], lease_owner="live-worker", lease_seconds=10, now=now + timedelta(seconds=12)))["valid"]
        expected = await row_snapshot(repository, item["id"])
    finally:
        release.set()
        claimed = await asyncio.wait_for(recovery, 3)
    assert claimed == []
    assert await row_snapshot(repository, item["id"]) == expected


@pytest.mark.asyncio
async def test_lost_heartbeat_cancels_execution_before_a_long_poll_interval(repository, monkeypatch):
    await create_batch(repository)
    started, release = threading.Event(), threading.Event()
    release.set()
    setup_executor(monkeypatch, started, release)
    service = make_service(repository)
    service._config = SubagentBatchesConfig(lease_seconds=10, poll_interval_seconds=60)
    running, cancelled = asyncio.Event(), asyncio.Event()
    mark_running = repository.mark_item_running

    async def mark(*args, **kwargs):
        valid = await mark_running(*args, **kwargs)
        if valid:
            running.set()
        return valid

    monkeypatch.setattr(repository, "mark_item_running", mark)
    result = SimpleNamespace(status=SubagentStatus.RUNNING, result=None, error=None, stop_reason=None, token_usage_records=None, ai_messages=[])

    def read_result(_id):
        return result

    def cancel(_id):
        result.status = SubagentStatus.COMPLETED
        cancelled.set()

    monkeypatch.setattr(service_module, "get_background_task_result", read_result)
    monkeypatch.setattr(service_module, "request_cancel_background_task", cancel)
    await service.run_once(now=datetime.now(UTC))
    task = next(iter(service._executions.values()))
    try:
        await asyncio.wait_for(running.wait(), 3)
        # Another worker handles the control request; no local cancellation shortcut.
        await repository.cancel_batch("batch-lease-test", user_id="user-1")
        await asyncio.wait_for(cancelled.wait(), 8)
        await asyncio.wait_for(task, 4)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    item = (await repository.list_items("batch-lease-test", user_id="user-1", include_result=True))[0]
    assert item["status"] == "cancelled" and item["result"] is None


@pytest.mark.asyncio
async def test_heartbeat_exit_drains_an_in_flight_renewal_across_repeated_cancellation():
    from deerflow.subagents.batch_lease import BatchItemLease

    renewing, finish_renewal, exit_context = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    class Repository:
        async def renew_item_lease(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                renewing.set()
                await finish_renewal.wait()
            return {"valid": True, "cancel_requested": False}

    async def supervise():
        async with BatchItemLease(Repository(), item_id="item", owner="generation", seconds=3):
            await exit_context.wait()

    task = asyncio.create_task(supervise())
    try:
        await asyncio.wait_for(renewing.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "caller must retain its in-flight database renewal"
        finish_renewal.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert calls == 2
        assert not any(t.get_name() == "batch-item-lease-item" for t in asyncio.all_tasks())
    finally:
        finish_renewal.set()
        exit_context.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
