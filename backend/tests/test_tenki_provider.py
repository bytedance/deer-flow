"""Unit tests for the Tenki community sandbox provider.

These run in CI without ``tenki`` installed: they cover the lazy-import
error path, provider lifecycle, path-safety guards, the native ``fs`` file
round-trip, warm-pool mechanics, and scope resolution — none of which need a live
sandbox. A single opt-in integration test (``test_integration_real_sandbox``)
exercises a real Tenki microVM end to end when ``TENKI_API_KEY`` is set.
"""

from __future__ import annotations

import errno
import logging
import os
import shlex
import sys
import threading
import time
import types

import pytest

from deerflow.community.tenki.provider import _BOOTSTRAP_TIMEOUT, TenkiSandboxProvider, _import_client
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


class _FakeMissingFileError(Exception):
    """Stand-in for ``tenki_sandbox.errors.FileNotFoundError`` (matched by name)."""


_FakeMissingFileError.__name__ = "FileNotFoundError"


class _FakeFileInfo:
    def __init__(self, path: str, size: int) -> None:
        self.path = path
        self.size = size
        self.is_dir = False


class _FakeFS:
    """In-memory stand-in for Tenki's native ``sandbox.fs`` API."""

    _READ_FRAME = 64  # small, so multi-frame reads are exercised

    def __init__(self, owner: _FakeSandbox) -> None:
        self._owner = owner

    def _guard(self) -> None:
        if self._owner.fs_error is not None:
            raise self._owner.fs_error

    def mkdir(self, path: str, *, recursive: bool = True, mode: int = 0o755) -> None:
        self._guard()
        self._owner.dirs.add(path)

    def read_bytes(self, path: str) -> bytes:
        self._guard()
        if path not in self._owner.files:
            raise _FakeMissingFileError(f"no such file or directory: {path}")
        return self._owner.files[path]

    def read_text(self, path: str, *, encoding: str = "utf-8") -> str:
        return self.read_bytes(path).decode(encoding, errors="replace")

    def read_stream(self, path: str, *, offset: int = 0, length: int = 0, chunk_bytes: int = 0):
        # A generator, like the real SDK: errors surface while iterating.
        data = self.read_bytes(path)
        for i in range(0, len(data), self._READ_FRAME):
            yield data[i : i + self._READ_FRAME]

    def write_stream(self, path: str, chunks, *, mode: int = 0o644, truncate: bool = True, sync: bool = False) -> None:
        self._guard()
        frames = list(chunks)
        self._owner.write_frame_counts.append(len(frames))
        self._owner.files[path] = b"".join(frames)

    def stat(self, path: str) -> _FakeFileInfo:
        self._guard()
        if path not in self._owner.files:
            raise _FakeMissingFileError(f"no such file or directory: {path}")
        return _FakeFileInfo(path, len(self._owner.files[path]))


