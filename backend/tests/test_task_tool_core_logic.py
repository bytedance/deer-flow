"""Core behavior tests for task tool orchestration."""

import asyncio
import gc
import importlib
import inspect
import threading
import time
import weakref
from enum import Enum
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.sandbox.security import LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE
from deerflow.subagents.capacity import SubagentExecutionCapacity
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.status_contract import (
    SUBAGENT_ERROR_KEY,
    SUBAGENT_MODEL_NAME_KEY,
    SUBAGENT_RESULT_BRIEF_KEY,
    SUBAGENT_RESULT_SHA256_KEY,
    SUBAGENT_STATUS_KEY,
    SUBAGENT_STOP_REASON_KEY,
    SUBAGENT_TOKEN_USAGE_KEY,
    SUBAGENT_TOOL_RECEIPTS_KEY,
)

# Use module import so tests can patch the exact symbols referenced inside task_tool().
# NOTE: conftest.py replaces deerflow.subagents.executor with a MagicMock, so the
# executor-bound names inside task_tool are mocks; tests patch them explicitly.
task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")


def test_parent_loop_middleware_recorder_proxy_delivers_on_owner_loop():
    """Subagent middleware events must never call RunJournal from the child loop."""
    calls: list[tuple[object, dict]] = []
    delivered = threading.Event()

    class LoopPinnedJournal:
        def record_middleware(self, **kwargs):
            calls.append((asyncio.get_running_loop(), dict(kwargs)))
            delivered.set()

    parent_loop = asyncio.new_event_loop()
    parent_thread = threading.Thread(
        target=parent_loop.run_forever,
        name="test-middleware-journal-parent-loop",
        daemon=True,
    )
    parent_thread.start()
    try:
        proxy = task_tool_module._ParentLoopMiddlewareRecorderProxy(
            LoopPinnedJournal(),
            parent_loop,
        )
        proxy.record_middleware(
            tag="loop_detection",
            name="LoopDetectionMiddleware",
            hook="after_model",
            action="warn",
            changes={"detection_layer": "identical_call_set"},
        )

        assert delivered.wait(timeout=5)
        assert len(calls) == 1
        observed_loop, kwargs = calls[0]
        assert observed_loop is parent_loop
        assert kwargs["tag"] == "loop_detection"
        assert kwargs["action"] == "warn"

        asyncio.run_coroutine_threadsafe(proxy.aclose(), parent_loop).result(timeout=5)
        proxy.record_middleware(tag="loop_detection", name="LoopDetectionMiddleware", hook="after_model", action="hard_stop", changes={})
        time.sleep(0.05)
        assert len(calls) == 1, "events emitted after the parent task boundary must be dropped"
    finally:
        parent_loop.call_soon_threadsafe(parent_loop.stop)
        parent_thread.join(timeout=5)
        parent_loop.close()


def test_parent_loop_middleware_recorder_proxy_drops_after_loop_closed():
    """A child event after asyncio.run teardown is a quiet no-op."""
    loop = asyncio.new_event_loop()
    loop.close()
    proxy = task_tool_module._ParentLoopMiddlewareRecorderProxy(MagicMock(), loop)

    proxy.record_middleware(
        tag="loop_detection",
        name="LoopDetectionMiddleware",
        hook="after_model",
        action="warn",
        changes={},
    )


def test_parent_loop_middleware_recorder_close_is_fail_open_off_owner_loop(caplog):
    """A bad close caller must not replace the task tool's original outcome."""
    owner_loop = asyncio.new_event_loop()
    proxy = task_tool_module._ParentLoopMiddlewareRecorderProxy(MagicMock(), owner_loop)
    try:
        with caplog.at_level("WARNING"):
            asyncio.run(proxy.aclose())

        assert proxy.is_closed is False
        assert "Cannot drain subagent middleware recorder from a non-owner loop" in caplog.text
    finally:
        owner_loop.close()


class FakeSubagentStatus(Enum):
    # Match production enum values so branch comparisons behave identically.
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


def _make_runtime(*, app_config=None) -> SimpleNamespace:
    # Minimal ToolRuntime-like object; task_tool only reads these three attributes.
    context = {"thread_id": "thread-1"}
    if app_config is not None:
        context["app_config"] = app_config
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": "/tmp/workspace",
                "uploads_path": "/tmp/uploads",
                "outputs_path": "/tmp/outputs",
            },
        },
        context=context,
        config={"metadata": {"model_name": "ark-model", "trace_id": "trace-1"}},
    )


def _make_subagent_config(name: str = "general-purpose") -> SubagentConfig:
    return SubagentConfig(
        name=name,
        description="General helper",
        system_prompt="Base system prompt",
        max_turns=50,
        timeout_seconds=10,
    )


def _make_result(
    status: FakeSubagentStatus,
    *,
    ai_messages: list[dict] | None = None,
    result: str | None = None,
    error: str | None = None,
    stop_reason: str | None = None,
    token_usage_records: list[dict] | None = None,
    tool_receipts: list[dict] | None = None,
    bash_executions: list[dict] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        ai_messages=ai_messages or [],
        result=result,
        error=error,
        stop_reason=stop_reason,
        token_usage_records=token_usage_records or [],
        usage_reported=False,
        tool_receipts=tool_receipts,
        bash_executions=bash_executions,
    )


def _run_task_tool(**kwargs) -> str | Command:
    """Execute the task tool across LangChain sync/async wrapper variants."""
    coroutine = getattr(task_tool_module.task_tool, "coroutine", None)
    if coroutine is not None:
        return asyncio.run(coroutine(**kwargs))
    return task_tool_module.task_tool.func(**kwargs)


def _task_tool_message(result: str | Command) -> ToolMessage:
    assert isinstance(result, Command)
    assert isinstance(result.update, dict)
    messages = result.update["messages"]
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, ToolMessage)
    return message


def test_task_result_command_derives_content_from_status_payload():
    signature = inspect.signature(task_tool_module._task_result_command)
    assert "content" not in signature.parameters

    completed = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-completed",
            status="completed",
            result="done",
        )
    )
    assert completed.content == "Task Succeeded. Result: done"
    assert completed.additional_kwargs[SUBAGENT_STATUS_KEY] == "completed"
    assert completed.additional_kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "done"

    completed_with_runtime_metadata = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-completed-metadata",
            status="completed",
            result="done",
            model_name="claude-3-7-sonnet",
            usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )
    )
    assert completed_with_runtime_metadata.additional_kwargs[SUBAGENT_MODEL_NAME_KEY] == "claude-3-7-sonnet"
    assert completed_with_runtime_metadata.additional_kwargs[SUBAGENT_TOKEN_USAGE_KEY]["total_tokens"] == 120

    failed = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-failed",
            status="failed",
            error="boom",
        )
    )
    assert failed.content == "Task failed. Error: boom"
    assert failed.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert failed.additional_kwargs[SUBAGENT_ERROR_KEY] == "boom"

    failed_without_detail = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-failed-empty",
            status="failed",
            error=None,
        )
    )
    assert failed_without_detail.content == "Task failed."
    assert failed_without_detail.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert failed_without_detail.additional_kwargs[SUBAGENT_ERROR_KEY] == "Task failed."

    cancelled = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-cancelled",
            status="cancelled",
            error=None,
        )
    )
    assert cancelled.content == "Task cancelled by user."
    assert cancelled.additional_kwargs[SUBAGENT_STATUS_KEY] == "cancelled"
    assert cancelled.additional_kwargs[SUBAGENT_ERROR_KEY] == "Task cancelled by user."

    timed_out_without_detail = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-timeout-empty",
            status="timed_out",
            error="",
        )
    )
    assert timed_out_without_detail.content == "Task timed out."
    assert timed_out_without_detail.additional_kwargs[SUBAGENT_STATUS_KEY] == "timed_out"
    assert timed_out_without_detail.additional_kwargs[SUBAGENT_ERROR_KEY] == "Task timed out."

    # #3875 Phase 2: a capped run keeps a normal status and carries the cap on
    # the additive ``subagent_stop_reason`` field; the model-visible text folds
    # a ``(capped: ...)`` note in. The recovered partial work still travels on
    # ``result_brief`` like a clean success.
    capped = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-capped",
            status="completed",
            result="investigated 3 of 5 sources",
            stop_reason="token_capped",
        )
    )
    assert capped.content == "Task Succeeded (capped: token budget). Result: investigated 3 of 5 sources"
    assert capped.additional_kwargs[SUBAGENT_STATUS_KEY] == "completed"
    assert capped.additional_kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "investigated 3 of 5 sources"
    assert len(capped.additional_kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64
    assert capped.additional_kwargs[SUBAGENT_STOP_REASON_KEY] == "token_capped"


def test_task_result_command_carries_loop_capped_from_real_loop_detection():
    """Real-path (#3875 Phase 2, ggnnggez review): drive the actual
    ``LoopDetectionMiddleware`` to a hard stop with repeated identical tool
    calls, feed the produced ``loop_capped`` through ``_task_result_command``,
    and assert the final task ``ToolMessage`` carries
    ``subagent_stop_reason=loop_capped`` — proving the loop cap reaches the wire
    the lead/ledger read, not just the in-memory result."""
    from langchain_core.messages import AIMessage

    from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

    # Drive the real middleware to a hard stop (4 identical calls, hard_limit=4).
    mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
    runtime = SimpleNamespace(context={"thread_id": "t", "run_id": "r1"})
    tool_calls = [{"name": "bash", "args": {"command": "ls"}, "id": "c1", "type": "tool_call"}]
    for _ in range(3):
        mw._apply({"messages": [AIMessage(content="", tool_calls=tool_calls)]}, runtime)
    hard_stop = mw._apply({"messages": [AIMessage(content="", tool_calls=tool_calls)]}, runtime)
    assert hard_stop is not None  # hard stop fired

    stop_reason = mw.consume_stop_reason("r1")
    assert stop_reason == "loop_capped"

    # The produced reason flows through the task-tool result path onto the wire.
    message = _task_tool_message(
        task_tool_module._task_result_command(
            tool_call_id="tc-loop",
            status="completed",
            result="partial work before the loop was broken",
            stop_reason=stop_reason,
        )
    )
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "completed"
    assert message.additional_kwargs[SUBAGENT_STOP_REASON_KEY] == "loop_capped"
    assert message.additional_kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "partial work before the loop was broken"
    assert "capped: repeated tool-call loop" in message.content


async def _no_sleep(_: float) -> None:
    return None


class _DummyScheduledTask:
    def add_done_callback(self, _callback):
        return None


def test_task_tool_returns_error_for_unknown_subagent(monkeypatch):
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: None)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["general-purpose"])

    result = _run_task_tool(
        runtime=None,
        description="执行任务",
        prompt="do work",
        subagent_type="general-purpose",
        tool_call_id="tc-1",
    )

    message = _task_tool_message(result)
    assert message.content == "Task failed. Error: Unknown subagent type 'general-purpose'. Available: general-purpose"
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert message.additional_kwargs[SUBAGENT_ERROR_KEY] == "Unknown subagent type 'general-purpose'. Available: general-purpose"


