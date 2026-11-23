"""Team service ownership covers startup, admission and worker shutdown."""

import asyncio
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.bundled_extension


@pytest.fixture
def team_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"))
    from deerflow_extension_agent_teams import service, store

    return service, store


@pytest.mark.asyncio
async def test_injected_store_lifecycle_runs_offloop_and_drains_before_close(team_modules):
    service_module, _ = team_modules
    events = []
    threads = []
    loop_thread = threading.get_ident()
    entered = asyncio.Event()

    class Store:
        def acquire_service_lock(self):
            threads.append(threading.get_ident())
            events.append("acquire")
            return self

        def check_service_lock(self):
            threads.append(threading.get_ident())

        def scheduling_snapshots(self):
            threads.append(threading.get_ident())
            return {}

        def close(self):
            threads.append(threading.get_ident())
            events.append("close")

    service = service_module.Teams(store=Store())

    async def worker():
        entered.set()
        try:
            await asyncio.Future()
        finally:
            events.append("worker drained")

    await service.start(None)
    service.workers["worker"] = asyncio.create_task(worker())
    try:
        await entered.wait()
    finally:
        await service.stop()
    assert events == ["acquire", "worker drained", "close"]
    assert threads and all(thread != loop_thread for thread in threads)
    assert not service.available and service.process_lock is None


@pytest.mark.asyncio
async def test_cancelled_start_closes_a_lock_acquired_after_cancellation(team_modules):
    service_module, _ = team_modules
    entered = asyncio.Event()
    release = threading.Event()
    closed = threading.Event()
    loop = asyncio.get_running_loop()

    class Store:
        def acquire_service_lock(self):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return SimpleNamespace(close=closed.set)

    service = service_module.Teams(store=Store())
    task = asyncio.create_task(service.start(None))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()
    assert service.process_lock is None and service.task is None and not service.available


@pytest.mark.asyncio
async def test_failed_second_start_preserves_the_active_service_lock(team_modules, tmp_path):
    service_module, _ = team_modules
    service = service_module.Teams(tmp_path / "teams.sqlite")
    await service.start(None)
    original_lock = service.process_lock
    try:
        with pytest.raises(sqlite3.OperationalError):
            await service.start(None)
        assert service.process_lock is original_lock and service.available
    finally:
        await service.stop()
        await asyncio.to_thread(original_lock.close)
    replacement = service_module.Teams(tmp_path / "teams.sqlite")
    await replacement.start(None)
    await replacement.stop()


@pytest.mark.asyncio
async def test_idle_service_detects_ownership_loss_and_drains_workers(team_modules):
    service_module, store_module = team_modules
    events = []
    entered = asyncio.Event()

    class Store:
        def acquire_service_lock(self):
            return self

        def scheduling_snapshots(self):
            return {}

        def check_service_lock(self):
            events.append("ownership lost")
            raise store_module.StoreUnavailable("lost")

        def close(self):
            events.append("close")

    service = service_module.Teams(store=Store())

    async def worker():
        entered.set()
        try:
            await asyncio.Future()
        finally:
            events.append("worker drained")

    service.workers["worker"] = asyncio.create_task(worker())
    await entered.wait()
    await service.start(None)
    try:
        await asyncio.wait_for(service.task, 3)
        assert not service.available and not service.handles and not service.workers
        assert events == ["ownership lost", "worker drained"]
    finally:
        await service.stop()
    assert events[-1] == "close"


@pytest.mark.asyncio
async def test_storage_failure_in_worker_stops_other_workers_without_deadlock(team_modules):
    service_module, store_module = team_modules
    entered, release, drained = (asyncio.Event() for _ in range(3))
    failed = []

    class Store:
        def acquire_service_lock(self):
            return self

        def check_service_lock(self):
            pass

        def scheduling_snapshots(self):
            return {}

        def get(self):
            failed.append(True)
            raise store_module.StoreUnavailable("lost")

        def close(self):
            pass

    service = service_module.Teams(store=Store())
    await service.start(None)

    async def failing_worker():
        await release.wait()
        with pytest.raises(store_module.StoreUnavailable):
            await service.db("get")

    async def other_worker():
        entered.set()
        try:
            await asyncio.Future()
        finally:
            drained.set()

    service.workers["failing"] = asyncio.create_task(failing_worker())
    service.workers["other"] = asyncio.create_task(other_worker())
    service.handles["team"] = object()
    try:
        await entered.wait()
        release.set()
        await asyncio.wait_for(drained.wait(), 3)
        assert failed and not service.available and not service.handles
    finally:
        await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_lost_ownership_prevents_run_admission_with_frozen_input(team_modules, resume):
    service_module, store_module = team_modules
    checks, starts = [], []

    class Store:
        def check_service_lock(self):
            checks.append(True)
            raise store_module.StoreUnavailable("lost")

        def change(self, *_):
            pass

    class Runs:
        async def start(self, **kwargs):
            starts.append(kwargs)

        async def resume(self, **kwargs):
            starts.append(kwargs)

    service = service_module.Teams(store=Store())
    service.available = True
    job = {"id": "job", "thread_id": "thread", "status": "resuming" if resume else "queued", "input": {"messages": []}, "run_id": "run" if resume else None, "resume": {"response": "answer", "key": "answer-key"}}
    with pytest.raises(store_module.StoreUnavailable):
        await service.advance("owner", {"id": "team"}, job, Runs())
    assert checks and not starts and not service.available


