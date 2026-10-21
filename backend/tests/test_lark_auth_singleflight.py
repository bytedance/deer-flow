"""Single-flight device-login runs for Lark browser authorization.

Regression coverage for the web authorization polling race: the request wait
budget used to double as the ``lark-cli auth login --device-code`` subprocess
lifetime. A wait timeout killed the CLI mid-transaction — after the device
code had been redeemed at the IdP but before the credentials were persisted —
and the next poll with the same code then failed with ``device_code is
invalid``. The login process lifecycle is now owned by the flow generation,
never by a request wait budget: polls attach to one shared run, waits only
time out the *caller*, and superseding flows terminate the orphaned process.

All worker-lifecycle synchronization uses ``threading.Event``; no sleep-based
timing thresholds.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import queue as queue_module
import signal
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths
from deerflow.integrations import lark_cli

pytestmark = pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")


def _config(skills_root: Path):
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )


def _patch_paths(monkeypatch, base_dir: Path) -> None:
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=base_dir))


def _advance_lark_flow(user_id: str = "alice") -> str:
    with lark_cli._lark_credential_lock(user_id):
        return lark_cli._advance_lark_flow_generation_locked(user_id)


def _authenticated_status(_user_id, _config, **_kwargs):
    return lark_cli.LarkIntegrationStatus(
        installed=True,
        version="v1.0.65",
        manifest_version="v1.0.65",
        latest_available_version=None,
        runtime_version_mismatch=False,
        app_configured=True,
        app_id="cli_mock",
        app_brand="feishu",
        skills_expected=27,
        skills_installed=27,
        installed_skills=("lark-doc",),
        enabled_skills=("lark-doc",),
        install_path="/tmp/lark",
        cli=lark_cli.LarkCliProbe(available=True),
        auth=lark_cli.LarkAuthProbe(status="authenticated", user="Alice"),
    )


class _FakeLoginProcess:
    """Popen-shaped double for the single-flight login process seam.

    A blocking instance stays "running" until ``release``/``kill`` so tests can
    hold the login transaction open across multiple polls without sleeps.
    """

    pid = None  # Markers treat a missing CLI pid as owned by this process.

    def __init__(self, *, stdout: str = "{}", stderr: str = "", returncode: int = 0, blocking: bool = False) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode
        self._released = threading.Event()
        self.killed = False
        if not blocking:
            self._released.set()

    def communicate(self, timeout=None):
        # Generous ceiling so a stuck test fails instead of hanging the suite.
        if not self._released.wait(timeout=30):
            raise AssertionError("test forgot to release the fake login process")
        return self._stdout, self._stderr

    @property
    def returncode(self) -> int:
        return self._returncode

    def kill(self) -> None:
        self.killed = True
        self._stdout = ""
        self._stderr = ""
        self._returncode = -9
        self._released.set()

    def poll(self):
        return self._returncode if self._released.is_set() else None

    def release(self, *, stdout: str = "{}", stderr: str = "", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode
        self._released.set()


class _LoginProcessFactory:
    def __init__(self, **process_kwargs) -> None:
        self._process_kwargs = process_kwargs
        self.spawned: list[tuple[list[str], str, _FakeLoginProcess]] = []
        self.unblocked = threading.Event()

    def __call__(self, args: list[str], *, user_id: str) -> _FakeLoginProcess:
        process = _FakeLoginProcess(**self._process_kwargs)
        self.spawned.append((args, user_id, process))
        if not process.killed:
            self.unblocked.set()
        return process

    @property
    def last(self) -> _FakeLoginProcess:
        return self.spawned[-1][2]


@pytest.fixture(autouse=True)
def _clean_login_runs():
    lark_cli._clear_lark_login_runs_for_tests()
    yield
    lark_cli._clear_lark_login_runs_for_tests()


@pytest.fixture
def web_auth_setup(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path / "home")
    monkeypatch.setattr(lark_cli, "_require_lark_cli_path", lambda: "/usr/bin/lark-cli")
    monkeypatch.setattr(lark_cli, "get_lark_integration_status", _authenticated_status)
    return _config(tmp_path / "skills")


def test_wait_timeout_neither_kills_nor_respawns_the_login_process(monkeypatch, web_auth_setup) -> None:
    """The reported race: a wait timeout must not kill the in-flight login
    (consuming the device code without persisting credentials), and the next
    poll must attach to the same run instead of restarting the CLI."""
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    factory = _LoginProcessFactory(blocking=True)
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    generation = _advance_lark_flow()

    with pytest.raises(TimeoutError, match="Complete authorization in the browser"):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)

    assert len(factory.spawned) == 1
    process = factory.last
    assert process.killed is False

    # The retry after a 504 reuses the same device code; it must not respawn.
    with pytest.raises(TimeoutError, match="Complete authorization in the browser"):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 1
    assert process.killed is False

    # User approves in the browser: the very same run completes the login.
    process.release(stdout="{}", returncode=0)
    result = lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation)
    assert result.success is True
    assert result.status.auth.status == "authenticated"
    assert len(factory.spawned) == 1
    assert process.killed is False


def test_superseding_flow_terminates_the_orphaned_login(monkeypatch, web_auth_setup) -> None:
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    factory = _LoginProcessFactory(blocking=True)
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    stale_generation = _advance_lark_flow()

    waiter_errors: list[BaseException] = []
    waiter = threading.Thread(
        target=lambda: waiter_errors.append(_complete_or_error(web_auth_setup, stale_generation)),
        name="test-complete-waiter",
    )
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=stale_generation, wait_timeout_seconds=0)
    assert factory.unblocked.wait(timeout=5)
    waiter.start()

    current_generation = _advance_lark_flow()
    waiter.join(timeout=30)

    assert len(waiter_errors) == 1
    assert isinstance(waiter_errors[0], lark_cli.LarkFlowSupersededError)
    assert factory.last.killed is True

    with pytest.raises(lark_cli.LarkFlowSupersededError, match="superseded"):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=stale_generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 1

    # The current generation starts a fresh run bound to its own device code.
    pending = pytest.raises(TimeoutError)
    with pending:
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="next-device-code", generation=current_generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 2
    assert factory.spawned[-1][0][-3:-1] == ["--device-code", "next-device-code"]


def _complete_or_error(config, generation: str) -> BaseException | None:
    try:
        lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation)
    except BaseException as exc:  # noqa: BLE001 - asserted by the caller
        return exc
    return None


def test_failed_login_outcome_is_shared_by_all_polls(monkeypatch, web_auth_setup) -> None:
    factory = _LoginProcessFactory(
        stdout="",
        stderr='{"error":{"message":"authorization failed: The device_code is invalid."}}',
        returncode=3,
    )
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    generation = _advance_lark_flow()

    errors: list[ValueError] = []
    for _ in range(2):
        with pytest.raises(ValueError, match="device_code is invalid") as exc_info:
            lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation)
        errors.append(exc_info.value)
    assert len(factory.spawned) == 1
    # Same outcome, but never the same shared exception instance.
    assert errors[0] is not errors[1]
    assert errors[0].args == errors[1].args


def test_supersession_overwrites_a_published_outcome(monkeypatch, web_auth_setup) -> None:
    """Outcome publication is serialized per run: once supersession fires it
    wins deterministically, even over an already-published success."""
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    factory = _LoginProcessFactory(blocking=True)
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    generation = _advance_lark_flow()

    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)
    factory.last.release(stdout="{}", returncode=0)
    result = lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation)
    assert result.success is True

    run = lark_cli._LARK_LOGIN_RUNS[("alice", generation)]
    lark_cli._abandon_lark_login_runs("alice")
    assert isinstance(run.outcome, lark_cli.LarkFlowSupersededError)


def test_successful_login_is_idempotent_for_late_polls(monkeypatch, web_auth_setup) -> None:
    factory = _LoginProcessFactory()
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    generation = _advance_lark_flow()

    for _ in range(2):
        result = lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation)
        assert result.success is True
    assert len(factory.spawned) == 1
    assert factory.last.killed is False


def test_concurrent_polls_share_one_login_process(monkeypatch, web_auth_setup) -> None:
    factory = _LoginProcessFactory(blocking=True)
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    generation = _advance_lark_flow()

    barrier = threading.Barrier(3)
    outcomes: list[object] = []

    def _poll() -> None:
        barrier.wait(timeout=30)
        try:
            outcomes.append(lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation))
        except BaseException as exc:  # noqa: BLE001 - asserted below
            outcomes.append(exc)

    threads = [threading.Thread(target=_poll, name=f"test-poll-{index}") for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=30)
    assert factory.unblocked.wait(timeout=5)
    factory.last.release(stdout="{}", returncode=0)
    for thread in threads:
        thread.join(timeout=30)

    assert len(factory.spawned) == 1
    assert len(outcomes) == 2
    assert all(isinstance(outcome, lark_cli.LarkAuthCompleteResult) and outcome.success for outcome in outcomes)


def test_poll_with_mismatched_device_code_is_rejected(monkeypatch, web_auth_setup) -> None:
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    factory = _LoginProcessFactory(blocking=True)
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    generation = _advance_lark_flow()

    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)
    with pytest.raises(ValueError, match="does not match the in-flight"):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="other-device-code", generation=generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 1
    assert factory.last.killed is False


def test_start_lark_auth_reissue_replaces_the_inflight_run(monkeypatch, web_auth_setup) -> None:
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    factory = _LoginProcessFactory(blocking=True)
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    monkeypatch.setattr(
        lark_cli,
        "_run_lark_cli_json",
        lambda *_args, **_kwargs: {"verification_url": "https://example.com/verify", "device_code": "new-device-code"},
    )
    generation = _advance_lark_flow()

    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 1

    start = lark_cli.start_lark_auth("alice", generation=generation)
    assert start.device_code == "new-device-code"
    assert factory.last.killed is True

    # A delayed poll for the replaced code is refused before it can claim the
    # flow's login slot; polls for the newly issued code proceed normally.
    with pytest.raises(ValueError, match="no longer the current"):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 1

    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="new-device-code", generation=generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 2


def test_failed_reissue_mint_keeps_the_previous_code_attachable(monkeypatch, web_auth_setup) -> None:
    """A reissue whose mint fails must degrade to the base behavior: the
    previous device code stays attachable instead of being fenced forever."""
    monkeypatch.setattr(lark_cli, "LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS", 0)
    factory = _LoginProcessFactory(blocking=True)
    monkeypatch.setattr(lark_cli, "_spawn_lark_login_process", factory)
    monkeypatch.setattr(
        lark_cli,
        "_run_lark_cli_json",
        lambda *_args, **_kwargs: {"verification_url": "https://example.com/verify", "device_code": "device-code"},
    )
    generation = _advance_lark_flow()
    start = lark_cli.start_lark_auth("alice", generation=generation)
    assert start.device_code == "device-code"

    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 1

    def _failing_mint(*_args, **_kwargs):
        raise TimeoutError("mint timed out")

    monkeypatch.setattr(lark_cli, "_run_lark_cli_json", _failing_mint)
    with pytest.raises(TimeoutError, match="mint timed out"):
        lark_cli.start_lark_auth("alice", generation=generation)

    # The fence still points at the previous code: polls attach, never 400.
    assert json.loads(lark_cli._lark_flow_state_path("alice").read_text(encoding="utf-8")) == {
        "generation": generation,
        "device_code_digest": lark_cli._lark_login_code_digest("device-code"),
    }
    with pytest.raises(TimeoutError):
        lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation, wait_timeout_seconds=0)
    assert len(factory.spawned) == 1

    factory.last.release(stdout="{}", returncode=0)
    result = lark_cli.complete_lark_auth("alice", web_auth_setup, device_code="device-code", generation=generation)
    assert result.success is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group guard")
def test_terminate_pid_only_group_kills_a_session_leader() -> None:
    """A pid that is not its own group leader (recycled/foreign shape) must be
    left alone; only the login CLI's own-session group is killed."""
    child = subprocess.Popen(["sleep", "30"])  # plain child: shares our group, never a leader
    try:
        lark_cli._terminate_pid(child.pid)
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()

    leader = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        lark_cli._terminate_pid(leader.pid)
        deadline = time.monotonic() + 5
        while leader.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert leader.poll() == -signal.SIGKILL
    finally:
        leader.kill()
        leader.wait()