def test_task_tool_enforces_caller_subagent_snapshot(monkeypatch):
    runtime = _make_runtime()
    runtime.config["metadata"]["allowed_subagents"] = ["planner"]
    captured = {}

    def available(*, allowed_subagents):
        captured["allowed"] = allowed_subagents
        return ["planner"]

    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", available)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())

    result = _run_task_tool(
        runtime=runtime,
        description="blocked delegation",
        prompt="do work",
        subagent_type="general-purpose",
        tool_call_id="tc-policy",
    )

    message = _task_tool_message(result)
    assert captured["allowed"] == ["planner"]
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert "Available: planner" in message.content


def test_task_tool_explains_when_caller_policy_permits_no_subagents(monkeypatch):
    runtime = _make_runtime()
    runtime.config["metadata"]["allowed_subagents"] = []
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda *, allowed_subagents: [])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())

    result = _run_task_tool(
        runtime=runtime,
        description="blocked delegation",
        prompt="do work",
        subagent_type="general-purpose",
        tool_call_id="tc-empty-policy",
    )

    message = _task_tool_message(result)
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert "Available: none permitted by caller policy" in message.content


def test_task_tool_forwards_the_run_extension_snapshot_to_executor(monkeypatch):
    """The lead run binds one immutable extension snapshot; delegation must
    carry that same object rather than re-reading the process singleton, which
    a concurrent replacement could have swapped underneath the run."""
    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY
    from deerflow.extensions.registry import ExtensionRegistry

    loaded = ExtensionRegistry().build()
    runtime = _make_runtime()
    runtime.context[EXTENSION_SNAPSHOT_CONTEXT_KEY] = loaded
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    _run_task_tool(runtime=runtime, description="test", prompt="p", subagent_type="general-purpose", tool_call_id="tc-ext")

    assert captured["executor_kwargs"]["extensions"] is loaded


def test_task_tool_installs_and_closes_narrow_loop_detection_recorder(monkeypatch):
    journal = MagicMock()
    runtime = _make_runtime()
    runtime.context["__run_journal"] = journal
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    _run_task_tool(runtime=runtime, description="test", prompt="p", subagent_type="general-purpose", tool_call_id="tc-journal")

    kwargs = captured["executor_kwargs"]
    proxy = kwargs["loop_detection_recorder"]
    assert proxy.is_closed is True
    proxy.record_middleware(tag="loop_detection", name="LoopDetectionMiddleware", hook="after_model", action="warn", changes={})
    journal.record_middleware.assert_not_called()


def test_task_tool_omits_extensions_without_a_run_snapshot(monkeypatch):
    """Callers outside the Gateway run path (embedded client, standalone
    LangGraph Server) install no snapshot; the executor must keep its existing
    singleton fallback instead of receiving a forged or missing value."""
    runtime = _make_runtime()
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    _run_task_tool(runtime=runtime, description="test", prompt="p", subagent_type="general-purpose", tool_call_id="tc-no-ext")

    assert "extensions" not in captured["executor_kwargs"]


def test_bound_task_tool_forwards_explicit_execution_capacity(monkeypatch):
    runtime = _make_runtime()
    captured = {}
    capacity = SubagentExecutionCapacity(SubagentRuntimeConfig(max_running=7))
    app_config = object()

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda **_kwargs: ["general-purpose"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name, **_kwargs: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    bound_tool = task_tool_module.bind_task_tool(capacity, app_config=app_config)
    coroutine = getattr(bound_tool, "coroutine", None)
    assert coroutine is not None
    asyncio.run(
        coroutine(
            runtime=runtime,
            description="test",
            prompt="p",
            subagent_type="general-purpose",
            tool_call_id="tc-capacity",
        )
    )

    assert captured["executor_kwargs"]["execution_capacity"] is capacity
    assert captured["executor_kwargs"]["app_config"] is app_config


def test_task_tool_forwards_channel_user_id_to_executor(monkeypatch):
    """The IM-channel sender identity must survive delegation: in group chats
    one thread serves many senders, so a subagent's bash commands need the
    dispatching turn's channel_user_id (same propagation rule as user_role /
    oauth attribution)."""
    runtime = _make_runtime()
    runtime.context["channel_user_id"] = "ou_group_sender_1"
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    output = _run_task_tool(
        runtime=runtime,
        description="运行子任务",
        prompt="collect diagnostics",
        subagent_type="general-purpose",
        tool_call_id="tc-channel-id",
    )

    message = _task_tool_message(output)
    assert message.content == "Task Succeeded. Result: done"
    assert captured["executor_kwargs"]["channel_user_id"] == "ou_group_sender_1"


def test_task_tool_forwards_is_internal_true_to_executor(monkeypatch):
    """is_internal=True must propagate to SubagentExecutor."""
    runtime = _make_runtime()
    runtime.context["is_internal"] = True
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    _run_task_tool(runtime=runtime, description="test", prompt="p", subagent_type="general-purpose", tool_call_id="tc-1")
    assert captured["executor_kwargs"]["is_internal"] is True


def test_task_tool_forwards_is_internal_false_to_executor(monkeypatch):
    """is_internal=False must also propagate explicitly (not skipped)."""
    runtime = _make_runtime()
    runtime.context["is_internal"] = False
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    _run_task_tool(runtime=runtime, description="test", prompt="p", subagent_type="general-purpose", tool_call_id="tc-1")
    assert captured["executor_kwargs"]["is_internal"] is False


def test_task_tool_copies_attributes_to_executor(monkeypatch):
    """Mapping authz_attributes must be copied; mutating parent doesn't affect executor."""
    runtime = _make_runtime()
    runtime.context["authz_attributes"] = {"dept": "eng"}
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    _run_task_tool(runtime=runtime, description="test", prompt="p", subagent_type="general-purpose", tool_call_id="tc-1")
    executor_attrs = captured["executor_kwargs"]["authz_attributes"]
    assert executor_attrs == {"dept": "eng"}
    # Mutate the executor's copy; original context should not change
    executor_attrs["dept"] = "changed"
    assert runtime.context["authz_attributes"]["dept"] == "eng"


def test_task_tool_rejects_non_mapping_attributes(monkeypatch):
    """Non-Mapping authz_attributes must raise TypeError, not silently become {}."""

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    runtime = _make_runtime()
    runtime.context["authz_attributes"] = ["not", "a", "mapping"]
    with pytest.raises(TypeError, match="authz_attributes must be a Mapping"):
        _run_task_tool(runtime=runtime, description="test", prompt="p", subagent_type="general-purpose", tool_call_id="tc-1")


def test_task_tool_rejects_bash_subagent_when_host_bash_disabled(monkeypatch):
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["general-purpose"])
    monkeypatch.setattr(task_tool_module, "is_host_bash_allowed", lambda: False)

    result = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="run commands",
        subagent_type="bash",
        tool_call_id="tc-bash",
    )

    message = _task_tool_message(result)
    assert isinstance(message.content, str)
    assert message.content.startswith("Task failed. Error: Bash subagent is disabled")
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert message.additional_kwargs[SUBAGENT_ERROR_KEY] == LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE


def test_task_tool_threads_runtime_app_config_to_subagent_dependencies(monkeypatch):
    app_config = object()
    config = _make_subagent_config(name="bash")
    runtime = _make_runtime(app_config=app_config)
    events = []
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            captured["prompt"] = prompt
            return task_id or "generated-task-id"

    def fake_get_available_subagent_names(*, app_config):
        captured["names_app_config"] = app_config
        return ["bash"]

    def fake_get_subagent_config(name, *, app_config):
        captured["config_lookup"] = (name, app_config)
        return config

    def fake_is_host_bash_allowed(config):
        captured["bash_gate_app_config"] = config
        return True

    def fake_get_available_tools(**kwargs):
        captured["tools_kwargs"] = kwargs
        return ["tool-a"]

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", fake_get_available_subagent_names)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", fake_get_subagent_config)
    monkeypatch.setattr(task_tool_module, "is_host_bash_allowed", fake_is_host_bash_allowed)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", fake_get_available_tools)

    output = _run_task_tool(
        runtime=runtime,
        description="运行命令",
        prompt="inspect files",
        subagent_type="bash",
        tool_call_id="tc-explicit-config",
    )

    message = _task_tool_message(output)
    assert message.content == "Task Succeeded. Result: done"
    assert captured["names_app_config"] is app_config
    assert captured["config_lookup"] == ("bash", app_config)
    assert captured["bash_gate_app_config"] is app_config
    assert captured["tools_kwargs"]["app_config"] is app_config
    assert captured["executor_kwargs"]["app_config"] is app_config
    assert captured["executor_kwargs"]["tools"] == ["tool-a"]


