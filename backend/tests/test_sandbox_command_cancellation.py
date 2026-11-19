from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from deerflow.sandbox.command_scope import command_owner
from deerflow.sandbox.lease import run_sync_lifecycle_operation
from deerflow.sandbox.local.local_sandbox import LocalSandbox


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False).stdout.strip()
        return bool(state) and not state.startswith("Z")
    except ProcessLookupError:
        return False


async def _pid(path: Path) -> int:
    for _ in range(200):
        if path.exists():
            return int(path.read_text())
        await asyncio.sleep(0.01)
    raise AssertionError("child did not start")


def _command(path: Path, *, background: bool) -> str:
    code = f"import os,time;from pathlib import Path;Path({str(path)!r}).write_text(str(os.getpid()));time.sleep(30)"
    command = f"{shlex.quote(sys.executable)} -u -c {shlex.quote(code)}"
    return f"{command} > /dev/null 2>&1 &" if background else command


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
@pytest.mark.asyncio
async def test_cancel_scope_stops_foreground_and_nohup_without_stopping_previous_preview(tmp_path):
    sandbox = LocalSandbox("owned-commands")
    foreground = None
    preview_pid = None
    preview_group = None
    try:
        with command_owner(sandbox, "previous-run"):
            sandbox.execute_command(_command(tmp_path / "preview.pid", background=True))
        preview_pid = await _pid(tmp_path / "preview.pid")
        preview_group = os.getpgid(preview_pid)
        sandbox.release_command_scope("previous-run")
        assert _alive(preview_pid), "ordinary completion must retain preview services"

        with command_owner(sandbox, "current-run"):
            sandbox.execute_command("nohup " + _command(tmp_path / "background.pid", background=True))
        background_pid = await _pid(tmp_path / "background.pid")

        async def execute_foreground():
            with command_owner(sandbox, "current-run"):
                return await run_sync_lifecycle_operation(
                    sandbox.execute_command,
                    _command(tmp_path / "foreground.pid", background=False),
                    _on_cancel=lambda: sandbox.request_command_cancel("current-run"),
                )

        foreground = asyncio.create_task(execute_foreground())
        foreground_pid = await _pid(tmp_path / "foreground.pid")
        foreground.cancel()
        foreground.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(foreground, 2)
        await asyncio.to_thread(sandbox.cancel_command_scope, "current-run")
        for _ in range(100):
            if not _alive(foreground_pid) and not _alive(background_pid):
                break
            await asyncio.sleep(0.01)
        assert not _alive(foreground_pid)
        assert not _alive(background_pid)
        assert _alive(preview_pid)

        sandbox.release_command_scope("current-run")
        with command_owner(sandbox, "current-run"):
            assert sandbox.execute_command("printf resumed") == "resumed"
        assert _alive(preview_pid)
    finally:
        if foreground is not None and not foreground.done():
            foreground.cancel()
            await asyncio.gather(foreground, return_exceptions=True)
        sandbox.cancel_command_scope("current-run")
        if preview_group is not None:
            try:
                os.killpg(preview_group, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.asyncio
async def test_cancellation_signal_runs_before_worker_drain_and_survives_repeated_cancel():
    started = threading.Event()
    stop = threading.Event()
    finished = threading.Event()

    def work(**_):
        started.set()
        stop.wait(2)
        finished.set()

    task = asyncio.create_task(run_sync_lifecycle_operation(work, _on_cancel=stop.set))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stop.is_set(), "cancel must be delivered before waiting for the blocking operation"
        assert finished.is_set(), "the worker must still drain before cancellation escapes"
    finally:
        stop.set()
        await asyncio.gather(task, return_exceptions=True)


class _Shell:
    def __init__(self):
        self.command = None
        self.killed = []
        self.calls = 0
        self.cancel = None
        self.controls = []

    def exec_command(self, **kwargs):
        from types import SimpleNamespace as N

        if kwargs["command"].startswith("python3 -c "):
            self.controls.append(kwargs["id"])
            return N(data=N(session_id=kwargs["id"], status="running"))
        self.calls += 1
        self.command = kwargs["command"]
        assert kwargs.get("async_mode") is True
        if self.cancel:
            self.cancel()
        return N(data=N(session_id="returned-session", status="running"))

    def wait_for_process(self, **kwargs):
        from types import SimpleNamespace as N

        return N(data=N(status="completed"))

    def create_session(self, **kwargs):
        pass

    def cleanup_session(self, *args, **kwargs):
        pass

    def view(self, **kwargs):
        from types import SimpleNamespace as N

        if kwargs["id"] in self.controls:
            return N(data=N(output='{"remaining":0}', exit_code=0, status="completed"))
        return N(data=N(status="completed", exit_code=7, console=[N(command="previous command", output="OLD_OUTPUT"), N(command=self.command, output="NEW_OUTPUT")]))

    def kill_process(self, **kwargs):
        from types import SimpleNamespace as N

        self.killed.append(kwargs["id"])
        return N(success=True)


def _aio(monkeypatch):
    from types import SimpleNamespace as N

    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    shell = _Shell()
    monkeypatch.setattr("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient", lambda **_: N(shell=shell))
    return AioSandbox("aio", "http://127.0.0.1:9", home_dir="/tmp"), shell


def test_aio_owned_command_keeps_only_its_output_and_exit_code(monkeypatch):
    sandbox, shell = _aio(monkeypatch)
    with command_owner(sandbox, "run"):
        result = sandbox.execute_command("same command")
    assert "NEW_OUTPUT" in result
    assert "OLD_OUTPUT" not in result
    assert "Exit Code: 7" in result
    assert shell.calls == 1


def test_aio_cancel_uses_separate_control_without_replaying_or_killing_shared_shell(monkeypatch):
    sandbox, shell = _aio(monkeypatch)
    shell.cancel = lambda: sandbox.request_command_cancel("run")
    with command_owner(sandbox, "run"):
        result = sandbox.execute_command("long command")
    assert "cancelled" in result
    assert shell.killed == []
    assert len(shell.controls) == 1
    assert shell.calls == 1
    assert not sandbox.requires_container_recycle


@pytest.mark.asyncio
async def test_cancelled_aio_waiter_never_starts_or_interrupts_another_scope(monkeypatch):
    sandbox, shell = _aio(monkeypatch)
    sandbox._lock.acquire()
    try:

        async def waiter():
            with command_owner(sandbox, "queued-run"):
                return await run_sync_lifecycle_operation(sandbox.execute_command, "queued", _on_cancel=lambda: sandbox.request_command_cancel("queued-run"))

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert shell.calls == 0
        assert shell.killed == []
    finally:
        sandbox._lock.release()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["interrupt", "failure", "loop_capped"])