# --- Cross-worker coordination (GATEWAY_WORKERS > 1) ------------------------

_CROSS_WORKER_CLI = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "v1.0.65"
  exit 0
fi

if [ "$1" = "auth" ] && [ "$2" = "login" ]; then
  echo $$ >> "$LARK_TEST_INVOCATIONS"
  cat "$LARK_TEST_RELEASE_FIFO" > /dev/null
  echo "token" >> "$LARK_TEST_TOKEN_FILE"
  echo "{}"
  exit 0
fi

if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  echo '{"identities":{"user":{"userName":"Alice"}}}'
  exit 0
fi

if [ "$1" = "config" ]; then
  printf '{"apps":[{"appId":"new-app","appSecret":"new-secret"}]}' > "$LARKSUITE_CLI_CONFIG_DIR/config.json"
  echo "{}"
  exit 0
fi

echo "{}"
exit 0
"""


def _cross_worker_config(base_dir: Path):
    skills_root = base_dir / "skills"
    (skills_root / "public").mkdir(parents=True, exist_ok=True)
    (skills_root / "custom").mkdir(exist_ok=True)
    return _config(skills_root)


def _await_lines(path: str, count: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with open(path, encoding="utf-8") as handle:
            if len(handle.read().splitlines()) >= count:
                return
        time.sleep(0.05)
    raise AssertionError(f"expected {count} invocation line(s) in {path}")


def _login_worker_a(base_dir: str, cli_dir: str, env: dict[str, str], invocations: str, out, cmd) -> None:
    """Owner worker: advances the flow, spawns the login, then completes it."""
    try:
        paths_module._paths = Paths(base_dir=Path(base_dir))
        os.environ.update(env)
        os.environ["PATH"] = f"{cli_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        lark_cli.LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS = 0
        config = _cross_worker_config(Path(base_dir))
        with lark_cli._lark_credential_lock("alice"):
            generation = lark_cli._advance_lark_flow_generation_locked("alice")
        out.put(("generation", generation))
        with pytest.raises(TimeoutError):
            lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation, wait_timeout_seconds=0)
        _await_lines(invocations, 1)  # The stub CLI has actually started.
        marker_path = lark_cli._lark_login_marker_path("alice", generation, lark_cli._lark_login_code_digest("device-code"))
        marker = lark_cli._read_json_object_file(marker_path)
        out.put(("spawned", marker["cli_pid"], str(marker_path)))
        # Block until the login ends (B's switch supersedes it).
        try:
            lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation, wait_timeout_seconds=45)
            out.put(("a_done", "unexpected-success"))
        except BaseException as exc:
            out.put(("a_done", type(exc).__name__))
        if cmd.get(timeout=30) != "scenario2":
            return
        with lark_cli._lark_credential_lock("alice"):
            second = lark_cli._advance_lark_flow_generation_locked("alice")
        out.put(("generation2", second))
        with pytest.raises(TimeoutError):
            lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=second, wait_timeout_seconds=0)
        out.put(("spawned2", lark_cli._read_json_object_file(lark_cli._lark_login_marker_path("alice", second, lark_cli._lark_login_code_digest("device-code")))["cli_pid"]))
        result = lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=second, wait_timeout_seconds=45)
        out.put(("a_done2", result.success))
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(("a_error", f"{type(exc).__name__}: {exc}"))


def _login_worker_b(base_dir: str, cli_dir: str, env: dict[str, str], invocations: str, out, cmd) -> None:
    """Non-owner worker: attaches to A's run, then switches the app (P1 fence)."""
    try:
        paths_module._paths = Paths(base_dir=Path(base_dir))
        os.environ.update(env)
        os.environ["PATH"] = f"{cli_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        lark_cli.LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS = 0
        config = _cross_worker_config(Path(base_dir))
        generation = cmd.get(timeout=30)
        # Retry attachment: time out as a foreign waiter without spawning a second CLI.
        with pytest.raises(TimeoutError):
            lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation, wait_timeout_seconds=0)
        with open(invocations, encoding="utf-8") as handle:
            out.put(("attached", len(handle.read().splitlines())))
        # Switching the app from the non-owner must fence A's in-flight login.
        lark_cli.set_lark_app_credentials("alice", config, app_id="new-app", app_secret="new-secret")
        out.put(("switched", None))
        generation2 = cmd.get(timeout=30)
        # Cross-worker success attachment: B completes through A's published result.
        result = lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation2, wait_timeout_seconds=45)
        out.put(("b_done2", result.success))
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(("b_error", f"{type(exc).__name__}: {exc}"))