def test_task_tool_emits_running_and_completed_events(monkeypatch):
    config = _make_subagent_config()
    runtime = _make_runtime()
    runtime.context["deerflow_trace_id"] = "task-trace-1"
    events = []
    dispatched_events = []
    captured = {}
    polled_execution_ids = []
    cleaned_execution_ids = []
    get_available_tools = MagicMock(return_value=["tool-a", "tool-b"])

    async def fake_emit_custom_event(payload, *, writer):
        writer(payload)
        dispatched_events.append(payload)

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            captured["prompt"] = prompt
            captured["task_id"] = task_id
            return "execution-456"

    # Simulate two polling rounds: first running (with one message), then completed.
    responses = iter(
        [
            _make_result(FakeSubagentStatus.RUNNING, ai_messages=[{"id": "m1", "content": "phase-1"}]),
            _make_result(
                FakeSubagentStatus.COMPLETED,
                ai_messages=[{"id": "m1", "content": "phase-1"}, {"id": "m2", "content": "phase-2"}],
                result="all done",
            ),
        ]
    )

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    def get_result(execution_id):
        polled_execution_ids.append(execution_id)
        return next(responses)

    monkeypatch.setattr(task_tool_module, "get_background_task_result", get_result)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", cleaned_execution_ids.append)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", fake_emit_custom_event)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    # task_tool lazily imports from deerflow.tools at call time, so patch that module-level function.
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools)

    output = _run_task_tool(
        runtime=runtime,
        prompt="collect diagnostics",
        subagent_type="general-purpose",
        tool_call_id="tc-123",
    )

    message = _task_tool_message(output)
    assert message.content == "Task Succeeded. Result: all done"
    assert captured["prompt"] == "collect diagnostics"
    assert captured["task_id"] == "tc-123"
    assert captured["executor_kwargs"]["thread_id"] == "thread-1"
    assert captured["executor_kwargs"]["parent_model"] == "ark-model"
    assert captured["executor_kwargs"]["deerflow_trace_id"] == "task-trace-1"
    assert captured["executor_kwargs"]["config"].max_turns == config.max_turns
    # Skills are no longer appended to system_prompt; they are loaded per-session
    # by SubagentExecutor and injected as conversation items (Codex pattern).
    assert captured["executor_kwargs"]["config"].system_prompt == "Base system prompt"

    get_available_tools.assert_called_once_with(model_name="ark-model", groups=None, subagent_enabled=False, include_upload_tool=False)

    event_types = [e["type"] for e in events]
    assert event_types == ["task_started", "task_running", "task_running", "task_completed"]
    assert dispatched_events == events
    assert polled_execution_ids == ["execution-456", "execution-456"]
    assert cleaned_execution_ids == ["execution-456"]
    assert {event["task_id"] for event in events} == {"tc-123"}
    assert events[0]["description"] == "collect diagnostics"
    assert events[0]["model_name"] == "ark-model"
    assert events[-1]["result"] == "all done"


def test_task_tool_emits_cumulative_usage_on_running_event(monkeypatch):
    config = _make_subagent_config()
    runtime = _make_runtime()
    events = []
    usage_records = [
        {
            "source_run_id": "subagent-call-1",
            "caller": "subagent:general-purpose",
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        }
    ]
    responses = iter(
        [
            _make_result(
                FakeSubagentStatus.RUNNING,
                ai_messages=[{"id": "m1", "content": "researching"}],
                token_usage_records=usage_records,
            ),
            _make_result(
                FakeSubagentStatus.COMPLETED,
                result="done",
                token_usage_records=usage_records,
            ),
        ]
    )

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: next(responses))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    _run_task_tool(
        runtime=runtime,
        description="research",
        prompt="find facts",
        subagent_type="general-purpose",
        tool_call_id="tc-live-usage",
    )

    running = next(event for event in events if event["type"] == "task_running")
    assert running["usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }
    assert running["model_name"] == "ark-model"


def test_task_tool_propagates_tool_groups_to_subagent(monkeypatch):
    """Verify tool_groups from parent metadata are passed to get_available_tools(groups=...)."""
    config = _make_subagent_config()
    parent_tool_groups = ["file:read", "file:write", "bash"]
    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {"workspace_path": "/tmp/workspace"},
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "ark-model", "trace_id": "trace-1", "tool_groups": parent_tool_groups}},
    )
    events = []
    get_available_tools = MagicMock(return_value=["tool-a"])

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools)

    output = _run_task_tool(
        runtime=runtime,
        description="执行任务",
        prompt="file work only",
        subagent_type="general-purpose",
        tool_call_id="tc-groups",
    )

    assert _task_tool_message(output).content == "Task Succeeded. Result: done"
    # The key assertion: groups should be propagated from parent metadata
    get_available_tools.assert_called_once_with(model_name="ark-model", groups=parent_tool_groups, subagent_enabled=False, include_upload_tool=False)


def test_task_tool_uses_subagent_model_override_for_tool_loading(monkeypatch):
    """Subagent model overrides should drive model-gated tool loading."""
    config = SubagentConfig(
        name="general-purpose",
        description="General helper",
        system_prompt="Base system prompt",
        model="vision-subagent-model",
        max_turns=50,
        timeout_seconds=10,
    )
    runtime = _make_runtime()
    runtime.config["metadata"]["model_name"] = "parent-text-model"
    events = []
    get_available_tools = MagicMock(return_value=[])

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools)

    output = _run_task_tool(
        runtime=runtime,
        description="inspect image",
        prompt="inspect the uploaded image",
        subagent_type="general-purpose",
        tool_call_id="tc-issue-2543",
    )

    assert _task_tool_message(output).content == "Task Succeeded. Result: done"
    get_available_tools.assert_called_once_with(
        model_name="vision-subagent-model",
        groups=None,
        subagent_enabled=False,
        include_upload_tool=False,
    )


def test_task_tool_inherits_parent_skill_allowlist_for_default_subagent(monkeypatch):
    config = _make_subagent_config()
    runtime = _make_runtime()
    runtime.config["metadata"]["available_skills"] = ["safe-skill"]
    events = []
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["config"] = kwargs["config"]

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    output = _run_task_tool(
        runtime=runtime,
        description="执行任务",
        prompt="use skills",
        subagent_type="general-purpose",
        tool_call_id="tc-skills",
    )

    assert _task_tool_message(output).content == "Task Succeeded. Result: done"
    assert captured["config"].skills == ["safe-skill"]


def test_task_tool_intersects_parent_and_subagent_skill_allowlists(monkeypatch):
    config = _make_subagent_config()
    config = SubagentConfig(
        name=config.name,
        description=config.description,
        system_prompt=config.system_prompt,
        max_turns=config.max_turns,
        timeout_seconds=config.timeout_seconds,
        skills=["safe-skill", "other-skill"],
    )
    runtime = _make_runtime()
    runtime.config["metadata"]["available_skills"] = ["safe-skill"]
    events = []
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["config"] = kwargs["config"]

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    output = _run_task_tool(
        runtime=runtime,
        description="执行任务",
        prompt="use skills",
        subagent_type="general-purpose",
        tool_call_id="tc-skills-intersection",
    )

    assert _task_tool_message(output).content == "Task Succeeded. Result: done"
    assert captured["config"].skills == ["safe-skill"]


def test_task_tool_no_tool_groups_passes_none(monkeypatch):
    """Verify that when metadata has no tool_groups, groups=None is passed (backward compat)."""
    config = _make_subagent_config()
    # Default _make_runtime() has no tool_groups in metadata
    runtime = _make_runtime()
    events = []
    get_available_tools = MagicMock(return_value=[])

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="ok"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools)

    output = _run_task_tool(
        runtime=runtime,
        description="执行任务",
        prompt="normal work",
        subagent_type="general-purpose",
        tool_call_id="tc-no-groups",
    )

    assert _task_tool_message(output).content == "Task Succeeded. Result: ok"
    # No tool_groups in metadata → groups=None (default behavior preserved)
    get_available_tools.assert_called_once_with(model_name="ark-model", groups=None, subagent_enabled=False, include_upload_tool=False)


def test_task_tool_runtime_none_passes_groups_none(monkeypatch):
    """Verify that when runtime is None, groups=None is passed (e.g., unknown subagent path exits early, but tools still load correctly)."""
    config = _make_subagent_config()
    events = []
    get_available_tools = MagicMock(return_value=[])

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="ok"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools)
    fallback_app_config = SimpleNamespace(models=[SimpleNamespace(name="default-model")])
    monkeypatch.setattr(task_tool_module, "get_app_config", lambda: fallback_app_config)

    output = _run_task_tool(
        runtime=None,
        description="执行任务",
        prompt="no runtime",
        subagent_type="general-purpose",
        tool_call_id="tc-no-runtime",
    )

    assert _task_tool_message(output).content == "Task Succeeded. Result: ok"
    # runtime is None -> metadata is empty dict -> groups=None, model falls back to app default.
    get_available_tools.assert_called_once_with(
        model_name="default-model",
        groups=None,
        subagent_enabled=False,
        include_upload_tool=False,
        app_config=fallback_app_config,
    )

    config = _make_subagent_config()
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.FAILED, error="subagent crashed"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="do fail",
        subagent_type="general-purpose",
        tool_call_id="tc-fail",
    )

    message = _task_tool_message(output)
    assert message.content == "Task failed. Error: subagent crashed"
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert message.additional_kwargs[SUBAGENT_ERROR_KEY] == "subagent crashed"
    assert events[-1]["type"] == "task_failed"
    assert events[-1]["error"] == "subagent crashed"


def test_task_tool_returns_timed_out_message(monkeypatch):
    config = _make_subagent_config()
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.TIMED_OUT, error="timeout"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="do timeout",
        subagent_type="general-purpose",
        tool_call_id="tc-timeout",
    )

    message = _task_tool_message(output)
    assert message.content == "Task timed out. Error: timeout"
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "timed_out"
    assert message.additional_kwargs[SUBAGENT_ERROR_KEY] == "timeout"
    assert events[-1]["type"] == "task_timed_out"
    assert events[-1]["error"] == "timeout"