class _FakeSandbox:
    """A fake tenki ``Sandbox``: a native ``fs`` API plus the handful of shell
    commands the adapter still emits for search, backed by one in-memory
    filesystem — so file and search round-trips are exercised for real.
    """

    def __init__(
        self,
        *,
        exec_error: Exception | None = None,
        close_error: Exception | None = None,
        fs_error: Exception | None = None,
        wait_ready_error: Exception | None = None,
    ) -> None:
        self.id = "remote-session-id"
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.write_frame_counts: list[int] = []
        self.exec_calls: list[dict] = []
        self.exec_error = exec_error
        self.close_error = close_error
        self.fs_error = fs_error
        self.wait_ready_error = wait_ready_error
        self.wait_ready_calls = 0
        self.closed = False
        self.fs = _FakeFS(self)

    def wait_ready(self, timeout: float = 180) -> None:
        self.wait_ready_calls += 1
        if self.wait_ready_error is not None:
            raise self.wait_ready_error

    def exec(self, *argv: str, cwd=None, env=None, timeout=None):
        self.exec_calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout": timeout})
        if self.exec_error is not None:
            raise self.exec_error
        if argv[:2] == ("sh", "-lc"):
            return self._run_script(argv[2])
        return _FakeResult()

    def _run_script(self, script: str) -> _FakeResult:
        if script == "echo ok":
            return _FakeResult(stdout=b"ok\n")
        if "BOOTSTRAP_OK" in script:  # provider create-time bootstrap script
            return _FakeResult(stdout=b"BOOTSTRAP_OK\n")
        if script.startswith("find "):
            root = shlex.split(script)[1]
            hits = [p for p in self.files if p == root or p.startswith(f"{root.rstrip('/')}/")]
            return _FakeResult(stdout=("\n".join(hits) + "\n").encode() if hits else b"")
        if script.startswith("grep "):
            # grep <flags> -e <pattern> <root> 2>/dev/null | head -N
            tokens = shlex.split(script)
            needle, root = tokens[tokens.index("-e") + 1], tokens[tokens.index("-e") + 2]
            lines = []
            for path, blob in sorted(self.files.items()):
                if not path.startswith(root):
                    continue
                for n, text in enumerate(blob.decode(errors="replace").splitlines(), start=1):
                    if needle in text:
                        lines.append(f"{path}:{n}:{text}")
            return _FakeResult(stdout=("\n".join(lines) + "\n").encode() if lines else b"")
        return _FakeResult()

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakeWorkspace:
    """Mirrors tenki 1.0.2 ``IdentityWorkspace``: id and name, no ``projects``."""

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


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
        self._workspaces = workspaces if workspaces is not None else [_FakeWorkspace("ws1", "Workspace")]

    def who_am_i(self):
        return _FakeIdentity(self._workspaces)

    # Keyword-only and deliberately WITHOUT **kwargs, mirroring tenki 1.0.2's
    # Client.create. The 0.4.0-era double accepted **kwargs, so it swallowed the
    # project_id the real 1.x rejects and the suite passed against a provider
    # that could not create a sandbox. An unexpected kwarg must be a TypeError
    # here exactly as it is against the real SDK.
    def create(
        self,
        *,
        name=None,
        workspace_id=None,
        sticky=False,
        wait=True,
        max_duration=None,
        image=None,
        cpu_cores=None,
        memory_mb=None,
        env=None,
    ):
        kwargs = {
            "name": name,
            "workspace_id": workspace_id,
            "sticky": sticky,
            "wait": wait,
        }
        for key, value in (
            ("max_duration", max_duration),
            ("image", image),
            ("cpu_cores", cpu_cores),
            ("memory_mb", memory_mb),
            ("env", env),
        ):
            if value is not None:
                kwargs[key] = value
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


def test_transient_transport_error_is_not_retried_and_not_evicted() -> None:
    # exec is not idempotent, so a transient transport error must NOT be retried
    # (re-running could double a command's side effects or duplicate a base64
    # write chunk). It surfaces as text, and — not being a terminal session
    # error — does not evict the sandbox.
    invalidated: list[tuple[str, str]] = []
    fake = _FakeSandbox(exec_error=RuntimeError("UNAVAILABLE: Socket closed"))
    box = TenkiSandbox("sb", fake, on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)))
    out = box.execute_command("echo ok")
    assert out.startswith("Error:")
    assert len(fake.exec_calls) == 1  # executed exactly once — no retry
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


def test_close_is_idempotent() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    box.close()
    box.close()  # idempotent
    assert box.is_closed is True
    assert fake.closed is True


def test_close_failure_leaves_sandbox_retryable() -> None:
    # Marking the adapter closed before a failed termination would strand a
    # running (billed) microVM with no handle left to retry it.
    fake = _FakeSandbox(close_error=RuntimeError("terminate rejected"))
    box = TenkiSandbox("sb", fake)
    with pytest.raises(RuntimeError, match="terminate rejected"):
        box.close()
    assert box.is_closed is False  # still ours to terminate

    fake.close_error = None
    box.close()
    assert box.is_closed is True


def test_close_treats_terminal_error_as_already_gone() -> None:
    fake = _FakeSandbox(close_error=_FakeSessionTerminatedError("session gone"))
    box = TenkiSandbox("sb", fake)
    box.close()  # nothing left to terminate → not an error
    assert box.is_closed is True


