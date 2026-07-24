"""Unit tests for the BoxLite community provider.
These run in CI without BoxLite installed: they cover the lazy-import error path,
provider lifecycle, the path-safety guards, and the warm pool lifecycle — none of
which need a live box.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import types

import pytest

from deerflow.community.boxlite.box import BoxliteBox
from deerflow.community.boxlite.provider import BoxliteProvider, _import_simplebox

# ── Fake BoxLite SDK ──────────────────────────────────────────────────


class _FakeBox:
    """A fake SimpleBox that records lifecycle calls without starting real VMs."""

    def __init__(self, *, image=None, name=None, memory_mib=None, cpus=None, **kwargs):
        self.id = name or "auto-gen-id"
        self.name = name
        self._image = image
        self._started = False
        self._stopped = False
        self._exec_history: list[tuple] = []

    async def start(self):
        self._started = True

    async def exec(self, *argv, env=None, timeout=None):
        self._exec_history.append((argv, env, timeout))
        _FakeResult = type("_FakeResult", (), {"stdout": "", "stderr": "", "exit_code": 0})
        # Health check: box.execute_command("echo ok") → exec("sh", "-lc", "echo ok")
        if len(argv) >= 3 and argv[0] == "sh" and argv[1] == "-lc" and argv[2] == "echo ok":
            return type("_FakeResult", (), {"stdout": "ok\n", "stderr": "", "exit_code": 0})()
        return _FakeResult()

    async def stop(self):
        self._stopped = True


def _fake_run(coro, *, timeout=None):
    """Sync runner that executes coroutines on a temporary event loop (no daemon thread)."""
    return asyncio.run(coro)


# ── Config stub ───────────────────────────────────────────────────────


def _stub_config(sandbox_attrs=None):
    """Stub get_app_config to return a config with given sandbox attrs."""
    attrs = sandbox_attrs or {}
    stub = types.SimpleNamespace(sandbox=types.SimpleNamespace(**attrs))
    return stub


def _no_boxlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import boxlite`` raise, regardless of whether it is installed."""
    monkeypatch.setitem(sys.modules, "boxlite", None)