@pytest.mark.asyncio
async def test_reconnect_checks_service_ownership_before_creating_threads(team_modules):
    service_module, store_module = team_modules
    checks, creations = [], []

    class Store:
        def get(self, *_):
            return {"id": "team", "members": [{"agent": "agent", "thread_id": "thread"}]}

        def check_service_lock(self):
            checks.append(True)
            raise store_module.StoreUnavailable("lost")

    class Runs:
        async def create_thread(self, **kwargs):
            creations.append(kwargs)

    service = service_module.Teams(store=Store())
    service.available = True
    context = SimpleNamespace(principal=SimpleNamespace(user_id="owner"), agent_runs=Runs())
    with pytest.raises(store_module.StoreUnavailable):
        await service.connect({"team_id": "team"}, context)
    assert checks and not creations and not service.available


@pytest.mark.asyncio
async def test_shutdown_waits_for_in_progress_storage_work_before_unlocking(team_modules):
    service_module, _ = team_modules
    loop = asyncio.get_running_loop()
    entered, cancelled = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    events = []

    class Store:
        def acquire_service_lock(self):
            return self

        def check_service_lock(self):
            pass

        def scheduling_snapshots(self):
            return {}

        def change(self):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            events.append("committed")

        def close(self):
            events.append("unlocked")

    service = service_module.Teams(store=Store())
    await service.start(None)

    async def worker():
        try:
            await service.db("change")
        finally:
            cancelled.set()

    worker_task = asyncio.create_task(worker())
    service.workers["worker"] = worker_task
    await entered.wait()
    stopping = asyncio.create_task(service.stop())
    try:
        # Once stop has requested worker cancellation, the synchronous call
        # must still hold up worker draining and release of the service lock.
        while not worker_task.cancelling():
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not cancelled.is_set() and not events
    finally:
        release.set()
        await asyncio.wait_for(stopping, 3)
    assert events == ["committed", "unlocked"]


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_already_stopping", [False, True])
async def test_cancelled_stop_waiters_leave_one_worker_drain_and_lock_release(team_modules, loop_already_stopping):
    service_module, _ = team_modules
    loop = asyncio.get_running_loop()
    entered, draining, release_worker, closing = (asyncio.Event() for _ in range(4))
    release_close = threading.Event()
    events = []

    class Store:
        def acquire_service_lock(self):
            return self

        def check_service_lock(self):
            pass

        def scheduling_snapshots(self):
            return {}

        def close(self):
            loop.call_soon_threadsafe(closing.set)
            assert release_close.wait(5)
            events.append("closed")

    service = service_module.Teams(store=Store())
    await service.start(None)

    async def worker():
        entered.set()
        try:
            await asyncio.Future()
        finally:
            draining.set()
            await release_worker.wait()
            events.append("drained")

    service.workers["worker"] = asyncio.create_task(worker())
    await entered.wait()
    if loop_already_stopping:
        service.task.cancel()
        await asyncio.wait_for(draining.wait(), 3)
    first_stop = asyncio.create_task(service.stop())
    second_stop = None
    try:
        await asyncio.wait_for(draining.wait(), 3)
        while service.shutdown_task is None:
            await asyncio.sleep(0)
        first_stop.cancel()
        second_stop = asyncio.create_task(service.stop())
        shutdown = service.shutdown_task
        done, _ = await asyncio.wait([first_stop], timeout=3)
        assert first_stop in done and first_stop.cancelled()
        assert not second_stop.done() and not shutdown.done()
        assert not events
        release_worker.set()
        await asyncio.wait_for(closing.wait(), 3)
        second_stop.cancel()
        done, _ = await asyncio.wait([second_stop], timeout=3)
        assert second_stop in done and second_stop.cancelled()
        assert service.shutdown_task is shutdown and not shutdown.done()
        assert service.process_lock is not None
        assert events == ["drained"]
    finally:
        release_worker.set()
        release_close.set()
        results = await asyncio.wait_for(asyncio.gather(first_stop, *([second_stop] if second_stop else []), return_exceptions=True), 3)
        await asyncio.wait_for(service.stop(), 3)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert events == ["drained", "closed"]
    assert service.process_lock is None and not service.workers and not service.available