def _release_fifo(fifo: Path, timeout: float = 10.0) -> None:
    """Write the release byte once the stub CLI is blocked reading the fifo."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise AssertionError("no reader on the release fifo")
            time.sleep(0.05)
    with os.fdopen(fd, "w") as handle:
        handle.write("go\n")


def _take(out, timeout: float = 30.0):
    try:
        return out.get(timeout=timeout)
    except queue_module.Empty as exc:
        raise AssertionError("timed out waiting for a worker message") from exc


def _await_pid_death(pid: int, timeout: float = 10.0) -> None:
    """A SIGKILLed CLI still registers as alive until its owner worker reaps it."""
    deadline = time.monotonic() + timeout
    while lark_cli._pid_alive(pid):
        if time.monotonic() >= deadline:
            raise AssertionError(f"pid {pid} is still alive")
        time.sleep(0.05)


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods() or lark_cli.fcntl is None,
    reason="requires POSIX fork and fcntl",
)
def test_login_run_coordinates_across_gateway_workers(tmp_path) -> None:
    """Two workers sharing one credential root share one login run, and a
    switch from the non-owner fences the owner worker's CLI (P1 regression)."""
    base_dir = tmp_path / "home"
    cli_dir = tmp_path / "cli bin"
    cli_dir.mkdir(parents=True)
    cli_path = cli_dir / "lark-cli"
    cli_path.write_text(_CROSS_WORKER_CLI, encoding="utf-8")
    cli_path.chmod(0o755)
    fifo = tmp_path / "release.fifo"
    os.mkfifo(fifo)
    invocations = tmp_path / "invocations.txt"
    invocations.touch()
    token_file = tmp_path / "token-write.txt"
    env = {
        "LARK_TEST_INVOCATIONS": str(invocations),
        "LARK_TEST_RELEASE_FIFO": str(fifo),
        "LARK_TEST_TOKEN_FILE": str(token_file),
    }

    context = multiprocessing.get_context("fork")
    a_out, a_cmd = context.Queue(), context.Queue()
    b_out, b_cmd = context.Queue(), context.Queue()
    worker_a = context.Process(target=_login_worker_a, args=(str(base_dir), str(cli_dir), env, str(invocations), a_out, a_cmd))
    worker_b = context.Process(target=_login_worker_b, args=(str(base_dir), str(cli_dir), env, str(invocations), b_out, b_cmd))
    worker_a.start()
    try:
        tag, generation = _take(a_out)
        assert tag == "generation"
        tag, cli_pid, marker_path = _take(a_out)
        assert tag == "spawned"
        assert lark_cli._pid_alive(cli_pid)

        worker_b.start()
        try:
            b_cmd.put(generation)
            assert _take(b_out) == ("attached", 1)  # foreign attach, no second CLI
            assert _take(b_out)[0] == "switched"

            # The non-owner switch killed A's CLI and fenced its credential writes.
            _await_pid_death(cli_pid)
            assert not Path(marker_path).exists()
            assert not token_file.exists()
            assert _take(a_out) == ("a_done", "LarkFlowSupersededError")

            # Cross-worker success attachment: A owns run 2, B completes via the result file.
            a_cmd.put("scenario2")
            tag, generation2 = _take(a_out)
            assert tag == "generation2"
            assert _take(a_out)[0] == "spawned2"
            b_cmd.put(generation2)
            _release_fifo(fifo)
            assert _take(a_out) == ("a_done2", True)
            assert _take(b_out) == ("b_done2", True)
            assert token_file.read_text(encoding="utf-8").splitlines() == ["token"]
            with open(invocations, encoding="utf-8") as handle:
                assert len(handle.read().splitlines()) == 2
        finally:
            worker_b.join(timeout=30)
            if worker_b.is_alive():
                worker_b.terminate()
    finally:
        worker_a.join(timeout=30)
        if worker_a.is_alive():
            worker_a.terminate()