def test_task_tool_surfaces_stop_reason_for_capped_run(monkeypatch):
    """#3875 Phase 2: a capped run keeps a normal status (``completed`` when it
    produced a final answer) and carries the cap on ``subagent_stop_reason``.
    The polling loop threads ``result.stop_reason`` through so the lead's
    ToolMessage carries it without parsing the result text."""
    config = _make_subagent_config()
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="investigated 3 of 5 sources", stop_reason="token_capped"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="do capped work",
        subagent_type="general-purpose",
        tool_call_id="tc-capped",
    )

    message = _task_tool_message(output)
    # The cap is folded into the model-visible text...
    assert message.content.startswith("Task Succeeded (capped: token budget)")
    assert "investigated 3 of 5 sources" in message.content
    # ...and carried structurally on the additive field.
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "completed"
    assert message.additional_kwargs[SUBAGENT_STOP_REASON_KEY] == "token_capped"
    assert message.additional_kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "investigated 3 of 5 sources"
    assert len(message.additional_kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64
    assert events[-1]["type"] == "task_completed"


def test_task_tool_polling_safety_timeout(monkeypatch):
    config = _make_subagent_config()
    # Keep max_poll_count small for test speed: (1 + 60) // 5 = 12
    config.timeout_seconds = 1
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    receipts = [
        {
            "id": "r1",
            "tool_call_id": "tc-before-poll-timeout",
            "tool_name": "write_file",
            "status": "success",
            "args_sha256": "a" * 16,
            "output_sha256": "b" * 16,
            "output_bytes": 3,
            "created_at": "2026-08-28T00:00:00+00:00",
        }
    ]
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[], tool_receipts=receipts),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="never finish",
        subagent_type="general-purpose",
        tool_call_id="tc-safety-timeout",
    )

    message = _task_tool_message(output)
    assert isinstance(message.content, str)
    assert message.content.startswith("Task polling timed out after 0 minutes")
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "polling_timed_out"
    assert message.additional_kwargs[SUBAGENT_ERROR_KEY] == message.content
    assert message.additional_kwargs[SUBAGENT_TOOL_RECEIPTS_KEY] == receipts
    assert events[0]["type"] == "task_started"
    assert events[-1]["type"] == "task_timed_out"


def test_cleanup_called_on_completed(monkeypatch):
    """Verify cleanup_background_task is called when task completes."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="complete task",
        subagent_type="general-purpose",
        tool_call_id="tc-cleanup-completed",
    )

    assert _task_tool_message(output).content == "Task Succeeded. Result: done"
    assert cleanup_calls == ["tc-cleanup-completed"]


def test_cleanup_called_on_failed(monkeypatch):
    """Verify cleanup_background_task is called when task fails."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.FAILED, error="error"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="fail task",
        subagent_type="general-purpose",
        tool_call_id="tc-cleanup-failed",
    )

    assert _task_tool_message(output).content == "Task failed. Error: error"
    assert cleanup_calls == ["tc-cleanup-failed"]


def test_cleanup_called_on_timed_out(monkeypatch):
    """Verify cleanup_background_task is called when task times out."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.TIMED_OUT, error="timeout"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="timeout task",
        subagent_type="general-purpose",
        tool_call_id="tc-cleanup-timedout",
    )

    assert _task_tool_message(output).content == "Task timed out. Error: timeout"
    assert cleanup_calls == ["tc-cleanup-timedout"]


def test_cleanup_not_called_on_polling_safety_timeout(monkeypatch):
    """Verify cleanup_background_task is NOT called directly on polling safety timeout.

    The task is still RUNNING so it cannot be safely removed yet. Instead,
    cooperative cancellation is requested and a deferred cleanup is scheduled.
    """
    config = _make_subagent_config()
    # Keep max_poll_count small for test speed: (1 + 60) // 5 = 12
    config.timeout_seconds = 1
    events = []
    cleanup_calls = []
    cancel_requests = []
    scheduled_cleanups = []

    class DummyCleanupTask:
        def add_done_callback(self, _callback):
            return None

    def fake_run_on_isolated_subagent_loop(coro):
        scheduled_cleanups.append(coro)
        coro.close()
        return DummyCleanupTask()

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", fake_run_on_isolated_subagent_loop)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )
    monkeypatch.setattr(
        task_tool_module,
        "request_cancel_background_task",
        lambda task_id: cancel_requests.append(task_id),
    )

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="never finish",
        subagent_type="general-purpose",
        tool_call_id="tc-no-cleanup-safety-timeout",
    )

    message = _task_tool_message(output)
    assert isinstance(message.content, str)
    assert message.content.startswith("Task polling timed out after 0 minutes")
    # cleanup_background_task must NOT be called directly (task is still RUNNING)
    assert cleanup_calls == []
    # cooperative cancellation must be requested
    assert cancel_requests == ["tc-no-cleanup-safety-timeout"]
    # a deferred cleanup coroutine must be scheduled
    assert len(scheduled_cleanups) == 1


def test_cleanup_scheduled_on_cancellation(monkeypatch):
    """Verify cancellation handler synchronously cleans up after shielded wait."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []
    poll_count = 0

    def get_result(_: str):
        nonlocal poll_count
        poll_count += 1
        # Main loop polls RUNNING twice, then shielded wait gets COMPLETED
        if poll_count <= 2:
            return _make_result(FakeSubagentStatus.RUNNING, ai_messages=[])
        return _make_result(FakeSubagentStatus.COMPLETED, result="done")

    sleep_count = 0

    async def cancel_on_second_sleep(_: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(task_tool_module, "get_background_task_result", get_result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", cancel_on_second_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    with pytest.raises(asyncio.CancelledError):
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="cancel task",
            subagent_type="general-purpose",
            tool_call_id="tc-cancelled-cleanup",
        )

    # Cleanup happens synchronously within the cancellation handler
    assert cleanup_calls == ["tc-cancelled-cleanup"]


def test_task_started_emit_failure_stops_subagent_reports_usage_and_cleans_up(monkeypatch):
    """An exception from the task_started emit — a real await point before the
    polling loop — must mirror the cancellation unwind: cooperative cancel,
    final usage reported to the parent RunJournal, and synchronous registry
    cleanup. A detached cleanup task would not survive asyncio.run() teardown
    on the synchronous tool path, so the terminal case must clean up directly."""
    config = _make_subagent_config()
    cancel_calls: list[str] = []
    cleanup_calls: list[str] = []
    reported: list = []
    terminal_result = _make_result(FakeSubagentStatus.COMPLETED, result="done")

    async def failing_emit(event, *, writer=None):
        raise RuntimeError("emit boom")

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: terminal_result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", failing_emit)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda execution_id: cancel_calls.append(execution_id))
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda execution_id: cleanup_calls.append(execution_id))
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda runtime, result: reported.append(result))
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    with pytest.raises(RuntimeError, match="emit boom"):
        _run_task_tool(
            runtime=_make_runtime(),
            description="test",
            prompt="p",
            subagent_type="general-purpose",
            tool_call_id="tc-emit-fail",
        )

    assert cancel_calls == ["tc-emit-fail"], "emit failure must cooperatively cancel the subagent"
    assert reported == [terminal_result], "emit failure must still report the subagent's final usage"
    assert cleanup_calls == ["tc-emit-fail"], "terminal subagent must be cleaned up synchronously"


def test_unexpected_poller_error_deferred_cleanup_survives_sync_invocation(monkeypatch):
    """Non-terminal fallback under synchronous tool invocation: the poller
    dies while the subagent never reaches terminal within the bounded wait, so
    removal is deferred — and the deferred cleanup must actually run after
    ``asyncio.run()`` tears down the caller loop. It runs on a loop that
    outlives the poller (the process-owned persistent subagent loop in
    production; an equivalent long-lived loop here), never on a caller-loop
    task, which teardown cancels. The unwind, scheduling wrapper, and cleanup
    coroutine are the real production code paths."""
    config = _make_subagent_config()
    reported: list = []
    cancel_calls: list[str] = []
    cleanup_calls: list[str] = []
    emit_calls = 0
    scheduled_handles: list = []
    main_thread = threading.current_thread()
    caller_loop_finished = threading.Event()
    execution_id = "exec-sync-poller-death"
    result = SimpleNamespace(
        status=FakeSubagentStatus.RUNNING,
        ai_messages=["partial"],
        result=None,
    )

    persistent_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=persistent_loop.run_forever, name="test-persistent-cleanup-loop", daemon=True)
    loop_thread.start()

    async def fail_on_status_emit(event, *, writer=None):
        nonlocal emit_calls
        emit_calls += 1
        if emit_calls >= 2:
            raise RuntimeError("status emit boom")
        return None

    def flip_terminal_off_caller_thread(queried_id):
        # The poller, its bounded unwind wait, and the final snapshot all run
        # on the caller thread (asyncio.run) and must keep seeing RUNNING so
        # the deferred path is taken; once the deferred cleaner polls from the
        # long-lived loop thread, the subagent reaches terminal. Gated on the
        # caller loop actually closing so the loop-pinned final report is
        # deterministically dropped here (while that loop is alive, delivery
        # is legitimate — that case is pinned by the live-loop test).
        if threading.current_thread() is not main_thread:
            caller_loop_finished.wait(timeout=10.0)
            result.status = FakeSubagentStatus.COMPLETED
        return result

    def transport_to_persistent_loop(coro):
        # Same primitive production uses via run_on_isolated_subagent_loop:
        # pin the coroutine to a loop that outlives the caller's asyncio.run()
        # loop instead of a caller-loop asyncio.create_task.
        handle = asyncio.run_coroutine_threadsafe(coro, persistent_loop)
        scheduled_handles.append(handle)
        return handle

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: execution_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", flip_terminal_off_caller_thread)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", fail_on_status_emit)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda execution_id_arg: cancel_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda execution_id_arg: cleanup_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", transport_to_persistent_loop)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda runtime, r, **kwargs: reported.append(r))
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    try:
        with pytest.raises(RuntimeError, match="status emit boom"):
            _run_task_tool(
                runtime=_make_runtime(),
                description="test",
                prompt="p",
                subagent_type="general-purpose",
                tool_call_id="tc-poll-fail-sync",
            )
        # asyncio.run() has returned: the caller loop is fully closed now, so
        # the deferred cleaner may safely flip to terminal.
        caller_loop_finished.set()

        # The caller loop is torn down by asyncio.run() at this point. The
        # cooperative cancel already fired and the snapshot usage was
        # reported on the caller loop itself... The stub accepts **kwargs so
        # the deferred final report (final=True) would ALSO be recorded if it
        # were ever delivered — the caller loop is closed by the time the
        # deferred cleaner reaches terminal, so the loop-pinned delivery
        # intentionally drops it and the count stays at exactly one.
        assert cancel_calls == [execution_id], "unexpected poller exit must cooperatively cancel the subagent"
        assert reported == [result], "snapshot usage reported on the caller loop; closed-loop final report must be dropped, not threaded in"

        # ...and the deferred cleanup, pinned to the long-lived loop, removes
        # the registry entry even though the caller loop that scheduled it is
        # gone. A caller-loop asyncio.create_task would have been cancelled at
        # teardown and this would time out.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not cleanup_calls:
            time.sleep(0.05)
        assert cleanup_calls == [execution_id], "deferred cleanup must run after caller-loop teardown"
        assert result.status is FakeSubagentStatus.COMPLETED
    finally:
        for handle in scheduled_handles:
            try:
                handle.result(timeout=5)
            except Exception:
                pass
            task_tool_module._deferred_cleanup_tasks.discard(handle)
        persistent_loop.call_soon_threadsafe(persistent_loop.stop)
        loop_thread.join(timeout=5)
        persistent_loop.close()