@pytest.fixture(autouse=True)
def _no_existing_boxlite_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provider startup reconciliation isolated from the real SDK state."""

    class _EmptyRuntime:
        def start(self):
            return self

        def stop(self):
            pass

        def list_info(self):
            return []

    class _EmptyBoxlite:
        @staticmethod
        def default():
            return _EmptyRuntime()

    monkeypatch.setattr("deerflow.community.boxlite.provider._import_sync_boxlite_runtime", lambda: _EmptyBoxlite)


def test_import_simplebox_missing_raises_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_boxlite(monkeypatch)
    with pytest.raises(ImportError, match=r"deerflow-harness\[boxlite\]"):
        _import_simplebox()


def test_acquire_without_boxlite_raises_and_shuts_down_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub config so the provider constructs without a config.yaml on disk.
    stub = types.SimpleNamespace(sandbox=types.SimpleNamespace())
    monkeypatch.setattr("deerflow.community.boxlite.provider.get_app_config", lambda: stub)
    _no_boxlite(monkeypatch)

    provider = BoxliteProvider()
    try:
        with pytest.raises(ImportError, match=r"deerflow-harness\[boxlite\]"):
            provider.acquire("thread-1", user_id="u")
    finally:
        provider.shutdown()  # must not raise even though no box was ever created
    # Idempotent shutdown.
    provider.shutdown()


def test_guard_traversal() -> None:
    assert BoxliteBox._guard_traversal("/mnt/user-data/workspace/a.txt") == "/mnt/user-data/workspace/a.txt"
    assert BoxliteBox._guard_traversal("relative/ok.txt") == "relative/ok.txt"
    with pytest.raises(PermissionError):
        BoxliteBox._guard_traversal("/mnt/user-data/../etc/passwd")
    with pytest.raises(ValueError):
        BoxliteBox._guard_traversal("")


def test_download_file_guards_reject_before_touching_box() -> None:
    # ``run`` must never be called: both guards raise before any exec.
    def _fail_run(_coro: object) -> None:
        raise AssertionError("download_file must reject the path before running a command")

    box = BoxliteBox("box-id", box=object(), run=_fail_run)
    with pytest.raises(PermissionError):
        box.download_file("/etc/passwd")  # outside the /mnt/user-data prefix
    with pytest.raises(PermissionError):
        box.download_file("/mnt/user-data/../etc/passwd")  # traversal


def test_execute_command_rejects_invalid_env_key() -> None:
    def _fail_run(_coro: object) -> None:
        raise AssertionError("execute_command must reject a bad env key before running")

    box = BoxliteBox("box-id", box=object(), run=_fail_run)
    with pytest.raises(ValueError, match=r"POSIX"):
        box.execute_command("echo hi", env={"BAD KEY": "x"})


def test_execute_command_forwards_timeout_to_sdk_and_loop_runner() -> None:
    """Command timeout must bound both BoxLite exec and the loop bridge future."""
    run_timeouts: list[float | None] = []

    def _recording_run(coro, *, timeout=None):
        run_timeouts.append(timeout)
        return asyncio.run(coro)

    fake = _FakeBox(name="box-id")
    box = BoxliteBox("box-id", box=fake, run=_recording_run)

    output = box.execute_command("echo ok", timeout=5)

    assert "ok" in output
    assert fake._exec_history[-1] == (("sh", "-lc", "echo ok"), None, 5)
    assert run_timeouts == [5]


def test_execute_command_invalidates_box_on_terminal_transport_error() -> None:
    invalidated: list[tuple[str, str]] = []

    def _failing_run(coro, *, timeout=None):
        coro.close()
        raise RuntimeError("vsock disconnected")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: vsock disconnected"
    assert invalidated == [("box-id", "vsock disconnected")]


def test_execute_command_does_not_invalidate_on_regular_command_error() -> None:
    invalidated: list[tuple[str, str]] = []

    def _failing_run(coro, *, timeout=None):
        coro.close()
        raise RuntimeError("user command failed")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: user command failed"
    assert invalidated == []


def test_execute_command_does_not_invalidate_on_retryable_transport_message() -> None:
    invalidated: list[tuple[str, str]] = []

    def _failing_run(coro, *, timeout=None):
        coro.close()
        raise RuntimeError("transport not ready, retry later")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: transport not ready, retry later"
    assert invalidated == []


def test_execute_command_uses_overridable_terminal_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    invalidated: list[tuple[str, str]] = []
    monkeypatch.setattr(BoxliteBox, "TERMINAL_ERROR_MARKERS", ("custom terminal marker",))
    monkeypatch.setattr(BoxliteBox, "RETRYABLE_ERROR_MARKERS", ())

    def _failing_run(coro, *, timeout=None):
        coro.close()
        raise RuntimeError("custom terminal marker")

    box = BoxliteBox(
        "box-id",
        box=_FakeBox(name="box-id"),
        run=_failing_run,
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )

    output = box.execute_command("echo hi")

    assert output == "Error: custom terminal marker"
    assert invalidated == [("box-id", "custom terminal marker")]


def test_execute_command_closed_box_returns_without_error_log(caplog) -> None:
    box = BoxliteBox("box-id", box=_FakeBox(name="box-id"), run=_fake_run)
    box.close()

    with caplog.at_level(logging.ERROR, logger="deerflow.community.boxlite.box"):
        output = box.execute_command("echo hi")

    assert output == "Error: sandbox has been closed"
    assert "Failed to execute command in BoxLite box" not in caplog.text


def test_sandbox_id_deterministic(monkeypatch):
    """_sandbox_id produces the same id for the same inputs."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    provider = BoxliteProvider()
    id1 = provider._sandbox_id("thread-1", "user-a")
    id2 = provider._sandbox_id("thread-1", "user-a")
    assert id1 == id2
    assert len(id1) == 8


def test_sandbox_id_different_users(monkeypatch):
    """Different users produce different ids for the same thread."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    provider = BoxliteProvider()
    id_a = provider._sandbox_id("thread-1", "user-a")
    id_b = provider._sandbox_id("thread-1", "user-b")
    assert id_a != id_b


def test_sandbox_id_different_threads(monkeypatch):
    """Different threads produce different ids for the same user."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    provider = BoxliteProvider()
    id_a = provider._sandbox_id("thread-1", "user-a")
    id_b = provider._sandbox_id("thread-2", "user-a")
    assert id_a != id_b


