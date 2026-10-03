"""Keep the parent sandbox lease alive through ordinary task acceptance reads."""

from __future__ import annotations

import asyncio
import importlib
import threading
import uuid
from enum import Enum
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from deerflow.sandbox.lease import (
    SANDBOX_LEASE_OWNER_CONTEXT_KEY,
    discard_sandbox_lease_manager,
    get_sandbox_lease_manager,
)
from deerflow.subagents.config import SubagentConfig

task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")
sandbox_tools = importlib.import_module("deerflow.sandbox.tools")
sandbox_provider_module = importlib.import_module("deerflow.sandbox.sandbox_provider")
authz_module = importlib.import_module("deerflow.authz.sandbox_authz")
tools_module = importlib.import_module("deerflow.tools")

pytestmark = pytest.mark.asyncio


class _SubagentStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class _RecordingSandbox:
    def __init__(self) -> None:
        self.read_started = threading.Event()
        self.allow_read_to_finish = threading.Event()
        self.read_finished = threading.Event()
        self.read_timeout_seconds = 10

    def execute_command(self, command: str, env=None, timeout=None) -> str:
        return "11"

    def read_file(self, path: str, start_line=None, end_line=None) -> str:
        self.read_started.set()
        if not self.allow_read_to_finish.wait(self.read_timeout_seconds):
            raise TimeoutError("test read was not released")
        self.read_finished.set()
        return "synthetic report body"

    def release_command_scope(self, scope_id: str) -> None:
        pass


class _RecordingProvider:
    def __init__(self) -> None:
        self.sandbox = _RecordingSandbox()
        self.sandbox_id = "synthetic:thread-1"
        self.released = threading.Event()
        self.events: list[tuple[str, bool | None]] = []
        self.events_lock = threading.Lock()

    def _record(self, name: str, reader_finished: bool | None = None) -> None:
        with self.events_lock:
            self.events.append((name, reader_finished))

    def acquire(self, thread_id=None, *, user_id=None) -> str:
        return self.sandbox_id

    async def acquire_async(self, thread_id=None, *, user_id=None) -> str:
        return self.acquire(thread_id, user_id=user_id)

    def get(self, sandbox_id: str):
        return self.sandbox if sandbox_id == self.sandbox_id else None

    def get_scoped(self, sandbox_id: str, *, thread_id: str, user_id: str):
        if (thread_id, user_id) == ("thread-1", "user-1"):
            return self.get(sandbox_id)
        return None

    def release(self, sandbox_id: str) -> None:
        self._record("provider_release", self.sandbox.read_finished.is_set())
        self.released.set()


def _completed_result() -> SimpleNamespace:
    return SimpleNamespace(
        status=_SubagentStatus.COMPLETED,
        ai_messages=[],
        result="done",
        error=None,
        stop_reason=None,
        token_usage_records=[],
        usage_reported=False,
        tool_receipts=None,
        bash_executions=None,
    )


def _parent_runtime(provider: _RecordingProvider) -> SimpleNamespace:
    thread_data = {
        "workspace_path": "/mnt/user-data/workspace",
        "uploads_path": "/mnt/user-data/uploads",
        "outputs_path": "/mnt/user-data/outputs",
    }
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": provider.sandbox_id},
            "thread_data": thread_data,
            "uploaded_files": [],
        },
        context={
            "thread_id": "thread-1",
            "user_id": "user-1",
            SANDBOX_LEASE_OWNER_CONTEXT_KEY: "parent-owner",
        },
        config={
            "metadata": {"model_name": "synthetic-model", "trace_id": "lifecycle-test"},
            "configurable": {"thread_id": "thread-1"},
        },
    )


async def _no_authorization(*args, **kwargs) -> None:
    return None


async def _no_event(*args, **kwargs) -> None:
    return None


async def _no_finalize(*args, **kwargs) -> None:
    return None


def _install_task_tool_boundaries(monkeypatch, provider: _RecordingProvider, execution_id: str) -> None:
    result = _completed_result()

    class ImmediateExecutor:
        def __init__(self, **kwargs) -> None:
            pass

        def execute_async(self, prompt: str, task_id=None) -> str:
            return execution_id

    monkeypatch.setattr(task_tool_module, "_get_runtime_app_config", lambda runtime: None)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda **kwargs: ["general-purpose"])
    monkeypatch.setattr(
        task_tool_module,
        "get_subagent_config",
        lambda *args, **kwargs: SubagentConfig(
            name="general-purpose",
            description="General helper",
            system_prompt="Synthetic child",
            max_turns=50,
            timeout_seconds=10,
        ),
    )
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", ImmediateExecutor)
    monkeypatch.setattr(task_tool_module, "SubagentStatus", _SubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _id: result)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _id: None)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda _id: None)
    monkeypatch.setattr(task_tool_module, "_finalize_interrupted_subagent", _no_finalize)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_tool_module, "resolve_subagent_model_name", lambda config, parent, **kwargs: parent or "synthetic-model")
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: provider)
    monkeypatch.setattr(sandbox_tools, "safe_app_config", lambda: None)
    monkeypatch.setattr(sandbox_tools, "authorize_sandbox_execution", lambda **kwargs: None)
    monkeypatch.setattr(sandbox_provider_module, "get_sandbox_provider", lambda: provider)
    monkeypatch.setattr(authz_module, "authorize_sandbox_execution_async", _no_authorization)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", _no_event)