def test_unexpected_error_with_failing_status_accessor_preserves_exception_and_attaches_cleanup(monkeypatch):
    """Persistent status-lookup failure: the registry accessor itself raises
    during polling and would raise again during finalization. The unwind must
    still (1) cooperatively cancel, (2) attach cleanup through a mechanism
    that does not depend on the failing accessor — the deferred cleaner, whose
    last resort force-removes the unreadable entry — and (3) re-raise the
    ORIGINAL poller exception, never one raised by finalization."""
    config = _make_subagent_config()
    cancel_calls: list[str] = []
    cleanup_calls: list[str] = []
    force_cleanup_calls: list[str] = []
    reported: list = []
    emit_calls = 0
    scheduled_handles: list = []
    execution_id = "exec-status-accessor-broken"

    persistent_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=persistent_loop.run_forever, name="test-broken-status-cleanup-loop", daemon=True)
    loop_thread.start()

    async def ok_emit(event, *, writer=None):
        nonlocal emit_calls
        emit_calls += 1
        return None

    def broken_accessor(queried_id):
        raise RuntimeError("registry lookup boom")

    def transport_to_persistent_loop(coro):
        handle = asyncio.run_coroutine_threadsafe(coro, persistent_loop)
        scheduled_handles.append(handle)
        return handle

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: execution_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", broken_accessor)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", ok_emit)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda execution_id_arg: cancel_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda execution_id_arg: cleanup_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "force_cleanup_background_task", lambda execution_id_arg: force_cleanup_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", transport_to_persistent_loop)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda runtime, r, **kwargs: reported.append(r))
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    try:
        # The ORIGINAL exception is the accessor failure from the polling
        # loop; finalization re-reading through the same broken accessor must
        # not replace it with anything else.
        with pytest.raises(RuntimeError, match="registry lookup boom"):
            _run_task_tool(
                runtime=_make_runtime(),
                description="test",
                prompt="p",
                subagent_type="general-purpose",
                tool_call_id=execution_id,
            )

        assert cancel_calls == [execution_id], "broken status accessor must not prevent cooperative cancellation"
        assert reported == [], "an unreadable result must not be force-reported"

        # The deferred cleaner keeps hitting the broken accessor and, once its
        # poll budget is exhausted, force-removes the entry instead of leaking
        # it forever.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not force_cleanup_calls:
            time.sleep(0.05)
        assert force_cleanup_calls == [execution_id], "deferred cleaner must force-remove an unreadable registry entry"
        assert cleanup_calls == [], "terminal-gated cleanup must not run for an unreadable entry"
    finally:
        for handle in scheduled_handles:
            try:
                handle.result(timeout=5)
            except Exception:
                pass
            task_tool_module._deferred_cleanup_tasks.discard(handle)
        persistent_loop.call_soon_threadsafe(persistent_loop.stop)
        loop_thread.join(timeout=5)
        persistent_loop.close()


def test_unexpected_error_re_raised_promptly_via_short_grace(monkeypatch):
    """A generic poller failure must not stall the parent run for the full
    execution timeout (~31 minutes by default) waiting on a subagent that may
    never observe cooperative cancellation. The unwind waits only a short
    grace period, then hands the remaining lifecycle to the deferred cleaner
    and re-raises the original error promptly."""
    config = _make_subagent_config()
    cancel_calls: list[str] = []
    scheduled_cleanups: list = []
    emit_calls = 0
    started = time.monotonic()

    class DummyCleanupTask:
        def add_done_callback(self, _callback):
            return None

    def fake_run_on_isolated_subagent_loop(coro):
        scheduled_cleanups.append(coro)
        coro.close()
        return DummyCleanupTask()

    async def fail_on_second_emit(event, *, writer=None):
        nonlocal emit_calls
        emit_calls += 1
        if emit_calls >= 2:
            raise RuntimeError("status emit boom")
        return None

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: "exec-grace"}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=["partial"]))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", fail_on_second_emit)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda execution_id: cancel_calls.append(execution_id))
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", fake_run_on_isolated_subagent_loop)
    # Real asyncio.sleep + a tiny grace window: the unwind must return within
    # the grace bound, not after max_poll_count * 5s.
    monkeypatch.setattr(task_tool_module, "_UNEXPECTED_EXIT_GRACE_SECONDS", 0.2)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    with pytest.raises(RuntimeError, match="status emit boom"):
        _run_task_tool(
            runtime=_make_runtime(),
            description="test",
            prompt="p",
            subagent_type="general-purpose",
            tool_call_id="tc-grace",
        )

    elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"unexpected-error unwind must re-raise promptly, took {elapsed:.1f}s"
    assert cancel_calls == ["exec-grace"], "grace-bounded unwind must still request cooperative cancellation"
    assert len(scheduled_cleanups) == 1, "remaining lifecycle must be handed to the deferred cleaner"


def test_deferred_cleanup_drops_final_usage_when_parent_loop_closed(monkeypatch):
    """The deferred cleaner removes the terminal entry, and the loop-pinned
    final usage report is DROPPED — not threaded in — when the parent loop
    that was captured at unwind time is already closed.

    On the synchronous ``asyncio.run`` path the run has finished and persisted
    its completion data by the time the deferred cleaner reaches a terminal
    result, so recording into the dead run's journal would account nothing;
    a ``to_thread`` report would instead race the journal from a foreign
    thread while some other run's loop may still touch it."""
    config = _make_subagent_config()
    cleanup_calls: list[str] = []
    cancel_calls: list[str] = []
    emit_calls = 0
    scheduled_handles: list = []
    main_thread = threading.current_thread()
    caller_loop_finished = threading.Event()
    execution_id = "exec-deferred-final-usage"
    result = SimpleNamespace(
        status=FakeSubagentStatus.RUNNING,
        ai_messages=["partial"],
        result=None,
        # The unwind's snapshot report already ran and set this flag; the
        # deferred final report must bypass it rather than return early.
        usage_reported=True,
        token_usage_records=[{"source_run_id": "run-1", "total_tokens": 10}],
    )

    class LoopPinnedJournal:
        """Real-recorder path: captures the running loop of every call, so a
        cross-thread report surfaces as a wrong-loop (or no-loop) entry."""

        def __init__(self) -> None:
            self.calls: list[tuple[object, list]] = []

        def record_external_llm_usage_records(self, records):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            self.calls.append((loop, list(records)))

    journal = LoopPinnedJournal()

    persistent_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=persistent_loop.run_forever, name="test-final-usage-cleanup-loop", daemon=True)
    loop_thread.start()

    async def fail_on_status_emit(event, *, writer=None):
        nonlocal emit_calls
        emit_calls += 1
        if emit_calls >= 2:
            raise RuntimeError("status emit boom")
        return None

    def flip_terminal_and_grow_usage_after_caller_teardown(queried_id):
        if threading.current_thread() is not main_thread:
            # Deterministic ordering: only reach terminal once the caller's
            # asyncio.run() loop has fully returned and closed. Flipping any
            # earlier would let the loop-pinned report legitimately deliver
            # while that loop is still alive (correct, but not what this
            # test pins down).
            caller_loop_finished.wait(timeout=10.0)
            result.status = FakeSubagentStatus.COMPLETED
            # Usage accumulated after the snapshot the unwind reported.
            result.token_usage_records = [
                {"source_run_id": "run-1", "total_tokens": 10},
                {"source_run_id": "run-2", "total_tokens": 25},
            ]
        return result

    def transport_to_persistent_loop(coro):
        handle = asyncio.run_coroutine_threadsafe(coro, persistent_loop)
        scheduled_handles.append(handle)
        return handle

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: execution_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", flip_terminal_and_grow_usage_after_caller_teardown)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", fail_on_status_emit)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda execution_id_arg: cancel_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda execution_id_arg: cleanup_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", transport_to_persistent_loop)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": "/tmp/workspace",
                "uploads_path": "/tmp/uploads",
                "outputs_path": "/tmp/outputs",
            },
        },
        context={"thread_id": "thread-1"},
        config={
            "metadata": {"model_name": "ark-model", "trace_id": "trace-1"},
            "callbacks": [journal],
        },
    )

    try:
        with pytest.raises(RuntimeError, match="status emit boom"):
            _run_task_tool(
                runtime=runtime,
                description="test",
                prompt="p",
                subagent_type="general-purpose",
                tool_call_id="tc-final-usage",
            )
        # asyncio.run() has returned: the caller loop is fully closed now, so
        # the deferred cleaner may safely flip to terminal.
        caller_loop_finished.set()

        assert cancel_calls == [execution_id]

        # The deferred cleaner reaches terminal off the caller thread and
        # removes the entry. The caller loop is closed by then, so the
        # loop-pinned final report is dropped: the recorder is real and
        # present (resolved at unwind time), so an empty journal proves the
        # drop is loop-based — a worker-thread report would have recorded
        # with no running loop instead.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not cleanup_calls:
            time.sleep(0.05)
        assert cleanup_calls == [execution_id], "deferred cleanup must remove the terminal entry"
        assert journal.calls == [], "closed parent loop must drop the final report, not deliver it cross-thread"
    finally:
        for handle in scheduled_handles:
            try:
                handle.result(timeout=5)
            except Exception:
                pass
            task_tool_module._deferred_cleanup_tasks.discard(handle)
        persistent_loop.call_soon_threadsafe(persistent_loop.stop)
        loop_thread.join(timeout=5)
        persistent_loop.close()