_CROSS_WORKER_CLI_IMMEDIATE = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "v1.0.65"
  exit 0
fi

if [ "$1" = "auth" ] && [ "$2" = "login" ]; then
  echo $$ >> "$LARK_TEST_INVOCATIONS"
  echo "{}"
  exit 0
fi

if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  echo '{"identities":{"user":{"userName":"Alice"}}}'
  exit 0
fi

if [ "$1" = "config" ]; then
  printf '{"apps":[{"appId":"new-app","appSecret":"new-secret"}]}' > "$LARKSUITE_CLI_CONFIG_DIR/config.json"
  echo "{}"
  exit 0
fi

echo "{}"
exit 0
"""


def _write_cross_worker_cli(directory: Path, *, gated: bool) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    cli_path = directory / "lark-cli"
    cli_path.write_text(_CROSS_WORKER_CLI if gated else _CROSS_WORKER_CLI_IMMEDIATE, encoding="utf-8")
    cli_path.chmod(0o755)
    return cli_path


def _await_file(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _count_lines(path: str, grace_seconds: float = 2.0) -> int:
    """Line count with a short grace window so a just-forked CLI can register."""
    deadline = time.monotonic() + grace_seconds
    count = 0
    while True:
        with open(path, encoding="utf-8") as handle:
            count = max(count, len(handle.read().splitlines()))
        if time.monotonic() >= deadline:
            return count
        time.sleep(0.05)


def _window_worker_a(base_dir: str, cli_dir: str, env: dict[str, str], invocations: str, pause_flag: str, release_flag: str, out, login_age_seconds: float = 0) -> None:
    """Owner paused between CLI exit and result publication (the P1 window)."""
    try:
        paths_module._paths = Paths(base_dir=Path(base_dir))
        os.environ.update(env)
        os.environ["PATH"] = f"{cli_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        lark_cli.LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS = 0
        # Advance only the peer's view of the attempt age; no wall-clock sleep.
        lark_cli.time = SimpleNamespace(time=lambda: time.time() - login_age_seconds, monotonic=time.monotonic, sleep=time.sleep)
        config = _cross_worker_config(Path(base_dir))
        with lark_cli._lark_credential_lock("alice"):
            generation = lark_cli._advance_lark_flow_generation_locked("alice")
        out.put(("generation", generation))

        real_ensure = lark_cli.ensure_lark_cli_credential_tree

        def _paused_ensure(*args, **kwargs):
            # Only the login worker thread pauses — the spawn path itself also
            # calls ensure (env overlay), and must not be blocked.
            if threading.current_thread().name.startswith("lark-login-"):
                Path(pause_flag).touch()
                _await_file(Path(release_flag), timeout=30)
            return real_ensure(*args, **kwargs)

        lark_cli.ensure_lark_cli_credential_tree = _paused_ensure
        with pytest.raises(TimeoutError):
            lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation, wait_timeout_seconds=0)
        _await_lines(invocations, 1)
        marker_path = lark_cli._lark_login_marker_path("alice", generation, lark_cli._lark_login_code_digest("device-code"))
        marker = lark_cli._read_json_object_file(marker_path)
        out.put(("spawned", marker["cli_pid"], str(marker_path)))
        result = lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation, wait_timeout_seconds=45)
        out.put(("a_done", result.success))
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(("a_error", f"{type(exc).__name__}: {exc}"))


def _window_worker_b(base_dir: str, cli_dir: str, invocations: str, out, cmd) -> None:
    """Foreign poller landing in the owner's exit-to-publication window."""
    try:
        paths_module._paths = Paths(base_dir=Path(base_dir))
        os.environ["PATH"] = f"{cli_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        os.environ["LARK_TEST_INVOCATIONS"] = invocations
        lark_cli.LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS = 0
        config = _cross_worker_config(Path(base_dir))
        generation = cmd.get(timeout=30)
        with pytest.raises(TimeoutError):
            lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation, wait_timeout_seconds=0)
        out.put(("b_first", _count_lines(invocations)))
        cmd.get(timeout=30)
        result = lark_cli.complete_lark_auth("alice", config, device_code="device-code", generation=generation, wait_timeout_seconds=45)
        out.put(("b_done", result.success))
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(("b_error", f"{type(exc).__name__}: {exc}"))


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods() or lark_cli.fcntl is None,
    reason="requires POSIX fork and fcntl",
)
@pytest.mark.parametrize("login_age_seconds", [0, 30])
def test_login_marker_ownership_covers_exit_to_publication_window(tmp_path, login_age_seconds) -> None:
    """CLI exit alone must not end ownership: while the owner is still alive
    and the result unpublished, a foreign poll must not spawn a second login
    for the same device code (P1 exit-to-publication regression)."""
    base_dir = tmp_path / "home"
    cli_dir = tmp_path / "cli bin"
    _write_cross_worker_cli(cli_dir, gated=False)
    invocations = tmp_path / "invocations.txt"
    invocations.touch()
    pause_flag = tmp_path / "paused"
    release_flag = tmp_path / "release"
    env = {"LARK_TEST_INVOCATIONS": str(invocations)}
    # Seed the app config so the success path reports authenticated.
    config_dir = base_dir / "users" / "alice" / "integrations" / "lark-cli" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"apps":[{"appId":"test-app","appSecret":"test-secret"}]}', encoding="utf-8")

    context = multiprocessing.get_context("fork")
    a_out, b_out, b_cmd = context.Queue(), context.Queue(), context.Queue()
    worker_a = context.Process(target=_window_worker_a, args=(str(base_dir), str(cli_dir), env, str(invocations), str(pause_flag), str(release_flag), a_out, login_age_seconds))
    worker_b = context.Process(target=_window_worker_b, args=(str(base_dir), str(cli_dir), str(invocations), b_out, b_cmd))
    worker_a.start()
    try:
        tag, generation = _take(a_out)
        assert tag == "generation"
        tag, cli_pid, marker_path = _take(a_out)
        assert tag == "spawned"
        # The CLI has exited; the owner is alive and paused before publishing.
        _await_pid_death(cli_pid)
        _await_file(pause_flag)
        assert Path(marker_path).exists()
        marker = json.loads(Path(marker_path).read_text(encoding="utf-8"))
        assert time.time() - marker["created_at"] >= login_age_seconds - 1

        worker_b.start()
        try:
            b_cmd.put(generation)
            # Foreign waiter recognizes the in-flight ownership: no second CLI.
            assert _take(b_out) == ("b_first", 1)
            release_flag.touch()
            b_cmd.put("finish")
            assert _take(a_out) == ("a_done", True)
            assert _take(b_out) == ("b_done", True)
            with open(invocations, encoding="utf-8") as handle:
                assert len(handle.read().splitlines()) == 1
        finally:
            worker_b.join(timeout=30)
            if worker_b.is_alive():
                worker_b.terminate()
    finally:
        release_flag.touch()
        worker_a.join(timeout=30)
        if worker_a.is_alive():
            worker_a.terminate()


