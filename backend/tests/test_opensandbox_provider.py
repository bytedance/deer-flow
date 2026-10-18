"""Unit tests for the optional OpenSandbox community provider.

The real ``opensandbox`` SDK is deliberately not required for this suite.  The
tests pin DeerFlow's adapter contract with a small synchronous fake: lazy
dependency loading, scoped lifecycle reuse, command forwarding, native file
transport, search parsing, path guards, and terminal-session eviction.
"""

from __future__ import annotations

import asyncio
import base64
import errno
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import types
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from deerflow.community.opensandbox.provider import OpenSandboxProvider, _import_sdk
from deerflow.community.opensandbox.sandbox import OpenSandboxSandbox
from deerflow.config.paths import Paths


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
        if "__DF_OUTPUT_SYNC__" in command:
            listing = "\0".join(self._owner.file_data) + "\0" if self._owner.file_data else ""
            return _execution(stdout=(base64.b64encode(listing.encode()).decode(), "__DF_OUTPUT_SYNC__:0:0:0"))
        if "__DF_SEARCH_STATUS__:" in command:
            return self._search(command)
        if command.startswith("find ") or "find -H " in command:
            return self._find(command)
        if command.startswith(("grep ", "{ grep ")):
            return self._grep(command)
        return _execution()

    def _find(self, command: str) -> _Execution:
        match = re.search(r"(?:^|[\s;{])find(?:\s+-[HLP])*\s+(\S+)", command)
        root = (match.group(1).strip("'\"") if match else "").rstrip("/") or "/"
        include_dirs = "-type d" in command
        paths = list(self._owner.file_data)
        if include_dirs:
            paths.extend(self._owner.directories)
        matches = sorted(path for path in set(paths) if path == root or path.startswith(f"{root}/"))
        if "__DF_FIND_STATUS__:" in command:
            status = 0 if matches else 1
            marker = "__DF_FIND_STATUS__:0" if matches else "__DF_FIND_STATUS__:missing"
            stdout = (*matches, "", marker) if matches else ("", marker)
            return _execution(stdout=stdout, exit_code=status)
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

    def _search(self, command: str) -> _Execution:
        # remote_search_command: a root-existence check, then the wrapped search and its status marker.
        root = shlex.split(re.search(r"\[ ! -e (.+?) \]; then", command).group(1))[0].rstrip("/") or "/"
        paths = set(self._owner.file_data) | set(self._owner.directories)
        if not any(path == root or path.startswith(f"{root}/") for path in paths):
            return _execution(stdout=("__DF_SEARCH_STATUS__:missing",))
        inner = command[command.index("{ ") + 2 : command.index('; echo $? > "$_st"; }')]
        if inner.startswith("find "):
            rows, status = [message.text for message in self._find(inner).logs.stdout], 0
        else:
            rows = [message.text for message in self._grep(inner).logs.stdout]
            status = 0 if rows else 1
        return _execution(stdout=(*rows, "", f"__DF_SEARCH_STATUS__:{status}"))


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
            # Already resolved by AppConfig at load time; a value that starts
            # with $ is the secret itself, not another reference.
            "environment": {"BASE": "1", "TOKEN": "$2b$12$resolved-secret"},
        },
    )
    provider.acquire("thread-1", user_id="user-1")
    call = sdk.create_calls[0]
    assert call["image"] == "python:3.12"
    assert call["timeout"] == timedelta(seconds=7200)
    assert call["ready_timeout"] == timedelta(seconds=18)
    assert call["env"] == {"BASE": "1", "TOKEN": "$2b$12$resolved-secret"}
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


@pytest.mark.parametrize(
    ("config_key", "value", "message"),
    [
        ("request_timeout", float("nan"), "sandbox.request_timeout must be positive"),
        ("request_timeout", float("inf"), "sandbox.request_timeout must be positive"),
        ("ready_timeout", float("nan"), "sandbox.ready_timeout must be positive"),
        ("ready_timeout", float("inf"), "sandbox.ready_timeout must be positive"),
        ("sandbox_timeout", float("nan"), "sandbox.sandbox_timeout must be non-negative"),
        ("sandbox_timeout", float("inf"), "sandbox.sandbox_timeout must be non-negative"),
    ],
)
def test_provider_rejects_non_finite_timeouts(
    monkeypatch: pytest.MonkeyPatch,
    config_key: str,
    value: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _install(monkeypatch, config={config_key: value})


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


def test_release_mirrors_outputs_for_gateway_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.gateway.routers.artifacts import _read_artifact_payload

    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    provider, sdk = _install(monkeypatch)
    try:
        sandbox_id = provider.acquire("thread", user_id="owner")
        box = provider.get(sandbox_id)
        box.write_file("/mnt/user-data/outputs/report.txt", "generated report")
        box.update_file("/mnt/user-data/outputs/charts/result.png", bytes(range(256)))
        provider.release(sandbox_id)

        outputs = paths.sandbox_outputs_dir("thread", user_id="owner")
        assert _read_artifact_payload(outputs / "report.txt", "report.txt", download=True)[0] == "file"
        assert (outputs / "report.txt").read_text(encoding="utf-8") == "generated report"
        assert (outputs / "charts/result.png").read_bytes() == bytes(range(256))
        assert not paths.sandbox_outputs_dir("thread", user_id="other-owner").exists()
        assert provider.acquire("thread", user_id="owner") == sandbox_id
        assert len(sdk.remotes) == 1
    finally:
        provider.shutdown()


@pytest.fixture
def output_sync_provider(monkeypatch, tmp_path):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: paths)
    provider, sdk = _install(monkeypatch)
    sandbox_id = provider.acquire("thread", user_id="owner")
    yield provider, sdk.remotes[0], sandbox_id, paths.sandbox_outputs_dir("thread", user_id="owner")
    provider.shutdown()