async def test_native_bash_to_worker_stops_owned_processes_before_release(monkeypatch, tmp_path, outcome):
    from types import SimpleNamespace as N
    from unittest.mock import AsyncMock, MagicMock

    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, run_agent
    from deerflow.sandbox.lease import get_sandbox_lease_manager
    from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider
    from deerflow.sandbox.tools import bash_tool

    sandbox = LocalSandbox("local:worker-cancel")
    provider = MagicMock()
    provider.get.return_value = sandbox
    provider.get_scoped.return_value = sandbox
    provider.acquire.return_value = sandbox.id
    provider.acquire_async = AsyncMock(return_value=sandbox.id)
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    run_manager = RunManager()
    record = await run_manager.create("native-bash-cancellation")
    background = tmp_path / "background.pid"
    foreground = tmp_path / "foreground.pid"
    release_seen = []

    def release(_sandbox_id):
        release_seen.append(True)
        assert not _alive(int(background.read_text()))
        if foreground.exists():
            assert not _alive(int(foreground.read_text()))

    provider.release.side_effect = release

    class Agent:
        async def astream(self, graph_input, config, **kwargs):
            context = config["configurable"]["__pregel_runtime"].context
            state = {"sandbox": {"sandbox_id": sandbox.id}, "thread_data": {key: str(tmp_path) for key in ("workspace_path", "outputs_path", "uploads_path")}}
            runtime = N(context=context, state=state, config=config)
            command = "nohup " + _command(background, background=True).replace(shlex.quote(sys.executable), "python3").replace(str(tmp_path), "/mnt/user-data/workspace")
            result = await bash_tool.coroutine(runtime=runtime, command=command)
            assert not result.startswith("Error:"), result
            await _pid(background)
            if outcome == "interrupt":
                command = _command(foreground, background=False).replace(shlex.quote(sys.executable), "python3").replace(str(tmp_path), "/mnt/user-data/workspace")
                await bash_tool.coroutine(runtime=runtime, command=command)
            elif outcome == "failure":
                raise RuntimeError("scripted model failure after starting a process")
            else:
                context["stop_reason"] = outcome
            yield {"messages": []}

    set_sandbox_provider(provider)
    task = asyncio.create_task(run_agent(N(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock()), run_manager, record, ctx=RunContext(checkpointer=None), agent_factory=lambda **_: Agent(), graph_input={}, config={}))
    record.task = task
    try:
        await _pid(background)
        if outcome == "interrupt":
            await _pid(foreground)
            await run_manager.cancel(record.run_id)
        await asyncio.wait_for(task, 5)
        assert release_seen == [True]
        assert record.status.value == ("interrupted" if outcome == "interrupt" else "error" if outcome == "failure" else "success")
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for path in (background, foreground):
            if path.exists() and _alive(int(path.read_text())):
                os.killpg(os.getpgid(int(path.read_text())), signal.SIGKILL)
        get_sandbox_lease_manager(provider).close()
        reset_sandbox_provider()


