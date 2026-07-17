"""Unit tests for the Tenki community sandbox provider.

These run in CI without ``tenki-sandbox`` installed: they cover the lazy-import
error path, provider lifecycle, path-safety guards, the base64 file round-trip,
warm-pool mechanics, and scope resolution — none of which need a live sandbox.
A single opt-in integration test (``test_integration_real_sandbox``) exercises a
real Tenki microVM end to end when ``TENKI_API_KEY`` is set.
"""

from __future__ import annotations

import base64
import os
import re
import shlex
import sys
import threading
import time
import types

import pytest

from deerflow.community.tenki.provider import TenkiSandboxProvider, _import_client
from deerflow.community.tenki.sandbox import TenkiSandbox

# ── Fake Tenki SDK ────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, exit_code: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode(errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode(errors="replace")


class _FakeSessionTerminatedError(RuntimeError):
    """Stand-in whose class name matches a Tenki terminal error."""


# Rename so ``type(e).__name__`` matches the adapter's terminal-name set.
_FakeSessionTerminatedError.__name__ = "SessionTerminatedError"


class _FakeSandbox:
    """A fake tenki ``Sandbox`` that interprets the handful of shell commands
    the adapter emits, backed by an in-memory filesystem — so write/read/
    download/list round-trips are exercised for real without a live VM.
    """

    def __init__(
        self,
        *,
        exec_error: Exception | None = None,
        close_error: Exception | None = None,
        exec_error_sequence: list[Exception | None] | None = None,
    ) -> None:
        self.id = "remote-session-id"
        self.files: dict[str, bytes] = {}
        self.exec_calls: list[tuple] = []
        self.exec_error = exec_error
        # Per-call errors popped in order; None means "succeed normally". Lets a
        # test make the first exec fail transiently and the retry succeed.
        self.exec_error_sequence = exec_error_sequence
        self.close_error = close_error
        self.closed = False

    def exec(self, *argv: str, cwd=None, env=None, timeout=None):
        self.exec_calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout": timeout})
        if self.exec_error_sequence:
            err = self.exec_error_sequence.pop(0)
            if err is not None:
                raise err
        if self.exec_error is not None:
            raise self.exec_error
        if argv[:2] == ("cat", "--"):
            path = argv[2]
            if path not in self.files:
                return _FakeResult(exit_code=1, stderr=b"cat: no such file")
            return _FakeResult(stdout=self.files[path])
        if argv[:2] == ("sh", "-lc"):
            return self._run_script(argv[2])
        return _FakeResult()

    def _run_script(self, script: str) -> _FakeResult:
        if script == "echo ok":
            return _FakeResult(stdout=b"ok\n")
        if "BOOTSTRAP_OK" in script:  # provider create-time bootstrap script
            return _FakeResult(stdout=b"BOOTSTRAP_OK\n")
        if script.startswith("mkdir -p"):
            return _FakeResult()
        m = re.match(r"^printf %s (.+) \| base64 -d (>>|>) (.+)$", script)
        if m:
            chunk_q, redir, path_q = m.groups()
            chunk = shlex.split(chunk_q)[0]
            path = shlex.split(path_q)[0]
            data = base64.b64decode(chunk)
            self.files[path] = (self.files.get(path, b"") + data) if redir == ">>" else data
            return _FakeResult()
        m = re.match(r"^: (>>|>) (.+)$", script)
        if m:
            redir, path_q = m.groups()
            path = shlex.split(path_q)[0]
            if redir == ">" or path not in self.files:
                self.files[path] = self.files.get(path, b"") if redir == ">>" else b""
            return _FakeResult()
        m = re.match(r"^wc -c < (.+)$", script)
        if m:
            path = shlex.split(m.group(1))[0]
            return _FakeResult(stdout=f"{len(self.files.get(path, b''))}\n".encode())
        m = re.match(r"^base64 (.+)$", script)
        if m:
            path = shlex.split(m.group(1))[0]
            return _FakeResult(stdout=base64.b64encode(self.files.get(path, b"")))
        if script.startswith("find "):
            root = shlex.split(script)[1]
            hits = [p for p in self.files if p == root or p.startswith(f"{root.rstrip('/')}/")]
            return _FakeResult(stdout=("\n".join(hits) + "\n").encode() if hits else b"")
        return _FakeResult()

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakeProject:
    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


