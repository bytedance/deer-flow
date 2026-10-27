import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_session_view_uses_distinct_shell_scopes_without_rewriting_file_contents():
    from deerflow.community.aio_sandbox.user_pool import UserSandboxView

    physical = MagicMock()
    physical.execute_command_in_scope.return_value = "ok"
    a = UserSandboxView("view-a", physical)
    b = UserSandboxView("view-b", physical)
    a.execute_command("pwd")
    b.execute_command("pwd")
    scopes = [call.kwargs["scope_id"] for call in physical.execute_command_in_scope.call_args_list if call.args[0] == "pwd"]
    assert scopes[0] != scopes[1]
    a.write_file("/mnt/user-data/outputs/file.txt", "literal /mnt/user-data")
    physical.write_file.assert_called_once_with("/mnt/user-data/outputs/file.txt", "literal /mnt/user-data", append=False)


def test_user_admission_waits_for_other_chat_but_not_another_user():
    from deerflow.community.aio_sandbox.user_pool import UserAdmission

    admission = UserAdmission(timeout=1)
    admission.acquire("alice", "a")
    admission.acquire("bob", "b")
    entered = threading.Event()

    def wait():
        admission.acquire("alice", "c")
        entered.set()

    worker = threading.Thread(target=wait)
    worker.start()
    assert not entered.wait(0.05)
    admission.release("alice", "a")
    assert entered.wait(1)
    worker.join()


def test_user_admission_times_out_and_remains_usable():
    from deerflow.community.aio_sandbox.user_pool import UserAdmission

    admission = UserAdmission(timeout=0.01)
    admission.acquire("alice", "a")
    with pytest.raises(TimeoutError):
        admission.acquire("alice", "b")
    admission.release("alice", "a")
    admission.acquire("alice", "b")


def test_pool_identity_shares_same_user_and_separates_other_users():
    from deerflow.community.aio_sandbox.user_pool import UserAioSandboxProvider

    assert UserAioSandboxProvider.pool_thread("alice") == UserAioSandboxProvider.pool_thread("alice")
    assert UserAioSandboxProvider.pool_thread("alice") != UserAioSandboxProvider.pool_thread("bob")


def test_explicit_skill_policy_uses_thread_isolation(tmp_path, monkeypatch):
    from deerflow.community.aio_sandbox import user_pool
    from deerflow.config.paths import Paths

    paths = Paths(tmp_path)
    root = paths.thread_skills_view_dir("a", user_id="alice")
    root.mkdir(parents=True)
    (root / ".projection-manifest.json").write_text('{"allowed_skills":["restricted"]}', encoding="utf-8")
    monkeypatch.setattr(user_pool, "get_paths", lambda: paths)
    assert user_pool.UserAioSandboxProvider._has_explicit_policy("a", "alice")


@pytest.fixture
def pool(tmp_path, monkeypatch):
    from deerflow.community.aio_sandbox import user_pool
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from deerflow.config.paths import Paths

    paths = Paths(tmp_path)
    monkeypatch.setattr(user_pool, "get_paths", lambda: paths)
    provider = object.__new__(user_pool.UserAioSandboxProvider)
    provider._admission = user_pool.UserAdmission(timeout=0.5)
    provider._pool_creation = threading.Lock()
    provider._lock = threading.Lock()
    provider._views, provider._view_created, provider._view_processes = {}, {}, {}
    provider._pool_roots, provider._fallback_users = set(), {}
    provider._sandbox_infos, provider._sandboxes, provider._warm_pool = {}, {}, {}
    provider._last_activity = {}
    provider._config = {"replicas": 2}
    provider._closing = False
    provider._wait_executor = ThreadPoolExecutor(max_workers=2)
    provider._wait_slots = threading.BoundedSemaphore(8)
    provider.activations = []

    def acquire(self, thread_id, *, user_id):
        identity = user_id + ":" + thread_id
        self._warm_pool.pop(identity, None)
        self._sandbox_infos[identity] = SimpleNamespace(container_name=identity)
        self._sandboxes.setdefault(identity, MagicMock(id=identity))
        return identity

    def release(self, identity):
        self._warm_pool[identity] = self._sandbox_infos.pop(identity, None)

    monkeypatch.setattr(AioSandboxProvider, "acquire", acquire)
    monkeypatch.setattr(AioSandboxProvider, "release", release)
    monkeypatch.setattr(AioSandboxProvider, "get", lambda self, identity: self._sandboxes.get(identity) if identity in self._sandbox_infos else None)
    monkeypatch.setattr(provider, "_prepare_pool_skills", lambda *args: None)
    monkeypatch.setattr(provider, "_activate_thread", lambda *args: provider.activations.append(args))
    monkeypatch.setattr(provider, "_process_snapshot", lambda *_: set())
    monkeypatch.setattr(provider, "_close_user_terminals", lambda *_: None)
    yield provider
    provider._wait_executor.shutdown(wait=True)