def test_deferred_final_usage_reported_on_parent_loop_with_real_recorder(monkeypatch):
    """Gateway shape: the parent run loop stays alive after the unexpected
    poller exit, and the deferred final usage report must be DELIVERED onto
    that loop — never from the deferred cleaner's thread.

    This exercises the real recorder path (``_find_usage_recorder`` →
    ``_report_subagent_usage`` → ``journal.record_external_llm_usage_records``)
    instead of stubbing ``_report_subagent_usage``: the journal captures the
    running loop of every call, so a cross-thread report would surface here as
    a wrong-loop (or no-loop) entry — the exact hazard ``deerflow_loop_bound``
    exists to prevent."""
    config = _make_subagent_config()
    cleanup_calls: list[str] = []
    cancel_calls: list[str] = []
    emit_calls = 0
    scheduled_handles: list = []
    execution_id = "exec-final-usage-live-loop"
    result = SimpleNamespace(
        status=FakeSubagentStatus.RUNNING,
        ai_messages=["partial"],
        result=None,
        # The snapshot report already ran during the run; the final report
        # must bypass this flag and deliver the post-snapshot delta.
        usage_reported=True,
        token_usage_records=[{"source_run_id": "run-1", "total_tokens": 10}],
    )

    class LoopPinnedJournal:
        def __init__(self) -> None:
            self.calls: list[tuple[object, list]] = []

        def record_external_llm_usage_records(self, records):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            self.calls.append((loop, list(records)))

    journal = LoopPinnedJournal()

    parent_loop = asyncio.new_event_loop()
    parent_thread = threading.Thread(target=parent_loop.run_forever, name="test-live-parent-run-loop", daemon=True)
    parent_thread.start()
    persistent_loop = asyncio.new_event_loop()
    persistent_thread = threading.Thread(target=persistent_loop.run_forever, name="test-final-usage-persistent-loop", daemon=True)
    persistent_thread.start()

    async def fail_on_status_emit(event, *, writer=None):
        nonlocal emit_calls
        emit_calls += 1
        if emit_calls >= 2:
            raise RuntimeError("status emit boom")
        return None

    def flip_terminal_and_grow_usage_from_deferred_thread(queried_id):
        if threading.current_thread() is persistent_thread:
            result.status = FakeSubagentStatus.COMPLETED
            # Usage accumulated after the snapshot the unwind reported.
            result.token_usage_records = [
                {"source_run_id": "run-1", "total_tokens": 10},
                {"source_run_id": "run-2", "total_tokens": 25},
            ]
        return result

    def transport_to_persistent_loop(coro):
        handle = asyncio.run_coroutine_threadsafe(coro, persistent_loop)
        scheduled_handles.append(handle)
        return handle

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: execution_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", flip_terminal_and_grow_usage_from_deferred_thread)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", fail_on_status_emit)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda execution_id_arg: cancel_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda execution_id_arg: cleanup_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", transport_to_persistent_loop)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": "/tmp/workspace",
                "uploads_path": "/tmp/uploads",
                "outputs_path": "/tmp/outputs",
            },
        },
        context={"thread_id": "thread-1"},
        config={
            "metadata": {"model_name": "ark-model", "trace_id": "trace-1"},
            "callbacks": [journal],
        },
    )

    try:
        coroutine = getattr(task_tool_module.task_tool, "coroutine", None)
        assert coroutine is not None
        tool_future = asyncio.run_coroutine_threadsafe(
            coroutine(
                runtime=runtime,
                description="test",
                prompt="p",
                subagent_type="general-purpose",
                tool_call_id="tc-final-usage-live",
            ),
            parent_loop,
        )
        with pytest.raises(RuntimeError, match="status emit boom"):
            tool_future.result(timeout=10)
        assert cancel_calls == [execution_id]

        # The deferred cleaner (persistent loop) reaches terminal, pins the
        # final report onto the still-live parent loop, and removes the entry.
        # Wait for the report to be OBSERVED on the parent loop, not merely
        # scheduled — the journal only records once the callback actually ran.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not journal.calls:
            time.sleep(0.05)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not cleanup_calls:
            time.sleep(0.05)
        assert cleanup_calls == [execution_id], "deferred cleanup must remove the terminal entry"

        assert len(journal.calls) == 1, "exactly one final usage report must be delivered"
        observed_loop, observed_records = journal.calls[0]
        assert observed_loop is parent_loop, f"record_external_llm_usage_records must run on the parent run loop that owns the RunJournal — got {observed_loop!r}"
        assert [r["source_run_id"] for r in observed_records] == ["run-1", "run-2"], "the final report must include the post-snapshot delta records"
        assert result.usage_reported is True
    finally:
        for handle in scheduled_handles:
            try:
                handle.result(timeout=5)
            except Exception:
                pass
            task_tool_module._deferred_cleanup_tasks.discard(handle)
        persistent_loop.call_soon_threadsafe(persistent_loop.stop)
        persistent_thread.join(timeout=5)
        persistent_loop.close()
        parent_loop.call_soon_threadsafe(parent_loop.stop)
        parent_thread.join(timeout=5)
        parent_loop.close()


@pytest.mark.asyncio
async def test_unexpected_error_grace_wait_cancellation_is_honored(monkeypatch):
    """A graph-node cancellation landing inside the generic-error grace wait
    must surface as CancelledError, not the original poller error.

    The shared unwind absorbs CancelledError (its never-raise contract keeps
    the deferred-cleanup attachment alive), so without the post-unwind
    ``task.cancelling()`` re-check the node would end as a failed tool call
    instead of an interrupted run."""
    config = _make_subagent_config()
    cancel_calls: list[str] = []
    emit_calls = 0
    unwind_entered = asyncio.Event()
    execution_id = "exec-grace-cancel"

    async def fail_on_status_emit(event, *, writer=None):
        nonlocal emit_calls
        emit_calls += 1
        if emit_calls >= 2:
            raise RuntimeError("status emit boom")
        return None

    async def absorbing_finalize(runtime_arg, execution_id_arg, trace_id_arg, max_polls, grace_seconds=None):
        # Mimic the production unwind: park inside the grace wait and absorb
        # the outer cancellation, then return so the tool's generic-error
        # branch continues past the unwind.
        unwind_entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: execution_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", fail_on_status_emit)
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda execution_id_arg: cancel_calls.append(execution_id_arg))
    monkeypatch.setattr(task_tool_module, "_finalize_interrupted_subagent", absorbing_finalize)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    coroutine = getattr(task_tool_module.task_tool, "coroutine", None)
    assert coroutine is not None
    tool_task = asyncio.create_task(
        coroutine(
            runtime=_make_runtime(),
            description="test",
            prompt="p",
            subagent_type="general-purpose",
            tool_call_id="tc-grace-cancel",
        )
    )
    await asyncio.wait_for(unwind_entered.wait(), timeout=10.0)
    tool_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tool_task
    assert cancel_calls == [execution_id]


@pytest.mark.asyncio
async def test_deferred_cleanup_does_not_retain_runtime(monkeypatch):
    """The deferred cleaner must retain only the resolved usage recorder and
    ids — never the whole ``runtime``. The strongly-referenced cleanup task
    lives for up to the full poll budget; through ``runtime`` it would pin
    the parent run's journal and event store for that entire window, worst
    on the polling-timeout path where a stuck subagent pins its run's
    journal for a second full timeout after the tool already returned."""
    orig_sleep = asyncio.sleep
    current_loop = asyncio.get_running_loop()

    def transport_to_current_loop(coro):
        return asyncio.run_coroutine_threadsafe(coro, current_loop)

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    # Never terminal: the cleaner keeps polling for its whole budget.
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]))
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", transport_to_current_loop)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", lambda _: orig_sleep(0))

    # SimpleNamespace rejects weakref; a plain class instance does not. Only
    # runtime.config is read on the scheduling path (recorder resolution).
    class WeakrefableRuntime:
        config = {"metadata": {"model_name": "ark-model", "trace_id": "trace-1"}}

    runtime = WeakrefableRuntime()
    runtime_ref = weakref.ref(runtime)
    handle = task_tool_module._schedule_deferred_subagent_cleanup(runtime, "exec-retain", "trace-retain", 50)
    assert handle in task_tool_module._deferred_cleanup_tasks
    del runtime
    gc.collect()

    assert runtime_ref() is None, "deferred cleanup must not pin the run runtime (journal + event store) for its poll budget"

    # Let the cleaner exhaust its budget (no-op sleeps) so the handle settles.
    await asyncio.wait_for(asyncio.wrap_future(handle), timeout=10.0)
    task_tool_module._deferred_cleanup_tasks.discard(handle)


def test_execute_async_failure_leaves_no_background_residue(monkeypatch):
    """``execute_async`` raises before the poller's guarded region starts
    (e.g. the persistent subagent loop failed to spin up). The registry entry
    is rolled back inside ``execute_async`` itself (see #5086), so the tool
    must simply propagate the error — no background entry, no deferred
    cleanup dependency on the loop that just failed to start."""
    config = _make_subagent_config()
    deferred_schedules: list = []
    cleanup_calls: list[str] = []
    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type(
            "FailingExecutor",
            (),
            {
                "__init__": lambda self, **kwargs: None,
                "execute_async": lambda self, prompt, task_id=None: (_ for _ in ()).throw(RuntimeError("Timed out starting isolated subagent event loop")),
            },
        ),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda execution_id_arg: cleanup_calls.append(execution_id_arg))
    monkeypatch.setattr(
        task_tool_module,
        "run_on_isolated_subagent_loop",
        lambda coro: deferred_schedules.append(coro) or (_ for _ in ()).throw(AssertionError("deferred cleanup must not be scheduled")),
    )
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    with pytest.raises(RuntimeError, match="Timed out starting isolated subagent event loop"):
        _run_task_tool(
            runtime=_make_runtime(),
            description="test",
            prompt="p",
            subagent_type="general-purpose",
            tool_call_id="tc-executor-submit-failure",
        )
    # Nothing was registered (execute_async rolls its own entry back before
    # re-raising), so nothing may be cancelled, cleaned, or deferred either —
    # the guarded region's invariants hold vacuously before it starts.
    assert deferred_schedules == []
    assert cleanup_calls == []