class _FakeWorkspace:
    def __init__(self, id: str, name: str, projects: list[_FakeProject]) -> None:
        self.id = id
        self.name = name
        self.projects = projects


class _FakeIdentity:
    def __init__(self, workspaces: list[_FakeWorkspace]) -> None:
        self.workspaces = workspaces


class _FakeClient:
    def __init__(self, *, workspaces=None, sandbox_factory=None, **kwargs) -> None:
        self.create_count = 0
        self.create_kwargs: list[dict] = []
        self._sandbox_factory = sandbox_factory or (lambda: _FakeSandbox())
        self.last_sandbox: _FakeSandbox | None = None
        self._by_id: dict[str, _FakeSandbox] = {}
        self._workspaces = workspaces if workspaces is not None else [_FakeWorkspace("ws1", "Workspace", [_FakeProject("proj1", "Project")])]

    def who_am_i(self):
        return _FakeIdentity(self._workspaces)

    def create(self, **kwargs):
        self.create_count += 1
        self.create_kwargs.append(kwargs)
        sandbox = self._sandbox_factory()
        sandbox.id = f"sb{self.create_count}"
        self._by_id[sandbox.id] = sandbox
        self.last_sandbox = sandbox
        return sandbox

    def get(self, sandbox_id):
        return self._by_id[sandbox_id]


# ── Config stub ───────────────────────────────────────────────────────


def _stub_config(sandbox_attrs=None):
    attrs = sandbox_attrs or {}
    return types.SimpleNamespace(sandbox=types.SimpleNamespace(**attrs))


def _install(monkeypatch, *, client=None, config_attrs=None):
    """Construct a provider with get_app_config + _import_client stubbed."""
    monkeypatch.setattr(
        "deerflow.community.tenki.provider.get_app_config",
        lambda: _stub_config(config_attrs),
    )
    if client is not None:
        monkeypatch.setattr(
            "deerflow.community.tenki.provider._import_client",
            lambda: lambda **kw: client,
        )
    provider = TenkiSandboxProvider()
    return provider


def _no_tenki(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "tenki_sandbox", None)


# ── Lazy import ────────────────────────────────────────────────────────


def test_import_client_missing_raises_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_tenki(monkeypatch)
    with pytest.raises(ImportError, match=r"deerflow-harness\[tenki\]"):
        _import_client()


def test_acquire_without_tenki_raises_and_shuts_down_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deerflow.community.tenki.provider.get_app_config", lambda: _stub_config())
    _no_tenki(monkeypatch)
    provider = TenkiSandboxProvider()
    try:
        with pytest.raises(ImportError, match=r"deerflow-harness\[tenki\]"):
            provider.acquire("thread-1", user_id="u")
    finally:
        provider.shutdown()
    provider.shutdown()  # idempotent


# ── Adapter: guards, env, output, terminal detection ──────────────────


def test_guard_traversal() -> None:
    assert TenkiSandbox._guard_traversal("/mnt/user-data/workspace/a.txt") == "/mnt/user-data/workspace/a.txt"
    assert TenkiSandbox._guard_traversal("relative/ok.txt") == "relative/ok.txt"
    with pytest.raises(PermissionError):
        TenkiSandbox._guard_traversal("/mnt/user-data/../etc/passwd")
    with pytest.raises(ValueError):
        TenkiSandbox._guard_traversal("")


def test_resolve_path_remaps_virtual_prefix_to_home() -> None:
    box = TenkiSandbox("sb", _FakeSandbox(), home_dir="/home/tenki")
    assert box._resolve_path("/mnt/user-data") == "/home/tenki"
    assert box._resolve_path("/mnt/user-data/workspace/a.txt") == "/home/tenki/workspace/a.txt"
    # Non-virtual absolute paths pass through unchanged.
    assert box._resolve_path("/etc/hostname") == "/etc/hostname"
    with pytest.raises(PermissionError):
        box._resolve_path("/mnt/user-data/../etc/passwd")


def test_download_file_guards_reject_before_touching_sandbox() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    with pytest.raises(PermissionError):
        box.download_file("/etc/passwd")  # outside the virtual prefix
    with pytest.raises(PermissionError):
        box.download_file("/mnt/user-data/../etc/passwd")  # traversal
    assert fake.exec_calls == []  # guards raised before any exec