def _reissue_owner_worker(base_dir: str, cli_dir: str, env: dict[str, str], invocations: str, out, cmd) -> None:
    """Original owner worker: its stale registry entry must not fence the replacement code."""
    try:
        paths_module._paths = Paths(base_dir=Path(base_dir))
        os.environ.update(env)
        os.environ["PATH"] = f"{cli_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        lark_cli.LARK_AUTH_COMPLETE_MIN_WAIT_SECONDS = 0
        config = _cross_worker_config(Path(base_dir))
        with lark_cli._lark_credential_lock("alice"):
            generation = lark_cli._advance_lark_flow_generation_locked("alice")
        out.put(("generation", generation))
        with pytest.raises(TimeoutError):
            lark_cli.complete_lark_auth("alice", config, device_code="code-A", generation=generation, wait_timeout_seconds=0)
        _await_lines(invocations, 1)
        out.put(("spawned", None))
        try:
            lark_cli.complete_lark_auth("alice", config, device_code="code-A", generation=generation, wait_timeout_seconds=45)
            out.put(("a_done", "unexpected-success"))
        except BaseException as exc:
            out.put(("a_done", type(exc).__name__))
        # The replacement poll now lands on the original owner (stale local registry).
        if cmd.get(timeout=30) != "try-code-B":
            return
        try:
            lark_cli.complete_lark_auth("alice", config, device_code="code-B", generation=generation, wait_timeout_seconds=0)
            out.put(("a_code_b", "completed"))
        except TimeoutError:
            out.put(("a_code_b", "pending"))
        except BaseException as exc:
            out.put(("a_code_b", type(exc).__name__))
        # The replaced code is fenced by the shared state.
        try:
            lark_cli.complete_lark_auth("alice", config, device_code="code-A", generation=generation, wait_timeout_seconds=0)
            out.put(("a_code_a", "unexpected-attach"))
        except BaseException as exc:
            out.put(("a_code_a", type(exc).__name__))
        # Keep code B alive until the parent has observed its invocation.
        cmd.get(timeout=30)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(("a_error", f"{type(exc).__name__}: {exc}"))
    finally:
        # Forked workers do not run the parent's pytest fixture teardown.
        with lark_cli._LARK_LOGIN_RUNS_LOCK:
            runs = list(lark_cli._LARK_LOGIN_RUNS.values())
        for run in runs:
            if run.process is not None:
                lark_cli._terminate_pid(run.process.pid)
        lark_cli._clear_lark_login_runs_for_tests()