def test_cancelled_cleanup_stops_after_timeout(monkeypatch):
    """Verify cancellation handler survives a shielded-wait timeout gracefully.

    When the subagent never reaches a terminal state, the shielded wait times
    out (or is interrupted), the handler reports whatever usage it can, calls
    cleanup (which is a no-op for non-terminal tasks), and re-raises.
    """
    config = _make_subagent_config()
    events = []
    report_calls = []
    cleanup_calls = []
    scheduled_cleanups = []

    # Always return RUNNING — subagent never finishes
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]),
    )

    async def cancel_on_first_sleep(_: float) -> None:
        raise asyncio.CancelledError

    def fake_report_subagent_usage(runtime, result):
        report_calls.append((runtime, result))

    class DummyCleanupTask:
        def __init__(self, coro):
            self.coro = coro

        def add_done_callback(self, callback):
            self.callback = callback

    def fake_run_on_isolated_subagent_loop(coro):
        scheduled_cleanups.append(coro)
        coro.close()
        return DummyCleanupTask(coro)

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", cancel_on_first_sleep)
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", fake_run_on_isolated_subagent_loop)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", fake_report_subagent_usage)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    with pytest.raises(asyncio.CancelledError):
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="cancel task",
            subagent_type="general-purpose",
            tool_call_id="tc-cancelled-timeout",
        )

    # Non-terminal tasks cannot be cleaned immediately; a deferred cleanup
    # keeps polling after the parent cancellation path exits.
    assert cleanup_calls == []
    assert len(scheduled_cleanups) == 1
    # _report_subagent_usage is called (but skips because result has no records)
    assert len(report_calls) == 1


def test_cancellation_wait_uses_subagent_polling_budget(monkeypatch):
    """Cancelled parent waits on the existing subagent polling budget, not a fixed timeout."""
    config = _make_subagent_config()
    events = []
    report_calls = []
    cleanup_calls = []
    sleep_count = 0
    result_polls = 0
    terminal_result = _make_result(FakeSubagentStatus.COMPLETED, result="done")

    def get_result(_: str):
        nonlocal result_polls
        result_polls += 1
        if result_polls < 5:
            return _make_result(FakeSubagentStatus.RUNNING, ai_messages=[])
        return terminal_result

    async def cancel_then_continue(_: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 1:
            raise asyncio.CancelledError

    def fake_report_subagent_usage(runtime, result):
        report_calls.append((runtime, result))

    async def fail_on_fixed_timeout(awaitable, *, timeout=None):
        raise AssertionError(f"cancellation wait should not use fixed timeout={timeout}")

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", get_result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", cancel_then_continue)
    monkeypatch.setattr(task_tool_module.asyncio, "wait_for", fail_on_fixed_timeout)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", fake_report_subagent_usage)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    with pytest.raises(asyncio.CancelledError):
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="cancel task",
            subagent_type="general-purpose",
            tool_call_id="tc-cancel-budget",
        )

    assert report_calls == [(_make_runtime(), terminal_result)]
    assert cleanup_calls == ["tc-cancel-budget"]


def test_cancellation_calls_request_cancel(monkeypatch):
    """Verify CancelledError path cancels the server-generated execution ID."""
    config = _make_subagent_config()
    events = []
    cancel_requests = []

    async def cancel_on_first_sleep(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: "execution-cancel"}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", cancel_on_first_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "request_cancel_background_task",
        lambda task_id: cancel_requests.append(task_id),
    )
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: None,
    )

    with pytest.raises(asyncio.CancelledError):
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="cancel me",
            subagent_type="general-purpose",
            tool_call_id="tc-cancel-request",
        )

    assert cancel_requests == ["execution-cancel"]


