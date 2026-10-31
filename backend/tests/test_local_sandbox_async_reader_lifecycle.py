"""Background output must survive the caller's event loop, like sync exec."""

import asyncio
import gc
import os
import shlex
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest

from deerflow.sandbox.local import local_sandbox

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")


@pytest.fixture(params=["asyncio", "uvloop"])
def loop_factory(request):
    if request.param == "uvloop":
        return pytest.importorskip("uvloop").new_event_loop
    return asyncio.new_event_loop


def _wait_for_report(report: Path) -> str:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if report.exists() and (result := report.read_text(encoding="utf-8")):
            return result
        time.sleep(0.01)
    pytest.fail("background writer did not report its result")


@pytest.mark.parametrize("exit_code", [0, 7])
def test_foreground_exit_does_not_wait_for_background_eof(tmp_path: Path, monkeypatch, loop_factory, exit_code) -> None:
    report = tmp_path / "background-result"
    monkeypatch.setattr(local_sandbox.LocalSandbox, "_get_shell", lambda self: "/bin/sh")
    # The foreground sleep ensures wait() starts before the shell exits.
    command = f"sleep 0.15; (sleep 1.5; printf done > {shlex.quote(str(report))}) & printf serving; exit {exit_code}"
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        output = runner.run(local_sandbox.LocalSandbox("t").execute_command_async(command, timeout=0.8))
        assert output == ("serving" if exit_code == 0 else "serving\nExit Code: 7")
    assert _wait_for_report(report) == "done"


def test_background_writer_survives_caller_loop_teardown(tmp_path: Path, monkeypatch, loop_factory) -> None:
    release = tmp_path / "release-writer"
    report = tmp_path / "writer-result"
    writer = (
        "import os, pathlib, sys, time\n"
        "release, report = map(pathlib.Path, sys.argv[1:])\n"
        "deadline = time.monotonic() + 5\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
        "try:\n"
        " os.write(1, b'background stdout\\n')\n"
        " os.write(2, b'background stderr\\n')\n"
        " result = 'write succeeded'\n"
        "except OSError as error: result = type(error).__name__\n"
        "report.write_text(result, encoding='utf-8')\n"
    )
    command = f"sleep 0.15; {shlex.quote(sys.executable)} -c {shlex.quote(writer)} {shlex.quote(str(release))} {shlex.quote(str(report))} & echo serving"
    processes = []
    groups = []
    threads = []
    original_spawn = asyncio.create_subprocess_exec
    original_drain = local_sandbox.LocalSandbox._start_pipe_drain

    def start_drain(*args, **kwargs):
        result = original_drain(*args, **kwargs)
        threads.append(result[1])
        return result

    async def spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        processes.append(process)
        groups.append(process.pid)
        return process

    monkeypatch.setattr(local_sandbox.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(local_sandbox.LocalSandbox, "_get_shell", lambda self: "/bin/sh")
    monkeypatch.setattr(local_sandbox.LocalSandbox, "_start_pipe_drain", staticmethod(start_drain))
    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            output = runner.run(local_sandbox.LocalSandbox("t").execute_command_async(command, timeout=1))
            assert output.strip() == "serving"
        # Finalize loop-owned transports before allowing the writer to continue.
        processes.clear()
        del runner
        gc.collect()
        release.touch()
        assert _wait_for_report(report) == "write succeeded"
        for thread in threads:
            thread.join(timeout=3)
            assert not thread.is_alive(), "EOF must release background readers"
    finally:
        release.touch()
        for group in groups:
            with suppress(ProcessLookupError):
                os.killpg(group, signal.SIGKILL)


def test_runner_shutdown_reaps_inflight_command(tmp_path: Path, monkeypatch, loop_factory) -> None:
    processes = []
    diagnostics = []
    original_spawn = asyncio.create_subprocess_exec
    marker = tmp_path / "unexpected-completion"

    async def main():
        spawned = asyncio.Event()

        async def spawn(*args, **kwargs):
            process = await original_spawn(*args, **kwargs)
            processes.append(process)
            spawned.set()
            return process

        monkeypatch.setattr(local_sandbox.asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(local_sandbox.LocalSandbox("t").execute_command_async(f"sleep 3; printf done > {shlex.quote(str(marker))}", timeout=5))
        await spawned.wait()
        return task

    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.get_loop().set_exception_handler(lambda _, context: diagnostics.append(context.get("message")))
        task = runner.run(main())

    assert task.cancelled()
    assert processes[0].returncode is not None
    assert processes[0].returncode < 0
    assert not marker.exists()
    assert not diagnostics