def _task_callable():
    tool = task_tool_module.task_tool
    invoke = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    assert invoke is not None
    return invoke


async def _wait_for_read_to_start(provider: _RecordingProvider) -> None:
    started = await asyncio.wait_for(asyncio.to_thread(provider.sandbox.read_started.wait, 5), timeout=6)
    assert started


@pytest.mark.parametrize("repeat_cancel", [False, True])
async def test_task_acceptance_cancellation_drains_reader_before_parent_lease_release(monkeypatch, repeat_cancel):
    provider = _RecordingProvider()
    manager = get_sandbox_lease_manager(provider)
    execution_id = f"acceptance-lifecycle-{uuid.uuid4()}"
    manager.acquire("parent-owner", "thread-1", user_id="user-1")
    _install_task_tool_boundaries(monkeypatch, provider, execution_id)
    task = asyncio.create_task(
        _task_callable()(
            runtime=_parent_runtime(provider),
            prompt="synthetic task",
            subagent_type="general-purpose",
            tool_call_id="tool-call-1",
            acceptance_criteria=["file:/mnt/user-data/workspace/report.txt exists"],
        )
    )

    try:
        await _wait_for_read_to_start(provider)
        task.cancel("parent cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        assert not provider.released.is_set()

        if repeat_cancel:
            task.cancel("repeated parent cancellation")
            await asyncio.sleep(0)
            assert not task.done()

        provider.sandbox.allow_read_to_finish.set()
        with pytest.raises(asyncio.CancelledError) as cancellation:
            await task
        assert cancellation.value.args == ("parent cancellation",)
        assert provider.sandbox.read_finished.is_set()
        assert not provider.released.is_set()

        await manager.release_async("parent-owner")
        assert provider.released.is_set()
        assert provider.events == [("provider_release", True)]
    finally:
        provider.sandbox.allow_read_to_finish.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await manager.release_async("parent-owner")
        discard_sandbox_lease_manager(provider)


async def test_task_acceptance_checker_exception_keeps_completed_task_and_releases_parent_lease(monkeypatch):
    provider = _RecordingProvider()
    manager = get_sandbox_lease_manager(provider)
    execution_id = f"acceptance-lifecycle-{uuid.uuid4()}"
    manager.acquire("parent-owner", "thread-1", user_id="user-1")
    _install_task_tool_boundaries(monkeypatch, provider, execution_id)

    def fail_checker(*args, **kwargs):
        raise RuntimeError("synthetic checker failure")

    monkeypatch.setattr(task_tool_module, "check_acceptance_criteria", fail_checker)
    try:
        command = await _task_callable()(
            runtime=_parent_runtime(provider),
            prompt="synthetic task",
            subagent_type="general-purpose",
            tool_call_id="tool-call-1",
            acceptance_criteria=["file:/mnt/user-data/workspace/report.txt exists"],
        )
        message = command.update["messages"][0]
        assert isinstance(message, ToolMessage)
        assert "done" in message.content
        assert message.additional_kwargs.get("subagent_acceptance_verdict") is None
        assert not provider.released.is_set()

        await manager.release_async("parent-owner")
        assert provider.released.is_set()
        assert provider.events == [("provider_release", False)]
    finally:
        await manager.release_async("parent-owner")
        discard_sandbox_lease_manager(provider)


async def test_task_acceptance_worker_exception_during_cancel_preserves_cancel_and_drains_before_release(monkeypatch, caplog):
    provider = _RecordingProvider()
    manager = get_sandbox_lease_manager(provider)
    execution_id = f"acceptance-lifecycle-{uuid.uuid4()}"
    manager.acquire("parent-owner", "thread-1", user_id="user-1")
    _install_task_tool_boundaries(monkeypatch, provider, execution_id)
    worker_started = threading.Event()
    allow_worker_to_fail = threading.Event()
    worker_finished = threading.Event()

    def fail_checker(*args, **kwargs):
        worker_started.set()
        if not allow_worker_to_fail.wait(timeout=10):
            raise TimeoutError("test checker was not released")
        worker_finished.set()
        raise RuntimeError("synthetic worker failure")

    monkeypatch.setattr(task_tool_module, "check_acceptance_criteria", fail_checker)
    task = asyncio.create_task(
        _task_callable()(
            runtime=_parent_runtime(provider),
            prompt="synthetic task",
            subagent_type="general-purpose",
            tool_call_id="tool-call-1",
            acceptance_criteria=["file:/mnt/user-data/workspace/report.txt exists"],
        )
    )

    try:
        started = await asyncio.wait_for(asyncio.to_thread(worker_started.wait, 5), timeout=6)
        assert started
        task.cancel("parent cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel("repeated parent cancellation")
        await asyncio.sleep(0)
        assert not task.done()

        allow_worker_to_fail.set()
        with pytest.raises(asyncio.CancelledError) as cancellation:
            await task
        assert cancellation.value.args == ("parent cancellation",)
        assert worker_finished.is_set()
        assert "Cancelled sandbox client operation failed while draining" in caplog.text
        assert not provider.released.is_set()

        await manager.release_async("parent-owner")
        assert provider.released.is_set()
    finally:
        allow_worker_to_fail.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await manager.release_async("parent-owner")
        discard_sandbox_lease_manager(provider)