def test_output_sync_refreshes_existing_content_and_keeps_literal_filename(output_sync_provider):
    provider, remote, sandbox_id, outputs = output_sync_provider
    virtual = "/mnt/user-data/outputs/report # 中文.txt"
    remote.file_data[virtual] = b"first version"
    provider.release(sandbox_id)
    assert (outputs / "report # 中文.txt").read_bytes() == b"first version"
    provider.acquire("thread", user_id="owner")
    remote.file_data[virtual] = b"newer version"
    provider.release(sandbox_id)
    assert (outputs / "report # 中文.txt").read_bytes() == b"newer version"
    assert not list(outputs.glob(".opensandbox-sync-*"))


@pytest.mark.parametrize("file_limit", [1, 2])
def test_output_sync_skips_invalid_utf8_record_within_file_budget(output_sync_provider, monkeypatch, caplog, file_limit):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"valid report"
    listing = b"/mnt/user-data/outputs/\xff\0/mnt/user-data/outputs/report.txt\0"
    monkeypatch.setattr(provider, "_MAX_SYNC_FILES", file_limit)
    monkeypatch.setattr(remote.commands, "run", lambda *args, **kwargs: _execution(stdout=(base64.b64encode(listing).decode(), "__DF_OUTPUT_SYNC__:0:0:0")))
    provider.release(sandbox_id)
    if file_limit == 2:
        assert (outputs / "report.txt").read_bytes() == b"valid report"
    else:
        assert not outputs.exists()
        assert remote.files.calls == []
    assert "non-UTF-8" in caplog.text
    assert sandbox_id in provider._warm_pool


def test_output_sync_refreshes_same_size_edits(output_sync_provider):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"first"
    provider.release(sandbox_id)
    assert (outputs / "report.txt").read_bytes() == b"first"
    provider.acquire("thread", user_id="owner")
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"later"
    provider.release(sandbox_id)
    assert (outputs / "report.txt").read_bytes() == b"later"