def test_same_user_reuses_physical_container_but_different_users_do_not(pool):
    a = pool.acquire("chat-a", user_id="alice")
    physical_a = pool.get(a).physical
    pool.release(a)
    assert pool.get(a) is None
    b = pool.acquire("chat-b", user_id="alice")
    c = pool.acquire("chat-c", user_id="bob")
    assert pool.get(b).physical is physical_a
    assert pool.get(c).physical is not physical_a
    assert [call[1] for call in pool.activations] == ["chat-a", "chat-b", "chat-c"]
    pool.release(b)
    pool.release(c)


@pytest.mark.asyncio
async def test_cancelling_waiter_does_not_switch_running_conversation(pool):
    from deerflow.sandbox.lease import get_sandbox_lease_manager

    manager = get_sandbox_lease_manager(pool)
    pool._admission.timeout = 5
    a = pool.acquire("chat-a", user_id="alice")
    task = asyncio.create_task(manager.acquire_async("waiting-owner", "chat-b", user_id="alice"))
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    assert len(pool.activations) == 1
    assert pool.get(a) is not None
    pool.release(a)
    b = await pool.acquire_async("chat-b", user_id="alice")
    assert pool.get(b) is not None
    pool.release(b)


def test_failed_workspace_switch_releases_capacity_and_user_admission(pool, monkeypatch):
    monkeypatch.setattr(pool, "_activate_thread", MagicMock(side_effect=RuntimeError("failed")))
    with pytest.raises(RuntimeError, match="failed"):
        pool.acquire("chat-a", user_id="alice")
    assert not pool._admission.active
    assert not pool._sandbox_infos


def test_active_capacity_is_hard_limit(pool, monkeypatch):
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

    create = MagicMock()
    monkeypatch.setattr(AioSandboxProvider, "_create_sandbox", create)
    monkeypatch.setattr(pool, "_evict_oldest_warm", lambda: None)
    pool._sandbox_infos.update({"one": object(), "two": object()})
    pool._admission.timeout = 0.01
    with pytest.raises(TimeoutError, match="并发"):
        pool._create_sandbox("three", "id-three", user_id="alice")
    create.assert_not_called()


def test_leftover_processes_force_recycling_before_next_conversation(pool, monkeypatch):
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

    view = pool.acquire("chat-a", user_id="alice")
    destroy = MagicMock()
    monkeypatch.setattr(AioSandboxProvider, "destroy", destroy)
    monkeypatch.setattr(pool, "_process_snapshot", lambda *_: {(100, 42)})
    pool.release(view)
    destroy.assert_called_once()
    assert not pool._admission.active


def test_prewarm_does_not_evict_if_capacity_fills_after_initial_check(pool, monkeypatch):
    from deerflow.community.aio_sandbox import user_pool

    pool._sandbox_infos.update({"one": object(), "two": object()})
    evict = MagicMock()
    monkeypatch.setattr(pool, "_evict_oldest_warm", evict)
    token = user_pool._prewarming.set(True)
    try:
        with pytest.raises(user_pool._PrewarmSkipped):
            pool._create_sandbox("three", "id-three", user_id="alice")
    finally:
        user_pool._prewarming.reset(token)
    evict.assert_not_called()


def test_reset_releases_single_gateway_ownership(pool, monkeypatch):
    shutdown = MagicMock()
    monkeypatch.setattr(pool, "shutdown", shutdown)
    pool.reset()
    shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_timeout_includes_time_queued_for_acquisition_worker(pool):

    pool._admission.timeout = 0.04
    blocker = threading.Event()
    workers = [pool._wait_executor.submit(blocker.wait) for _ in range(2)]
    task = asyncio.create_task(pool.acquire_async("chat-a", user_id="alice"))
    await asyncio.sleep(0.08)
    blocker.set()
    with pytest.raises(TimeoutError):
        await task
    for worker in workers:
        worker.result(timeout=1)
    assert not pool.activations
