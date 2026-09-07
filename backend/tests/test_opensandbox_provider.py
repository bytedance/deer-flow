"""Unit tests for the optional OpenSandbox community provider.

The real ``opensandbox`` SDK is deliberately not required for this suite.  The
tests pin DeerFlow's adapter contract with a small synchronous fake: lazy
dependency loading, scoped lifecycle reuse, command forwarding, native file
transport, search parsing, path guards, and terminal-session eviction.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import re
import shlex
import sys
import threading
import time
import types
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest

from deerflow.community.opensandbox.provider import OpenSandboxProvider, _import_sdk
from deerflow.community.opensandbox.sandbox import OpenSandboxSandbox


@dataclass
class _Message:
    text: str


@dataclass
class _Result:
    text: str | None


@dataclass
class _Logs:
    stdout: list[_Message] = field(default_factory=list)
    stderr: list[_Message] = field(default_factory=list)


@dataclass
class _Execution:
    exit_code: int | None = 0
    logs: _Logs = field(default_factory=_Logs)
    result: list[_Result] = field(default_factory=list)


def _execution(*, stdout: tuple[str, ...] = (), stderr: tuple[str, ...] = (), result: tuple[str, ...] = (), exit_code: int | None = 0) -> _Execution:
    return _Execution(
        exit_code=exit_code,
        logs=_Logs(
            stdout=[_Message(text) for text in stdout],
            stderr=[_Message(text) for text in stderr],
        ),
        result=[_Result(text) for text in result],
    )


@dataclass
class _FakeRunCommandOpts:
    background: bool = False
    working_directory: str | None = None
    timeout: timedelta | None = None
    uid: int | None = None
    gid: int | None = None
    envs: dict[str, str] | None = None


class _FakeFiles:
    def __init__(self, owner: _FakeRemote) -> None:
        self._owner = owner
        self.calls: list[tuple[str, str]] = []

    def _guard(self) -> None:
        if self._owner.file_error is not None:
            raise self._owner.file_error

    def read_file(self, path: str, *, encoding: str = "utf-8") -> str:
        self._guard()
        self.calls.append(("read_file", path))
        if path not in self._owner.file_data:
            raise FileNotFoundError(path)
        return self._owner.file_data[path].decode(encoding, errors="replace")

    def read_bytes(self, path: str) -> bytes:
        self._guard()
        self.calls.append(("read_bytes", path))
        if path not in self._owner.file_data:
            raise FileNotFoundError(path)
        return self._owner.file_data[path]

    def read_bytes_stream(self, path: str):
        self._guard()
        self.calls.append(("read_bytes_stream", path))
        if path not in self._owner.file_data:
            raise FileNotFoundError(path)
        data = self._owner.file_data[path]
        try:
            yield from (data[index : index + 3] for index in range(0, len(data), 3))
        finally:
            self._owner.stream_closed = True

    def write_file(self, path: str, data: str | bytes, *, mode: int = 755) -> None:
        self._guard()
        self.calls.append(("write_file", path))
        self._owner.file_data[path] = data.encode() if isinstance(data, str) else bytes(data)
        parent = path.rsplit("/", 1)[0]
        while parent:
            self._owner.directories.add(parent)
            parent = parent.rsplit("/", 1)[0]


class _FakeCommands:
    def __init__(self, owner: _FakeRemote) -> None:
        self._owner = owner
        self.calls: list[tuple[str, _FakeRunCommandOpts | None]] = []

    def run(self, command: str, *, opts: _FakeRunCommandOpts | None = None) -> _Execution:
        self.calls.append((command, opts))
        if self._owner.command_error is not None:
            raise self._owner.command_error
        if command.startswith("mkdir -p /mnt/user-data/"):
            return _execution(stderr=("bootstrap failed",), exit_code=self._owner.bootstrap_exit_code)
        if command == "true":
            return _execution(exit_code=self._owner.health_exit_code)
        if command == "mixed-output":
            return _execution(stdout=("out-1", "out-2"), stderr=("err-1",), exit_code=7)
        if command == "result-output":
            return _execution(stdout=("stdout",), result=("result",), stderr=("stderr",))
        if command == "silent-failure":
            return _execution(exit_code=9)
        if command == "missing-complete":
            return _execution(stderr=("stream ended",), exit_code=None)
        if command.startswith("find "):
            return self._find(command)
        if command.startswith(("grep ", "{ grep ")):
            return self._grep(command)
        return _execution()

    def _find(self, command: str) -> _Execution:
        tokens = shlex.split(command)
        root = tokens[1].rstrip("/") or "/"
        include_dirs = "d" in tokens
        paths = list(self._owner.file_data)
        if include_dirs:
            paths.extend(self._owner.directories)
        matches = sorted(path for path in set(paths) if path == root or path.startswith(f"{root}/"))
        return _execution(stdout=tuple(matches))

    def _grep(self, command: str) -> _Execution:
        tokens = shlex.split(command)
        pattern = tokens[tokens.index("-e") + 1]
        root = tokens[tokens.index("-e") + 2].rstrip("/")
        flags = 0 if "-i" not in tokens else re.IGNORECASE
        literal = "-F" in tokens
        rows: list[str] = []
        for path, data in sorted(self._owner.file_data.items()):
            if path != root and not path.startswith(f"{root}/"):
                continue
            for line_number, line in enumerate(data.decode(errors="replace").splitlines(), start=1):
                matched = pattern.lower() in line.lower() if literal and flags else pattern in line if literal else re.search(pattern, line, flags) is not None
                if matched:
                    rows.append(f"{path}:{line_number}:{line}")
        if self._owner.grep_duplicate_rows:
            rows.extend(rows)
        return _execution(stdout=tuple(rows))


class _FakeRemote:
    def __init__(self, remote_id: str, *, bootstrap_exit_code: int | None = 0) -> None:
        self.id = remote_id
        self.bootstrap_exit_code = bootstrap_exit_code
        self.health_exit_code: int | None = 0
        self.command_error: Exception | None = None
        self.file_error: Exception | None = None
        self.renew_error: Exception | None = None
        self.renew_calls: list[timedelta] = []
        self.destroy_calls = 0
        self.file_data: dict[str, bytes] = {}
        self.directories: set[str] = set()
        self.stream_closed = False
        self.grep_duplicate_rows = False
        self.commands = _FakeCommands(self)
        self.files = _FakeFiles(self)

    def renew(self, timeout: timedelta) -> None:
        self.renew_calls.append(timeout)
        if self.renew_error is not None:
            raise self.renew_error

    def destroy(self) -> None:
        self.destroy_calls += 1


class _FakeSandboxClass:
    def __init__(self, remote_factory=None) -> None:
        self.remote_factory = remote_factory
        self.create_calls: list[dict[str, Any]] = []
        self.remotes: list[_FakeRemote] = []

    def create(self, image: str, **kwargs: Any) -> _FakeRemote:
        self.create_calls.append({"image": image, **kwargs})
        index = len(self.remotes) + 1
        remote = self.remote_factory(index) if self.remote_factory is not None else _FakeRemote(f"remote-{index}")
        self.remotes.append(remote)
        return remote


class _FakeConnectionConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _TerminalApiError(RuntimeError):
    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.status_code = status_code


def _stub_config(attrs: dict[str, Any] | None = None) -> types.SimpleNamespace:
    values = {"idle_timeout": 0, **(attrs or {})}
    return types.SimpleNamespace(sandbox=types.SimpleNamespace(**values))


def _install(monkeypatch: pytest.MonkeyPatch, *, sdk: _FakeSandboxClass | None = None, config: dict[str, Any] | None = None) -> tuple[OpenSandboxProvider, _FakeSandboxClass]:
    fake_sdk = sdk or _FakeSandboxClass()
    monkeypatch.setattr("deerflow.community.opensandbox.provider.get_app_config", lambda: _stub_config(config))
    monkeypatch.setattr(
        "deerflow.community.opensandbox.provider._import_sdk",
        lambda: (fake_sdk, _FakeConnectionConfig, _FakeRunCommandOpts),
    )
    return OpenSandboxProvider(), fake_sdk


def _box(
    remote: _FakeRemote,
    *,
    on_terminal_failure=None,
    default_env=None,
    sandbox_timeout: timedelta | None = None,
    default_command_timeout: float = 600,
) -> OpenSandboxSandbox:
    return OpenSandboxSandbox(
        "sandbox-id",
        remote,
        run_command_opts_cls=_FakeRunCommandOpts,
        default_env=default_env,
        sandbox_timeout=sandbox_timeout,
        default_command_timeout=default_command_timeout,
        on_terminal_failure=on_terminal_failure,
    )


def test_missing_sdk_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for module_name in (
        "opensandbox",
        "opensandbox.sync",
        "opensandbox.config.connection_sync",
        "opensandbox.models.execd",
    ):
        monkeypatch.setitem(sys.modules, module_name, None)
    with pytest.raises(ImportError, match=r"deerflow-harness\[opensandbox\]"):
        _import_sdk()


def test_provider_defers_sdk_import_until_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deerflow.community.opensandbox.provider.get_app_config", lambda: _stub_config())
    calls = 0

    def fail_if_called():
        nonlocal calls
        calls += 1
        raise AssertionError("SDK imported")

    monkeypatch.setattr("deerflow.community.opensandbox.provider._import_sdk", fail_if_called)
    provider = OpenSandboxProvider()
    assert calls == 0
    with pytest.raises(AssertionError, match="SDK imported"):
        provider.acquire("thread", user_id="user")
    assert calls == 1
    provider.shutdown()


def test_create_passes_connection_lifetime_scope_and_environment(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("OPEN_SANDBOX_TEST_VALUE", "resolved")
    monkeypatch.delenv("OPEN_SANDBOX_ABSENT_VALUE", raising=False)
    provider, sdk = _install(
        monkeypatch,
        config={
            "image": "python:3.12",
            "api_key": "secret",
            "domain": "sandbox.example",
            "protocol": "https",
            "request_timeout": 12,
            "ready_timeout": 18,
            "sandbox_timeout": 7200,
            "use_server_proxy": True,
            "environment": {
                "BASE": "1",
                "FROM_ENV": "$OPEN_SANDBOX_TEST_VALUE",
                "MISSING_ENV": "$OPEN_SANDBOX_ABSENT_VALUE",
            },
        },
    )
    provider.acquire("thread-1", user_id="user-1")
    call = sdk.create_calls[0]
    assert call["image"] == "python:3.12"
    assert call["timeout"] == timedelta(seconds=7200)
    assert call["ready_timeout"] == timedelta(seconds=18)
    assert call["env"] == {"BASE": "1", "FROM_ENV": "resolved", "MISSING_ENV": ""}
    assert call["metadata"] == {
        "deer_flow_provider": "opensandbox",
        "deer_flow_thread": "thread-1",
        "deer_flow_user": "user-1",
    }
    assert call["connection_config"].kwargs == {
        "api_key": "secret",
        "domain": "sandbox.example",
        "protocol": "https",
        "request_timeout": timedelta(seconds=12),
        "use_server_proxy": True,
    }
    assert "unauthenticated localhost:8080" not in caplog.text
    assert "remote OpenSandbox domain uses HTTP" not in caplog.text
    provider.shutdown()


def test_missing_connection_config_warns_about_sdk_default(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("OPEN_SANDBOX_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_SANDBOX_DOMAIN", raising=False)

    provider, _ = _install(monkeypatch)

    assert any(record.levelno == logging.WARNING and "unauthenticated localhost:8080" in record.getMessage() for record in caplog.records)
    assert "remote OpenSandbox domain uses HTTP" not in caplog.text
    provider.shutdown()


def test_remote_http_connection_warns_without_logging_api_key(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="deerflow.community.opensandbox.provider")
    provider, _ = _install(
        monkeypatch,
        config={"api_key": "not-a-real-secret", "domain": "sandbox.example", "protocol": "http"},
    )

    assert any(record.levelno == logging.WARNING and "remote OpenSandbox domain uses HTTP" in record.getMessage() for record in caplog.records)
    assert "not-a-real-secret" not in caplog.text
    provider.shutdown()


def test_null_sandbox_timeout_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch, config={"sandbox_timeout": None})

    provider.acquire("thread-1", user_id="user-1")

    assert sdk.create_calls[0]["timeout"] == timedelta(hours=4)
    provider.shutdown()


@pytest.mark.parametrize("exit_code", [17, None])
def test_bootstrap_failure_destroys_created_remote(monkeypatch: pytest.MonkeyPatch, exit_code: int | None) -> None:
    sdk = _FakeSandboxClass(lambda index: _FakeRemote(f"remote-{index}", bootstrap_exit_code=exit_code))
    provider, _ = _install(monkeypatch, sdk=sdk)
    with pytest.raises(RuntimeError, match="bootstrap"):
        provider.acquire("thread-1", user_id="user-1")
    assert sdk.remotes[0].destroy_calls == 1
    assert provider._sandboxes == {}
    assert provider._warm_pool == {}
    provider.shutdown()


def test_scope_reuse_and_user_thread_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch)
    first = provider.acquire("thread-1", user_id="user-1")
    assert provider.acquire("thread-1", user_id="user-1") == first
    other_user = provider.acquire("thread-1", user_id="user-2")
    other_thread = provider.acquire("thread-2", user_id="user-1")
    assert len({first, other_user, other_thread}) == 3
    assert len(sdk.create_calls) == 3
    assert sdk.remotes[0].renew_calls == [timedelta(hours=4)]
    assert len({id(call["connection_config"]) for call in sdk.create_calls}) == 3
    provider.shutdown()


def test_active_scope_terminal_renewal_failure_rebuilds_in_same_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch)
    sandbox_id = provider.acquire("thread-1", user_id="user-1")
    sdk.remotes[0].renew_error = _TerminalApiError("sandbox expired", status_code=410)

    assert provider.acquire("thread-1", user_id="user-1") == sandbox_id
    assert len(sdk.create_calls) == 2
    assert sdk.remotes[0].destroy_calls == 1
    replacement = provider.get(sandbox_id)
    assert replacement is not None and replacement.remote_id == "remote-2"
    provider.shutdown()


def test_active_scope_non_terminal_renewal_failure_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch)
    sandbox_id = provider.acquire("thread-1", user_id="user-1")
    sdk.remotes[0].renew_error = RuntimeError("temporary management failure")

    with pytest.raises(RuntimeError, match="temporary management failure"):
        provider.acquire("thread-1", user_id="user-1")
    assert len(sdk.create_calls) == 1
    assert sdk.remotes[0].destroy_calls == 0
    assert provider.get(sandbox_id) is not None
    sdk.remotes[0].renew_error = None
    provider.shutdown()


def test_release_and_same_scope_warm_reclaim(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch)
    sandbox_id = provider.acquire("thread-1", user_id="user-1")
    provider.release(sandbox_id)
    assert sandbox_id not in provider._sandboxes
    assert sandbox_id in provider._warm_pool
    assert provider.acquire("thread-1", user_id="user-1") == sandbox_id
    assert len(sdk.create_calls) == 1
    assert sdk.remotes[0].commands.calls[-1][0] == "true"
    provider.shutdown()


@pytest.mark.parametrize("exit_code", [1, None])
def test_unhealthy_warm_entry_is_destroyed_and_replaced(monkeypatch: pytest.MonkeyPatch, exit_code: int | None) -> None:
    provider, sdk = _install(monkeypatch)
    sandbox_id = provider.acquire("thread-1", user_id="user-1")
    provider.release(sandbox_id)
    sdk.remotes[0].health_exit_code = exit_code
    assert provider.acquire("thread-1", user_id="user-1") == sandbox_id
    assert sdk.remotes[0].destroy_calls == 1
    assert len(sdk.create_calls) == 2
    provider.shutdown()


def test_reset_parks_active_and_shutdown_destroys_active_and_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch)
    active_id = provider.acquire("active", user_id="user")
    warm_id = provider.acquire("warm", user_id="user")
    provider.release(warm_id)
    provider.reset()
    assert provider._sandboxes == {}
    assert {active_id, warm_id} == set(provider._warm_pool)
    provider.shutdown()
    provider.shutdown()
    assert [remote.destroy_calls for remote in sdk.remotes] == [1, 1]
    assert provider._sandboxes == {} and provider._warm_pool == {}


def test_shutdown_stops_idle_reaper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OpenSandboxProvider, "IDLE_CHECK_INTERVAL", 0.01)
    provider, _ = _install(monkeypatch, config={"idle_timeout": 60})
    checker = provider._idle_checker_thread
    provider.shutdown()
    assert provider._idle_checker_stop.is_set()
    assert checker is not None and not checker.is_alive()


def test_execute_forwards_env_timeout_and_combines_streams() -> None:
    remote = _FakeRemote("remote")
    box = _box(remote, default_env={"BASE": "1"})
    # A nonzero exit with non-empty output keeps the authoritative marker
    # (LocalSandbox parity) instead of losing the failure.
    assert box.execute_command("mixed-output", env={"EXTRA": "2"}, timeout=5) == "out-1\nout-2\nerr-1\nExit Code: 7"
    _, opts = remote.commands.calls[-1]
    assert opts is not None
    assert opts.envs == {"BASE": "1", "EXTRA": "2"}
    assert opts.timeout == timedelta(seconds=5)
    assert box.execute_command("result-output") == "stdout\nresult\nstderr"
    assert box.execute_command("silent-failure") == "Command exited with code 9"
    assert box.execute_command("missing-complete") == "Error: OpenSandbox command completed without an exit code: stream ended"


def test_operations_renew_remote_lifetime_and_bound_default_commands() -> None:
    remote = _FakeRemote("remote")
    remote.file_data["/mnt/user-data/workspace/note.txt"] = b"note"
    box = _box(
        remote,
        sandbox_timeout=timedelta(seconds=60),
        default_command_timeout=120,
    )

    assert box.execute_command("true") == "(no output)"
    _, opts = remote.commands.calls[-1]
    assert opts is not None and opts.timeout == timedelta(seconds=120)
    assert remote.renew_calls[-1] == timedelta(seconds=150)

    assert box.read_file("/mnt/user-data/workspace/note.txt") == "note"
    assert remote.renew_calls[-1] == timedelta(seconds=60)


def test_short_operation_cannot_shorten_in_flight_command_renewal() -> None:
    remote = _FakeRemote("remote")
    remote.file_data["/mnt/user-data/workspace/note.txt"] = b"note"
    box = _box(
        remote,
        sandbox_timeout=timedelta(seconds=60),
        default_command_timeout=120,
    )
    command_started = threading.Event()
    finish_command = threading.Event()
    file_started = threading.Event()
    short_renew_attempted = threading.Event()
    original_run = remote.commands.run
    original_renew = remote.renew

    def blocking_run(command: str, *, opts: _FakeRunCommandOpts | None = None) -> _Execution:
        command_started.set()
        assert finish_command.wait(timeout=2)
        return original_run(command, opts=opts)

    remote.commands.run = blocking_run  # type: ignore[method-assign]

    def observed_renew(timeout: timedelta) -> None:
        if timeout == timedelta(seconds=60):
            short_renew_attempted.set()
        original_renew(timeout)

    remote.renew = observed_renew  # type: ignore[method-assign]
    command_result: list[str] = []
    file_result: list[str] = []
    command_thread = threading.Thread(target=lambda: command_result.append(box.execute_command("long-command")))

    def read_file() -> None:
        file_started.set()
        file_result.append(box.read_file("/mnt/user-data/workspace/note.txt"))

    file_thread = threading.Thread(target=read_file)
    command_thread.start()
    assert command_started.wait(timeout=2)
    file_thread.start()
    assert file_started.wait(timeout=2)
    assert not short_renew_attempted.wait(timeout=0.1)
    assert file_thread.is_alive()
    assert remote.renew_calls == [timedelta(seconds=150)]

    finish_command.set()
    command_thread.join(timeout=2)
    file_thread.join(timeout=2)
    assert command_result == ["(no output)"]
    assert file_result == ["note"]
    assert remote.renew_calls == [timedelta(seconds=150), timedelta(seconds=60)]


def test_explicit_cleanup_mode_skips_renewal() -> None:
    remote = _FakeRemote("remote")
    box = _box(remote, sandbox_timeout=None)
    assert box.execute_command("true") == "(no output)"
    assert remote.renew_calls == []


@pytest.mark.parametrize("timeout", [0, -1])
def test_execute_rejects_unbounded_or_negative_timeout(timeout: float) -> None:
    remote = _FakeRemote("remote")
    box = _box(remote)
    assert box.execute_command("true", timeout=timeout).startswith("Error: timeout must be positive")
    assert remote.commands.calls == []


def test_execute_rejects_invalid_environment_key() -> None:
    box = _box(_FakeRemote("remote"))
    with pytest.raises(ValueError, match="POSIX"):
        box.execute_command("true", env={"BAD KEY": "x"})


def test_text_binary_append_and_line_ranges() -> None:
    box = _box(_FakeRemote("remote"))
    path = "/mnt/user-data/workspace/note.txt"
    box.write_file(path, "one\ntwo\nthree")
    assert box.read_file(path, 2, 3) == "two\nthree"
    box.write_file(path, "\nfour", append=True)
    assert box.read_file(path) == "one\ntwo\nthree\nfour"
    binary_path = "/mnt/user-data/outputs/blob.bin"
    box.update_file(binary_path, b"\x00\xffpayload")
    assert box.download_file(binary_path) == b"\x00\xffpayload"


def test_download_rejects_oversize_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("deerflow.community.opensandbox.sandbox._MAX_DOWNLOAD_SIZE", 4)
    remote = _FakeRemote("remote")
    path = "/mnt/user-data/outputs/oversize.bin"
    remote.file_data[path] = b"12345"

    with pytest.raises(OSError) as excinfo:
        _box(remote).download_file(path)

    assert excinfo.value.errno == errno.EFBIG
    assert remote.files.calls == [("read_bytes_stream", path)]
    assert remote.stream_closed


def test_list_glob_and_grep_return_virtual_paths() -> None:
    remote = _FakeRemote("remote")
    remote.grep_duplicate_rows = True
    box = _box(remote)
    box.write_file("/mnt/user-data/workspace/src/a.py", "Needle here\nsecond\n")
    box.write_file("/mnt/user-data/workspace/vendor/b.py", "needle there\n")
    assert box.list_dir("/mnt/user-data/workspace") == [
        "/mnt/user-data/workspace",
        "/mnt/user-data/workspace/src",
        "/mnt/user-data/workspace/src/a.py",
        "/mnt/user-data/workspace/vendor",
        "/mnt/user-data/workspace/vendor/b.py",
    ]
    found, truncated = box.glob("/mnt/user-data/workspace", "src/*.py")
    assert found == ["/mnt/user-data/workspace/src/a.py"]
    assert truncated is False
    matches, truncated = box.grep("/mnt/user-data/workspace", "needle", glob="src/*.py", literal=True)
    assert [(match.path, match.line_number, match.line) for match in matches] == [("/mnt/user-data/workspace/src/a.py", 1, "Needle here")]
    assert truncated is False
    grep_tokens = shlex.split(remote.commands.calls[-1][0])
    assert "--include=*.py" in grep_tokens
    assert "-m100" in grep_tokens

    box.grep("/mnt/user-data/workspace", "needle", glob="src/*.py; echo injected", literal=True)
    unsafe_glob_tokens = shlex.split(remote.commands.calls[-1][0])
    assert "--include=*.py; echo injected" in unsafe_glob_tokens
    assert unsafe_glob_tokens.count("grep") == 2
    assert 'status=$?; [ "$status" -eq 2 ] &&' in remote.commands.calls[-1][0]
    fallback_tokens = unsafe_glob_tokens[unsafe_glob_tokens.index("grep", 2) :]
    assert not any(token.startswith("--include=") or token.startswith("-m") for token in fallback_tokens)


def test_search_rejects_non_positive_limits_and_negative_depth() -> None:
    remote = _FakeRemote("remote")
    box = _box(remote)
    with pytest.raises(ValueError, match="max_depth"):
        box.list_dir("/mnt/user-data/workspace", max_depth=-1)
    with pytest.raises(ValueError, match="max_results"):
        box.glob("/mnt/user-data/workspace", "*", max_results=0)
    with pytest.raises(ValueError, match="max_results"):
        box.grep("/mnt/user-data/workspace", "text", max_results=-1)
    assert remote.commands.calls == []


@pytest.mark.parametrize(
    "path",
    ["", "relative.txt", "/mnt/user-data/../etc/passwd", "\\mnt\\user-data\\..\\etc\\passwd"],
)
def test_path_guard_rejects_unsafe_paths(path: str) -> None:
    box = _box(_FakeRemote("remote"))
    with pytest.raises((ValueError, PermissionError)):
        box.read_file(path)


def test_download_rejects_outside_virtual_prefix_before_sdk_call() -> None:
    remote = _FakeRemote("remote")
    box = _box(remote)
    with pytest.raises(PermissionError):
        box.download_file("/etc/passwd")
    assert remote.files.calls == []


def test_missing_file_api_404_does_not_evict_sandbox() -> None:
    invalidated: list[tuple[str, str]] = []
    remote = _FakeRemote("remote")
    remote.file_error = _TerminalApiError("file not found", status_code=404)
    box = _box(remote, on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)))
    assert box.read_file("/mnt/user-data/workspace/missing.txt").startswith("Error:")
    assert invalidated == []


def test_terminal_renewal_failure_evicts_before_operation() -> None:
    invalidated: list[tuple[str, str]] = []
    remote = _FakeRemote("remote")
    remote.renew_error = _TerminalApiError("sandbox expired")
    box = _box(
        remote,
        sandbox_timeout=timedelta(minutes=5),
        on_terminal_failure=lambda sandbox_id, reason: invalidated.append((sandbox_id, reason)),
    )
    assert box.execute_command("true") == "Error: sandbox expired"
    assert invalidated == [("sandbox-id", "sandbox expired")]
    assert remote.commands.calls == []


def test_terminal_error_evicts_active_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch)
    sandbox_id = provider.acquire("thread-1", user_id="user-1")
    box = provider.get(sandbox_id)
    assert box is not None
    sdk.remotes[0].command_error = _TerminalApiError("sandbox is gone")
    assert box.execute_command("true") == "Error: sandbox is gone"
    assert provider.get(sandbox_id) is None
    assert sdk.remotes[0].destroy_calls == 1
    provider.shutdown()


def test_concurrent_same_scope_acquire_creates_once(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, sdk = _install(monkeypatch)
    original_create = sdk.create
    started = threading.Event()

    def slow_create(image: str, **kwargs: Any) -> _FakeRemote:
        started.set()
        time.sleep(0.05)
        return original_create(image, **kwargs)

    sdk.create = slow_create  # type: ignore[method-assign]
    results: list[str] = []

    first = threading.Thread(target=lambda: results.append(provider.acquire("thread", user_id="user")))
    second = threading.Thread(target=lambda: results.append(provider.acquire("thread", user_id="user")))
    first.start()
    assert started.wait(timeout=2)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)
    assert len(results) == 2 and results[0] == results[1]
    assert len(sdk.create_calls) == 1
    provider.shutdown()


@pytest.mark.asyncio
async def test_cancelled_acquire_async_serializes_retry_behind_abandoned_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancelled acquire_async abandons the body thread, not the lock.

    Regression test (#4741): the serializer hold must follow the abandoned
    body to completion, so a retry for the same scope serializes behind it
    instead of overlapping it and creating a duplicate, untracked remote.
    """
    provider, sdk = _install(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    original_create = sdk.create

    def blocking_create(image: str, **kwargs: Any) -> _FakeRemote:
        started.set()
        assert release.wait(timeout=10)
        return original_create(image, **kwargs)

    sdk.create = blocking_create  # type: ignore[method-assign]

    first = asyncio.create_task(provider.acquire_async("thread", user_id="user"))
    assert await asyncio.to_thread(started.wait, 10)  # body is blocked inside create()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()  # abandoned body runs to completion and registers
    second = await provider.acquire_async("thread", user_id="user")

    expected_id = provider._sandbox_id("thread", "user")
    assert len(sdk.create_calls) == 1  # no duplicate remote sandbox
    assert second == expected_id
    assert provider._thread_sandboxes[provider._thread_key("thread", "user")] == expected_id
    provider.shutdown()


def test_sandbox_id_matches_shared_identity():
    from deerflow.sandbox.identity import derive_sandbox_scope_token

    assert OpenSandboxProvider._sandbox_id("t-1", "u-1") == derive_sandbox_scope_token(user_id="u-1", thread_id="t-1")
    assert OpenSandboxProvider._sandbox_id("t-1", "") == derive_sandbox_scope_token(user_id="", thread_id="t-1")


def test_list_dir_and_glob_preserve_trailing_space_in_filename() -> None:
    # "notes.txt " (trailing space) is a legal Linux filename; find prints it
    # verbatim, one entry per line, so a per-line strip() corrupts the name.
    remote = _FakeRemote("remote")
    box = _box(remote)
    box.write_file("/mnt/user-data/workspace/notes.txt ", "payload")

    assert "/mnt/user-data/workspace/notes.txt " in box.list_dir("/mnt/user-data/workspace")

    found, truncated = box.glob("/mnt/user-data/workspace", "notes*")
    assert found == ["/mnt/user-data/workspace/notes.txt "]
    assert truncated is False