def test_execute_command_rejects_invalid_env_key() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    with pytest.raises(ValueError, match=r"POSIX"):
        box.execute_command("echo hi", env={"BAD KEY": "x"})


def test_execute_command_formats_stdout_and_forwards_env_timeout() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake, default_env={"BASE": "1"})
    out = box.execute_command("echo ok", env={"EXTRA": "2"}, timeout=5)
    assert out == "ok\n"  # combined output is returned verbatim (matches boxlite/e2b)
    call = fake.exec_calls[-1]
    assert call["argv"] == ("sh", "-lc", "echo ok")
    assert call["env"] == {"BASE": "1", "EXTRA": "2"}
    assert call["timeout"] == 5
    assert call["cwd"] is None  # no forced cwd; runs in sandbox default dir


def test_execute_command_returns_error_as_text() -> None:
    box = TenkiSandbox("sb", _FakeSandbox(exec_error=RuntimeError("boom")))
    assert box.execute_command("echo hi") == "Error: boom"


def test_execute_command_closed_returns_error() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.close()
    assert box.execute_command("echo hi") == "Error: sandbox has been closed"


def test_terminal_failure_triggers_callback() -> None:
    invalidated: list[tuple[str, str]] = []
    box = TenkiSandbox(
        "sb",
        _FakeSandbox(exec_error=_FakeSessionTerminatedError("session gone")),
        on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)),
    )
    out = box.execute_command("echo hi")
    assert out == "Error: session gone"
    assert invalidated == [("sb", "session gone")]


def test_regular_error_does_not_trigger_terminal_callback() -> None:
    invalidated: list[tuple[str, str]] = []
    box = TenkiSandbox(
        "sb",
        _FakeSandbox(exec_error=RuntimeError("user command failed")),
        on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)),
    )
    box.execute_command("echo hi")
    assert invalidated == []


def test_transient_transport_error_retries_once_and_succeeds() -> None:
    fake = _FakeSandbox(exec_error_sequence=[RuntimeError("UNAVAILABLE: Socket closed"), None])
    box = TenkiSandbox("sb", fake)
    out = box.execute_command("echo ok")
    assert out == "ok\n"
    assert len(fake.exec_calls) == 2  # failed once, retried once


def test_transient_error_that_persists_is_surfaced() -> None:
    invalidated: list[tuple[str, str]] = []
    fake = _FakeSandbox(exec_error=RuntimeError("UNAVAILABLE: Socket closed"))
    box = TenkiSandbox("sb", fake, on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)))
    out = box.execute_command("echo ok")
    assert out.startswith("Error:")
    assert len(fake.exec_calls) == 2  # one retry, then given up
    assert invalidated == []  # transient, not terminal → sandbox not evicted


def test_connection_error_is_terminal() -> None:
    invalidated: list[tuple[str, str]] = []
    box = TenkiSandbox(
        "sb",
        _FakeSandbox(exec_error=ConnectionError("reset")),
        on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)),
    )
    box.execute_command("echo hi")
    assert invalidated == [("sb", "reset")]


def test_close_is_idempotent_and_swallows_errors() -> None:
    fake = _FakeSandbox(close_error=RuntimeError("close boom"))
    box = TenkiSandbox("sb", fake)
    box.close()  # must not raise
    box.close()  # idempotent
    assert box.is_closed is True
    assert fake.closed is True


# ── Adapter: real base64 file round-trip ──────────────────────────────


def test_file_round_trip_text() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/note.txt", "hello world")
    assert box.read_file("/mnt/user-data/workspace/note.txt") == "hello world"


def test_file_round_trip_large_binary_chunks() -> None:
    # Larger than one base64 chunk so the chunked-append path is exercised.
    box = TenkiSandbox("sb", _FakeSandbox())
    data = bytes(range(256)) * 400  # ~100 KB → multiple 60000-char b64 chunks
    box.update_file("/mnt/user-data/outputs/blob.bin", data)
    assert box.download_file("/mnt/user-data/outputs/blob.bin") == data


def test_append_accumulates() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/log.txt", "a")
    box.write_file("/mnt/user-data/workspace/log.txt", "b", append=True)
    assert box.read_file("/mnt/user-data/workspace/log.txt") == "ab"


