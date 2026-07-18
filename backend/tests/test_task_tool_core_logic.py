"""Core behavior tests for task tool orchestration."""

import asyncio
import importlib
import inspect
from enum import Enum
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.sandbox.security import LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.status_contract import (
    SUBAGENT_ERROR_KEY,
    SUBAGENT_MODEL_NAME_KEY,
    SUBAGENT_RESULT_BRIEF_KEY,
    SUBAGENT_RESULT_SHA256_KEY,
    SUBAGENT_STATUS_KEY,
    SUBAGENT_STOP_REASON_KEY,
    SUBAGENT_TOKEN_USAGE_KEY,
)

# Use module import so tests can patch the exact symbols referenced inside task_tool().
task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")


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
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        ai_messages=ai_messages or [],
        result=result,
        error=error,
        stop_reason=stop_reason,
        token_usage_records=token_usage_records or [],
        usage_reported=False,
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
    captured = {}
    get_available_tools = MagicMock(return_value=["tool-a", "tool-b"])

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            captured["prompt"] = prompt
            captured["task_id"] = task_id
            return task_id or "generated-task-id"

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

    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: next(responses))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)
    # task_tool lazily imports from deerflow.tools at call time, so patch that module-level function.
    monkeypatch.setattr("deerflow.tools.get_available_tools", get_available_tools)

    output = _run_task_tool(
        runtime=runtime,
        description="运行子任务",
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

    get_available_tools.assert_called_once_with(model_name="ark-model", groups=None, subagent_enabled=False)

    event_types = [e["type"] for e in events]
    assert event_types == ["task_started", "task_running", "task_running", "task_completed"]
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
    get_available_tools.assert_called_once_with(model_name="ark-model", groups=parent_tool_groups, subagent_enabled=False)


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
    get_available_tools.assert_called_once_with(model_name="ark-model", groups=None, subagent_enabled=False)


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

    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]),
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

    def fake_create_task(coro):
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
    monkeypatch.setattr(task_tool_module.asyncio, "create_task", fake_create_task)
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

    def fake_create_task(coro):
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
    monkeypatch.setattr(task_tool_module.asyncio, "create_task", fake_create_task)
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
    """Verify CancelledError path calls request_cancel_background_task(task_id)."""
    config = _make_subagent_config()
    events = []
    cancel_requests = []

    async def cancel_on_first_sleep(_: float) -> None:
        raise asyncio.CancelledError

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

    assert cancel_requests == ["tc-cancel-request"]


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

    records = [
        {"source_run_id": "r1", "caller": "subagent:general-purpose", "input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        {"source_run_id": "r2", "caller": "subagent:general-purpose", "input_tokens": 200, "output_tokens": 80, "total_tokens": 280},
    ]
    result = _make_result(status, result="ok" if status == FakeSubagentStatus.COMPLETED else None, error="err" if status != FakeSubagentStatus.COMPLETED else None, token_usage_records=records)

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
        tool_call_id="tc-usage",
    )

    terminal_events = [e for e in events if e["type"] == expected_type]
    assert len(terminal_events) == 1
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


def test_subagent_usage_cache_is_skipped_when_config_file_is_missing(monkeypatch):
    monkeypatch.setattr(
        task_tool_module,
        "get_app_config",
        MagicMock(side_effect=FileNotFoundError("missing config")),
    )

    assert task_tool_module._token_usage_cache_enabled(None) is False


def test_subagent_usage_cache_is_skipped_when_token_usage_is_disabled(monkeypatch):
    config = _make_subagent_config()
    app_config = SimpleNamespace(token_usage=SimpleNamespace(enabled=False))
    runtime = _make_runtime(app_config=app_config)
    records = [{"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}]
    result = _make_result(FakeSubagentStatus.COMPLETED, result="done", token_usage_records=records)

    task_tool_module._subagent_usage_cache.clear()
    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda *, app_config: ["general-purpose"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _, *, app_config: config)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _: None)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    _run_task_tool(
        runtime=runtime,
        description="test",
        prompt="do work",
        subagent_type="general-purpose",
        tool_call_id="tc-disabled-cache",
    )

    assert task_tool_module.pop_cached_subagent_usage("tc-disabled-cache") is None


def test_subagent_usage_cache_is_cleared_when_polling_raises(monkeypatch):
    config = _make_subagent_config()
    app_config = SimpleNamespace(token_usage=SimpleNamespace(enabled=True))
    runtime = _make_runtime(app_config=app_config)

    task_tool_module._subagent_usage_cache["tc-error"] = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda *, app_config: ["general-purpose"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _, *, app_config: config)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_background_task_result", MagicMock(side_effect=RuntimeError("poll failed")))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", MagicMock(return_value=[]))

    with pytest.raises(RuntimeError, match="poll failed"):
        _run_task_tool(
            runtime=runtime,
            description="test",
            prompt="do work",
            subagent_type="general-purpose",
            tool_call_id="tc-error",
        )

    assert task_tool_module.pop_cached_subagent_usage("tc-error") is None