def _reissue_issuer_worker(base_dir: str, cli_dir: str, env: dict[str, str], out, cmd) -> None:
    """Reissue worker: mints code B for the same generation from another worker."""
    try:
        paths_module._paths = Paths(base_dir=Path(base_dir))
        os.environ.update(env)
        os.environ["PATH"] = f"{cli_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        generation = cmd.get(timeout=30)
        lark_cli._run_lark_cli_json = lambda *_args, **_kwargs: {"verification_url": "https://example.com/verify", "device_code": "code-B"}
        result = lark_cli.start_lark_auth("alice", generation=generation)
        out.put(("reissued", result.device_code))
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(("b_error", f"{type(exc).__name__}: {exc}"))


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods() or lark_cli.fcntl is None,
    reason="requires POSIX fork and fcntl",
)
def test_reissue_poll_landing_on_original_owner_is_not_fenced(tmp_path) -> None:
    """A reissue served by worker B must evict the stale registry entry on the
    original owner A: the replacement code's poll landing on A proceeds instead
    of being rejected by the cached code (P2 stale-registry regression)."""
    base_dir = tmp_path / "home"
    cli_dir = tmp_path / "cli bin"
    _write_cross_worker_cli(cli_dir, gated=True)
    fifo = tmp_path / "release.fifo"
    os.mkfifo(fifo)
    invocations = tmp_path / "invocations.txt"
    invocations.touch()
    env = {
        "LARK_TEST_INVOCATIONS": str(invocations),
        "LARK_TEST_RELEASE_FIFO": str(fifo),
        "LARK_TEST_TOKEN_FILE": str(tmp_path / "token-write.txt"),
    }

    context = multiprocessing.get_context("fork")
    a_out, a_cmd = context.Queue(), context.Queue()
    b_out, b_cmd = context.Queue(), context.Queue()
    worker_a = context.Process(target=_reissue_owner_worker, args=(str(base_dir), str(cli_dir), env, str(invocations), a_out, a_cmd))
    worker_b = context.Process(target=_reissue_issuer_worker, args=(str(base_dir), str(cli_dir), env, b_out, b_cmd))
    worker_a.start()
    try:
        tag, generation = _take(a_out)
        assert tag == "generation"
        assert _take(a_out)[0] == "spawned"

        worker_b.start()
        try:
            b_cmd.put(generation)
            assert _take(b_out) == ("reissued", "code-B")
            # B's reissue superseded A's in-flight login for code A.
            assert _take(a_out) == ("a_done", "LarkFlowSupersededError")

            # The replacement poll landing on the original owner proceeds.
            a_cmd.put("try-code-B")
            assert _take(a_out) == ("a_code_b", "pending")
            assert _count_lines(str(invocations)) == 2
            # The replaced code is fenced by the shared state, not the stale registry.
            assert _take(a_out) == ("a_code_a", "ValueError")
        finally:
            worker_b.join(timeout=30)
            if worker_b.is_alive():
                worker_b.terminate()
    finally:
        a_cmd.put("finish")
        worker_a.join(timeout=30)
        if worker_a.is_alive():
            worker_a.terminate()


