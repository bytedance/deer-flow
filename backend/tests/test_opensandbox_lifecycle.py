"""Offline lifecycle ownership; only the external SDK boundary is synthetic."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from deerflow.community.opensandbox.provider import OpenSandboxProvider


class Remote:
    def __init__(self, identifier, *, failure=None, bootstrap_failure=False):
        self.id = identifier
        self.failure = failure
        self.bootstrap_failure = bootstrap_failure
        self.transport_closed = False
        self.destroy_calls = 0
        self.commands = SimpleNamespace(run=self.run)

    def run(self, command, **kwargs):
        return SimpleNamespace(exit_code=1 if self.bootstrap_failure else 0, logs=SimpleNamespace(stdout=[], stderr=[]), result=[])

    def renew(self, timeout):
        if self.transport_closed:
            raise RuntimeError("synthetic client transport closed")

    def destroy(self):
        self.destroy_calls += 1
        if self.transport_closed:
            raise RuntimeError("synthetic client transport already closed")
        # Mirrors SandboxSync.destroy: close transport even when DELETE fails.
        self.transport_closed = True
        if self.failure is not None:
            raise self.failure


@pytest.fixture
def provider(monkeypatch):
    config = dict(
        api_key="synthetic-secret",
        domain="synthetic.invalid",
        protocol="https",
        request_timeout=7,
        ready_timeout=10,
        sandbox_timeout=3600,
        command_timeout=10,
        environment={},
        replicas=3,
        idle_timeout=0,
        use_server_proxy=False,
        image="synthetic",
    )
    monkeypatch.setattr(OpenSandboxProvider, "_load_config", lambda self: config)
    monkeypatch.setattr("deerflow.community.opensandbox.provider.atexit.register", lambda callback: None)
    remotes = []
    manager_calls = []
    managers = []
    manager_errors = []

    def create(image, **kwargs):
        remote = Remote(f"remote-{len(remotes) + 1}")
        remotes.append(remote)
        return remote

    def config_class(**kwargs):
        return SimpleNamespace(options=kwargs)

    class Manager:
        def __init__(self, connection_config):
            self.connection_config = connection_config
            self.closed = False
            managers.append(self)

        @classmethod
        def create(cls, connection_config):
            return cls(connection_config)

        def kill_sandbox(self, sandbox_id):
            manager_calls.append(sandbox_id)
            if manager_errors:
                raise manager_errors.pop(0)

        def close(self):
            self.closed = True

    monkeypatch.setattr("deerflow.community.opensandbox.provider._import_sdk", lambda: (SimpleNamespace(create=create), config_class, lambda **kwargs: kwargs))
    # raising=False also lets the same regression execute on unchanged main.
    monkeypatch.setattr("deerflow.community.opensandbox.provider._import_manager", lambda: Manager, raising=False)
    value = OpenSandboxProvider()
    value._test_remotes = remotes
    value._test_manager_calls = manager_calls
    value._test_managers = managers
    value._test_manager_errors = manager_errors
    yield value
    manager_errors.clear()
    value.shutdown()


@pytest.mark.parametrize("origin", ["shutdown", "idle", "replicas", "invalidation"])
def test_failed_delete_retries_with_fresh_management_client(provider, origin):
    sandbox_id = provider.acquire("thread", user_id="owner")
    remote = provider._test_remotes[0]
    remote.failure = OSError("synthetic delete unavailable")
    if origin == "shutdown":
        with pytest.raises(RuntimeError, match="terminat|cleanup"):
            provider.shutdown()
    elif origin == "invalidation":
        provider._invalidate_sandbox(sandbox_id, "synthetic terminal failure")
    else:
        # User-less release avoids unrelated output mirroring in this fixture.
        with provider._lock:
            box = provider._sandboxes.pop(sandbox_id)
            provider._thread_sandboxes.clear()
            provider._warm_pool[sandbox_id] = (box, 0)
        if origin == "idle":
            provider._reap_expired_warm(1)
        else:
            provider._evict_oldest_warm()
    assert remote.transport_closed
    assert provider.get(sandbox_id) is None
    provider.shutdown()
    assert remote.destroy_calls == 1
    assert provider._test_manager_calls == [remote.id]
    assert all(manager.closed for manager in provider._test_managers)
    assert provider._test_managers[0].connection_config.options["request_timeout"].total_seconds() == 7


def test_retry_failure_stays_owned_and_closes_each_management_client(provider):
    provider.acquire("thread", user_id="owner")
    remote = provider._test_remotes[0]
    remote.failure = OSError("initial failure")
    with pytest.raises(RuntimeError, match="terminat|cleanup"):
        provider.shutdown()
    provider._test_manager_errors.append(OSError("retry unavailable"))
    with pytest.raises(RuntimeError, match="terminat|cleanup"):
        provider.shutdown()
    assert provider._test_managers[0].closed
    provider.shutdown()
    assert provider._test_manager_calls == [remote.id, remote.id]
    assert remote.destroy_calls == 1


def test_bootstrap_failure_retains_failed_delete_without_replacing_original_error(provider, monkeypatch):
    sdk, config_class, opts = provider._get_sdk()
    create = sdk.create

    def fail_bootstrap(*args, **kwargs):
        remote = create(*args, **kwargs)
        remote.bootstrap_failure = True
        remote.failure = OSError("delete unavailable")
        return remote

    monkeypatch.setattr(sdk, "create", fail_bootstrap)
    with pytest.raises(RuntimeError, match="bootstrap"):
        provider.acquire("thread", user_id="owner")
    provider.shutdown()
    assert provider._test_manager_calls == ["remote-1"]


@pytest.mark.parametrize("thread_id", [None, "thread"])
@pytest.mark.parametrize("stop", ["reset", "shutdown"])
def test_stop_fences_late_created_sandbox(provider, monkeypatch, thread_id, stop):
    started, resume = threading.Event(), threading.Event()
    sdk, _, _ = provider._get_sdk()
    create = sdk.create

    def gated_create(*args, **kwargs):
        started.set()
        assert resume.wait(5)
        return create(*args, **kwargs)

    monkeypatch.setattr(sdk, "create", gated_create)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(provider.acquire, thread_id, user_id="owner")
        try:
            assert started.wait(5)
            if stop == "shutdown":
                with pytest.raises(RuntimeError, match="acquir"):
                    provider.shutdown()
            else:
                provider.reset()
        finally:
            resume.set()
        with pytest.raises(RuntimeError, match="retir|shut"):
            future.result(timeout=5)
    provider.shutdown()
    assert not provider._sandboxes
    assert not provider._warm_pool
    assert provider._test_remotes[0].destroy_calls == 1


def test_reset_rejects_new_random_acquire(provider):
    provider.reset()
    with pytest.raises(RuntimeError, match="retir|shut"):
        provider.acquire()
    assert not provider._test_remotes


def test_old_callback_cannot_destroy_replacement(provider):
    sandbox_id = provider.acquire("thread", user_id="owner")
    previous = provider.get(sandbox_id)
    provider._invalidate_sandbox(sandbox_id, "first failure")
    assert provider.acquire("thread", user_id="owner") == sandbox_id
    replacement = provider.get(sandbox_id)
    previous._note_failure(ConnectionError("late old operation failure"))
    assert provider.get(sandbox_id) is replacement
    assert provider._test_remotes[1].destroy_calls == 0


def test_idle_cleanup_retries_and_counts_pending_remote_capacity(provider):
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider._test_remotes[0].failure = OSError("initial failure")
    provider._invalidate_sandbox(sandbox_id, "synthetic failure")
    assert provider._replica_count() == (3, 1)
    provider._cleanup_idle_resources(1)
    assert provider._replica_count() == (3, 0)
    assert provider._test_manager_calls == ["remote-1"]


def test_reset_preserves_pending_and_existing_generations(provider):
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider._test_remotes[0].failure = OSError("old generation failure")
    provider._invalidate_sandbox(sandbox_id, "old operation")
    assert provider.acquire("thread", user_id="owner") == sandbox_id
    provider.reset()
    assert sandbox_id in provider._warm_pool
    assert provider._replica_count() == (3, 2)
    provider.shutdown()
    assert provider._test_manager_calls == ["remote-1"]
    assert provider._test_remotes[1].destroy_calls == 1


def test_reaper_failure_keeps_admission_fenced_and_shutdown_retryable(provider, monkeypatch):
    stop = provider._stop_idle_checker

    def fail():
        raise RuntimeError("synthetic reaper still running")

    monkeypatch.setattr(provider, "_stop_idle_checker", fail)
    try:
        with pytest.raises(RuntimeError, match="reaper"):
            provider.shutdown()
        with pytest.raises(RuntimeError, match="retir|shut"):
            provider.acquire()
    finally:
        monkeypatch.setattr(provider, "_stop_idle_checker", stop)
    provider.shutdown()


def test_invalidation_transfers_pending_ownership_before_close_worker_starts(provider, monkeypatch):
    sandbox_id = provider.acquire("thread", user_id="owner")
    provider._test_remotes[0].failure = OSError("initial failure")
    entered, resume = threading.Event(), threading.Event()
    close = provider._destroy_quietly
    main_thread = threading.current_thread()

    def gated(*args, **kwargs):
        if threading.current_thread() is not main_thread:
            entered.set()
            assert resume.wait(5)
        return close(*args, **kwargs)

    monkeypatch.setattr(provider, "_destroy_quietly", gated)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(provider._invalidate_sandbox, sandbox_id, "synthetic failure")
        try:
            assert entered.wait(5)
            with pytest.raises(RuntimeError, match="terminations pending"):
                provider.shutdown()
        finally:
            resume.set()
        future.result(timeout=5)
    provider.shutdown()
    assert provider._test_manager_calls == ["remote-1"]