# ── Adapter: native fs file round-trip ────────────────────────────────


def test_file_round_trip_text() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/note.txt", "hello world")
    assert box.read_file("/mnt/user-data/workspace/note.txt") == "hello world"


def test_write_creates_parent_directory() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    box.write_file("/mnt/user-data/workspace/nested/note.txt", "hi")
    assert "/home/tenki/workspace/nested" in fake.dirs


def test_file_round_trip_large_binary_streams_in_frames() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    data = bytes(range(256)) * 8192  # 2 MB → more than one 1 MiB upload frame
    box.update_file("/mnt/user-data/outputs/blob.bin", data)
    assert fake.write_frame_counts[-1] > 1
    assert box.download_file("/mnt/user-data/outputs/blob.bin") == data


def test_append_accumulates() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/log.txt", "a")
    box.write_file("/mnt/user-data/workspace/log.txt", "b", append=True)
    assert box.read_file("/mnt/user-data/workspace/log.txt") == "ab"


def test_append_to_missing_file_creates_it() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/new.txt", "first", append=True)
    assert box.read_file("/mnt/user-data/workspace/new.txt") == "first"


def test_read_missing_file_returns_error() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    assert box.read_file("/mnt/user-data/workspace/nope.txt").startswith("Error:")


def test_download_missing_file_raises_oserror() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    with pytest.raises(OSError):
        box.download_file("/mnt/user-data/outputs/nope.bin")


def test_download_cap_counts_bytes_actually_received(monkeypatch) -> None:
    # The cap must not rely on a separate size probe: a file that grows between
    # the probe and the read would slip past it.
    monkeypatch.setattr("deerflow.community.tenki.sandbox._MAX_DOWNLOAD_SIZE", 100)
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    fake.files["/home/tenki/outputs/big.bin"] = b"x" * 500
    with pytest.raises(OSError) as excinfo:
        box.download_file("/mnt/user-data/outputs/big.bin")
    assert excinfo.value.errno == errno.EFBIG


def test_download_size_cap_does_not_evict_sandbox(monkeypatch) -> None:
    # Hitting the size cap is a client-side limit, not a dead session — the
    # sandbox must stay live.
    monkeypatch.setattr("deerflow.community.tenki.sandbox._MAX_DOWNLOAD_SIZE", 100)
    invalidated: list[tuple[str, str]] = []
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake, on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)))
    fake.files["/home/tenki/outputs/big.bin"] = b"x" * 500
    with pytest.raises(OSError):
        box.download_file("/mnt/user-data/outputs/big.bin")
    assert invalidated == []


def test_download_terminal_transport_error_evicts_sandbox() -> None:
    # A ConnectionError mid-stream is an OSError subclass and terminal; the old
    # `except OSError: raise` re-raised it before _note_failure, so a session
    # that died mid-download never got evicted.
    invalidated: list[tuple[str, str]] = []
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake, on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)))
    box.write_file("/mnt/user-data/outputs/f.bin", "payload")
    fake.fs_error = ConnectionError("connection reset mid-stream")
    with pytest.raises(ConnectionError):
        box.download_file("/mnt/user-data/outputs/f.bin")
    assert invalidated == [("sb", "connection reset mid-stream")]


def test_fs_terminal_failure_evicts_sandbox() -> None:
    invalidated: list[tuple[str, str]] = []
    fake = _FakeSandbox(fs_error=_FakeSessionTerminatedError("session gone"))
    box = TenkiSandbox("sb", fake, on_terminal_failure=lambda sid, reason: invalidated.append((sid, reason)))
    with pytest.raises(Exception, match="session gone"):
        box.write_file("/mnt/user-data/workspace/a.txt", "x")
    assert invalidated == [("sb", "session gone")]


# ── Adapter: returned paths stay caller-facing ────────────────────────


