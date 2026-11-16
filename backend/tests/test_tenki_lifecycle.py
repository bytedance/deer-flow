"""Offline ownership regressions using the real provider and adapter lifecycle."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from deerflow.community.tenki.provider import TenkiSandboxProvider
from deerflow.community.tenki.sandbox import TenkiSandbox


class Remote:
    def __init__(self, errors=()):
        self.errors = list(errors)
        self.calls = 0
        self.closed = False

    def close(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        self.closed = True

    def wait_ready(self):
        pass

    def exec(self, *args, **kwargs):
        return SimpleNamespace(timed_out=False, exit_code=0, stdout_text="BOOTSTRAP_OK", stderr_text="")


@pytest.fixture
def exit_callbacks(monkeypatch):
    callbacks = []
    monkeypatch.setattr("deerflow.community.tenki.provider.atexit.register", callbacks.append)
    return callbacks


@pytest.fixture
def provider(monkeypatch, exit_callbacks):
    config = dict(idle_timeout=0, replicas=3, api_key=None, base_url=None, workspace_id="synthetic", sticky=False, max_duration=60, image=None, cpu_cores=None, memory_mb=None, environment={}, home_dir="/home/tenki")
    monkeypatch.setattr(TenkiSandboxProvider, "_load_config", lambda self: config)
    value = TenkiSandboxProvider()
    yield value
    value.shutdown()


def test_atexit_logs_incomplete_cleanup_without_losing_retry(provider, exit_callbacks, caplog):
    remote = Remote([OSError("synthetic termination unavailable") for _ in range(2)])
    box = TenkiSandbox("synthetic", remote)
    provider._sandboxes[box.id] = box
    with pytest.raises(RuntimeError, match="Tenki shutdown incomplete"):
        provider.shutdown()

    caplog.clear()
    exit_callbacks[0]()
    assert remote.calls == 2
    assert provider._pending_closes[id(box)] is box
    assert not provider._shutdown_complete
    assert not provider._accepting
    assert "Tenki shutdown incomplete: 0 acquires and 1 terminations pending" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)

    provider.shutdown()
    assert remote.closed
    assert remote.calls == 3
    assert provider._shutdown_complete
    assert not provider._pending_closes


def test_atexit_success_is_quiet(provider, exit_callbacks, caplog):
    remote = Remote()
    box = TenkiSandbox("synthetic", remote)
    provider._sandboxes[box.id] = box
    exit_callbacks[0]()
    exit_callbacks[0]()
    assert remote.closed
    assert remote.calls == 1
    assert provider._shutdown_complete
    assert not caplog.records


def test_atexit_preserves_unexpected_shutdown_errors(provider, exit_callbacks, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(provider, "_stop_idle_checker", lambda: (_ for _ in ()).throw(RuntimeError("reaper still running")))
        with pytest.raises(RuntimeError, match="reaper still running"):
            exit_callbacks[0]()


@pytest.mark.parametrize("replacement_location", ["active", "warm"])
@pytest.mark.parametrize("first_close_fails", [False, True])
def test_late_terminal_failure_cannot_evict_replacement(provider, replacement_location, first_close_fails):
    started, release = threading.Event(), threading.Event()
    old_remote = Remote([OSError("termination unavailable")] if first_close_fails else [])
    new_remote = Remote()
    remotes = iter([old_remote, new_remote])
    provider._client = SimpleNamespace(create=lambda **kwargs: next(remotes))
    sandbox_id = provider.acquire("thread", user_id="user")
    old = provider.get(sandbox_id)

    def fail_old_command(*args, **kwargs):
        if args[-1] == "old-in-flight":
            started.set()
            assert release.wait(5)
        raise ConnectionError("old connection lost")

    def healthy_command(*args, **kwargs):
        text = "BOOTSTRAP_OK\n" if "BOOTSTRAP_OK" in args[-1] else "ok\n"
        return SimpleNamespace(timed_out=False, exit_code=0, stdout_text=text, stderr_text="")

    old_remote.exec = fail_old_command
    new_remote.exec = healthy_command
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(old.execute_command, "old-in-flight")
        try:
            assert started.wait(5)
            assert "old connection lost" in old.execute_command("first-failure")
            assert provider.get(sandbox_id) is None
            assert provider.acquire("thread", user_id="user") == sandbox_id
            replacement = provider.get(sandbox_id)
            assert replacement is not old
            if replacement_location == "warm":
                provider.release(sandbox_id)
        finally:
            release.set()
        assert "old connection lost" in pending.result(timeout=5)

    tracked = provider.get(sandbox_id) if replacement_location == "active" else provider._warm_pool[sandbox_id][0]
    assert tracked is replacement
    assert not replacement.is_closed
    assert new_remote.calls == 0
    assert old_remote.calls == 1
    assert (id(old) in provider._pending_closes) is first_close_fails
    # The retained replacement still serves the same scope, including a real
    # warm health probe. Fencing old failures must not reject healthy reuse.
    assert provider.acquire("thread", user_id="user") == sandbox_id
    assert provider.get(sandbox_id) is replacement
    assert replacement.execute_command("echo ok") == "ok\n"


def test_current_generation_terminal_callback_still_evicts(provider):
    remote = Remote()
    provider._client = SimpleNamespace(create=lambda **kwargs: remote)
    sandbox_id = provider.acquire("thread", user_id="user")
    sandbox = provider.get(sandbox_id)

    def fail_command(*args, **kwargs):
        raise ConnectionError("current connection lost")

    remote.exec = fail_command
    assert "current connection lost" in sandbox.execute_command("fail")
    assert provider.get(sandbox_id) is None
    assert not provider._thread_sandboxes
    assert sandbox.is_closed
    assert remote.calls == 1


@pytest.mark.parametrize("thread_id", ["thread", None])
def test_shutdown_fences_late_creation(provider, monkeypatch, thread_id):
    started, release = threading.Event(), threading.Event()
    remote = Remote()

    def create(sandbox_id):
        started.set()
        assert release.wait(5)
        return TenkiSandbox(sandbox_id, remote)

    monkeypatch.setattr(provider, "_create_sandbox", create)
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(provider.acquire, thread_id, user_id="user")
        try:
            assert started.wait(5)
            with pytest.raises(RuntimeError, match="acquir"):
                provider.shutdown()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="shut|retir"):
            work.result(timeout=5)
    provider.shutdown()
    assert remote.closed
    assert not provider._sandboxes
    assert not provider._thread_sandboxes


@pytest.mark.parametrize("thread_id", ["thread", None])
def test_reset_fences_late_creation_without_reparking(provider, monkeypatch, thread_id):
    started, release = threading.Event(), threading.Event()
    remote = Remote()

    def create(sandbox_id):
        started.set()
        assert release.wait(5)
        return TenkiSandbox(sandbox_id, remote)

    monkeypatch.setattr(provider, "_create_sandbox", create)
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(provider.acquire, thread_id, user_id="user")
        try:
            assert started.wait(5)
            provider.reset()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="shut|retir"):
            work.result(timeout=5)
    assert remote.closed
    assert not provider._sandboxes
    assert not provider._warm_pool


def test_shutdown_rejects_new_random_acquire(provider, monkeypatch):
    created = []
    monkeypatch.setattr(provider, "_create_sandbox", lambda sandbox_id: created.append(sandbox_id))
    provider.shutdown()
    with pytest.raises(RuntimeError, match="shut|retir"):
        provider.acquire()
    assert created == []


@pytest.mark.parametrize("origin", ["idle", "replicas", "shutdown", "invalidation"])
def test_failed_termination_retains_ownership_for_retry(provider, origin):
    remote = Remote([OSError("synthetic termination unavailable")])
    box = TenkiSandbox("synthetic", remote)
    if origin in {"idle", "replicas"}:
        provider._warm_pool[box.id] = (box, 0)
        if origin == "idle":
            provider._reap_expired_warm(1)
        else:
            provider._evict_oldest_warm()
    else:
        provider._sandboxes[box.id] = box
        if origin == "shutdown":
            with pytest.raises(RuntimeError, match="terminat|cleanup"):
                provider.shutdown()
        else:
            provider._invalidate_sandbox(box.id, "synthetic failure")
    assert not remote.closed
    assert provider.get(box.id) is None
    provider.shutdown()
    assert remote.closed
    assert remote.calls == 2


@pytest.mark.parametrize("error", [ConnectionError("lost ack"), BrokenPipeError("broken pipe"), EOFError("closed response")])
def test_ambiguous_termination_is_retryable(error):
    remote = Remote([error])
    box = TenkiSandbox("synthetic", remote)
    with pytest.raises(type(error)):
        box.close()
    assert not box.is_closed
    box.close()
    assert box.is_closed
    assert remote.calls == 2


def test_readiness_failure_does_not_forget_failed_cleanup(provider):
    remote = Remote([OSError("termination unavailable")])

    def fail_ready():
        raise ValueError("synthetic readiness failure")

    remote.wait_ready = fail_ready
    provider._client = SimpleNamespace(create=lambda **kwargs: remote)
    with pytest.raises(ValueError, match="readiness"):
        provider.acquire("thread", user_id="user")
    provider.shutdown()
    assert remote.closed
    assert remote.calls == 2


@pytest.mark.asyncio
async def test_cancelled_async_acquire_still_owns_late_creation(provider, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    remote = Remote()

    def create(sandbox_id):
        started.set()
        try:
            assert release.wait(5)
            return TenkiSandbox(sandbox_id, remote)
        finally:
            finished.set()

    monkeypatch.setattr(provider, "_create_sandbox", create)
    work = asyncio.create_task(provider.acquire_async("thread", user_id="user"))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        with pytest.raises(RuntimeError, match="acquir"):
            provider.shutdown()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        # Join the already-started SDK worker before the fixture's retry.
        await asyncio.to_thread(provider._acquire_serializer.executor.shutdown, wait=True)
    provider.shutdown()
    assert remote.closed
    assert not provider._sandboxes


def test_idle_sweep_retries_failed_close_and_counts_pending_capacity(provider):
    remote = Remote([OSError("try later")])
    box = TenkiSandbox("synthetic", remote)
    provider._warm_pool[box.id] = (box, 0)
    provider._cleanup_idle_resources(1)
    assert provider._replica_count() == (3, 1)
    provider._cleanup_idle_resources(1)
    assert remote.closed
    assert provider._replica_count() == (3, 0)


def test_replacement_does_not_erase_old_generation_cleanup(provider):
    old_remote = Remote([OSError("old generation unavailable")])
    new_remote = Remote()
    sandbox_id = provider._sandbox_id("thread", "user")
    old_box = TenkiSandbox(sandbox_id, old_remote)
    provider._sandboxes[sandbox_id] = old_box
    provider._invalidate_sandbox(sandbox_id, "old transport broke")
    provider._client = SimpleNamespace(create=lambda **kwargs: new_remote)
    assert provider.acquire("thread", user_id="user") == sandbox_id
    assert provider.get(sandbox_id) is not old_box
    assert provider._replica_count() == (3, 2)
    provider.shutdown()
    assert old_remote.closed
    assert new_remote.closed
    assert old_remote.calls == 2
    assert new_remote.calls == 1


def test_shutdown_and_reaper_share_single_termination_owner(provider):
    started, release = threading.Event(), threading.Event()
    remote = Remote()
    original_close = remote.close

    def close():
        started.set()
        assert release.wait(5)
        original_close()

    remote.close = close
    box = TenkiSandbox("synthetic", remote)
    provider._warm_pool[box.id] = (box, 0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(provider._reap_expired_warm, 1)
        try:
            assert started.wait(5)
            with pytest.raises(RuntimeError, match="terminations pending"):
                provider.shutdown()
        finally:
            release.set()
        work.result(timeout=5)
    provider.shutdown()
    assert remote.calls == 1


@pytest.mark.parametrize("origin", ["invalidation", "release"])
def test_retirement_transfers_ownership_before_releasing_registry_lock(provider, monkeypatch, origin):
    entered, resume = threading.Event(), threading.Event()
    remote = Remote([OSError("temporary termination failure")])
    box = TenkiSandbox("synthetic", remote)
    provider._sandboxes[box.id] = box
    close = provider._close_quietly
    main_thread = threading.current_thread()

    def paused_close(*args, **kwargs):
        if threading.current_thread() is not main_thread:
            entered.set()
            assert resume.wait(5)
        return close(*args, **kwargs)

    monkeypatch.setattr(provider, "_close_quietly", paused_close)
    if origin == "release":
        provider._shutdown_called = True
    operation = (lambda: provider._invalidate_sandbox(box.id, "synthetic")) if origin == "invalidation" else (lambda: provider.release(box.id))
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(operation)
        try:
            assert entered.wait(5)
            with pytest.raises(RuntimeError, match="terminations pending"):
                provider.shutdown()
        finally:
            resume.set()
        work.result(timeout=5)
    provider.shutdown()
    assert remote.closed
    assert remote.calls == 2


@pytest.mark.parametrize("thread_id", ["thread", None])
def test_reset_rejects_new_acquires(provider, monkeypatch, thread_id):
    created = []
    monkeypatch.setattr(provider, "_create_sandbox", lambda sandbox_id: created.append(sandbox_id))
    provider.reset()
    with pytest.raises(RuntimeError, match="retired"):
        provider.acquire(thread_id, user_id="user")
    assert not created


def test_reaper_shutdown_failure_does_not_reopen_admission(provider, monkeypatch):
    original = provider._stop_idle_checker
    monkeypatch.setattr(provider, "_stop_idle_checker", lambda: (_ for _ in ()).throw(RuntimeError("reaper still running")))
    try:
        with pytest.raises(RuntimeError, match="reaper"):
            provider.shutdown()
        with pytest.raises(RuntimeError, match="shut|retir"):
            provider.acquire()
    finally:
        monkeypatch.setattr(provider, "_stop_idle_checker", original)
    provider.shutdown()


def test_reset_preserves_existing_warm_resource_until_shutdown(provider):
    remote = Remote()
    box = TenkiSandbox("synthetic", remote)
    provider._sandboxes[box.id] = box
    provider.reset()
    assert not remote.closed
    assert box.id in provider._warm_pool
    provider.shutdown()
    assert remote.closed


@pytest.mark.parametrize("name", ["InvalidStateError", "StreamClosedError"])
def test_non_terminal_sdk_state_error_does_not_acknowledge_termination(name):
    error = type(name, (RuntimeError,), {})("termination not confirmed")
    remote = Remote([error])
    box = TenkiSandbox("synthetic", remote)
    with pytest.raises(type(error)):
        box.close()
    assert not box.is_closed
    box.close()
    assert remote.calls == 2


@pytest.mark.asyncio
async def test_cancelled_async_acquire_remains_reusable_while_provider_open(provider, monkeypatch):
    started, release = threading.Event(), threading.Event()
    remote = Remote()

    def create(sandbox_id):
        started.set()
        assert release.wait(5)
        return TenkiSandbox(sandbox_id, remote)

    monkeypatch.setattr(provider, "_create_sandbox", create)
    work = asyncio.create_task(provider.acquire_async("thread", user_id="user"))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
    finally:
        release.set()
    sandbox_id = await provider.acquire_async("thread", user_id="user")
    assert provider.get(sandbox_id) is not None
    assert not remote.closed
