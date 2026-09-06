"""Unit tests for the BoxLite community provider.
These run in CI without BoxLite installed: they cover the lazy-import error path,
provider lifecycle, the path-safety guards, and the warm pool lifecycle — none of
which need a live box.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
import threading
import time
import types

import pytest

from deerflow.community.boxlite.box import BoxliteBox
from deerflow.community.boxlite.provider import BoxliteProvider, _import_simplebox
from deerflow.trace_context import get_current_trace_id, request_trace_context

_LEGACY_COLLIDING_IDENTITIES = (
    ("user-9721", "thread-9721"),
    ("user-94361", "thread-94361"),
)

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


def test_execute_command_appends_exit_marker_when_failure_has_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """LocalSandbox parity: a nonzero exit survives in the output text even
    when the command produced output (acceptance-checklist evidence)."""
    box = BoxliteBox("box-id", box=object(), run=_fake_run)
    monkeypatch.setattr(
        box,
        "_exec",
        lambda *argv, **kwargs: types.SimpleNamespace(exit_code=1, stdout="5 passed, 1 error\n", stderr=""),
    )

    assert box.execute_command("make test") == "5 passed, 1 error\n\nExit Code: 1"


def test_read_file_supports_optional_line_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    box = BoxliteBox("box-id", box=object(), run=_fake_run)

    def _fake_exec(*argv: str):
        calls.append(argv)
        return types.SimpleNamespace(
            exit_code=0,
            stdout="line 1\nline 2\nline 3\nline 4\nline 5",
            stderr="",
        )

    monkeypatch.setattr(box, "_exec", _fake_exec)

    assert box.read_file("/mnt/user-data/workspace/range.txt") == "line 1\nline 2\nline 3\nline 4\nline 5"
    assert box.read_file("/mnt/user-data/workspace/range.txt", start_line=2, end_line=4) == "line 2\nline 3\nline 4"
    assert box.read_file("/mnt/user-data/workspace/range.txt", start_line=4) == "line 4\nline 5"
    assert box.read_file("/mnt/user-data/workspace/range.txt", end_line=2) == "line 1\nline 2"
    assert all(call == ("cat", "--", "/mnt/user-data/workspace/range.txt") for call in calls)


def test_grep_always_prints_filename_for_single_file_paths() -> None:
    fake = _FakeBox(name="box-id")
    box = BoxliteBox("box-id", box=fake, run=_fake_run)

    box.grep("/mnt/user-data/uploads/report.md", "needle")

    grep_commands = [argv[0][2] for argv in fake._exec_history if argv[0][:2] == ("sh", "-lc") and argv[0][2].startswith("grep ")]
    assert grep_commands
    assert "-H" in grep_commands[-1].split()


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
    assert len(id1) == 16


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


@pytest.mark.asyncio
async def test_acquire_async_propagates_request_trace_context(monkeypatch):
    """acquire_async must carry request ContextVars into the worker thread.

    Regression test (#5089): the dedicated-executor bridge replaced the
    inherited ``to_thread`` acquire (which copies contextvars). Without an
    explicit ``copy_context`` the worker thread reads the trace id bound by
    ``request_trace_context()`` as unset and logs ``trace_id=-``.
    """
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

    seen: list[str | None] = []
    original = BoxliteProvider._acquire_scope_locked

    def spy(self, key, sandbox_id):
        # Runs inside the executor worker thread, under the copied context.
        seen.append(get_current_trace_id())
        return original(self, key, sandbox_id)

    monkeypatch.setattr(BoxliteProvider, "_acquire_scope_locked", spy)

    try:
        with request_trace_context("trace-boxlite-5089"):
            sid = await provider.acquire_async("thread-1", user_id="u1")
        assert sid
        assert seen == ["trace-boxlite-5089"]
    finally:
        # _fake_run uses asyncio.run, which cannot run inside this test's event
        # loop thread; shut down on a worker thread so box close() completes.
        await asyncio.to_thread(provider.shutdown)


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

    reclaimed = provider._reclaim_warm_pool(sid, ("u1", "thread-1"))
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

    reclaimed = provider._reclaim_warm_pool(sid, ("u1", "thread-1"))
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

    reclaimed = provider._reclaim_warm_pool(sid, ("u1", "thread-1"))
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

    reclaimed = provider._reclaim_warm_pool(
        "adopted",
        ("some-user", "some-thread"),
    )
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
    with pytest.raises(RuntimeError, match="closed"):
        with provider._acquire_serializer.hold("k"):
            pass
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


def test_wider_id_separates_known_legacy_collision():
    identity_a, identity_b = _LEGACY_COLLIDING_IDENTITIES
    user_a, thread_a = identity_a
    user_b, thread_b = identity_b

    old_a = hashlib.sha256(f"{user_a}:{thread_a}".encode()).hexdigest()[:8]
    old_b = hashlib.sha256(f"{user_b}:{thread_b}".encode()).hexdigest()[:8]

    assert old_a == old_b
    assert BoxliteProvider._sandbox_id(thread_a, user_a) != BoxliteProvider._sandbox_id(
        thread_b,
        user_b,
    )


def test_forced_collision_never_overwrites_active_tenant(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider._import_simplebox",
        lambda: _FakeBox,
    )
    monkeypatch.setattr(
        BoxliteProvider,
        "_sandbox_id",
        staticmethod(lambda thread_id, user_id: "deadbeefdeadbeef"),
    )

    provider = BoxliteProvider()
    provider._loop.run = _fake_run

    sandbox_id = provider.acquire("thread-a", user_id="user-a")
    box_a = provider.get(sandbox_id)
    provider.release(sandbox_id)

    assert box_a is not None
    assert sandbox_id in provider._warm_pool

    with pytest.raises(RuntimeError, match="Sandbox ID collision"):
        provider.acquire("thread-b", user_id="user-b")

    assert provider._warm_pool[sandbox_id][0] is box_a
    assert not box_a.is_closed
    assert provider.acquire("thread-a", user_id="user-a") == sandbox_id
    assert provider.get(sandbox_id) is box_a
    provider.shutdown()


def test_late_same_tenant_collision_reuses_active_box(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )

    provider = BoxliteProvider()
    sandbox_id = "deadbeefdeadbeef"
    key = ("user-a", "thread-a")
    active = BoxliteBox(
        sandbox_id,
        _FakeBox(name=f"deer-flow-boxlite-{sandbox_id}"),
        _fake_run,
        default_env={},
    )
    duplicate = BoxliteBox(
        sandbox_id,
        _FakeBox(name=f"deer-flow-boxlite-{sandbox_id}"),
        _fake_run,
        default_env={},
    )

    monkeypatch.setattr(
        BoxliteProvider,
        "_sandbox_id",
        staticmethod(lambda thread_id, user_id: sandbox_id),
    )

    def _create_box_with_late_registration(_sandbox_id):
        with provider._lock:
            provider._boxes[sandbox_id] = active
            provider._active_box_identity[sandbox_id] = key
        return duplicate

    monkeypatch.setattr(provider, "_create_box", _create_box_with_late_registration)

    assert provider.acquire("thread-a", user_id="user-a") == sandbox_id
    assert duplicate.is_closed
    assert provider.get(sandbox_id) is active
    assert provider._thread_boxes[key] == sandbox_id
    provider.shutdown()


def test_failed_health_check_does_not_remove_swapped_warm_entry(monkeypatch):
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: _stub_config(),
    )

    provider = BoxliteProvider()
    stale = BoxliteBox(
        "shared-id",
        _FakeBox(name="deer-flow-boxlite-shared-id"),
        _fake_run,
        default_env={},
    )
    replacement = BoxliteBox(
        "shared-id",
        _FakeBox(name="deer-flow-boxlite-shared-id"),
        _fake_run,
        default_env={},
    )
    provider._warm_pool["shared-id"] = (stale, time.time())
    provider._warm_pool_identity["shared-id"] = ("user-a", "thread-a")

    def _swap_during_health_check(*args, **kwargs):
        with provider._lock:
            provider._warm_pool["shared-id"] = (replacement, time.time())
            provider._warm_pool_identity["shared-id"] = (
                "user-b",
                "thread-b",
            )
        return "not healthy"

    monkeypatch.setattr(stale, "execute_command", _swap_during_health_check)

    with pytest.raises(RuntimeError, match="Sandbox ID collision"):
        provider._reclaim_warm_pool(
            "shared-id",
            ("user-a", "thread-a"),
        )
    assert provider._warm_pool["shared-id"][0] is replacement
    assert provider._warm_pool_identity["shared-id"] == (
        "user-b",
        "thread-b",
    )
    assert not replacement.is_closed
    provider.shutdown()


def test_sandbox_id_matches_shared_identity():
    from deerflow.sandbox.identity import derive_sandbox_scope_token

    assert BoxliteProvider._sandbox_id("t-1", "u-1") == derive_sandbox_scope_token(user_id="u-1", thread_id="t-1")


def test_sandbox_id_none_user_quirk_pinned():
    """BoxLite passes user_id through raw; None renders as the literal "None".

    Quirk pinned per RFC #4741 §2.2 (its _thread_key uses "" instead, so the
    two disagree). NOT fixed here — unifying the resolution is a separate
    behavior-changing decision with its own follow-up issue.
    """
    from deerflow.sandbox.identity import derive_sandbox_scope_token

    assert BoxliteProvider._sandbox_id("t-1", None) == derive_sandbox_scope_token(user_id="None", thread_id="t-1")


def test_list_dir_and_glob_preserve_trailing_space_in_filename() -> None:
    # "notes.txt " (trailing space) is a legal Linux filename; find prints it
    # verbatim, one entry per line, so a per-line strip() corrupts the name.
    class _FindBox:
        async def exec(self, *argv, env=None, timeout=None):
            return types.SimpleNamespace(stdout="/mnt/user-data/workspace/notes.txt \n", stderr="", exit_code=0)

    box = BoxliteBox("box-id", box=_FindBox(), run=_fake_run)

    assert box.list_dir("/mnt/user-data/workspace") == ["/mnt/user-data/workspace/notes.txt "]

    found, truncated = box.glob("/mnt/user-data/workspace", "notes*")
    assert found == ["/mnt/user-data/workspace/notes.txt "]
    assert truncated is False