def test_search_results_use_virtual_paths() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/pkg/mod.py", "def foo():\n    return 42\n")

    assert box.list_dir("/mnt/user-data/workspace") == ["/mnt/user-data/workspace/pkg/mod.py"]

    found, truncated = box.glob("/mnt/user-data/workspace", "**/*.py")
    assert found == ["/mnt/user-data/workspace/pkg/mod.py"] and not truncated

    matches, _ = box.grep("/mnt/user-data/workspace", "return")
    assert [m.path for m in matches] == ["/mnt/user-data/workspace/pkg/mod.py"]
    assert matches[0].line_number == 2

    # Results feed straight back into the file APIs.
    assert box.read_file(found[0]).startswith("def foo()")


def test_grep_glob_keeps_its_directory_prefix() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/src/a.js", "const x = 1;\n")
    box.write_file("/mnt/user-data/workspace/vendor/b.js", "const x = 2;\n")

    matches, _ = box.grep("/mnt/user-data/workspace", "const x", glob="src/*.js")
    assert [m.path for m in matches] == ["/mnt/user-data/workspace/src/a.js"]


def test_grep_passes_capital_h_so_single_file_matches_parse() -> None:
    # Without -H, `grep -r` on a path that resolves to a single file prints
    # "line:text" and the file:line:text unpack drops every match. The flag must
    # always be present regardless of the other options.
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    box.write_file("/mnt/user-data/workspace/a.txt", "needle here\n")
    box.grep("/mnt/user-data/workspace", "needle")
    grep_scripts = [c["argv"][2] for c in fake.exec_calls if c["argv"][:2] == ("sh", "-lc") and c["argv"][2].startswith("grep ")]
    assert grep_scripts and "-H" in shlex.split(grep_scripts[0])


def test_grep_single_file_path_with_matching_glob() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    box.write_file("/mnt/user-data/workspace/a.txt", "needle here\n")

    matches, truncated = box.grep("/mnt/user-data/workspace/a.txt", "needle", glob="*.txt")

    assert [m.path for m in matches] == ["/mnt/user-data/workspace/a.txt"]
    assert truncated is False


def _grep_script(fake: _FakeSandbox) -> list[str]:
    scripts = [c["argv"][2] for c in fake.exec_calls if c["argv"][:2] == ("sh", "-lc") and c["argv"][2].startswith("grep ")]
    assert scripts, "no grep command was issued"
    return shlex.split(scripts[0])


def test_grep_literal_uses_fixed_string_flag() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    box.write_file("/mnt/user-data/workspace/a.txt", "a.b\n")
    box.grep("/mnt/user-data/workspace", "a.b", literal=True)
    tokens = _grep_script(fake)
    assert "-F" in tokens and "-E" not in tokens  # -F matches the pattern literally
    assert "-i" in tokens  # case-insensitive is still the default


def test_grep_case_sensitive_omits_ignore_case_flag() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    box.write_file("/mnt/user-data/workspace/a.txt", "Needle\n")
    box.grep("/mnt/user-data/workspace", "Needle", case_sensitive=True)
    tokens = _grep_script(fake)
    assert "-i" not in tokens  # case-sensitive → no -i
    assert "-E" in tokens


def test_glob_include_dirs_adds_directory_type_to_find() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    box.glob("/mnt/user-data/workspace", "*", include_dirs=True)
    find_scripts = [c["argv"][2] for c in fake.exec_calls if c["argv"][:2] == ("sh", "-lc") and c["argv"][2].startswith("find ")]
    assert find_scripts and "-type d" in find_scripts[-1]  # dirs requested, not just files


def test_list_dir_forwards_max_depth() -> None:
    fake = _FakeSandbox()
    box = TenkiSandbox("sb", fake)
    box.list_dir("/mnt/user-data/workspace", max_depth=4)
    find_scripts = [c["argv"][2] for c in fake.exec_calls if c["argv"][:2] == ("sh", "-lc") and c["argv"][2].startswith("find ")]
    assert find_scripts and "-maxdepth 4" in find_scripts[-1]


def test_paths_outside_the_virtual_prefix_are_reported_as_is() -> None:
    box = TenkiSandbox("sb", _FakeSandbox())
    assert box._virtual_path("/etc/hostname") == "/etc/hostname"
    assert box._virtual_path("/home/tenki") == "/mnt/user-data"