# ---------------------------------------------------------------------------
# Publication-race regressions (willem-bd 2026-10-21 round)
# ---------------------------------------------------------------------------


def test_write_result_once_does_not_bypass_hardening_failure(monkeypatch, tmp_path) -> None:
    """A rejected credential boundary must not become a permissive write."""
    _patch_paths(monkeypatch, tmp_path / "home")
    # ensure_lark_cli_credential_tree is mocked below, so create the root it
    # would have created; tempfile.mkstemp(dir=...) requires it to exist.
    lark_cli._lark_cli_credential_root("alice").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        lark_cli,
        "ensure_lark_cli_credential_tree",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("simulated fs hiccup")),
    )
    user_id = "alice"
    generation = "gen"
    digest = lark_cli._lark_login_code_digest("code-A")
    with pytest.raises(OSError, match="simulated fs hiccup"):
        lark_cli._write_lark_login_result_once(user_id, generation, digest, {"ok": False, "kind": "superseded", "error": "sweep"})
    assert not lark_cli._lark_login_result_path(user_id, generation, digest).exists()


def test_abandoned_marker_requires_a_new_device_code(monkeypatch, tmp_path) -> None:
    """An uncertain redeemed code is rejected after the publication grace."""
    base_dir = tmp_path / "home"
    user_id = "alice"
    generation = "gen"
    digest = lark_cli._lark_login_code_digest("code-A")
    now = time.time()
    _patch_paths(monkeypatch, base_dir)
    lark_cli.ensure_lark_cli_credential_tree(user_id)
    marker_path = lark_cli._lark_login_marker_path(user_id, generation, digest)
    marker_path.write_text(
        json.dumps({"generation": generation, "device_code_digest": digest, "cli_pid": None, "owner_pid": os.getpid(), "cli_exit_observed_at": now - 60.0, "created_at": now - 1.0}),
        encoding="utf-8",
    )
    with lark_cli._lark_credential_lock(user_id):
        with pytest.raises(ValueError, match="Restart the authorization flow"):
            lark_cli._read_live_lark_login_marker_locked(user_id, generation, "code-A")
    assert marker_path.exists(), "an uncertain code must not become a free login slot"
