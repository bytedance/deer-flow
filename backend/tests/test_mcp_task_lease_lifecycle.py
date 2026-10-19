"""Durable ownership must outlive slow MCP control calls, without duplicate claims."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.mcp_tasks.service as service_module
from app.mcp_tasks.service import McpTaskService
from deerflow.config.database_config import DatabaseConfig
from deerflow.mcp.tasks import McpTaskConnectionUnavailableError, McpTaskDriverRegistry, TaskSnapshot, TaskStatus
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.mcp_tasks import McpTaskRepository
from deerflow.persistence.thread_meta.model import ThreadMetaRow


class Clock(datetime):
    current = datetime(2030, 1, 1, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        return cls.current


@pytest_asyncio.fixture
async def task_repo(tmp_path, monkeypatch):
    Clock.current = datetime(2030, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(service_module, "datetime", Clock)
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    factory = get_session_factory()
    async with factory() as session:
        session.add(ThreadMetaRow(thread_id="thread-1", user_id="user-1", metadata_json={}, created_at=Clock.current, updated_at=Clock.current))
        await session.commit()
    repo = McpTaskRepository(factory)
    await create_working(repo, "task-1")
    try:
        yield repo
    finally:
        await close_engine()


async def create_working(repo, task_id, driver_name="fake"):
    await repo.create(
        task_id=task_id,
        user_id="user-1",
        thread_id="thread-1",
        expected_thread_incarnation=None,
        run_id="run-1",
        tool_call_id="call-1",
        server_name="reports",
        driver_name=driver_name,
        remote_task_id="remote-" + task_id,
        task_name="Report",
        status="working",
        result=None,
        result_preview=None,
        result_truncated=False,
        result_artifact=None,
        error=None,
        input_required=None,
        next_poll_at=Clock.current,
        driver_data={},
    )


class SlowDriver:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.stopped = asyncio.Event()

    async def get_status(self, _task):
        self.calls += 1
        self.started.set()
        try:
            await self.finish.wait()
            return TaskSnapshot(status=TaskStatus.COMPLETED, result={"answer": 42})
        finally:
            self.stopped.set()

    async def cancel(self, task):
        await self.get_status(task)
        return TaskSnapshot(status=TaskStatus.CANCELLED)


def make_service(repo, driver):
    drivers = McpTaskDriverRegistry()
    drivers.register("fake", driver)
    return McpTaskService(repository=repo, drivers=drivers, poll_interval_seconds=1, lease_seconds=5, max_concurrent_polls=2)


async def read_task(repo):
    return await repo.get("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("reclaimed", [False, True])
@pytest.mark.parametrize("connection_unavailable", [False, True])
async def test_cancel_snapshot_discard_is_logged_without_changing_peer_or_retry_state(task_repo, monkeypatch, caplog, reclaimed, connection_unavailable):
    repo = task_repo
    await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    apply = repo.apply_cancel_snapshot
    peer = None

    async def apply_after_ownership_check(*args, **kwargs):
        nonlocal peer
        if reclaimed:
            # Pause at the persistence boundary after _require_control_lease(),
            # then let another worker reclaim before the real fenced UPDATE.
            Clock.current += timedelta(seconds=6)
            await repo.claim_cancel_requests(now=Clock.current, lease_owner="peer", lease_seconds=5, limit=1)
            peer = await read_task(repo)
        return await apply(*args, **kwargs)

    monkeypatch.setattr(repo, "apply_cancel_snapshot", apply_after_ownership_check)
    driver = SlowDriver()
    driver.finish.set()
    if connection_unavailable:

        async def missing_connection(_task):
            raise McpTaskConnectionUnavailableError("MCP task connection was removed")

        monkeypatch.setattr(driver, "cancel", missing_connection)
    with caplog.at_level("INFO", logger=service_module.__name__):
        await make_service(repo, driver)._run_cancellations(now=Clock.current)

    stored = await read_task(repo)
    messages = [record.getMessage() for record in caplog.records if "Discarded MCP task cancel result" in record.getMessage()]
    if reclaimed:
        assert peer is not None and peer["lease_owner"] == "peer"
        assert stored == peer, "discarding the old snapshot must not mutate or retry the peer's claim"
        assert len(messages) == 1 and "task_id=task-1" in messages[0]
    else:
        assert stored["status"] == ("failed" if connection_unavailable else "cancelled")
        assert messages == [], "an applied cancellation must not be reported as discarded"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,expected", [("poll", "completed"), ("cancel", "cancelled")])
async def test_slow_control_call_keeps_claim_and_persists_terminal_result(task_repo, phase, expected):
    repo = task_repo
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    driver = SlowDriver()
    service = make_service(repo, driver)
    cycle = asyncio.create_task(service.run_once(now=Clock.current))
    try:
        await asyncio.wait_for(driver.started.wait(), timeout=3)
        Clock.current += timedelta(seconds=4)
        # One real heartbeat interval (5/3s), with a controlled durable clock.
        await asyncio.sleep(2)
        Clock.current += timedelta(seconds=2)
        claim = repo.claim_due_tasks if phase == "poll" else repo.claim_cancel_requests
        peer = await claim(now=Clock.current, lease_owner="peer", lease_seconds=5, limit=1)
        assert peer == [], "a live slow control call lost its lease and was reclaimed"
        driver.finish.set()
        await asyncio.wait_for(cycle, timeout=3)
        assert (await read_task(repo))["status"] == expected
    finally:
        driver.finish.set()
        await asyncio.wait_for(asyncio.gather(cycle, return_exceptions=True), timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_sqlite_claims_have_one_winner_when_reads_overlap(task_repo, monkeypatch, phase):
    repo = task_repo
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    claim = repo.claim_due_tasks if phase == "poll" else repo.claim_cancel_requests
    read = asyncio.Event()
    resume = asyncio.Event()
    execute = AsyncSession.execute
    first = None

    async def pause_first_select(session, statement, *args, **kwargs):
        result = await execute(session, statement, *args, **kwargs)
        if asyncio.current_task() is first and statement.is_select and not read.is_set():
            read.set()
            await resume.wait()
        return result

    monkeypatch.setattr(AsyncSession, "execute", pause_first_select)
    first = asyncio.create_task(claim(now=Clock.current, lease_owner="first", lease_seconds=5, limit=1))
    second = None
    try:
        await asyncio.wait_for(read.wait(), timeout=3)
        second = asyncio.create_task(claim(now=Clock.current, lease_owner="second", lease_seconds=5, limit=1))
        # Let the competitor attempt its claim while the first read is paused.
        # Serialized cancel claims and fenced poll UPDATEs must each yield one winner.
        await asyncio.wait({second}, timeout=0.2)
        resume.set()
        a, b = await asyncio.wait_for(asyncio.gather(first, second), timeout=3)
        assert len(a) + len(b) == 1, "both workers received the same durable task"
    finally:
        resume.set()
        await asyncio.gather(*[t for t in (first, second) if t is not None], return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
@pytest.mark.parametrize("drift", ["owner", "token", "expired", "other_phase", "terminal"])
async def test_renewal_cannot_revive_or_change_an_ineligible_claim(task_repo, phase, drift):
    repo = task_repo
    initial = Clock.current
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=initial)
    claim = repo.claim_due_tasks if phase == "poll" else repo.claim_cancel_requests
    row = (await claim(now=initial, lease_owner="worker", lease_seconds=5, limit=1))[0]
    from sqlalchemy import update

    from deerflow.persistence.mcp_tasks.model import McpTaskRow

    if drift in {"other_phase", "terminal"}:
        values = {"status": "completed"} if drift == "terminal" else {"cancel_requested_at": initial if phase == "poll" else None}
        async with repo._sf() as session:
            await session.execute(update(McpTaskRow).where(McpTaskRow.id == "task-1").values(**values))
            await session.commit()
    now = initial + timedelta(seconds=6 if drift == "expired" else 1)
    renewed = await repo.renew_control_claim(
        "task-1",
        phase=phase,
        lease_owner="wrong" if drift == "owner" else "worker",
        lease_token="wrong" if drift == "token" else row["lease_token"],
        now=now,
        lease_seconds=5,
    )
    assert renewed is False
    async with repo._sf() as session:
        stored = await session.get(McpTaskRow, "task-1")
        assert stored.lease_expires_at.replace(tzinfo=UTC) == initial + timedelta(seconds=5)
        assert stored.lease_token == row["lease_token"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_renewal_extends_only_lease_and_never_moves_expiry_backwards(task_repo, phase):
    repo = task_repo
    initial = Clock.current
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=initial)
    claim = repo.claim_due_tasks if phase == "poll" else repo.claim_cancel_requests
    row = (await claim(now=initial, lease_owner="worker", lease_seconds=5, limit=1))[0]
    for seconds in (4, 2):
        assert await repo.renew_control_claim("task-1", phase=phase, lease_owner="worker", lease_token=row["lease_token"], now=initial + timedelta(seconds=seconds), lease_seconds=5)
    assert await claim(now=initial + timedelta(seconds=6), lease_owner="peer", lease_seconds=5, limit=1) == []
    from deerflow.persistence.mcp_tasks.model import McpTaskRow

    async with repo._sf() as session:
        stored = await session.get(McpTaskRow, "task-1")
        assert stored.lease_expires_at.replace(tzinfo=UTC) == initial + timedelta(seconds=9)
        assert stored.updated_at.replace(tzinfo=UTC) == initial
        assert stored.poll_attempt_count == row["poll_attempt_count"]
        assert stored.cancel_attempt_count == row["cancel_attempt_count"]
        assert stored.last_polled_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_reclaimed_control_call_is_stopped_without_touching_peer_claim(task_repo, phase):
    repo = task_repo
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    driver = SlowDriver()
    service = make_service(repo, driver)
    cycle = asyncio.create_task(service.run_once(now=Clock.current))
    try:
        await asyncio.wait_for(driver.started.wait(), timeout=3)
        Clock.current += timedelta(seconds=6)
        claim = repo.claim_due_tasks if phase == "poll" else repo.claim_cancel_requests
        peer = (await claim(now=Clock.current, lease_owner="peer", lease_seconds=5, limit=1))[0]
        await asyncio.wait_for(driver.stopped.wait(), timeout=3)
        await asyncio.wait_for(cycle, timeout=3)
        assert (await read_task(repo))["status"] == "working"
        assert await repo.renew_control_claim("task-1", phase=phase, lease_owner="peer", lease_token=peer["lease_token"], now=Clock.current, lease_seconds=5)
    finally:
        driver.finish.set()
        await asyncio.wait_for(asyncio.gather(cycle, return_exceptions=True), timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_failed_renewal_stops_remote_call_without_recording_task_failure(task_repo, monkeypatch, phase):
    repo = task_repo
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    renew = repo.renew_control_claim
    admitted = False

    async def unavailable_after_admission(*args, **kwargs):
        nonlocal admitted
        if admitted:
            raise RuntimeError("database unavailable during heartbeat")
        admitted = True
        return await renew(*args, **kwargs)

    monkeypatch.setattr(repo, "renew_control_claim", unavailable_after_admission)
    driver = SlowDriver()
    cycle = asyncio.create_task(make_service(repo, driver).run_once(now=Clock.current))
    try:
        await asyncio.wait_for(driver.started.wait(), timeout=3)
        await asyncio.wait_for(driver.stopped.wait(), timeout=3)
        await asyncio.wait_for(cycle, timeout=3)
        stored = await read_task(repo)
        assert stored["status"] == "working"
        assert stored["last_poll_error"] is None
        assert stored["last_cancel_error"] is None
        assert stored["consecutive_poll_error_count"] == 0
    finally:
        driver.finish.set()
        await asyncio.wait_for(asyncio.gather(cycle, return_exceptions=True), timeout=3)


@pytest.mark.asyncio
async def test_heartbeat_covers_snapshot_persistence_after_remote_completion(task_repo, monkeypatch):
    repo = task_repo
    applying = asyncio.Event()
    commit = asyncio.Event()
    apply = repo.apply_snapshot

    async def delayed_write(*args, **kwargs):
        applying.set()
        await commit.wait()
        return await apply(*args, **kwargs)

    monkeypatch.setattr(repo, "apply_snapshot", delayed_write)
    driver = SlowDriver()
    driver.finish.set()
    cycle = asyncio.create_task(make_service(repo, driver).run_once(now=Clock.current))
    try:
        await asyncio.wait_for(applying.wait(), timeout=3)
        Clock.current += timedelta(seconds=4)
        await asyncio.sleep(2)
        Clock.current += timedelta(seconds=2)
        assert await repo.claim_due_tasks(now=Clock.current, lease_owner="peer", lease_seconds=5, limit=1) == []
        commit.set()
        await asyncio.wait_for(cycle, timeout=3)
        assert (await read_task(repo))["status"] == "completed"
    finally:
        commit.set()
        await asyncio.wait_for(asyncio.gather(cycle, return_exceptions=True), timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_claim_expiring_during_acquisition_does_not_start_remote_call(task_repo, monkeypatch, phase):
    repo = task_repo
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    method = "claim_due_tasks" if phase == "poll" else "claim_cancel_requests"
    claim = getattr(repo, method)

    async def delayed_claim(**kwargs):
        rows = await claim(**kwargs)
        if rows:
            Clock.current += timedelta(seconds=6)
        return rows

    monkeypatch.setattr(repo, method, delayed_claim)
    driver = SlowDriver()
    driver.finish.set()
    await asyncio.wait_for(make_service(repo, driver).run_once(now=Clock.current), timeout=3)
    assert not driver.started.is_set()
    assert (await read_task(repo))["status"] == "working"


class DrainingDriver(SlowDriver):
    def __init__(self):
        super().__init__()
        self.cleanup = asyncio.Event()
        self.calls = 0

    async def get_status(self, task):
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cleanup.set()
            await self.finish.wait()
            return TaskSnapshot(status=TaskStatus.COMPLETED, result={"late": True})
        finally:
            self.stopped.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_repeated_cancellation_retains_local_owner_until_remote_cleanup(task_repo, monkeypatch, phase):
    repo = task_repo
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    driver = DrainingDriver()
    service = make_service(repo, driver)
    service._max_concurrent_polls = 1
    cycle = asyncio.create_task(service.run_once(now=Clock.current))
    try:
        await asyncio.wait_for(driver.started.wait(), timeout=3)
        cycle.cancel("first cancellation")
        await asyncio.wait_for(driver.cleanup.wait(), timeout=3)
        cycle.cancel("second cancellation")
        with pytest.raises(asyncio.CancelledError, match="first cancellation"):
            await asyncio.wait_for(cycle, timeout=3)
        Clock.current += timedelta(seconds=6)
        await asyncio.wait_for(service.run_once(now=Clock.current), timeout=3)
        assert driver.calls == 1
        driver.finish.set()
        await asyncio.wait_for(driver.stopped.wait(), timeout=3)
        # Wait for the existing service-owned batch handoff, not a sleep guess.
        await asyncio.wait_for(asyncio.gather(*service._compensation_tasks), timeout=3)
        assert (await read_task(repo))["status"] == "working"
        assert service._active_control_calls == set()
        # Once cleanup really completes, ordinary recovery can resume.
        monkeypatch.setattr(driver, "get_status", SlowDriver.get_status.__get__(driver))
        await asyncio.wait_for(service.run_once(now=Clock.current), timeout=3)
        assert (await read_task(repo))["status"] == ("completed" if phase == "poll" else "cancelled")
    finally:
        driver.finish.set()
        await asyncio.wait_for(asyncio.gather(cycle, *service._compensation_tasks, return_exceptions=True), timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["poll", "cancel"])
async def test_hung_renewal_stops_control_call_before_lease_expires(task_repo, monkeypatch, phase):
    repo = task_repo
    if phase == "cancel":
        await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    renew = repo.renew_control_claim
    renew_started = asyncio.Event()
    release_renewal = asyncio.Event()
    admitted = False

    async def hang_after_admission(*args, **kwargs):
        nonlocal admitted
        if admitted:
            renew_started.set()
            await release_renewal.wait()
        admitted = True
        return await renew(*args, **kwargs)

    monkeypatch.setattr(repo, "renew_control_claim", hang_after_admission)
    driver = SlowDriver()
    cycle = asyncio.create_task(make_service(repo, driver).run_once(now=Clock.current))
    try:
        await asyncio.wait_for(driver.started.wait(), timeout=3)
        await asyncio.wait_for(renew_started.wait(), timeout=3)
        await asyncio.wait_for(driver.stopped.wait(), timeout=2.5)
        await asyncio.wait_for(cycle, timeout=3)
        assert (await read_task(repo))["status"] == "working"
    finally:
        release_renewal.set()
        driver.finish.set()
        await asyncio.wait_for(asyncio.gather(cycle, return_exceptions=True), timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("uncooperative_child", ["renewal", "driver"])
async def test_uncertain_renewal_cleanup_hands_off_without_stalling_other_tasks(task_repo, monkeypatch, uncooperative_child):
    repo = task_repo
    renew = repo.renew_control_claim
    renewal_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish_cleanup = asyncio.Event()
    admitted = False

    async def uncooperative_renewal(*args, **kwargs):
        nonlocal admitted
        if args[0] != "task-1":
            return await renew(*args, **kwargs)
        if not admitted:
            admitted = True
            return await renew(*args, **kwargs)
        renewal_started.set()
        if uncooperative_child == "driver":
            return False
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_started.set()
            await finish_cleanup.wait()
            return False

    class DrainingDriver(SlowDriver):
        async def get_status(self, task):
            if uncooperative_child == "renewal":
                return await super().get_status(task)
            self.calls += 1
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await finish_cleanup.wait()
                return TaskSnapshot(status=TaskStatus.COMPLETED, result={"stale": True})
            finally:
                self.stopped.set()

    monkeypatch.setattr(repo, "renew_control_claim", uncooperative_renewal)
    monkeypatch.setattr(service_module, "_CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    driver = DrainingDriver()
    service = make_service(repo, driver)
    cycle = asyncio.create_task(service.run_once(now=Clock.current))
    try:
        await asyncio.wait_for(renewal_started.wait(), timeout=3)
        await asyncio.wait_for(cleanup_started.wait(), timeout=3)
        await asyncio.wait_for(asyncio.shield(cycle), timeout=0.5)
        assert driver.stopped.is_set() == (uncooperative_child == "renewal")
        assert (await read_task(repo))["status"] == "working"
        # A draining renewal still owns its local slot, even after its old
        # durable lease becomes eligible for recovery.
        Clock.current += timedelta(seconds=6)
        await create_working(repo, "task-2", driver_name="healthy")
        healthy = SlowDriver()
        healthy.finish.set()
        service._drivers.register("healthy", healthy)
        await asyncio.wait_for(service.run_once(now=Clock.current), timeout=3)
        assert driver.calls == 1
        assert healthy.calls == 1
        assert (await repo.get("task-2", user_id="user-1", thread_id="thread-1", thread_incarnation=None))["status"] == "completed"
        assert service._active_control_calls == {"task-1"}
        finish_cleanup.set()
        await asyncio.wait_for(asyncio.gather(*service._compensation_tasks), timeout=3)
        assert service._active_control_calls == set()
        assert (await read_task(repo))["status"] == "working", "draining driver persisted its stale result"
    finally:
        finish_cleanup.set()
        driver.finish.set()
        await asyncio.wait_for(asyncio.gather(cycle, *service._compensation_tasks, return_exceptions=True), timeout=3)


@pytest.mark.asyncio
async def test_concurrent_scans_recheck_control_capacity_at_execution(task_repo, monkeypatch):
    repo = task_repo
    await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    await create_working(repo, "task-2")
    claim = repo.claim_cancel_requests
    cancel_claimed = asyncio.Event()
    return_claim = asyncio.Event()

    async def delayed_cancel_claim(**kwargs):
        rows = await claim(**kwargs)
        if rows:
            cancel_claimed.set()
            await return_claim.wait()
        return rows

    monkeypatch.setattr(repo, "claim_cancel_requests", delayed_cancel_claim)
    driver = SlowDriver()
    service = make_service(repo, driver)
    service._max_concurrent_polls = 1
    first = asyncio.create_task(service.run_once(now=Clock.current))
    second = None
    try:
        await asyncio.wait_for(cancel_claimed.wait(), timeout=3)
        second = asyncio.create_task(service.run_once(now=Clock.current))
        await asyncio.wait_for(driver.started.wait(), timeout=3)
        return_claim.set()
        await asyncio.wait_for(asyncio.shield(first), timeout=1)
        assert driver.calls == 1, "distinct poll/cancel claims exceeded shared control capacity"
        driver.finish.set()
        await asyncio.wait_for(second, timeout=3)
        assert (await repo.get("task-2", user_id="user-1", thread_id="thread-1", thread_incarnation=None))["status"] == "completed"
        assert (await read_task(repo))["status"] == "working"
    finally:
        return_claim.set()
        driver.finish.set()
        await asyncio.wait_for(asyncio.gather(*[t for t in (first, second) if t is not None], return_exceptions=True), timeout=3)


@pytest.mark.asyncio
async def test_missing_connection_cancel_does_not_persist_after_local_ownership_loss(task_repo, monkeypatch):
    repo = task_repo
    await repo.request_cancel("task-1", user_id="user-1", thread_id="thread-1", thread_incarnation=None, requested_at=Clock.current)
    driver = SlowDriver()
    applied = []
    apply = repo.apply_cancel_snapshot

    async def missing_connection(_task):
        # A transport may finish with an error after ignoring lease-loss cancellation.
        lost = service_module._control_lease_lost.get()
        assert lost is not None
        lost.set()
        raise McpTaskConnectionUnavailableError("MCP task connection was removed")

    async def record_apply(*args, **kwargs):
        applied.append(args)
        return await apply(*args, **kwargs)

    monkeypatch.setattr(driver, "cancel", missing_connection)
    monkeypatch.setattr(repo, "apply_cancel_snapshot", record_apply)
    await make_service(repo, driver)._run_cancellations(now=Clock.current)

    assert applied == []
    assert (await read_task(repo))["status"] == "working"