# ── Provider: id derivation ───────────────────────────────────────────


def test_sandbox_id_deterministic(monkeypatch):
    provider = _install(monkeypatch)
    assert provider._sandbox_id("t1", "u1") == provider._sandbox_id("t1", "u1")
    assert len(provider._sandbox_id("t1", "u1")) == 16  # 64-bit, like community/e2b_sandbox


def test_sandbox_id_distinct_users_and_threads(monkeypatch):
    provider = _install(monkeypatch)
    assert provider._sandbox_id("t1", "u1") != provider._sandbox_id("t1", "u2")
    assert provider._sandbox_id("t1", "u1") != provider._sandbox_id("t2", "u1")


def test_idle_timeout_zero_disables_reaper(monkeypatch):
    provider = _install(monkeypatch, config_attrs={"idle_timeout": 0})
    assert provider._config["idle_timeout"] == 0
    assert provider._idle_checker_thread is None
    provider.shutdown()


def test_load_config_rejects_invalid_environment_key(monkeypatch):
    # The config `environment` is merged into every command; a bad key must
    # fail fast at load time, like the per-call env in execute_command, not
    # surface as a confusing SDK error at create/exec time.
    monkeypatch.setattr("deerflow.community.tenki.provider.get_app_config", lambda: _stub_config({"environment": {"bad-key": "1"}}))
    with pytest.raises(ValueError, match=r"POSIX"):
        TenkiSandboxProvider()


def test_load_config_accepts_valid_environment_key(monkeypatch):
    provider = _install(monkeypatch, config_attrs={"environment": {"PYTHONUNBUFFERED": "1"}})
    assert provider._config["environment"] == {"PYTHONUNBUFFERED": "1"}
    provider.shutdown()


# ── Provider: acquire / create / warm pool ────────────────────────────