@pytest.mark.parametrize(
    "names",
    [
        ("Report.txt", "report.txt"),
        ("Charts/report.txt", "charts/report.txt"),
        ("Charts/first.txt", "charts/second.txt"),
        ("nested/Report.txt", "nested/report.txt"),
        ("Charts", "charts/report.txt"),
        ("Résumé.txt", "résumé.txt"),
        ("résumé.txt", "re\u0301sume\u0301.txt"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_output_sync_rejects_ambiguous_remote_names_before_copying(output_sync_provider, caplog, names, reverse):
    provider, remote, sandbox_id, outputs = output_sync_provider
    names = names[::-1] if reverse else names
    remote.file_data.update({f"/mnt/user-data/outputs/{name}": f"content {index}".encode() for index, name in enumerate(names)})
    remote.file_data["/mnt/user-data/outputs/safe.txt"] = b"unambiguous report"

    provider.release(sandbox_id)

    assert sorted(path.relative_to(outputs).as_posix() for path in outputs.rglob("*") if path.is_file()) == ["safe.txt"]
    assert (outputs / "safe.txt").read_bytes() == b"unambiguous report"
    assert remote.files.calls == [("read_bytes_stream", "/mnt/user-data/outputs/safe.txt")]
    assert "ambiguous" in caplog.text
    assert sandbox_id in provider._warm_pool


def test_output_sync_collision_preflight_includes_records_beyond_file_limit(output_sync_provider, monkeypatch):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data.update(
        {
            "/mnt/user-data/outputs/Report.txt": b"first report",
            "/mnt/user-data/outputs/safe.txt": b"safe report",
            "/mnt/user-data/outputs/report.txt": b"different report",
        }
    )
    monkeypatch.setattr(provider, "_MAX_SYNC_FILES", 2)

    provider.release(sandbox_id)

    assert sorted(path.name for path in outputs.iterdir()) == ["safe.txt"]
    assert remote.files.calls == [("read_bytes_stream", "/mnt/user-data/outputs/safe.txt")]


def test_output_sync_remote_collision_preserves_previous_copy(output_sync_provider):
    provider, remote, sandbox_id, outputs = output_sync_provider
    outputs.mkdir(parents=True)
    (outputs / "Report.txt").write_bytes(b"previous complete report")
    remote.file_data.update({"/mnt/user-data/outputs/Report.txt": b"new upper report", "/mnt/user-data/outputs/report.txt": b"new lower report"})

    provider.release(sandbox_id)

    assert (outputs / "Report.txt").read_bytes() == b"previous complete report"
    assert sorted(path.name for path in outputs.iterdir()) == ["Report.txt"]
    assert remote.files.calls == []


@pytest.mark.parametrize("names", [("Report.txt", "report.txt"), ("Charts/old.txt", "charts/new.txt"), ("Résumé.txt", "résumé.txt"), ("résumé.txt", "re\u0301sume\u0301.txt")])
def test_output_sync_preserves_existing_host_alias(output_sync_provider, names):
    provider, remote, sandbox_id, outputs = output_sync_provider
    existing, incoming = names
    previous = outputs / existing
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"previous complete report")
    remote.file_data[f"/mnt/user-data/outputs/{incoming}"] = b"different remote report"
    remote.file_data["/mnt/user-data/outputs/safe.txt"] = b"safe report"

    provider.release(sandbox_id)

    assert previous.read_bytes() == b"previous complete report"
    assert sorted(path.relative_to(outputs).as_posix() for path in outputs.rglob("*") if path.is_file()) == sorted([existing, "safe.txt"])
    assert remote.files.calls == [("read_bytes_stream", "/mnt/user-data/outputs/safe.txt")]


def test_output_sync_rejects_alias_planted_during_download(output_sync_provider, monkeypatch):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data["/mnt/user-data/outputs/Report.txt"] = b"remote report"
    read_stream = remote.files.read_bytes_stream

    def plant_alias(path):
        (outputs / "report.txt").write_bytes(b"other complete report")
        yield from read_stream(path)

    monkeypatch.setattr(remote.files, "read_bytes_stream", plant_alias)
    provider.release(sandbox_id)

    assert (outputs / "report.txt").read_bytes() == b"other complete report"
    assert sorted(path.name for path in outputs.iterdir()) == ["report.txt"]


def test_output_sync_keeps_distinct_files_in_the_same_directory(output_sync_provider):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data.update({"/mnt/user-data/outputs/Charts/first.txt": b"first", "/mnt/user-data/outputs/Charts/second.txt": b"second"})

    provider.release(sandbox_id)

    assert (outputs / "Charts/first.txt").read_bytes() == b"first"
    assert (outputs / "Charts/second.txt").read_bytes() == b"second"


@pytest.mark.parametrize("name", ["con.txt", "PRN", "aux .log", "NUL.bin", "COM9", "lpt1.doc", "COM¹.txt", "LPT²", "CONIN$.txt", "CONOUT$"])
def test_output_destination_rejects_reserved_components_without_deprecated_api(tmp_path, monkeypatch, name):
    from pathlib import PureWindowsPath

    def unavailable(*args):
        raise AssertionError("PureWindowsPath.is_reserved is unavailable")

    monkeypatch.setattr(PureWindowsPath, "is_reserved", unavailable)
    with pytest.raises(ValueError, match="Unsafe"):
        OpenSandboxProvider._output_destination(tmp_path / "outputs", f"/mnt/user-data/outputs/{name}")
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("name", ["CONSOLE.txt", "COM10.txt", "LPT0", "report # 中文.txt"])
def test_output_destination_accepts_nonreserved_names_without_deprecated_api(tmp_path, monkeypatch, name):
    from pathlib import PureWindowsPath

    def unavailable(*args):
        raise AssertionError("PureWindowsPath.is_reserved is unavailable")

    monkeypatch.setattr(PureWindowsPath, "is_reserved", unavailable)
    outputs = tmp_path / "outputs"
    assert OpenSandboxProvider._output_destination(outputs, f"/mnt/user-data/outputs/{name}") == outputs / name


@pytest.mark.parametrize("remote_path", ["/tmp/outside", "/mnt/user-data/uploads/input.txt", "/mnt/user-data/outputs/../outside", "/mnt/user-data/outputs//bad", "/mnt/user-data/outputs/C:bad", "/mnt/user-data/outputs/NUL.txt"])
def test_output_sync_rejects_unconfined_paths(output_sync_provider, remote_path):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data[remote_path] = b"untrusted listing"
    provider.release(sandbox_id)
    assert remote.files.calls == []
    assert not outputs.exists()
    assert sandbox_id in provider._warm_pool


@pytest.mark.parametrize("link_root", [True, False])
def test_output_sync_rejects_host_symlink_components(output_sync_provider, tmp_path, link_root):
    from support.symlinks import symlink_or_skip

    provider, remote, sandbox_id, outputs = output_sync_provider
    outside = tmp_path / "outside"
    outside.mkdir()
    outputs.parent.mkdir(parents=True, exist_ok=True)
    if link_root:
        symlink_or_skip(outputs, outside, target_is_directory=True)
        name = "report.txt"
    else:
        outputs.mkdir()
        symlink_or_skip(outputs / "nested", outside, target_is_directory=True)
        name = "nested/report.txt"
    remote.file_data[f"/mnt/user-data/outputs/{name}"] = b"must not escape"
    provider.release(sandbox_id)
    assert list(outside.iterdir()) == []
    assert remote.files.calls == []


def test_output_sync_transfer_failure_preserves_previous_copy(output_sync_provider, caplog):
    provider, remote, sandbox_id, outputs = output_sync_provider
    outputs.mkdir(parents=True)
    (outputs / "report.txt").write_bytes(b"old complete version")
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"new version"
    remote.file_error = RuntimeError("temporary file transport failure")
    provider.release(sandbox_id)
    assert (outputs / "report.txt").read_bytes() == b"old complete version"
    assert sandbox_id in provider._warm_pool
    assert "Could not synchronize" in caplog.text


def test_output_sync_failed_replace_cleans_staging(output_sync_provider, monkeypatch):
    provider, remote, sandbox_id, outputs = output_sync_provider
    outputs.mkdir(parents=True)
    (outputs / "report.txt").write_bytes(b"old complete version")
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"new version"

    def fail_replace(self, target):
        raise PermissionError("destination temporarily open")

    monkeypatch.setattr(Path, "replace", fail_replace)
    provider.release(sandbox_id)
    assert (outputs / "report.txt").read_bytes() == b"old complete version"
    assert sorted(p.name for p in outputs.iterdir()) == ["report.txt"]


def test_output_sync_partial_download_failure_stops_remaining_transfers(output_sync_provider, monkeypatch):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data.update({"/mnt/user-data/outputs/first.txt": b"123", "/mnt/user-data/outputs/second.txt": b"456"})
    started = []

    def partial_stream(path):
        started.append(path)
        yield b"123"
        raise OSError("connection failed after receiving bytes")

    monkeypatch.setattr(remote.files, "read_bytes_stream", partial_stream)
    provider.release(sandbox_id)
    assert started == ["/mnt/user-data/outputs/first.txt"]
    assert not (outputs / "first.txt").exists()
    assert not list(outputs.glob(".opensandbox-sync-*"))
    assert sandbox_id in provider._warm_pool


@pytest.mark.parametrize("limit", ["files", "bytes", "listing", "deadline"])
def test_output_sync_is_bounded(output_sync_provider, monkeypatch, caplog, limit):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data.update({"/mnt/user-data/outputs/first.txt": b"123", "/mnt/user-data/outputs/second.txt": b"456"})
    if limit == "files":
        monkeypatch.setattr(provider, "_MAX_SYNC_FILES", 1)
    elif limit == "bytes":
        monkeypatch.setattr(provider, "_MAX_SYNC_TOTAL_BYTES", 4)
    elif limit == "listing":
        monkeypatch.setattr(provider, "_MAX_SYNC_LISTING_BYTES", 4)
    else:
        monkeypatch.setattr(provider, "_SYNC_DEADLINE_SECONDS", 1)
        monkeypatch.setattr("deerflow.community.opensandbox.provider.time", types.SimpleNamespace(monotonic=iter([0, 2]).__next__, time=time.time))
    provider.release(sandbox_id)
    if limit in {"files", "bytes"}:
        assert (outputs / "first.txt").read_bytes() == b"123"
        assert not (outputs / "second.txt").exists()
    else:
        assert not outputs.exists()
    assert sandbox_id in provider._warm_pool
    assert caplog.records


def test_output_sync_closes_stream_when_single_file_exceeds_cap(output_sync_provider, monkeypatch):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data["/mnt/user-data/outputs/large.txt"] = b"123456789"
    monkeypatch.setattr("deerflow.community.opensandbox.provider._MAX_DOWNLOAD_SIZE", 4)
    provider.release(sandbox_id)
    assert not (outputs / "large.txt").exists()
    assert remote.stream_closed


@pytest.mark.parametrize("ticks", [[2], [0, 2]])
def test_bounded_download_deadline_closes_native_stream(monkeypatch, ticks):
    remote = _FakeRemote("remote")
    path = "/mnt/user-data/outputs/report.txt"
    remote.file_data[path] = b"123456789"
    box = _box(remote)
    monkeypatch.setattr("deerflow.community.opensandbox.sandbox.time", types.SimpleNamespace(monotonic=iter(ticks).__next__))
    with pytest.raises(TimeoutError, match="synchronization timed out"):
        box._download_file_bounded(path, max_bytes=100, deadline=1)
    assert remote.stream_closed


@pytest.fixture
def output_sync_shell(output_sync_provider, monkeypatch, tmp_path):
    """Run the production listing pipeline; only rebase the transport paths."""
    provider, remote, sandbox_id, outputs = output_sync_provider
    if os.name == "nt":
        shell = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if not shell.is_file():
            pytest.skip("Git Bash required for real output-listing execution on Windows")
        shell = str(shell)

        def posix_path(path):
            return subprocess.check_output([shell, "-c", 'cygpath -u "$1"', "sh", str(path)], text=True, encoding="utf-8").strip()
    else:
        shell = shutil.which("sh")
        if shell is None:
            pytest.skip("POSIX sh required")
        posix_path = str
    native = tmp_path / "remote-outputs"
    native.mkdir()
    native_root = posix_path(native)
    fake_bin = tmp_path / "sync-bin"
    fake_bin.mkdir()

    def run(command, *, opts=None):
        command = command.replace("/mnt/user-data/outputs", native_root)
        command = f"PATH={shlex.quote(posix_path(fake_bin))}:$PATH; " + command
        proc = subprocess.run([shell, "-c", command], capture_output=True, text=True, encoding="utf-8", check=False, timeout=10)
        stdout = proc.stdout
        if proc.returncode == 0 and "\n__DF_OUTPUT_SYNC__:" in stdout:
            payload, marker = stdout.rstrip("\n").rsplit("\n", 1)
            # The host's native temporary path replaces the remote mount only
            # at this SDK transport boundary; status and filename bytes survive.
            try:
                listing = base64.b64decode("".join(payload.split()), validate=True)
                listing = listing.replace(native_root.encode(), b"/mnt/user-data/outputs")
                stdout = base64.b64encode(listing).decode() + "\n" + marker
            except ValueError:
                pass
        return _execution(stdout=tuple(stdout.split("\n")), stderr=(proc.stderr,), exit_code=proc.returncode)

    monkeypatch.setattr(remote.commands, "run", run)
    return provider, remote, sandbox_id, outputs, native, fake_bin


def test_output_sync_real_shell_handles_empty_and_literal_filenames(output_sync_shell):
    provider, remote, sandbox_id, outputs, native, _ = output_sync_shell
    provider.release(sandbox_id)
    assert not outputs.exists()
    provider.acquire("thread", user_id="owner")
    names = ["中文 # $(echo injected).txt", "nested/result.bin"]
    if os.name != "nt":
        names.append("newline\nand\ttab.txt")
    for name in names:
        payload = bytes(range(256))
        target = native / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        remote.file_data[f"/mnt/user-data/outputs/{name}"] = payload
    provider.release(sandbox_id)
    for name in names:
        assert (outputs / name).read_bytes() == bytes(range(256))


@pytest.mark.parametrize("binary", ["find", "head", "base64", "mktemp"])
def test_output_sync_real_shell_propagates_each_pipeline_failure(output_sync_shell, binary, caplog):
    provider, remote, sandbox_id, outputs, native, fake_bin = output_sync_shell
    (native / "report.txt").write_bytes(b"report")
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"report"
    failing = fake_bin / binary
    failing.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    failing.chmod(0o755)
    provider.release(sandbox_id)
    assert not outputs.exists()
    assert not remote.files.calls
    assert "listing failed" in caplog.text
    assert sandbox_id in provider._warm_pool


def test_output_sync_real_shell_listing_overflow_never_downloads(output_sync_shell, monkeypatch, caplog):
    provider, remote, sandbox_id, outputs, native, _ = output_sync_shell
    for index in range(30):
        (native / f"file-{index}.txt").write_bytes(b"data")
    monkeypatch.setattr(provider, "_MAX_SYNC_LISTING_BYTES", 16)
    provider.release(sandbox_id)
    assert not outputs.exists()
    assert not remote.files.calls
    assert "listing exceeded" in caplog.text


def test_output_sync_real_shell_rejects_unexpected_sigpipe(output_sync_shell, caplog):
    provider, remote, sandbox_id, outputs, native, fake_bin = output_sync_shell
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"report"
    failing = fake_bin / "find"
    failing.write_text("#!/bin/sh\nprintf '/mnt/user-data/outputs/report.txt\\0'\nexit 141\n", encoding="utf-8")
    failing.chmod(0o755)
    provider.release(sandbox_id)
    assert not outputs.exists() and not remote.files.calls
    assert "listing failed" in caplog.text


@pytest.mark.parametrize(
    ("case", "warning"),
    [
        ("complete", "traversal errors"),
        ("incomplete", "listing was incomplete"),
        ("oversized", "listing exceeded"),
        ("head_failure", "listing failed"),
        ("encoder_failure", "listing failed"),
        ("find_failure", "listing failed"),
    ],
)
def test_output_sync_real_shell_find_walk_error_preserves_only_complete_listing(output_sync_shell, monkeypatch, caplog, case, warning):
    provider, remote, sandbox_id, outputs, native, fake_bin = output_sync_shell
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"report"
    find = fake_bin / "find"
    tail = "printf 'unfinished'\n" if case == "incomplete" else ""
    status = 2 if case == "find_failure" else 1
    find.write_text(f"#!/bin/sh\nprintf '/mnt/user-data/outputs/report.txt\\0'\n{tail}echo 'find: entry vanished' >&2\nexit {status}\n", encoding="utf-8")
    find.chmod(0o755)
    if case == "oversized":
        monkeypatch.setattr(provider, "_MAX_SYNC_LISTING_BYTES", 16)
    elif case in {"head_failure", "encoder_failure"}:
        binary = "head" if case == "head_failure" else "base64"
        command = "cat" if binary == "head" else "command -p base64"
        failing = fake_bin / binary
        failing.write_text(f"#!/bin/sh\n{command}\nexit 1\n", encoding="utf-8")
        failing.chmod(0o755)
    provider.release(sandbox_id)
    if case == "complete":
        assert (outputs / "report.txt").read_bytes() == b"report"
    else:
        assert not outputs.exists() and not remote.files.calls
    assert warning in caplog.text
    assert sandbox_id in provider._warm_pool


def test_output_sync_real_shell_does_not_follow_remote_links(output_sync_shell, tmp_path, caplog):
    from support.symlinks import symlink_or_skip

    provider, remote, sandbox_id, outputs, native, _ = output_sync_shell
    outside = tmp_path / "remote-outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside")
    symlink_or_skip(native / "linked", outside, target_is_directory=True)
    provider.release(sandbox_id)
    assert not outputs.exists() and not remote.files.calls
    provider.acquire("thread", user_id="owner")
    (native / "linked").unlink()
    native.rmdir()
    symlink_or_skip(native, outside, target_is_directory=True)
    provider.release(sandbox_id)
    assert not outputs.exists() and not remote.files.calls
    assert "listing failed" in caplog.text


def test_reacquire_waits_until_release_output_sync_finishes(output_sync_provider, monkeypatch):
    provider, remote, sandbox_id, outputs = output_sync_provider
    remote.file_data["/mnt/user-data/outputs/report.txt"] = b"report"
    box = provider.get(sandbox_id)
    original = box._download_file_bounded
    started, unblock, acquire_started, acquired = (threading.Event() for _ in range(4))
    errors = []

    def blocked_download(*args, **kwargs):
        started.set()
        assert unblock.wait(10)
        return original(*args, **kwargs)

    original_checkout = provider._acquire_serializer._checkout

    def checked_checkout(key):
        result = original_checkout(key)
        if threading.current_thread().name == "next-turn":
            acquire_started.set()
        return result

    def reacquire():
        try:
            assert provider.acquire("thread", user_id="owner") == sandbox_id
            acquired.set()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(box, "_download_file_bounded", blocked_download)
    monkeypatch.setattr(provider._acquire_serializer, "_checkout", checked_checkout)
    release = threading.Thread(target=provider.release, args=(sandbox_id,))
    acquire = threading.Thread(target=reacquire, name="next-turn")
    try:
        release.start()
        assert started.wait(10)
        assert sandbox_id not in provider._warm_pool
        acquire.start()
        assert acquire_started.wait(10)
        assert not acquired.is_set()
    finally:
        unblock.set()
        release.join(10)
        if acquire.ident is not None:
            acquire.join(10)
    assert not release.is_alive() and not acquire.is_alive()
    assert not errors and acquired.is_set()
    assert (outputs / "report.txt").read_bytes() == b"report"


@pytest.mark.parametrize("transition", ["shutdown", "reset"])
def test_release_is_noop_when_lifecycle_closes_before_serializer_hold(output_sync_provider, monkeypatch, transition):
    provider, remote, sandbox_id, outputs = output_sync_provider
    original_hold = provider._acquire_serializer.hold

    def close_before_hold(key):
        getattr(provider, transition)()
        return original_hold(key)

    monkeypatch.setattr(provider._acquire_serializer, "hold", close_before_hold)
    provider.release(sandbox_id)
    assert provider.get(sandbox_id) is None
    assert not outputs.exists()


@pytest.mark.parametrize("untrack", [True, False])
def test_release_tolerates_typed_closure_independent_of_message(output_sync_provider, monkeypatch, untrack):
    from deerflow.sandbox import acquire_serialization

    provider, remote, sandbox_id, outputs = output_sync_provider

    def close_before_hold(key):
        if untrack:
            provider.reset()
        raise acquire_serialization.AcquireSerializerClosed("No further scope holders accepted")

    monkeypatch.setattr(provider._acquire_serializer, "hold", close_before_hold)
    if untrack:
        provider.release(sandbox_id)
        assert provider.get(sandbox_id) is None
    else:
        with pytest.raises(acquire_serialization.AcquireSerializerClosed):
            provider.release(sandbox_id)


def test_release_does_not_swallow_unrelated_runtime_error_with_old_closure_message(output_sync_provider, monkeypatch):
    provider, remote, sandbox_id, outputs = output_sync_provider

    def fail_hold(key):
        provider.reset()
        raise RuntimeError("AcquireSerializer is closed")

    monkeypatch.setattr(provider._acquire_serializer, "hold", fail_hold)
    with pytest.raises(RuntimeError, match="AcquireSerializer is closed"):
        provider.release(sandbox_id)


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


def _command_error_execution(*, error_value: str, exit_code: int | None = None, error_name: str = "CommandExecError", stdout: tuple[str, ...] = (), stderr: tuple[str, ...] = (), result: tuple[str, ...] = ()) -> Any:
    execution = _execution(stdout=stdout, stderr=stderr, result=result, exit_code=exit_code)
    return types.SimpleNamespace(**vars(execution), error=types.SimpleNamespace(name=error_name, value=error_value))


@pytest.mark.parametrize(
    ("stdout", "stderr", "result", "expected_body"),
    [
        ((), (), (), ""),
        (("partial output",), (), (), "partial output\n"),
        (("out-1", "out-2"), ("stderr",), ("result",), "out-1\nout-2\nresult\nstderr\n"),
    ],
)
def test_execute_command_server_side_deadline_appends_exit_marker(stdout: tuple[str, ...], stderr: tuple[str, ...], result: tuple[str, ...], expected_body: str) -> None:
    # The SDK cannot parse this deadline error value as an integer, so it
    # returns an Execution with exit_code=None rather than raising TimeoutError.
    remote = _FakeRemote("remote")
    remote.commands.run = lambda command, opts=None: _command_error_execution(error_value="context deadline exceeded", stdout=stdout, stderr=stderr, result=result)  # type: ignore[method-assign]
    box = _box(remote, sandbox_timeout=timedelta(seconds=60), default_command_timeout=120)

    assert box.execute_command("sleep 9999", timeout=5) == f"{expected_body}Error: command timed out\nExit Code: 124"


@pytest.mark.parametrize("error_value", ["credential lookup failed", "context canceled", "signal: killed", "timeout while starting process", ""])
def test_execute_command_other_missing_exit_codes_are_not_timeouts(error_value: str) -> None:
    remote = _FakeRemote("remote")
    remote.commands.run = lambda command, opts=None: _command_error_execution(error_value=error_value)  # type: ignore[method-assign]
    box = _box(remote, sandbox_timeout=timedelta(seconds=60), default_command_timeout=120)

    assert box.execute_command("true", timeout=5) == f"Error: OpenSandbox command completed without an exit code: CommandExecError: {error_value}"


@pytest.mark.parametrize("exit_code", [-1, 7, 124])
def test_execute_command_numeric_error_events_keep_their_exit_code(exit_code: int) -> None:
    # execd sends ordinary nonzero exits through CommandExecError too. In
    # particular, -1 only proves signal termination, not a command deadline.
    remote = _FakeRemote("remote")
    remote.commands.run = lambda command, opts=None: _command_error_execution(error_value=str(exit_code), exit_code=exit_code, stdout=("partial output",))  # type: ignore[method-assign]
    box = _box(remote, sandbox_timeout=timedelta(seconds=60), default_command_timeout=120)

    assert box.execute_command("exit-or-signal", timeout=5) == f"partial output\nCommandExecError: {exit_code}\nExit Code: {exit_code}"


@pytest.mark.parametrize("exit_code", [None, 7])
def test_execute_command_deadline_text_on_other_errors_is_not_a_command_timeout(exit_code: int | None) -> None:
    remote = _FakeRemote("remote")
    remote.commands.run = lambda command, opts=None: _command_error_execution(error_value="context deadline exceeded", exit_code=exit_code, error_name="OtherError")  # type: ignore[method-assign]
    box = _box(remote, sandbox_timeout=timedelta(seconds=60), default_command_timeout=120)

    result = box.execute_command("true", timeout=5)
    assert "OtherError: context deadline exceeded" in result
    assert "command timed out" not in result
    assert not result.endswith("Exit Code: 124")


@pytest.mark.parametrize("message", ["", "context deadline exceeded"])
def test_execute_command_transport_exception_is_not_a_shell_timeout(message: str) -> None:
    remote = _FakeRemote("remote")
    remote.command_error = TimeoutError(message)
    box = _box(remote, sandbox_timeout=timedelta(seconds=60), default_command_timeout=120)

    # Even an injected builtin TimeoutError must not turn a provider/renewal
    # failure into an authoritative shell exit. The real SDK wraps this error.
    assert box.execute_command("true", timeout=5) == f"Error: {message}"


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
    # A start past EOF comes back empty rather than raising, and a negative
    # start reads from the first line instead of wrapping around.
    assert box.read_file(path, 99) == ""
    assert box.read_file(path, -1) == "one\ntwo\nthree\nfour"
    assert box.read_file(path, end_line=-1) == ""
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
    assert "-m101" in grep_tokens

    box.grep("/mnt/user-data/workspace", "needle", glob="src/*.py; echo injected", literal=True)
    unsafe_glob_tokens = shlex.split(remote.commands.calls[-1][0])
    assert "--include=*.py; echo injected" in unsafe_glob_tokens
    assert unsafe_glob_tokens.count("grep") == 2
    # The fallback runs only on the primary's status 2, and the primary's
    # status is kept otherwise so a missing grep (127) is not "no matches".
    assert 'status=$?; if [ "$status" -eq 2 ]; then' in remote.commands.calls[-1][0]
    assert '(exit "$status")' in remote.commands.calls[-1][0]
    fallback_tokens = unsafe_glob_tokens[unsafe_glob_tokens.index("grep", unsafe_glob_tokens.index("grep") + 1) :]
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


def test_list_dir_raises_when_find_returns_no_entries() -> None:
    remote = _FakeRemote("remote")
    box = _box(remote)

    with pytest.raises(FileNotFoundError):
        box.list_dir("/mnt/user-data/missing")


def test_list_dir_raises_oserror_when_find_exit_is_not_missing_path() -> None:
    # find exit 1 is "start point absent"; 127 (no binary) must not look missing.
    box = _box(_FakeRemote("remote"))
    box._run = lambda *args, **kwargs: _execution(exit_code=127)

    with pytest.raises(OSError, match="exited with code 127"):
        box.list_dir("/mnt/user-data/workspace")


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


# ── Remote grep/glob failure contract against a real POSIX sh (#5376) ─────────

_RS_POSIX = pytest.mark.skipif(
    os.name == "nt" or any(shutil.which(tool) is None for tool in ("sh", "head", "grep", "find")),
    reason="POSIX sh, head, grep and find required",
)


def _rs_env(tmp_path, failing: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if failing is not None:
        bin_dir = tmp_path / "fake-bin"
        bin_dir.mkdir()
        fake = bin_dir / failing
        fake.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
        fake.chmod(0o755)
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


def _rs_box(tmp_path, monkeypatch, failing: str | None = None) -> OpenSandboxSandbox:
    box = _box(_FakeRemote("remote"))
    shell_env = _rs_env(tmp_path, failing)

    def run(command: str, *, env=None, timeout=None) -> _Execution:
        # ``sh -c`` (not ``-lc``) keeps a login profile from overriding the fake PATH.
        proc = subprocess.run(["sh", "-c", command], capture_output=True, text=True, env=shell_env, check=False)
        return _execution(stdout=(proc.stdout,), stderr=(proc.stderr,) if proc.stderr else (), exit_code=proc.returncode)

    monkeypatch.setattr(box, "_run", run)
    return box


def _rs_search(box, op: str, root: str):
    return box.grep(root, "needle") if op == "grep" else box.glob(root, "**/*.py")


@_RS_POSIX
@pytest.mark.parametrize("op", ["grep", "glob"])
def test_remote_search_missing_root_raises_file_not_found(tmp_path, monkeypatch, op) -> None:
    with pytest.raises(FileNotFoundError):
        _rs_search(_rs_box(tmp_path, monkeypatch), op, str(tmp_path / "missing"))


@_RS_POSIX
@pytest.mark.parametrize(("op", "binary"), [("grep", "grep"), ("glob", "find")])
def test_remote_search_missing_binary_raises_instead_of_no_matches(tmp_path, monkeypatch, op, binary) -> None:
    with pytest.raises(OSError, match="exited with code 127"):
        _rs_search(_rs_box(tmp_path, monkeypatch, failing=binary), op, str(tmp_path))


@_RS_POSIX
def test_remote_search_keeps_real_matches_and_genuine_no_match(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def needle():\n", encoding="utf-8")
    box = _rs_box(tmp_path, monkeypatch)

    matches, _ = box.grep(str(tmp_path), "needle")
    assert [(os.path.basename(m.path), m.line_number) for m in matches] == [("app.py", 1)]
    assert box.grep(str(tmp_path), "zzz_nothing") == ([], False)
    found, _ = box.glob(str(tmp_path), "**/*.py")
    assert [os.path.basename(path) for path in found] == ["app.py"]
    assert box.glob(str(tmp_path), "*.md") == ([], False)


@_RS_POSIX
@pytest.mark.parametrize(("op", "entries", "truncated"), [("grep", 51, False), ("grep", 52, True), ("glob", 51, False), ("glob", 52, True)])
def test_remote_search_reports_truncation_when_the_cap_hides_filtered_results(tmp_path, monkeypatch, op, entries, truncated) -> None:
    # max_results=1 caps the raw stream at 51 lines, and every line falls outside
    # the glob, so nothing survives the Python-side filter. Only the cap decides
    # whether that empty result is complete; reporting it as such reads as "no
    # matches" while an in-scope file may sit past the cap.
    (tmp_path / "other").mkdir()
    for index in range(entries):
        (tmp_path / "other" / f"f{index}.js").write_text("needle\n", encoding="utf-8")
    box = _rs_box(tmp_path, monkeypatch)

    if op == "grep":
        result = box.grep(str(tmp_path), "needle", glob="src/*.js", max_results=1)
    else:
        result = box.glob(str(tmp_path), "src/*.js", max_results=1)

    assert result == ([], truncated)


@_RS_POSIX
@pytest.mark.parametrize(("op", "entries", "truncated"), [("grep", 1, False), ("grep", 2, True), ("glob", 1, False), ("glob", 2, True)])
def test_remote_search_exactly_full_is_not_truncated(tmp_path, monkeypatch, op, entries, truncated) -> None:
    # max_results=1 over a tree holding one in-scope match is a complete result:
    # the Python-side loop used to return on the max-th match without looking for
    # one more, so an exhausted search over a one-match tree read as cut off. A
    # second match keeps that report honest.
    (tmp_path / "src").mkdir()
    for index in range(entries):
        (tmp_path / "src" / f"f{index}.js").write_text("needle\n", encoding="utf-8")
    box = _rs_box(tmp_path, monkeypatch)

    if op == "grep":
        matches, reported = box.grep(str(tmp_path), "needle", glob="src/*.js", max_results=1)
    else:
        matches, reported = box.glob(str(tmp_path), "src/*.js", max_results=1)

    assert len(matches) == 1
    assert reported is truncated


@_RS_POSIX
@pytest.mark.parametrize(("entries", "truncated"), [(50, False), (51, True)])
def test_remote_grep_reports_single_file_overflow(tmp_path, monkeypatch, entries, truncated) -> None:
    # The shell command must retain one more match per file than the caller's
    # cap. Otherwise 51 matches in this single file look complete at a cap of
    # 50 because the raw-output cap is not reached.
    source = tmp_path / "src.py"
    source.write_text("needle\n" * entries, encoding="utf-8")

    matches, reported = _rs_box(tmp_path, monkeypatch).grep(str(tmp_path), "needle", max_results=50)

    assert len(matches) == 50
    assert reported is truncated