def test_idle_timeout_zero_is_preserved_and_disables_reaper(monkeypatch):
    """idle_timeout=0 is a valid config value and disables the reaper thread."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"idle_timeout": 0}),
    )

    provider = BoxliteProvider()

    assert provider._config["idle_timeout"] == 0
    assert provider._idle_checker_thread is None
    provider.shutdown()


def test_create_box_passes_prefixed_sandbox_id_as_name(monkeypatch):
    """_create_box gives BoxLite a DeerFlow-owned name prefix."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    # Inject fake SimpleBox and fake loop runner
    created_boxes = []

    class _RecordingBox(_FakeBox):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created_boxes.append(kwargs)

    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _RecordingBox,
    )

    provider = BoxliteProvider()
    # Replace _loop.run with our sync runner
    provider._loop.run = _fake_run

    box = provider._create_box("test-sandbox-id")
    assert len(created_boxes) == 1
    assert created_boxes[0]["name"] == "deer-flow-boxlite-test-sandbox-id"
    assert box.id == "test-sandbox-id"


def test_startup_reconciliation_adopts_prefixed_existing_boxes(monkeypatch):
    """Existing DeerFlow-named BoxLite boxes are adopted into the warm pool."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    stopped: list[str] = []

    class _NativeBox:
        def stop(self):
            stopped.append("adopted")

    class _Runtime:
        def start(self):
            return self

        def stop(self):
            pass

        def list_info(self):
            return [
                types.SimpleNamespace(name="deer-flow-boxlite-adopted"),
                types.SimpleNamespace(name="unrelated-box"),
                types.SimpleNamespace(name=None),
            ]

        def get(self, name):
            if name == "deer-flow-boxlite-adopted":
                return _NativeBox()
            raise AssertionError(f"unexpected box lookup: {name}")

    class _Boxlite:
        @staticmethod
        def default():
            return _Runtime()

    monkeypatch.setattr("deerflow.community.boxlite.provider._import_sync_boxlite_runtime", lambda: _Boxlite)

    provider = BoxliteProvider()

    assert list(provider._warm_pool) == ["adopted"]
    adopted_box = provider._warm_pool["adopted"][0]
    assert adopted_box.id == "adopted"

    provider.shutdown()
    assert stopped == ["adopted"]


def test_release_parks_in_warm_pool(monkeypatch):
    """After release, box is in warm pool, not destroyed."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # Acquire a box
    sid = provider.acquire("thread-1", user_id="u1")

    # Verify box is active
    assert sid in provider._boxes
    assert sid not in provider._warm_pool

    # Release
    provider.release(sid)

    # Verify box is in warm pool, not active
    assert sid not in provider._boxes
    assert sid in provider._warm_pool
    box, ts = provider._warm_pool[sid]
    assert isinstance(box, BoxliteBox)
    assert not box._box._stopped  # VM not destroyed


def test_acquire_reclaims_from_warm_pool(monkeypatch):
    """acquire reclaims a warm pool box for the same thread."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # First acquire → create
    sid1 = provider.acquire("thread-1", user_id="u1")
    provider.release(sid1)

    # Second acquire → should reclaim from warm pool
    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid1 == sid2  # Same deterministic ID
    assert sid2 in provider._boxes
    assert sid2 not in provider._warm_pool


def test_explicit_recent_reclaim_skip_avoids_health_check(monkeypatch):
    """A configured skip window can reclaim recently released boxes without a ping."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    box, _ = provider._warm_pool[sid]

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("health check should be skipped for recently released boxes")

    monkeypatch.setattr(box, "execute_command", _fail_if_called)

    reclaimed = provider._reclaim_warm_pool(sid)
    assert reclaimed == sid
    assert sid in provider._boxes
    assert sid not in provider._warm_pool

    provider.shutdown()