def test_task_tool_returns_cancelled_message(monkeypatch):
    """Verify polling a CANCELLED result emits task_cancelled event and returns message."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []

    # First poll: RUNNING, second poll: CANCELLED
    responses = iter(
        [
            _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]),
            _make_result(FakeSubagentStatus.CANCELLED, error="Cancelled by user"),
        ]
    )

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)

    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: next(responses))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    output = _run_task_tool(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="some task",
        subagent_type="general-purpose",
        tool_call_id="tc-poll-cancelled",
    )

    message = _task_tool_message(output)
    assert message.content == "Task cancelled by user. Error: Cancelled by user"
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "cancelled"
    assert message.additional_kwargs[SUBAGENT_ERROR_KEY] == "Cancelled by user"
    assert any(e.get("type") == "task_cancelled" for e in events)
    assert cleanup_calls == ["tc-poll-cancelled"]


def test_task_tool_emits_completed_metadata(monkeypatch):
    config = _make_subagent_config()

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    message = _task_tool_message(
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="do work",
            subagent_type="general-purpose",
            tool_call_id="tc-completed-metadata",
        )
    )

    assert message.content == "Task Succeeded. Result: done"
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "completed"
    assert message.additional_kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "done"
    assert len(message.additional_kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64


def test_task_tool_emits_disappeared_task_metadata(monkeypatch):
    config = _make_subagent_config()
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: None)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    message = _task_tool_message(
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="missing task",
            subagent_type="general-purpose",
            tool_call_id="tc-missing",
        )
    )

    assert message.content == "Task failed. Error: Task tc-missing disappeared from background tasks"
    assert message.additional_kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert message.additional_kwargs[SUBAGENT_ERROR_KEY] == "Task tc-missing disappeared from background tasks"
    assert events[-1]["type"] == "task_failed"


def test_task_tool_bounds_large_result_metadata(monkeypatch):
    config = _make_subagent_config()
    huge = "x" * 10000

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: _make_result(FakeSubagentStatus.COMPLETED, result=huge))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    message = _task_tool_message(
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="large result",
            subagent_type="general-purpose",
            tool_call_id="tc-large-result",
        )
    )

    assert message.content == f"Task Succeeded. Result: {huge}"
    assert len(message.additional_kwargs[SUBAGENT_RESULT_BRIEF_KEY]) <= 2000
    assert len(message.additional_kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64


def test_cancellation_reports_subagent_usage(monkeypatch):
    """Verify cancellation handler waits (shielded) for subagent terminal state,
    then reports the final token usage before re-raising CancelledError.

    The report must happen synchronously within the cancellation handler so
    the parent worker's finally block sees the updated journal totals.
    """
    config = _make_subagent_config()
    events = []
    report_calls = []
    cleanup_calls = []

    # Terminal result with token usage collected after cancellation processing
    cancel_result = _make_result(FakeSubagentStatus.CANCELLED, error="Cancelled by user")
    cancel_result.token_usage_records = [{"source_run_id": "sub-run-1", "caller": "subagent:gp", "input_tokens": 50, "output_tokens": 25, "total_tokens": 75}]
    cancel_result.usage_reported = False

    poll_count = 0

    def get_result(_: str):
        nonlocal poll_count
        poll_count += 1
        # Main loop polls 3 times (RUNNING each time to keep looping)
        if poll_count <= 3:
            running = _make_result(FakeSubagentStatus.RUNNING, ai_messages=[])
            running.token_usage_records = []
            running.usage_reported = False
            return running
        # Shielded wait poll gets the terminal result
        return cancel_result

    sleep_count = 0

    async def cancel_on_third_sleep(_: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 3:
            raise asyncio.CancelledError

    def fake_report_subagent_usage(runtime, result):
        report_calls.append((runtime, result))

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", get_result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", cancel_on_third_sleep)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", fake_report_subagent_usage)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(task_tool_module, "request_cancel_background_task", lambda _: None)
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    with pytest.raises(asyncio.CancelledError):
        _run_task_tool(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="cancel me",
            subagent_type="general-purpose",
            tool_call_id="tc-cancel-report",
        )

    # _report_subagent_usage is called synchronously within the cancellation
    # handler (after the shielded wait), before CancelledError is re-raised.
    assert len(report_calls) == 1
    assert report_calls[0][1] is cancel_result
    assert cleanup_calls == ["tc-cancel-report"]


@pytest.mark.parametrize(
    "status, expected_type",
    [
        (FakeSubagentStatus.COMPLETED, "task_completed"),
        (FakeSubagentStatus.FAILED, "task_failed"),
        (FakeSubagentStatus.CANCELLED, "task_cancelled"),
        (FakeSubagentStatus.TIMED_OUT, "task_timed_out"),
    ],
)
def test_terminal_events_include_usage(monkeypatch, status, expected_type):
    """Terminal task events include a usage summary from token_usage_records."""
    config = _make_subagent_config()
    runtime = _make_runtime()
    events = []
    dispatched_events = []

    async def fake_emit_custom_event(payload, *, writer):
        writer(payload)
        dispatched_events.append(payload)

    records = [
        {"source_run_id": "r1", "caller": "subagent:general-purpose", "input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        {"source_run_id": "r2", "caller": "subagent:general-purpose", "input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
    ]
    result = _make_result(status, result="ok" if status == FakeSubagentStatus.COMPLETED else None, error="err" if status != FakeSubagentStatus.COMPLETED else None, token_usage_records=records)

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module, "aemit_custom_event", fake_emit_custom_event)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    _run_task_tool(
        runtime=runtime,
        description="test",
        prompt="do work",
        subagent_type="general-purpose",
        tool_call_id="tc-usage",
    )

    terminal_events = [e for e in events if e["type"] == expected_type]
    assert len(terminal_events) == 1
    assert dispatched_events == events
    assert terminal_events[0]["usage"] == {
        "input_tokens": 300,
        "output_tokens": 130,
        "total_tokens": 430,
    }


def test_terminal_event_usage_none_when_no_records(monkeypatch):
    """Terminal event has usage=None when token_usage_records is empty."""
    config = _make_subagent_config()
    runtime = _make_runtime()
    events = []

    result = _make_result(FakeSubagentStatus.COMPLETED, result="done", token_usage_records=[])

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    _run_task_tool(
        runtime=runtime,
        description="test",
        prompt="do work",
        subagent_type="general-purpose",
        tool_call_id="tc-no-records",
    )

    completed = [e for e in events if e["type"] == "task_completed"]
    assert len(completed) == 1
    assert completed[0]["usage"] is None


@pytest.mark.asyncio
async def test_deferred_cleanup_task_retained_and_survives_gc(monkeypatch):
    """Verify deferred cleanup is retained in _deferred_cleanup_tasks and completes after GC."""
    cleaned = []
    orig_sleep = asyncio.sleep

    # Route the production transport onto this test's running loop so the
    # scheduled coroutine actually executes; the retention and completion
    # behavior under test is the real scheduling wrapper.
    current_loop = asyncio.get_running_loop()

    def transport_to_current_loop(coro):
        return asyncio.run_coroutine_threadsafe(coro, current_loop)

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="ok"))
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", cleaned.append)
    monkeypatch.setattr(task_tool_module, "run_on_isolated_subagent_loop", transport_to_current_loop)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", lambda _: orig_sleep(0))

    task = task_tool_module._schedule_deferred_subagent_cleanup(_make_runtime(), "exec-gc", "trace-gc", 5)
    assert task in task_tool_module._deferred_cleanup_tasks
    weak_task = weakref.ref(task)
    del task
    gc.collect()

    assert weak_task() is not None and weak_task() in task_tool_module._deferred_cleanup_tasks
    for _ in range(10):
        if cleaned:
            break
        await orig_sleep(0.01)
    await orig_sleep(0.01)

    assert cleaned == ["exec-gc"]
    # The transport runs on this test's own loop, so the production
    # add_done_callback(_deferred_cleanup_tasks.discard) fires on the same
    # loop — deterministic once `cleaned` was observed. The assert (not a
    # manual discard) is the point: if that done-callback were deleted from
    # _schedule_deferred_subagent_cleanup, the handle would linger and this
    # would fail instead of the test silently cleaning up after itself.
    for _ in range(10):
        if weak_task() not in task_tool_module._deferred_cleanup_tasks:
            break
        await orig_sleep(0.01)
    assert weak_task() not in task_tool_module._deferred_cleanup_tasks
    task_tool_module._deferred_cleanup_tasks.discard(weak_task())


def _receipt_fixture(rid: str = "r1", tool: str = "write_file", status: str = "success") -> dict:
    return {
        "id": rid,
        "tool_call_id": f"tc-{rid}",
        "tool_name": tool,
        "status": status,
        "args_sha256": "a" * 16,
        "output_sha256": "b" * 16,
        "output_bytes": 10,
        "created_at": "2026-08-24T00:00:00+00:00",
    }


def _run_completed_task_tool(monkeypatch, *, result_text: str, tool_receipts: list[dict] | None, **result_kwargs) -> ToolMessage:
    """Drive the completed branch and return the terminal ToolMessage."""

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result=result_text, tool_receipts=tool_receipts, **result_kwargs),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    command = _run_task_tool(
        runtime=_make_runtime(),
        description="test",
        prompt="p",
        subagent_type="general-purpose",
        tool_call_id="tc-verify",
    )
    return _task_tool_message(command)


def _run_completed_task_tool_with_criteria(monkeypatch, *, criteria: list[str], bash_executions: list[dict] | None = None) -> ToolMessage:
    """Drive the completed branch with acceptance criteria attached.

    The workspace-scoped file leaves read through the lazily imported
    ``read_current_file_content``; patching the sandbox module attribute swaps
    in a fake reader without touching the sandbox provider stack.
    """
    # The checklist reads through the sandbox-native virtual path form.
    files = {"/mnt/user-data/outputs/report.md": "report body"}
    monkeypatch.setattr(
        "deerflow.sandbox.tools.read_current_file_content",
        lambda _runtime, path: files[path] if path in files else (_ for _ in ()).throw(FileNotFoundError(path)),
    )
    # A bounded size is established before any read; fake the prober over the
    # same fake filesystem.
    monkeypatch.setattr(
        "deerflow.subagents.acceptance_checks._probe_file_size",
        lambda _runtime, path, _thread_data: len(files[path].encode("utf-8")) if path in files else (_ for _ in ()).throw(FileNotFoundError(path)),
    )

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done", tool_receipts=None, bash_executions=bash_executions),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    command = _run_task_tool(
        runtime=_make_runtime(),
        description="test",
        prompt="p",
        subagent_type="general-purpose",
        tool_call_id="tc-acceptance",
        acceptance_criteria=criteria,
    )
    return _task_tool_message(command)


def test_task_tool_completed_stamps_acceptance_verdict(monkeypatch):
    message = _run_completed_task_tool_with_criteria(
        monkeypatch,
        criteria=["file:../outputs/report.md non-empty", "tests_passed:make test", "open ended"],
        bash_executions=[{"tool_call_id": "tc-1", "tool_name": "bash", "command": "make test", "output_tail": "12 passed", "status": "success", "shell_persistent": False}],
    )

    verdict = message.additional_kwargs["subagent_acceptance_verdict"]
    assert verdict["source"] == "acceptance_checklist"
    assert [leaf["holds"] for leaf in verdict["leaves"]] == [True, True, False]
    assert verdict["unchecked"] == ["open ended"]
    # The rendered checklist section rides the model-visible result text.
    assert "- [holds] file:../outputs/report.md non-empty" in message.content
    assert "- [holds] tests_passed:make test" in message.content
    assert "- [UNVERIFIED] open ended" in message.content


def test_task_tool_completed_without_criteria_stamps_no_acceptance_verdict(monkeypatch):
    message = _run_completed_task_tool(monkeypatch, result_text="done", tool_receipts=None)

    assert "subagent_acceptance_verdict" not in message.additional_kwargs
    assert "Acceptance checklist" not in message.content


def test_task_tool_acceptance_check_failure_is_isolated(monkeypatch):
    def exploding_check(*_args, **_kwargs):
        raise RuntimeError("checker blew up")

    monkeypatch.setattr(task_tool_module, "check_acceptance_criteria", exploding_check)

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done", tool_receipts=None),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    command = _run_task_tool(
        runtime=_make_runtime(),
        description="test",
        prompt="p",
        subagent_type="general-purpose",
        tool_call_id="tc-acceptance-fail",
        acceptance_criteria=["file:../outputs/report.md exists"],
    )
    message = _task_tool_message(command)

    # The checker error never changes the outcome: completed result, no verdict.
    assert message.content.startswith("Task Succeeded.")
    assert "subagent_acceptance_verdict" not in message.additional_kwargs


def test_task_tool_completed_attaches_receipts_and_verdict(monkeypatch):
    receipts = [_receipt_fixture("r1", "write_file")]
    message = _run_completed_task_tool(monkeypatch, result_text="saved the report [r1]", tool_receipts=receipts)

    assert message.additional_kwargs["subagent_tool_receipts"] == receipts
    verdict = message.additional_kwargs["subagent_receipt_verdict"]
    assert verdict["citation_resolved"] is True
    assert verdict["resolved"] == ["r1"]


def test_task_tool_completed_flags_unknown_citation(monkeypatch):
    receipts = [_receipt_fixture("r1", "write_file")]
    message = _run_completed_task_tool(monkeypatch, result_text="uploaded [r9]", tool_receipts=receipts)

    verdict = message.additional_kwargs["subagent_receipt_verdict"]
    assert verdict["citation_resolved"] is False
    assert verdict["unknown"] == ["r9"]


def test_task_tool_completed_flags_uncited_action_claims(monkeypatch):
    message = _run_completed_task_tool(monkeypatch, result_text="I wrote the report.", tool_receipts=[])

    verdict = message.additional_kwargs["subagent_receipt_verdict"]
    assert verdict["no_citation_claims"] is True
    assert verdict["citation_resolved"] is False


def test_task_tool_completed_without_receipts_produces_no_verdict(monkeypatch):
    # receipts=None means no harvest happened (disabled or pre-stream end):
    # skip the verdict entirely, keeping disabled deployments pre-PR2.
    message = _run_completed_task_tool(monkeypatch, result_text="done [r1]", tool_receipts=None)

    assert "subagent_receipt_verdict" not in message.additional_kwargs
    assert "subagent_tool_receipts" not in message.additional_kwargs


def test_task_tool_failed_carries_receipts_without_verdict(monkeypatch):
    receipts = [_receipt_fixture("r1", "bash", status="error")]

    class DummyExecutor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.FAILED, error="boom", tool_receipts=receipts),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    command = _run_task_tool(
        runtime=_make_runtime(),
        description="test",
        prompt="p",
        subagent_type="general-purpose",
        tool_call_id="tc-failed",
    )
    message = _task_tool_message(command)
    assert message.additional_kwargs["subagent_tool_receipts"] == receipts
    assert "subagent_receipt_verdict" not in message.additional_kwargs


def _capture_executor_call(monkeypatch, **call_kwargs):
    """Run task_tool with a dummy executor and return (executor_kwargs, prompt)."""
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            captured["prompt"] = prompt
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: _make_subagent_config())
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    kwargs = {
        "runtime": _make_runtime(),
        "description": "test",
        "prompt": "do the work",
        "subagent_type": "general-purpose",
        "tool_call_id": "tc-criteria",
    }
    kwargs.update(call_kwargs)
    _run_task_tool(**kwargs)
    return captured["executor_kwargs"], captured["prompt"]


def test_task_tool_forwards_acceptance_criteria_to_executor(monkeypatch):
    """RFC #4651 PR3: criteria travel via the executor constructor; the
    executor appends them to the subagent's task HumanMessage as untrusted
    data at state-build time. The delegated prompt itself stays free of
    criteria so the tool never dictates the channel."""
    criteria = ["file:../outputs/report.md non-empty", "tests_passed:make test"]

    executor_kwargs, delegated_prompt = _capture_executor_call(monkeypatch, acceptance_criteria=criteria)

    assert executor_kwargs["acceptance_criteria"] == criteria
    assert "<acceptance_criteria>" not in delegated_prompt


def test_task_tool_forwards_no_criteria_by_default(monkeypatch):
    executor_kwargs, delegated_prompt = _capture_executor_call(monkeypatch)

    assert executor_kwargs["acceptance_criteria"] is None
    assert "<acceptance_criteria>" not in delegated_prompt
