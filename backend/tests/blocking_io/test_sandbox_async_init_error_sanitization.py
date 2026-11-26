"""Unexpected sandbox-init error sanitization must stay off the async event loop."""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from deerflow.sandbox import tools as sandbox_tools
from deerflow.sandbox.exceptions import SandboxRuntimeError

pytestmark = pytest.mark.asyncio


def _reset_local_mask_caches() -> None:
    sandbox_tools._mask_source_roots.cache_clear()
    for fn in (sandbox_tools._get_skills_host_path, sandbox_tools._get_acp_workspace_host_path):
        if hasattr(fn, "_cached"):
            delattr(fn, "_cached")


def _build_thread_data(base: Path) -> dict[str, str]:
    user_data = base / "users" / "u1" / "threads" / "t1" / "user-data"
    return {
        "workspace_path": str(user_data / "workspace"),
        "uploads_path": str(user_data / "uploads"),
        "outputs_path": str(user_data / "outputs"),
    }


async def test_ls_async_init_unexpected_error_sanitizes_off_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local sandbox unexpected init errors must run path masking off the event loop."""
    thread_data = _build_thread_data(tmp_path)
    workspace_path = thread_data["workspace_path"]
    await asyncio.to_thread(Path(workspace_path).mkdir, parents=True, exist_ok=True)
    _reset_local_mask_caches()

    class FailingProvider:
        def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str | None = None):
            raise RuntimeError(f"boom at {workspace_path}/secret.txt")

    loop_tid = threading.get_ident()
    exists_on_loop: list[bool] = []
    realpath_on_loop: list[bool] = []
    orig_exists = Path.exists
    orig_realpath = os.path.realpath

    def tracked_exists(self: Path) -> bool:
        exists_on_loop.append(threading.get_ident() == loop_tid)
        return orig_exists(self)

    def tracked_realpath(path, *args, **kwargs):
        realpath_on_loop.append(threading.get_ident() == loop_tid)
        return orig_realpath(path, *args, **kwargs)

    async def _noop_authz(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: FailingProvider())
    monkeypatch.setattr(sandbox_tools, "authorize_sandbox_execution_async", _noop_authz)
    monkeypatch.setattr(Path, "exists", tracked_exists)
    monkeypatch.setattr(os.path, "realpath", tracked_realpath)

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local:u1:t1"}, "thread_data": thread_data},
        context={"thread_id": "t1", "user_id": "u1"},
        tool_call_id="tc-ls-1",
    )

    result = await sandbox_tools._ls_tool_async(runtime, "/mnt/user-data/workspace")

    assert result == "Error: Unexpected error initializing sandbox: RuntimeError: boom at /mnt/user-data/workspace/secret.txt"
    assert workspace_path not in result
    assert exists_on_loop, "expected Path.exists() to run during local path sanitization"
    assert realpath_on_loop, "expected os.path.realpath() to run during local path sanitization"
    assert not any(exists_on_loop), "Path.exists() ran on the asyncio event loop thread"
    assert not any(realpath_on_loop), "os.path.realpath() ran on the asyncio event loop thread"


async def test_read_file_async_init_unexpected_error_preserves_structured_tool_message_off_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """read_file structured ToolMessage error path must also sanitize off-loop."""
    thread_data = _build_thread_data(tmp_path)
    workspace_path = thread_data["workspace_path"]
    await asyncio.to_thread(Path(workspace_path).mkdir, parents=True, exist_ok=True)
    _reset_local_mask_caches()

    class FailingProvider:
        def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str | None = None):
            raise RuntimeError(f"cannot inspect {workspace_path}/report.md")

    loop_tid = threading.get_ident()
    sanitize_threads: list[int] = []
    orig_sanitize = sandbox_tools._sanitize_error

    def tracked_sanitize(error: Exception, runtime=None) -> str:
        sanitize_threads.append(threading.get_ident())
        return orig_sanitize(error, runtime)

    async def _noop_authz(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: FailingProvider())
    monkeypatch.setattr(sandbox_tools, "authorize_sandbox_execution_async", _noop_authz)
    monkeypatch.setattr(sandbox_tools, "_sanitize_error", tracked_sanitize)

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local:u1:t1"}, "thread_data": thread_data},
        context={"thread_id": "t1", "user_id": "u1"},
        tool_call_id="tc-read-1",
    )

    result = await sandbox_tools._read_file_tool_async(runtime, "/mnt/user-data/workspace/report.md")

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "tc-read-1"
    assert "/mnt/user-data/workspace/report.md" in result.content
    assert workspace_path not in result.content
    assert sanitize_threads
    assert all(tid != loop_tid for tid in sanitize_threads)


async def test_non_local_sandbox_and_sandbox_error_semantics_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-local errors and SandboxError subclasses must preserve existing formatting."""

    async def _noop_authz(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(sandbox_tools, "authorize_sandbox_execution_async", _noop_authz)

    class NonLocalProvider:
        def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str | None = None):
            raise RuntimeError("remote provider unavailable")

    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: NonLocalProvider())
    non_local_runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio-123"}},
        context={"thread_id": "t1", "user_id": "u1"},
        tool_call_id="tc-non-local",
    )
    res_non_local = await sandbox_tools._ls_tool_async(non_local_runtime, "/mnt/user-data/workspace")
    assert res_non_local == "Error: Unexpected error initializing sandbox: RuntimeError: remote provider unavailable"

    class SandboxErrorProvider:
        def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str | None = None):
            raise SandboxRuntimeError("sandbox lease expired")

    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: SandboxErrorProvider())
    res_sandbox_err = await sandbox_tools._ls_tool_async(non_local_runtime, "/mnt/user-data/workspace")
    assert res_sandbox_err == "Error: sandbox lease expired"


