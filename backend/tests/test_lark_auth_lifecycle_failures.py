"""Offline failure injection at the login process and filesystem boundaries."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths
from deerflow.integrations import lark_cli

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")


class _LoginProcess:
    pid = None

    def __init__(self):
        self.released = threading.Event()
        self.killed = False

    def communicate(self, timeout=None):
        assert self.released.wait(10), "test did not release the login process"
        return "{}", ""

    @property
    def returncode(self):
        return -9 if self.killed else 0

    def poll(self):
        return self.returncode if self.released.is_set() else None

    def kill(self):
        self.killed = True
        self.released.set()


@pytest.fixture
def login_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=tmp_path / "home"))
    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "synthetic-lark-cli")
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    spawned = []

    def spawn(*_args, **_kwargs):
        process = _LoginProcess()
        spawned.append(process)
        return process

    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", spawn)
    with lark_cli._lark_credential_lock("alice"):
        generation = lark_cli._advance_lark_flow_generation_locked("alice")
    yield generation, spawned
    for process in spawned:
        process.kill()
    lark_cli._clear_lark_login_runs_for_tests()


@pytest.mark.parametrize("operation", ["mkstemp", "write", "chmod", "publish"])
def test_result_io_failure_is_terminal_for_local_and_foreign_polls(monkeypatch, login_flow, operation):
    generation, spawned = login_flow
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    injected = threading.Event()

    def is_result_temp(path):
        return Path(path).name.startswith("..login-result-")

    def fail():
        injected.set()
        raise OSError(errno.EIO, "synthetic result I/O failure")

    if operation == "mkstemp":
        original = lark_cli.tempfile.mkstemp

        def mkstemp(*args, **kwargs):
            if kwargs.get("prefix", "").startswith("..login-result-"):
                fail()
            return original(*args, **kwargs)

        monkeypatch.setattr(lark_cli.tempfile, "mkstemp", mkstemp)
    elif operation == "publish":

        def fail_publication(original):
            def publish(source, destination, *args, **kwargs):
                if Path(destination).name.startswith(".login-result-"):
                    fail()
                return original(source, destination, *args, **kwargs)

            return publish

        monkeypatch.setattr(os, "link", fail_publication(os.link))
        monkeypatch.setattr(os, "replace", fail_publication(os.replace))
    else:
        name = "write_text" if operation == "write" else "chmod"
        original = getattr(Path, name)

        def file_operation(path, *args, **kwargs):
            if is_result_temp(path):
                fail()
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, name, file_operation)

    spawned[0].released.set()
    with pytest.raises(ValueError, match="Restart the authorization flow"):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=5)
    assert injected.is_set(), "failure injection was not reached"

    # A fresh worker has no registry entry; the shared terminal receipt must
    # reject this code instead of starting a second login.
    with lark_cli._LARK_LOGIN_RUNS_LOCK:
        run = lark_cli._LARK_LOGIN_RUNS.pop(("alice", generation))
    run.thread.join(5)
    assert not run.thread.is_alive()
    with pytest.raises(ValueError, match="Restart the authorization flow"):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    assert len(spawned) == 1


def test_lost_result_and_fallback_are_bounded_without_redeeming_again(monkeypatch, login_flow):
    generation, spawned = login_flow
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    run = lark_cli._LARK_LOGIN_RUNS[("alice", generation)]
    failed_destinations = set()
    original_replace = os.replace

    def replace(source, destination, *args, **kwargs):
        name = Path(destination).name
        if name.startswith((".login-result-", ".login-run-")):
            failed_destinations.add(name.split("-")[1])
            raise OSError(errno.ENOSPC, "synthetic full credential volume")
        return original_replace(source, destination, *args, **kwargs)

    with monkeypatch.context() as storage_failure:
        storage_failure.setattr(os, "replace", replace)
        spawned[0].released.set()
        with pytest.raises(ValueError, match="Restart the authorization flow"):
            lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=5)
        run.thread.join(5)
        assert not run.thread.is_alive()
    assert failed_destinations == {"result", "run"}
    with lark_cli._LARK_LOGIN_RUNS_LOCK:
        lark_cli._LARK_LOGIN_RUNS.pop(("alice", generation))

    # Storage recovers, but neither result nor failure receipt made it to disk.
    # A new worker may wait one publication grace, then must reject the old code.
    clock = [lark_cli.time.time()]
    monkeypatch.setattr(lark_cli, "time", SimpleNamespace(time=lambda: clock[0], monotonic=lark_cli.time.monotonic, sleep=lark_cli.time.sleep))
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    clock[0] += lark_cli._LARK_LOGIN_OWNER_ALIVE_GRACE_SECONDS + 1
    with pytest.raises(ValueError, match="Restart the authorization flow"):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    assert len(spawned) == 1
    digest = lark_cli._lark_login_code_digest("code-A")
    assert lark_cli._lark_login_marker_path("alice", generation, digest).is_file()
    assert not lark_cli._lark_login_result_path("alice", generation, digest).exists()


def test_foreign_poll_rereads_result_after_marker_disappears(monkeypatch, login_flow):
    generation, spawned = login_flow
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    run = lark_cli._LARK_LOGIN_RUNS[("alice", generation)]
    digest = lark_cli._lark_login_code_digest("code-A")
    marker = lark_cli._lark_login_marker_path("alice", generation, digest)
    result = lark_cli._lark_login_result_path("alice", generation, digest)
    original_is_file = Path.is_file
    injected = threading.Event()

    def is_file(path):
        if path == marker and not injected.is_set():
            # The foreign poll has already read a missing result. Let the
            # real owner finish publishing before its next marker probe.
            assert not result.exists()
            injected.set()
            spawned[0].released.set()
            run.thread.join(10)
            assert not run.thread.is_alive()
            assert result.is_file() and not marker.exists()
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", is_file)
    assert lark_cli._await_lark_login_result("alice", generation, "code-A", 0) == {"ok": True}
    assert injected.is_set(), "publication must straddle the foreign poll's two reads"
    assert len(spawned) == 1


@pytest.mark.parametrize("failure_step", ["reserve_marker", "marker_pid", "spawn", "thread_start"])
def test_failed_startup_reaps_cli_and_wakes_an_attached_poll(monkeypatch, tmp_path, failure_step):
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=tmp_path / "home"))
    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "synthetic-lark-cli")
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    with lark_cli._lark_credential_lock("alice"):
        generation = lark_cli._advance_lark_flow_generation_locked("alice")
    spawned, attached = [], []
    injected = threading.Event()

    def spawn(*_args, **_kwargs):
        if failure_step == "spawn":
            injected.set()
            raise OSError(errno.EAGAIN, "synthetic process launch failure")
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=os.name != "nt")
        spawned.append(process)
        return process

    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", spawn)
    original_start = threading.Thread.start

    def fail_start(thread):
        if thread.name.startswith("lark-login-"):
            attached.append(lark_cli._LARK_LOGIN_RUNS[("alice", generation)])
            injected.set()
            raise RuntimeError("can't start new thread")
        return original_start(thread)

    if failure_step in {"reserve_marker", "marker_pid"}:
        original_write = lark_cli._write_json_file_atomic

        def fail_marker(path, payload):
            should_fail = failure_step == "reserve_marker" or payload.get("cli_pid") is not None
            if path.name.startswith(".login-run-") and "outcome" not in payload and should_fail:
                injected.set()
                raise OSError(errno.ENOSPC, "synthetic marker write failure")
            return original_write(path, payload)

        monkeypatch.setattr(lark_cli, "_write_json_file_atomic", fail_marker)
        error = OSError
    elif failure_step == "thread_start":
        monkeypatch.setattr(threading.Thread, "start", fail_start)
        error = RuntimeError
    else:
        error = OSError
    try:
        with pytest.raises(error):
            lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
        assert injected.is_set()
        assert ("alice", generation) not in lark_cli._LARK_LOGIN_RUNS
        assert all(process.poll() is not None for process in spawned), "startup failure leaked a real CLI"
        for run in attached:
            assert run.done.is_set(), "a concurrent waiter would remain blocked"
            assert isinstance(run.outcome, BaseException)
        with pytest.raises(ValueError):
            lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
        assert len(spawned) <= 1, "a failed startup must leave a terminal receipt"
    finally:
        with lark_cli._LARK_LOGIN_RUNS_LOCK:
            lark_cli._LARK_LOGIN_RUNS.pop(("alice", generation), None)
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("cleanup", ["temporary_result", "marker"])
def test_cleanup_failure_preserves_a_published_result(monkeypatch, login_flow, cleanup):
    generation, spawned = login_flow
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    original_unlink = Path.unlink
    injected = threading.Event()

    def unlink(path, *args, **kwargs):
        match = path.name.startswith("..login-result-") if cleanup == "temporary_result" else path.name.startswith(".login-run-")
        if match and threading.current_thread().name.startswith("lark-login-"):
            injected.set()
            raise PermissionError(errno.EACCES, "synthetic cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    spawned[0].released.set()
    first = lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=5)
    assert injected.is_set()
    with lark_cli._LARK_LOGIN_RUNS_LOCK:
        run = lark_cli._LARK_LOGIN_RUNS.pop(("alice", generation))
    run.thread.join(5)
    assert run.outcome == {}
    second = lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    assert second.success == first.success
    assert len(spawned) == 1


@pytest.mark.parametrize("publication_fails", [False, True])
def test_supersession_receipt_survives_recovered_publication(monkeypatch, login_flow, publication_fails):
    generation, spawned = login_flow
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", None, generation=generation, device_code="code-A", wait_timeout_seconds=0)
    run = lark_cli._LARK_LOGIN_RUNS[("alice", generation)]
    injected = threading.Event()

    def fail_once(original):
        def publish(source, destination, *args, **kwargs):
            if publication_fails and Path(destination).name.startswith(".login-result-") and not injected.is_set():
                injected.set()
                raise OSError(errno.EIO, "synthetic one-shot publication failure")
            return original(source, destination, *args, **kwargs)

        return publish

    monkeypatch.setattr(os, "link", fail_once(os.link))
    monkeypatch.setattr(os, "replace", fail_once(os.replace))
    monkeypatch.setattr(lark_cli, "_run_lark_cli_json", lambda *_args, **_kwargs: {"verification_url": "https://example.com/verify", "device_code": "code-B"})
    lark_cli.start_lark_auth("alice", generation=generation)
    run.thread.join(5)
    assert not run.thread.is_alive()
    assert injected.is_set() is publication_fails
    assert isinstance(run.outcome, lark_cli.LarkFlowSupersededError)
    digest = lark_cli._lark_login_code_digest("code-A")
    payload = lark_cli._read_json_object_file(lark_cli._lark_login_result_path("alice", generation, digest))
    assert payload["kind"] == "superseded", "a recovered owner must adopt the fallback receipt"
    assert spawned[0].killed