def test_aio_failed_cleanup_never_claims_clean_or_allows_warm_reuse(monkeypatch):
    from types import SimpleNamespace as N

    sandbox, shell = _aio(monkeypatch)
    with command_owner(sandbox, "run"):
        assert "NEW_OUTPUT" in sandbox.execute_command("echo done")
    monkeypatch.setattr(sandbox, "_create_shell_session", lambda _: "control")
    monkeypatch.setattr(sandbox, "_cleanup_session_best_effort", lambda *_, **__: None)
    monkeypatch.setattr(shell, "exec_command", lambda **_: N(data=N(session_id="control", status="running")))
    monkeypatch.setattr(shell, "view", lambda **_: N(data=N(output='{"remaining":1}', exit_code=0, status="completed")))
    with pytest.raises(RuntimeError, match="did not stop"):
        sandbox.cancel_command_scope("run")
    assert sandbox.requires_container_recycle


@pytest.mark.parametrize("cancel", [False, True])
def test_aio_env_command_keeps_output_exit_and_cleans_its_session(monkeypatch, cancel):
    from types import SimpleNamespace as N

    sandbox, shell = _aio(monkeypatch)
    closed = []

    class Bash:
        calls = 0

        def create_session(self, **kwargs):
            pass

        def exec(self, **kwargs):
            assert kwargs["async_mode"]
            assert kwargs["env"] == {"FAKE_KEY": "test-only"}
            self.calls += 1
            if cancel:
                sandbox.request_command_cancel("run")
            return N(data=N(command_id="actual-command"))

        def output(self, **kwargs):
            assert kwargs["command_id"] == "actual-command"
            return N(data=N(stdout="中文 output", stderr="diagnostic", offset=12, stderr_offset=10, command=N(status="completed", exit_code=7)))

        def close_session(self, session_id, **kwargs):
            closed.append(session_id)

    bash = Bash()
    sandbox._client.bash = bash
    with command_owner(sandbox, "run"):
        result = sandbox.execute_command("echo result", env={"FAKE_KEY": "test-only"})
    assert bash.calls == 1
    assert len(closed) == 1
    if cancel:
        assert "cancelled" in result
        assert len(shell.controls) == 1
    else:
        assert "中文 output" in result and "diagnostic" in result and "Exit Code: 7" in result
        assert shell.controls == []
    assert not sandbox.requires_container_recycle