def test_create_passes_prefixed_name_and_scope(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    sid = provider.acquire("thread-1", user_id="u1")
    assert sid in provider._sandboxes
    kwargs = client.create_kwargs[0]
    assert kwargs["name"].startswith("deer-flow-tenki-")
    assert kwargs["workspace_id"] == "ws1"
    # Tenki 1.x has no project layer; passing one is a TypeError against the SDK.
    assert "project_id" not in kwargs
    provider.shutdown()


def test_create_waits_client_side_and_configures_lifetime(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client, config_attrs={"max_duration": 7200})
    provider.acquire("thread-1", user_id="u1")
    kwargs = client.create_kwargs[0]
    # wait=False keeps the handle on our side of create() so a readiness failure
    # is still terminable (see the next test).
    assert kwargs["wait"] is False
    assert client.last_sandbox.wait_ready_calls == 1
    # Without an explicit lifetime, Tenki reaps the sandbox out from under a
    # long-lived thread at its default (~30 min).
    assert kwargs["max_duration"] == 7200
    assert kwargs["sticky"] is False
    provider.shutdown()


def test_create_default_lifetime_is_explicit(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    provider.acquire("thread-1", user_id="u1")
    assert client.create_kwargs[0]["max_duration"] == pytest.approx(4 * 60 * 60)
    provider.shutdown()


def test_create_terminates_the_microvm_when_readiness_fails(monkeypatch):
    client = _FakeClient(sandbox_factory=lambda: _FakeSandbox(wait_ready_error=RuntimeError("never became ready")))
    provider = _install(monkeypatch, client=client)
    with pytest.raises(RuntimeError, match="never became ready"):
        provider.acquire("thread-1", user_id="u1")
    # The session exists remotely even though create() failed — it must not leak.
    assert client.last_sandbox.closed is True
    assert provider._sandboxes == {}
    provider.shutdown()


def test_create_survives_bootstrap_failure(monkeypatch, caplog):
    # Bootstrap is best-effort: the file APIs still work via the home remap, so a
    # non-zero bootstrap must warn, not fail the acquire.
    class _BootstrapFailSandbox(_FakeSandbox):
        def _run_script(self, script: str) -> _FakeResult:
            if "BOOTSTRAP_OK" in script:
                return _FakeResult(exit_code=1, stderr=b"permission denied")
            return super()._run_script(script)

    client = _FakeClient(sandbox_factory=lambda: _BootstrapFailSandbox())
    provider = _install(monkeypatch, client=client)
    with caplog.at_level("WARNING"):
        sid = provider.acquire("thread-1", user_id="u1")
    box = provider.get(sid)
    assert box is not None and not box.is_closed  # usable despite bootstrap failure
    assert any("bootstrap" in r.message.lower() for r in caplog.records)
    provider.shutdown()


def test_bootstrap_is_non_interactive_and_time_bounded(monkeypatch):
    # The bootstrap runs under the per-scope acquire lock, so it must not hang:
    # `sudo -n` fails fast instead of blocking on a password prompt, and the exec
    # carries a timeout so any other stall drops to the warning path.
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    provider.acquire("thread-1", user_id="u1")
    bootstrap = next(c for c in client.last_sandbox.exec_calls if "BOOTSTRAP_OK" in (c["argv"][2] if len(c["argv"]) > 2 else ""))
    assert "sudo -n ln -sfn" in bootstrap["argv"][2]
    # Pin the actual bounded value, not merely "some timeout": a regression to
    # timeout=0 (no timeout in some SDKs) would slip past an `is not None` check.
    assert bootstrap["timeout"] == _BOOTSTRAP_TIMEOUT
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


def test_scope_auto_resolves_single_workspace(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client)
    provider.acquire("thread-1", user_id="u1")
    assert client.create_kwargs[0]["workspace_id"] == "ws1"
    provider.shutdown()


def test_explicit_workspace_id_skips_lookup(monkeypatch):
    client = _FakeClient()
    provider = _install(monkeypatch, client=client, config_attrs={"workspace_id": "explicit"})
    provider.acquire("thread-1", user_id="u1")
    assert client.create_kwargs[0]["workspace_id"] == "explicit"
    provider.shutdown()


def test_ambiguous_workspace_raises(monkeypatch):
    client = _FakeClient(workspaces=[_FakeWorkspace("ws1", "A"), _FakeWorkspace("ws2", "B")])
    provider = _install(monkeypatch, client=client)
    with pytest.raises(ValueError, match="workspace_id"):
        provider.acquire("thread-1", user_id="u1")
    provider.shutdown()


def test_stale_project_id_is_ignored_with_a_warning(monkeypatch, caplog):
    """A 0.4.0-era config keeps booting; the dead key says so instead of going quiet.

    SandboxConfig is ``extra="allow"``, so an unread project_id would sit in
    config.yaml scoping nothing. It also used to short-circuit the identity
    lookup, so silently dropping it changes how scope resolves.
    """
    client = _FakeClient()
    with caplog.at_level(logging.WARNING, logger="deerflow.community.tenki.provider"):
        provider = _install(monkeypatch, client=client, config_attrs={"project_id": "proj_legacy"})
    assert "sandbox.project_id is ignored" in caplog.text
    provider.acquire("thread-1", user_id="u1")
    assert "project_id" not in client.create_kwargs[0]
    assert client.create_kwargs[0]["workspace_id"] == "ws1"
    provider.shutdown()


def test_create_rejects_project_id_like_the_real_sdk(monkeypatch):
    """Guards the hole that let the 1.x break through: the old double took **kwargs.

    tenki 1.0.2's Client.create is keyword-only with no **kwargs, so a stray
    project_id raises TypeError. The double must do the same or a provider that
    cannot create a sandbox goes on passing its tests.
    """
    client = _FakeClient()
    with pytest.raises(TypeError, match="project_id"):
        client.create(name="n", workspace_id="ws1", project_id="proj1")


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


def test_sandbox_id_matches_shared_identity():
    from deerflow.sandbox.identity import derive_sandbox_scope_token

    assert TenkiSandboxProvider._sandbox_id("t-1", "u-1") == derive_sandbox_scope_token(user_id="u-1", thread_id="t-1")
    assert TenkiSandboxProvider._sandbox_id("t-1", "") == derive_sandbox_scope_token(user_id="", thread_id="t-1")