async def test_async_init_error_sanitization_drains_on_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation during off-loop error sanitization must drain the worker before propagating."""
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class FailingProvider:
        def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str | None = None):
            raise RuntimeError("init failed")

    def blocking_sanitize(error: Exception, runtime=None) -> str:
        started.set()
        release.wait(timeout=5.0)
        finished.set()
        return f"{type(error).__name__}: {error}"

    async def _noop_authz(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: FailingProvider())
    monkeypatch.setattr(sandbox_tools, "authorize_sandbox_execution_async", _noop_authz)
    monkeypatch.setattr(sandbox_tools, "_sanitize_error", blocking_sanitize)

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local:u1:t1"}},
        context={"thread_id": "t1", "user_id": "u1"},
        tool_call_id="tc-cancel",
    )

    task = asyncio.create_task(sandbox_tools._ls_tool_async(runtime, "/mnt/user-data/workspace"))
    try:
        deadline = asyncio.get_running_loop().time() + 5.0
        while not started.is_set():
            if task.done():
                if task.cancelled():
                    pytest.fail("tool task was cancelled before reaching sanitizer")
                exc = task.exception()
                if exc is not None:
                    pytest.fail(f"tool task raised before reaching sanitizer: {type(exc).__name__}: {exc}")
                pytest.fail(f"tool task returned before reaching sanitizer: {task.result()!r}")
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("timed out waiting for off-loop sanitizer to start")
            await asyncio.sleep(0.01)

        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done(), "task must wait for the off-loop sanitization worker to drain"
        assert not finished.is_set()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        with contextlib.suppress(BaseException):
            await task


async def test_async_write_and_replace_readonly_guard_stays_off_event_loop_with_cold_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold skills-path cache reads during async write/replace preflight must stay off-loop."""
    config_file = tmp_path / "config.yaml"
    await asyncio.to_thread(config_file.write_text, "skills:\n  container_path: /mnt/skills\n", "utf-8")

    loop_tid = threading.get_ident()
    config_reads_on_loop: list[bool] = []

    def tracked_get_app_config():
        config_reads_on_loop.append(threading.get_ident() == loop_tid)
        # Perform real stat/read so the strict Blockbuster gate also fails if run on-loop.
        config_file.stat()
        config_file.read_text(encoding="utf-8")
        return SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills"),
            sandbox=SimpleNamespace(mounts=[], write_file_max_bytes=0),
        )

    class FakeRemoteSandbox:
        id = "remote-blocking-io-1"

        def __init__(self) -> None:
            self.files: dict[str, str] = {}

        def read_file(self, target: str) -> str:
            return self.files[target]

        def write_file(self, target: str, content: str, append: bool = False) -> None:
            self.files[target] = (self.files.get(target, "") + content) if append else content

    remote_sandbox = FakeRemoteSandbox()
    init_calls: list[str] = []

    async def fake_ensure_async(_rt):
        init_calls.append("async")
        return remote_sandbox

    def fake_ensure_sync(_rt):
        init_calls.append("sync")
        return remote_sandbox

    async def _noop_authz(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("deerflow.config.get_app_config", tracked_get_app_config)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized_async", fake_ensure_async)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", fake_ensure_sync)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda _rt: None)
    monkeypatch.setattr(sandbox_tools, "authorize_sandbox_execution_async", _noop_authz)

    def _clear_skills_cache() -> None:
        if hasattr(sandbox_tools._get_skills_container_path, "_cached"):
            delattr(sandbox_tools._get_skills_container_path, "_cached")

    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": remote_sandbox.id}},
        context={"thread_id": "t1", "user_id": "u1"},
        config={},
    )

    try:
        # 1. Ordinary workspace write and str_replace with a cold cache.
        _clear_skills_cache()
        assert await sandbox_tools._write_file_tool_async(runtime, "/mnt/user-data/workspace/note.txt", "hello world") == "OK"
        _clear_skills_cache()
        assert await sandbox_tools._str_replace_tool_async(runtime, "/mnt/user-data/workspace/note.txt", "world", "deer") == "OK"
        assert remote_sandbox.files["/mnt/user-data/workspace/note.txt"] == "hello deer"

        # 2. Rejected read-only paths with a cold cache must stay off-loop and avoid acquisition.
        init_calls.clear()
        _clear_skills_cache()
        assert await sandbox_tools._write_file_tool_async(runtime, "/mnt/skills/public/demo/SKILL.md", "tamper") == "Error: Permission denied writing to file: /mnt/skills/public/demo/SKILL.md"
        _clear_skills_cache()
        assert await sandbox_tools._str_replace_tool_async(runtime, "/mnt/skills/public/demo/SKILL.md", "a", "b") == "Error: Permission denied accessing file: /mnt/skills/public/demo/SKILL.md"
        assert init_calls == []

        assert len(config_reads_on_loop) >= 4
        assert not any(config_reads_on_loop), "get_app_config() ran on the asyncio event loop thread"
    finally:
        _clear_skills_cache()