def test_aio_cleanup_does_not_report_success_without_pidfd_support():
    from deerflow.community.aio_sandbox.command_cleanup import cleanup_command

    command = shlex.split(cleanup_command("a" * 32))
    # Run the actual controller with an unsupported-kernel response; no real
    # process is inspected or signalled on any platform.
    bootstrap = "import json,os,select,signal,sys,time,errno; os.listdir=lambda _:['123']; os.pidfd_open=lambda _:(_ for _ in ()).throw(OSError(errno.ENOSYS,'pidfd unavailable')); script=sys.argv.pop(1); exec(script)"
    result = subprocess.run([sys.executable, "-c", bootstrap, command[2], command[3]], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2)
    assert result.returncode != 0
    assert "pidfd unavailable" in result.stderr
    assert '"remaining": 0' not in result.stdout


@pytest.mark.parametrize("case", ["missing-command", "missing-stdout-cursor", "missing-stderr-cursor", "completed-without-cursors", "empty-poll"])
def test_aio_owned_bash_handles_optional_output_fields_without_unsafe_reuse(monkeypatch, case):
    from types import SimpleNamespace as N
    from unittest.mock import MagicMock

    from agent_sandbox.types.bash_command_info import BashCommandInfo
    from agent_sandbox.types.bash_output_result import BashOutputResult

    sandbox, _ = _aio(monkeypatch)
    bash = MagicMock()
    bash.exec.return_value = N(data=N(command_id="owned-command"))
    completed = {"stdout": "done", "stderr": "diagnostic", "status": "completed"}
    frames = {
        "missing-command": [{"stdout": "partial", "command_missing": True}],
        "missing-stdout-cursor": [{"stdout": "partial", "stderr_offset": 0}],
        "missing-stderr-cursor": [{"stderr": "partial", "offset": 0}],
        "completed-without-cursors": [completed],
        "empty-poll": [{"stdout": "one", "stderr": "two", "offset": 3, "stderr_offset": 3}, {}, completed],
    }[case]
    # A second response makes an erroneous continuation deterministic instead
    # of leaving this regression in a polling loop until its timeout.
    frames = [*frames, completed]
    observed = []

    def output(**kwargs):
        observed.append(kwargs)
        frame = dict(frames[len(observed) - 1])
        missing = frame.pop("command_missing", False)
        status = frame.pop("status", "running")
        command = None if missing else BashCommandInfo(command_id="owned-command", command="echo result", status=status, exit_code=7 if status == "completed" else None)
        return N(data=BashOutputResult(session_id=kwargs["session_id"], command=command, **frame))

    bash.output.side_effect = output
    sandbox._client.bash = bash
    with command_owner(sandbox, "run"):
        result = sandbox.execute_command("echo result", env={"FAKE_KEY": "test-only"})

    bash.exec.assert_called_once()
    bash.close_session.assert_called_once()
    if case.startswith("missing-"):
        assert result.startswith("Error: AIO bash")
        assert sandbox.requires_container_recycle
        assert len(observed) == 1
    else:
        assert "done" in result and "diagnostic" in result and "Exit Code: 7" in result
        assert not sandbox.requires_container_recycle
        if case == "empty-poll":
            assert len(observed) == 3
            assert [(row["offset"], row["stderr_offset"]) for row in observed] == [(0, 0), (3, 3), (3, 3)]
            assert result.startswith("onedone\n") and "twodiagnostic" in result
        else:
            assert len(observed) == 1