def test_recent_reclaim_validates_by_default(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    box, _ = provider._warm_pool[sid]
    calls = 0
    original_execute = box.execute_command

    def _record_health_check(command: str, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(box, "execute_command", _record_health_check)

    reclaimed = provider._reclaim_warm_pool(sid)
    assert reclaimed == sid
    assert calls == 1
    assert sid in provider._boxes
    assert sid not in provider._warm_pool

    provider.shutdown()


def test_default_recent_reclaim_drops_dead_warm_box(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    box, _ = provider._warm_pool[sid]

    def _dead_health_check(command: str, *args, **kwargs):
        assert command == "echo ok"
        return "Error: vsock disconnected"

    monkeypatch.setattr(box, "execute_command", _dead_health_check)

    reclaimed = provider._reclaim_warm_pool(sid)
    assert reclaimed is None
    assert sid not in provider._boxes
    assert sid not in provider._warm_pool
    assert sid not in provider._skip_health_check_warm_ids
    assert box.is_closed is True

    provider.shutdown()


def test_dead_active_box_invalidation_closes_adapter(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    box = provider.get(sid)
    assert box is not None

    def _dead_run(coro, *, timeout=None):
        coro.close()
        raise RuntimeError("vsock disconnected")

    box._run = _dead_run

    output = box.execute_command("echo hi")
    assert output == "Error: vsock disconnected"
    assert box._closed is True
    assert provider.get(sid) is None

    provider.shutdown()


def test_adopted_warm_pool_box_still_health_checks(monkeypatch):
    """Startup-adopted boxes must still pass a health check before reclaim."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )

    provider = BoxliteProvider()
    adopted = BoxliteBox(
        "adopted",
        _FakeBox(name="deer-flow-boxlite-adopted"),
        _fake_run,
        default_env={},
    )
    provider._warm_pool["adopted"] = (adopted, time.time())
    calls = 0
    original_execute = adopted.execute_command

    def _record_health_check(command: str, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_execute(command, *args, **kwargs)

    monkeypatch.setattr(adopted, "execute_command", _record_health_check)

    reclaimed = provider._reclaim_warm_pool("adopted")
    assert reclaimed == "adopted"
    assert calls == 1
    assert "adopted" in provider._boxes
    assert "adopted" not in provider._warm_pool

    provider.shutdown()


def test_dead_active_box_is_invalidated_after_command_failure(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    box = provider.get(sid)
    assert box is not None

    def _dead_run(coro, *, timeout=None):
        coro.close()
        raise RuntimeError("vsock disconnected")

    box._run = _dead_run

    output = box.execute_command("echo hi")
    assert output == "Error: vsock disconnected"
    assert provider.get(sid) is None

    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid2 == sid
    assert provider.get(sid2) is not None

    provider.shutdown()


def test_stale_closed_adapter_cannot_invalidate_recreated_box(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"health_check_skip_seconds": 5}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    stale_box = provider.get(sid)
    assert stale_box is not None

    def _dead_run(coro, *, timeout=None):
        coro.close()
        raise RuntimeError("vsock disconnected")

    stale_box._run = _dead_run
    stale_box.execute_command("echo hi")
    assert provider.get(sid) is None

    provider._loop.run = _fake_run
    sid2 = provider.acquire("thread-1", user_id="u1")
    replacement = provider.get(sid2)
    assert sid2 == sid
    assert replacement is not None
    assert replacement is not stale_box

    stale_box.execute_command("echo again")

    assert provider.get(sid) is replacement
    assert replacement._closed is False

    provider.shutdown()


def test_acquire_different_threads_dont_reclaim_each_other(monkeypatch):
    """Thread A's box can't be reclaimed by thread B."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_a = provider.acquire("thread-a", user_id="u1")
    provider.release(sid_a)

    # Thread B acquires — should NOT get thread A's box
    sid_b = provider.acquire("thread-b", user_id="u1")
    assert sid_b != sid_a  # Different deterministic ID
    assert sid_a in provider._warm_pool  # A's box still in warm pool
    assert sid_b in provider._boxes  # B's box is new


def test_warm_pool_reclaim_failed_health_check_creates_new(monkeypatch):
    """Dead warm pool box is evicted and a new one created."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid1 = provider.acquire("thread-1", user_id="u1")
    provider.release(sid1)
    assert sid1 in provider._warm_pool

    # Corrupt the warm pool box: close it so health check fails
    box, _ = provider._warm_pool[sid1]
    box.close()  # Stop VM, marks _closed=True

    # Re-acquire — health check should fail on the dead box
    # A new box is created with the same deterministic ID
    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid2 == sid1  # Same deterministic ID
    assert sid2 in provider._boxes
    replacement = provider.get(sid2)
    assert replacement is not None
    assert replacement is not box
    assert replacement._closed is False


def test_concurrent_same_thread_acquire_creates_one_box(monkeypatch):
    """Concurrent acquires for one thread serialize before creating a named box."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run
    original_create_box = provider._create_box
    create_started = threading.Event()
    created: list[str] = []

    def slow_create_box(sandbox_id: str) -> BoxliteBox:
        create_started.set()
        time.sleep(0.1)
        created.append(sandbox_id)
        return original_create_box(sandbox_id)

    provider._create_box = slow_create_box  # type: ignore[method-assign]
    results: list[str] = []

    def acquire() -> None:
        results.append(provider.acquire("thread-1", user_id="u1"))

    first = threading.Thread(target=acquire)
    second = threading.Thread(target=acquire)
    first.start()
    assert create_started.wait(timeout=2)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert len(results) == 2
    assert results[0] == results[1]
    assert len(created) == 1
    assert results[0] in provider._boxes
    provider.shutdown()


def test_release_during_shutdown_closes_instead_of_reparking(monkeypatch):
    """release() must not park a VM after shutdown has begun."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid = provider.acquire("thread-1", user_id="u1")
    box = provider._boxes[sid]
    with provider._lock:
        provider._shutdown_called = True

    provider.release(sid)

    assert sid not in provider._boxes
    assert sid not in provider._warm_pool
    assert box._closed
    provider._loop.close()


def test_reset_parks_running_resources_for_later_cleanup(monkeypatch):
    """reset() stops thread reuse but leaves VMs tracked for cleanup."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_active = provider.acquire("thread-active", user_id="u1")
    sid_warm = provider.acquire("thread-warm", user_id="u1")
    provider.release(sid_warm)
    active_box = provider._boxes[sid_active]
    warm_box = provider._warm_pool[sid_warm][0]
    checker_thread = provider._idle_checker_thread
    loop_thread = provider._loop._thread

    provider.reset()

    assert provider._boxes == {}
    assert provider._warm_pool[sid_active][0] is active_box
    assert provider._warm_pool[sid_warm][0] is warm_box
    assert provider._thread_boxes == {}
    assert provider._acquire_locks == {}
    assert not active_box._closed
    assert not warm_box._closed
    assert not provider._shutdown_called
    assert not provider._idle_checker_stop.is_set()
    assert checker_thread is not None
    assert checker_thread.is_alive()
    assert loop_thread.is_alive()

    provider.shutdown()
    assert active_box._closed
    assert warm_box._closed
    assert provider._idle_checker_stop.is_set()
    assert not checker_thread.is_alive()


def test_reset_parked_resources_are_reaped_after_idle_timeout(monkeypatch):
    """VMs parked by reset remain visible to warm-pool idle cleanup."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_active = provider.acquire("thread-active", user_id="u1")
    sid_warm = provider.acquire("thread-warm", user_id="u1")
    provider.release(sid_warm)
    active_box = provider._boxes[sid_active]
    warm_box = provider._warm_pool[sid_warm][0]

    provider.reset()

    provider._warm_pool[sid_active] = (active_box, time.time() - 9999)
    provider._warm_pool[sid_warm] = (warm_box, time.time() - 9999)
    provider._reap_expired_warm(idle_timeout=1)

    assert provider._warm_pool == {}
    assert active_box._closed
    assert warm_box._closed
    provider.shutdown()


# ── Task 6: Idle reaper ───────────────────────────────────────────────


def test_idle_reaper_destroys_expired_warm_boxes(monkeypatch):
    """Idle reaper daemon destroys warm pool boxes that exceed the idle timeout."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    # Use a very short check interval so the reaper runs quickly
    monkeypatch.setattr(BoxliteProvider, "IDLE_CHECK_INTERVAL", 0.1)
    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # Acquire and release a box into the warm pool
    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)

    assert sid in provider._warm_pool

    # Backdate the warm-pool timestamp so it appears long-expired
    warm_box = provider._warm_pool[sid][0]
    provider._warm_pool[sid] = (warm_box, time.time() - 9999)

    # Wait long enough for the reaper to detect and destroy it
    time.sleep(0.3)

    # Box should be gone from warm pool and closed
    assert sid not in provider._warm_pool
    assert warm_box._closed

    provider.shutdown()


# ── Task 7: Replica enforcement ───────────────────────────────────────


def test_replica_enforcement_evicts_oldest_warm(monkeypatch):
    """When warm pool exceeds replica limit, the oldest box is evicted."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"replicas": 2}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # Fill warm pool with 2 boxes from different threads
    sid_a = provider.acquire("thread-a", user_id="u1")
    provider.release(sid_a)

    sid_b = provider.acquire("thread-b", user_id="u1")
    provider.release(sid_b)

    assert len(provider._warm_pool) == 2
    assert sid_a in provider._warm_pool
    assert sid_b in provider._warm_pool

    # Make sid_a definitely older by backdating its timestamp
    box_a = provider._warm_pool[sid_a][0]
    provider._warm_pool[sid_a] = (box_a, time.time() - 100)
    # Refresh sid_b's timestamp so it's newer
    box_b = provider._warm_pool[sid_b][0]
    provider._warm_pool[sid_b] = (box_b, time.time())

    # Acquiring a third thread triggers replica enforcement:
    # warm pool count (2) >= replicas (2) → evict oldest (sid_a)
    sid_c = provider.acquire("thread-c", user_id="u1")

    # Oldest (sid_a) should be evicted (gone from warm pool, closed)
    assert sid_a not in provider._warm_pool
    assert box_a._closed
    # Newer (sid_b) should remain in warm pool
    assert sid_b in provider._warm_pool
    # New box (sid_c) should be active
    assert sid_c in provider._boxes
    assert sid_c not in provider._warm_pool

    provider.shutdown()


def test_replica_enforcement_counts_active_and_warm(monkeypatch):
    """replicas caps active + warm boxes, not warm boxes alone."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config({"replicas": 2}),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sid_active = provider.acquire("thread-active", user_id="u1")
    sid_warm = provider.acquire("thread-warm", user_id="u1")
    provider.release(sid_warm)
    warm_box = provider._warm_pool[sid_warm][0]

    sid_new = provider.acquire("thread-new", user_id="u1")

    assert sid_active in provider._boxes
    assert sid_new in provider._boxes
    assert sid_warm not in provider._warm_pool
    assert warm_box._closed
    provider.shutdown()


# ── Task 8: Shutdown and reset including warm pool ────────────────────


def test_shutdown_stops_idle_reaper_and_destroys_all_boxes(monkeypatch):
    """shutdown stops the idle reaper thread and destroys all active + warm boxes."""
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    # Create one active box (thread-1) and one warm pool box (thread-2 released)
    sid_active = provider.acquire("thread-1", user_id="u1")
    sid_warm = provider.acquire("thread-2", user_id="u1")
    provider.release(sid_warm)

    assert sid_active in provider._boxes
    assert sid_warm in provider._warm_pool

    # Get box references before shutdown
    box_active = provider._boxes[sid_active]
    box_warm = provider._warm_pool[sid_warm][0]

    # Remember the idle checker thread
    checker_thread = provider._idle_checker_thread

    provider.shutdown()

    # Idle checker should be stopped
    assert provider._idle_checker_stop.is_set()
    assert checker_thread is not None
    assert not checker_thread.is_alive()

    # All boxes (active + warm) should be closed
    assert box_active._closed
    assert box_warm._closed

    # All collections should be empty
    assert len(provider._boxes) == 0
    assert len(provider._warm_pool) == 0
    assert len(provider._thread_boxes) == 0