def test_read_missing_file_returns_error() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    assert box.read_file("/mnt/user-data/workspace/nope.txt").startswith("Error:")


# ── Provider: id derivation ───────────────────────────────────────────


def test_sandbox_id_deterministic(monkeypatch):
    provider = _install(monkeypatch)
    assert provider._sandbox_id("t1", "u1") == provider._sandbox_id("t1", "u1")
    assert len(provider._sandbox_id("t1", "u1")) == 8


def test_sandbox_id_distinct_users_and_threads(monkeypatch):
    provider = _install(monkeypatch)
    assert provider._sandbox_id("t1", "u1") != provider._sandbox_id("t1", "u2")
    assert provider._sandbox_id("t1", "u1") != provider._sandbox_id("t2", "u1")


def test_idle_timeout_zero_disables_reaper(monkeypatch):
    provider = _install(monkeypatch, config_attrs={"idle_timeout": 0})
    assert provider._config["idle_timeout"] == 0
    assert provider._idle_checker_thread is None
    provider.shutdown()


# ── Provider: acquire / create / warm pool ────────────────────────────


def test_create_passes_prefixed_name_and_scope(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid = provider.acquire("thread-1", user_id="u1")
    assert sid in provider._sandboxes
    kwargs = client.create_kwargs[0]
    assert kwargs["name"].startswith("deer-flow-tenki-")
    assert kwargs["project_id"] == "proj1"
    assert kwargs["workspace_id"] == "ws1"
    provider.shutdown()


def test_release_parks_in_warm_pool(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    assert sid not in provider._sandboxes
    assert sid in provider._warm_pool
    sandbox, _ = provider._warm_pool[sid]
    assert not sandbox.is_closed  # microVM not terminated
    provider.shutdown()


def test_acquire_reclaims_from_warm_pool(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid1 = provider.acquire("thread-1", user_id="u1")
    provider.release(sid1)
    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid1 == sid2
    assert client.create_count == 1  # reused, not recreated
    assert sid2 in provider._sandboxes
    provider.shutdown()


def test_different_threads_dont_reclaim_each_other(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid_a = provider.acquire("thread-a", user_id="u1")
    provider.release(sid_a)
    sid_b = provider.acquire("thread-b", user_id="u1")
    assert sid_b != sid_a
    assert sid_a in provider._warm_pool
    assert sid_b in provider._sandboxes
    provider.shutdown()


def test_warm_pool_reclaim_failed_health_check_creates_new(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid1 = provider.acquire("thread-1", user_id="u1")
    provider.release(sid1)
    # Kill the warm sandbox so the health check fails.
    sandbox, _ = provider._warm_pool[sid1]
    sandbox.close()
    sid2 = provider.acquire("thread-1", user_id="u1")
    assert sid2 == sid1  # same deterministic id
    assert client.create_count == 2  # a fresh sandbox was created
    replacement = provider.get(sid2)
    assert replacement is not None and not replacement.is_closed
    provider.shutdown()


def test_terminal_failure_evicts_active_sandbox(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid = provider.acquire("thread-1", user_id="u1")
    box = provider.get(sid)
    assert box is not None
    # Only fail command-time, not the create-time mkdir bootstrap.
    client.last_sandbox.exec_error = _FakeSessionTerminatedError("gone")
    box.execute_command("echo hi")  # terminal failure → invalidate
    assert provider.get(sid) is None
    provider.shutdown()


def test_concurrent_same_thread_acquire_creates_one_sandbox(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    original_create = provider._create_sandbox
    create_started = threading.Event()

    def slow_create(sandbox_id: str):
        create_started.set()
        time.sleep(0.1)
        return original_create(sandbox_id)

    provider._create_sandbox = slow_create  # type: ignore[method-assign]
    results: list[str] = []

    def worker():
        results.append(provider.acquire("thread-1", user_id="u1"))

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert create_started.wait(timeout=2)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert len(results) == 2
    assert results[0] == results[1]
    assert client.create_count == 1
    provider.shutdown()


def test_release_during_shutdown_closes_instead_of_reparking(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid = provider.acquire("thread-1", user_id="u1")
    box = provider._sandboxes[sid]
    with provider._lock:
        provider._shutdown_called = True
    provider.release(sid)
    assert sid not in provider._sandboxes
    assert sid not in provider._warm_pool
    assert box.is_closed


def test_reset_parks_running_for_later_cleanup(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid_active = provider.acquire("thread-active", user_id="u1")
    sid_warm = provider.acquire("thread-warm", user_id="u1")
    provider.release(sid_warm)
    active_box = provider._sandboxes[sid_active]
    provider.reset()
    assert provider._sandboxes == {}
    assert provider._warm_pool[sid_active][0] is active_box
    assert provider._thread_sandboxes == {}
    assert not active_box.is_closed
    provider.shutdown()
    assert active_box.is_closed


def test_idle_reaper_destroys_expired_warm(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(TenkiSandboxProvider, "IDLE_CHECK_INTERVAL", 0.1)
    provider = _install(monkeypatch, client=client)
    sid = provider.acquire("thread-1", user_id="u1")
    provider.release(sid)
    warm_box = provider._warm_pool[sid][0]
    provider._warm_pool[sid] = (warm_box, time.time() - 9999)
    time.sleep(0.3)
    assert sid not in provider._warm_pool
    assert warm_box.is_closed
    provider.shutdown()


def test_replica_enforcement_evicts_oldest_warm(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client, config_attrs={"replicas": 2})
    sid_a = provider.acquire("thread-a", user_id="u1")
    provider.release(sid_a)
    sid_b = provider.acquire("thread-b", user_id="u1")
    provider.release(sid_b)
    box_a = provider._warm_pool[sid_a][0]
    provider._warm_pool[sid_a] = (box_a, time.time() - 100)
    provider._warm_pool[sid_b] = (provider._warm_pool[sid_b][0], time.time())
    provider.acquire("thread-c", user_id="u1")
    assert sid_a not in provider._warm_pool
    assert box_a.is_closed
    assert sid_b in provider._warm_pool
    provider.shutdown()


def test_shutdown_destroys_all_and_stops_reaper(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid_active = provider.acquire("thread-1", user_id="u1")
    sid_warm = provider.acquire("thread-2", user_id="u1")
    provider.release(sid_warm)
    box_active = provider._sandboxes[sid_active]
    box_warm = provider._warm_pool[sid_warm][0]
    checker = provider._idle_checker_thread
    provider.shutdown()
    assert provider._idle_checker_stop.is_set()
    assert checker is not None and not checker.is_alive()
    assert box_active.is_closed and box_warm.is_closed
    assert provider._sandboxes == {} and provider._warm_pool == {}


# ── Provider: scope resolution ─────────────────────────────────────────


def test_scope_auto_resolves_single(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    provider.acquire("thread-1", user_id="u1")
    assert client.create_kwargs[0]["project_id"] == "proj1"
    assert client.create_kwargs[0]["workspace_id"] == "ws1"
    provider.shutdown()


def test_explicit_project_id_skips_lookup(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client, config_attrs={"project_id": "explicit"})
    provider.acquire("thread-1", user_id="u1")
    assert client.create_kwargs[0]["project_id"] == "explicit"
    provider.shutdown()


def test_ambiguous_project_raises(monkeypatch):
    client = _FakeClient(workspaces=[_FakeWorkspace("ws1", "W", [_FakeProject("p1", "A"), _FakeProject("p2", "B")])])
    provider = _install(monkeypatch, client=client)
    with pytest.raises(ValueError, match="project_id"):
        provider.acquire("thread-1", user_id="u1")
    provider.shutdown()


# ── Live integration (opt-in) ──────────────────────────────────────────


@pytest.mark.skipif(
    not os.getenv("TENKI_API_KEY") and not os.getenv("TENKI_AUTH_TOKEN"),
    reason="requires a real Tenki API key (TENKI_API_KEY); network integration test",
)
def test_integration_real_sandbox(monkeypatch):
    monkeypatch.setattr("deerflow.community.tenki.provider.get_app_config", lambda: _stub_config())
    provider = TenkiSandboxProvider()
    try:
        sid = provider.acquire("it-thread", user_id="it-user")
        box = provider.get(sid)
        assert box is not None
        assert "42" in box.execute_command("python3 -c 'print(6 * 7)'")
        box.write_file("/mnt/user-data/workspace/it.txt", "tenki-e2e")
        assert box.read_file("/mnt/user-data/workspace/it.txt") == "tenki-e2e"
    finally:
        provider.shutdown()
