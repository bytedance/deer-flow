"""LocalSandbox async command execution must keep the event loop responsive."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import pytest

from deerflow.sandbox import tools
from deerflow.sandbox.local.local_sandbox import LocalSandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.name == "nt", reason="POSIX async subprocess semantics"),
]


async def test_async_command_keeps_event_loop_responsive() -> None:
    """A long-running sandbox command runs without monopolizing the loop: a
    concurrent timer must fire on time while the command is still in flight.
    This is the blocking-I/O guard for execute_command_async — the whole point
    of the async path is that the gateway loop keeps serving other tasks (IM
    channels, concurrent runs) while a command runs."""
    sandbox = LocalSandbox("t")

    started = time.monotonic()
    command_task = asyncio.create_task(sandbox.execute_command_async("sleep 1", timeout=10))
    await asyncio.sleep(0.2)
    timer_elapsed = time.monotonic() - started
    await command_task
    total = time.monotonic() - started

    assert timer_elapsed < 0.9, f"event loop stalled for {timer_elapsed:.2f}s during async command execution"
    assert total >= 1.0, "command should actually have run for its full duration"


@pytest.mark.parametrize("sync_only", [False, True], ids=["async-provider", "sync-provider"])
@pytest.mark.parametrize("failure", [None, "execute", "initialize"])
async def test_full_bash_coroutine_keeps_path_masking_offloop(tmp_path, monkeypatch, sync_only, failure) -> None:
    """Exercise real preparation and output/error masking under the strict gate."""
    workspace = str(tmp_path / "workspace")
    loop_thread = threading.get_ident()
    secret = "synthetic-bash-regression-secret"
    calls = []

    def execute(command, env=None, timeout=None):
        if sync_only:
            assert threading.get_ident() != loop_thread
        calls.append((command, env, timeout))
        output = f"{workspace}/result.txt {env['REVIEW_TEST_SECRET']}"
        if failure == "execute":
            raise RuntimeError(output)
        return output

    async def execute_async(*args, **kwargs):
        return execute(*args, **kwargs)

    sandbox = SimpleNamespace(execute_command=execute, environment={})
    if not sync_only:
        sandbox.execute_command_async = execute_async

    async def initialize(runtime):
        if failure == "initialize":
            raise RuntimeError(f"cannot initialize {workspace}/result.txt")
        return sandbox

    async def config():
        return None

    monkeypatch.setattr(tools, "safe_app_config_async", config)
    monkeypatch.setattr(tools, "ensure_sandbox_initialized_async", initialize)
    monkeypatch.setattr(tools, "ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr(tools, "is_host_bash_allowed", lambda: True)
    monkeypatch.setattr(tools, "read_active_secrets", lambda context: {"REVIEW_TEST_SECRET": secret})
    monkeypatch.setattr(tools, "_bash_output_config", lambda: (20000, 3))
    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local:test"},
            "thread_data": {"workspace_path": workspace},
            "thread_directories_created": True,
        },
        context={},
        config={},
    )
    output = await tools.bash_tool.coroutine(runtime=runtime, command="echo result")

    assert "/mnt/user-data/workspace/result.txt" in output
    assert workspace not in output
    assert secret not in output
    if failure:
        assert output.startswith("Error: Unexpected error")
    else:
        assert not output.startswith("Error:")
    if failure != "initialize":
        assert len(calls) == 1
        assert calls[0][1] == {"REVIEW_TEST_SECRET": secret}
        assert calls[0][2] == 3