@pytest.mark.asyncio
@pytest.mark.parametrize("stall_at", ["database", "worker", "close"])
async def test_gateway_stop_timeout_continues_while_team_cleanup_keeps_ownership(team_modules, stall_at):
    from deerflow.extensions.gateway import stop_services
    from deerflow.extensions.registry import ExtensionRegistry

    service_module, _ = team_modules
    loop = asyncio.get_running_loop()
    entered, draining, closing = (asyncio.Event() for _ in range(3))
    release_worker = asyncio.Event()
    release_storage = threading.Event()
    events = []

    class Store:
        def acquire_service_lock(self):
            return self

        def check_service_lock(self):
            pass

        def scheduling_snapshots(self):
            return {}

        def change(self):
            loop.call_soon_threadsafe(entered.set)
            assert release_storage.wait(10)
            events.append("committed")

        def close(self):
            loop.call_soon_threadsafe(closing.set)
            if stall_at == "close":
                assert release_storage.wait(10)
            events.append("closed")

    class OtherService:
        async def start(self, deps):
            pass

        async def stop(self):
            events.append("other stopped")

    service = service_module.Teams(store=Store())
    await service.start(None)

    async def worker():
        try:
            if stall_at == "database":
                await service.db("change")
            else:
                entered.set()
                await asyncio.Future()
        finally:
            draining.set()
            if stall_at == "worker":
                await release_worker.wait()
            events.append("drained")

    service.workers["worker"] = asyncio.create_task(worker())
    registry = ExtensionRegistry()
    with registry.attributed_to("other:install"):
        registry.service(OtherService())
    with registry.attributed_to("teams:install"):
        registry.service(service)
    stopping = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        # Use the real host timeout path with a short budget, while an explicit
        # barrier keeps cleanup stalled until all timeout assertions finish.
        stopping = asyncio.create_task(stop_services(registry.build(), timeout_seconds=0.01))
        if stall_at == "worker":
            await asyncio.wait_for(draining.wait(), 3)
        elif stall_at == "close":
            await asyncio.wait_for(closing.wait(), 3)
        done, _ = await asyncio.wait([stopping], timeout=3)
        assert stopping in done, "Team cleanup swallowed the Gateway stop timeout"
        diagnostics = stopping.result()
        assert len(diagnostics) == 1
        assert diagnostics[0].source == "teams:install"
        assert "timed out" in diagnostics[0].message
        assert "other stopped" in events and "closed" not in events
        assert not service.available and service.process_lock is not None
        assert not service.shutdown_task.done() and not service.shutdown_task.cancelling()
    finally:
        release_worker.set()
        release_storage.set()
        if stopping is not None:
            await asyncio.wait_for(stopping, 3)
        await asyncio.wait_for(service.stop(), 3)
    assert events[-1] == "closed" and events.count("closed") == 1
    assert events.index("drained") < events.index("closed")
    if stall_at == "database":
        assert events.index("committed") < events.index("drained")
    assert service.process_lock is None and not service.workers


@pytest.mark.asyncio
async def test_detached_shutdown_failure_is_reported_without_storage_details(team_modules, caplog):
    service_module, _ = team_modules
    loop = asyncio.get_running_loop()
    closing = asyncio.Event()
    release = threading.Event()

    class Store:
        def close(self):
            loop.call_soon_threadsafe(closing.set)
            assert release.wait(10)
            raise RuntimeError("private storage connection details")

    service = service_module.Teams(store=Store())
    service.process_lock = service.store
    stopping = asyncio.create_task(service.stop())
    try:
        await asyncio.wait_for(closing.wait(), 3)
        stopping.cancel()
        done, _ = await asyncio.wait([stopping], timeout=3)
        assert stopping in done and stopping.cancelled()
        shutdown_done = asyncio.Event()
        service.shutdown_task.add_done_callback(lambda _: shutdown_done.set())
        release.set()
        await asyncio.wait_for(shutdown_done.wait(), 3)
        assert "Agent teams shutdown failed" in caplog.text
        assert "private storage connection details" not in caplog.text
        # Reporting detached failures must not consume the error for a later
        # stop caller or replace the shared shutdown with a second attempt.
        with pytest.raises(RuntimeError, match="private storage connection details"):
            await service.stop()
    finally:
        release.set()
        await asyncio.gather(stopping, service.shutdown_task, return_exceptions=True)
