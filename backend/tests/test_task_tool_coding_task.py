import asyncio
import importlib
import json
from enum import Enum
from types import SimpleNamespace

import pytest

from deerflow.subagents.config import SubagentConfig

task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")


class FakeSubagentStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(
        state={"sandbox": None, "thread_data": None},
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "test-model"}},
    )


def test_coding_task_is_claimed_before_delegation_and_completed_after_success(
    monkeypatch,
):
    calls: list[tuple] = []

    class FakeGraph:
        def claim(self, task_id: str, owner: str):
            calls.append(("claim", task_id, owner))
            return SimpleNamespace(worktree=None)

        def get_upstream_artifacts(self, task_id: str):
            calls.append(("upstream", task_id))
            return []

        def complete(self, task_id: str, artifact=None):
            calls.append(("complete", task_id, artifact))

    class FakeExecutor:
        def __init__(self, **_kwargs):
            pass

        def execute_async(self, prompt: str, task_id: str):
            calls.append(("execute", prompt, task_id))
            return task_id

    config = SubagentConfig(
        name="code-analyzer",
        description="Analyze code",
        system_prompt="Analyze code",
        timeout_seconds=10,
        artifact_type="analysis_report",
    )
    analysis_report = {
        "report_type": "analysis_report",
        "summary": "analysis done",
        "relevant_files": ["pricing.py"],
        "implementation_steps": ["fix calculation"],
        "risks": [],
        "test_plan": ["run unit tests"],
        "implementer_input": "apply the verified formula",
    }
    result = SimpleNamespace(
        status=FakeSubagentStatus.COMPLETED,
        ai_messages=[],
        result=json.dumps(analysis_report),
        error=None,
        stop_reason=None,
        token_usage_records=[],
        usage_reported=False,
    )

    monkeypatch.setattr(task_tool_module, "_token_usage_cache_enabled", lambda _config: False)
    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["code-analyzer"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name: config)
    monkeypatch.setattr(task_tool_module, "resolve_runtime_user_id", lambda _runtime: "alice")
    monkeypatch.setattr(
        task_tool_module,
        "create_task_graph",
        lambda thread_id, *, user_id: calls.append(("create_graph", thread_id, user_id)) or FakeGraph(),
    )
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", FakeExecutor)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _task_id: None)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_args: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])

    async def ignore_event(_payload, *, writer):
        del writer

    monkeypatch.setattr(task_tool_module, "aemit_custom_event", ignore_event)

    coroutine = task_tool_module.task_tool.coroutine
    assert coroutine is not None
    asyncio.run(
        coroutine(
            runtime=_runtime(),
            description="Analyze task",
            prompt="Inspect the code",
            subagent_type="code-analyzer",
            tool_call_id="tool-call-1",
            coding_task_id="task-1",
        )
    )

    assert calls == [
        ("create_graph", "thread-1", "alice"),
        ("claim", "task-1", "code-analyzer"),
        ("upstream", "task-1"),
        ("execute", "Inspect the code", "tool-call-1"),
        ("complete", "task-1", analysis_report),
    ]


@pytest.mark.parametrize(
    ("status", "error", "expected_reason"),
    [
        (FakeSubagentStatus.FAILED, "tests failed", "tests failed"),
        (FakeSubagentStatus.CANCELLED, None, "Subagent task was cancelled"),
        (FakeSubagentStatus.TIMED_OUT, None, "Subagent task timed out"),
        (None, None, "Task tool-call-1 disappeared from background tasks"),
    ],
)
def test_coding_task_is_failed_for_each_terminal_failure(monkeypatch, status, error, expected_reason):
    calls: list[tuple] = []

    class FakeGraph:
        def claim(self, task_id: str, owner: str):
            calls.append(("claim", task_id, owner))
            return SimpleNamespace(worktree=None)

        def get_upstream_artifacts(self, _task_id: str):
            return []

        def fail(self, task_id: str, reason: str):
            calls.append(("fail", task_id, reason))

    class FakeExecutor:
        def __init__(self, **_kwargs):
            pass

        def execute_async(self, prompt: str, task_id: str):
            calls.append(("execute", prompt, task_id))
            return task_id

    config = SubagentConfig(
        name="code-analyzer",
        description="Analyze code",
        system_prompt="Analyze code",
        timeout_seconds=10,
    )
    result = None
    if status is not None:
        result = SimpleNamespace(
            status=status,
            ai_messages=[],
            result=None,
            error=error,
            stop_reason=None,
            token_usage_records=[],
            usage_reported=False,
        )

    monkeypatch.setattr(task_tool_module, "_token_usage_cache_enabled", lambda _config: False)
    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["code-analyzer"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name: config)
    monkeypatch.setattr(task_tool_module, "resolve_runtime_user_id", lambda _runtime: "alice")
    monkeypatch.setattr(
        task_tool_module,
        "create_task_graph",
        lambda _thread_id, *, user_id: FakeGraph(),
    )
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", FakeExecutor)
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _task_id: None)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_args: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])

    async def ignore_event(_payload, *, writer):
        del writer

    monkeypatch.setattr(task_tool_module, "aemit_custom_event", ignore_event)

    coroutine = task_tool_module.task_tool.coroutine
    assert coroutine is not None
    asyncio.run(
        coroutine(
            runtime=_runtime(),
            description="Analyze task",
            prompt="Inspect the code",
            subagent_type="code-analyzer",
            tool_call_id="tool-call-1",
            coding_task_id="task-1",
        )
    )

    assert calls == [
        ("claim", "task-1", "code-analyzer"),
        ("execute", "Inspect the code", "tool-call-1"),
        ("fail", "task-1", expected_reason),
    ]


def test_coding_task_is_failed_when_subagent_cannot_start(monkeypatch):
    calls: list[tuple] = []

    class FakeGraph:
        def claim(self, task_id: str, owner: str):
            calls.append(("claim", task_id, owner))
            return SimpleNamespace(worktree=None)

        def get_upstream_artifacts(self, _task_id: str):
            return []

        def fail(self, task_id: str, reason: str):
            calls.append(("fail", task_id, reason))

    class FailingExecutor:
        def __init__(self, **_kwargs):
            pass

        def execute_async(self, _prompt: str, task_id: str):
            calls.append(("execute", task_id))
            raise RuntimeError("worker unavailable")

    config = SubagentConfig(
        name="code-analyzer",
        description="Analyze code",
        system_prompt="Analyze code",
        timeout_seconds=10,
    )

    monkeypatch.setattr(task_tool_module, "_token_usage_cache_enabled", lambda _config: False)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["code-analyzer"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name: config)
    monkeypatch.setattr(task_tool_module, "resolve_runtime_user_id", lambda _runtime: "alice")
    monkeypatch.setattr(
        task_tool_module,
        "create_task_graph",
        lambda _thread_id, *, user_id: FakeGraph(),
    )
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", FailingExecutor)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])

    coroutine = task_tool_module.task_tool.coroutine
    assert coroutine is not None
    with pytest.raises(RuntimeError, match="worker unavailable"):
        asyncio.run(
            coroutine(
                runtime=_runtime(),
                description="Analyze task",
                prompt="Inspect the code",
                subagent_type="code-analyzer",
                tool_call_id="tool-call-1",
                coding_task_id="task-1",
            )
        )

    assert calls == [
        ("claim", "task-1", "code-analyzer"),
        ("execute", "tool-call-1"),
        ("fail", "task-1", "Failed to start subagent: worker unavailable"),
    ]


def test_coding_task_worktree_is_passed_as_subagent_workspace_without_mutating_parent(
    monkeypatch,
):
    calls: list[tuple] = []
    fingerprints: list[str] = []
    captured_executor_kwargs: dict = {}
    upstream_artifacts = [
        {"report_type": "analysis_report", "summary": "inspect pricing.py"},
        {"report_type": "implementation_report", "summary": "fixed formula"},
    ]
    parent_thread_data = {
        "workspace_path": "D:/sandbox/thread-1/user-data/workspace",
        "uploads_path": "D:/sandbox/thread-1/user-data/uploads",
        "outputs_path": "D:/sandbox/thread-1/user-data/outputs",
    }
    runtime = _runtime()
    runtime.state["thread_data"] = parent_thread_data

    class FakeGraph:
        def claim(self, task_id: str, owner: str):
            calls.append(("claim", task_id, owner))
            return SimpleNamespace(worktree="E:/projectA/.worktrees/coding-run")

        def get_upstream_artifacts(self, task_id: str):
            calls.append(("upstream", task_id))
            return upstream_artifacts

        def complete(self, task_id: str, artifact=None):
            calls.append(("complete", task_id, artifact))

    class FakeExecutor:
        def __init__(self, **kwargs):
            captured_executor_kwargs.update(kwargs)

        def execute_async(self, prompt: str, task_id: str):
            calls.append(("execute", prompt, task_id))
            return task_id

    config = SubagentConfig(
        name="code-reviewer",
        description="Review code",
        system_prompt="Review code",
        timeout_seconds=10,
        workspace_access="read_only",
    )
    result = SimpleNamespace(
        status=FakeSubagentStatus.COMPLETED,
        ai_messages=[],
        result="analysis done",
        error=None,
        stop_reason=None,
        token_usage_records=[],
        usage_reported=False,
    )

    monkeypatch.setattr(task_tool_module, "_token_usage_cache_enabled", lambda _config: False)
    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["code-reviewer"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name: config)
    monkeypatch.setattr(task_tool_module, "resolve_runtime_user_id", lambda _runtime: "alice")
    monkeypatch.setattr(
        task_tool_module,
        "create_task_graph",
        lambda _thread_id, *, user_id: FakeGraph(),
    )
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", FakeExecutor)
    monkeypatch.setattr(
        task_tool_module,
        "capture_worktree_fingerprint",
        lambda path: fingerprints.append(path) or "stable-fingerprint",
    )
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: result)
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)
    monkeypatch.setattr(task_tool_module, "cleanup_background_task", lambda _task_id: None)
    monkeypatch.setattr(task_tool_module, "_report_subagent_usage", lambda *_args: None)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])

    async def ignore_event(_payload, *, writer):
        del writer

    monkeypatch.setattr(task_tool_module, "aemit_custom_event", ignore_event)

    coroutine = task_tool_module.task_tool.coroutine
    assert coroutine is not None
    asyncio.run(
        coroutine(
            runtime=runtime,
            description="Analyze task",
            prompt="Inspect the code",
            subagent_type="code-reviewer",
            tool_call_id="tool-call-1",
            coding_task_id="task-1",
        )
    )

    assert captured_executor_kwargs["thread_data"] == {
        **parent_thread_data,
        "workspace_path": "E:/projectA/.worktrees/coding-run",
    }
    assert runtime.state["thread_data"] is parent_thread_data
    assert runtime.state["thread_data"]["workspace_path"] == "D:/sandbox/thread-1/user-data/workspace"
    assert calls == [
        ("claim", "task-1", "code-reviewer"),
        ("upstream", "task-1"),
        (
            "execute",
            (f"{task_tool_module._CODING_WORKSPACE_INSTRUCTION}\n\nInspect the code\n\n{task_tool_module._UPSTREAM_ARTIFACTS_INSTRUCTION.format(artifacts=task_tool_module.render_upstream_artifacts(upstream_artifacts))}"),
            "tool-call-1",
        ),
        ("complete", "task-1", None),
    ]
    assert fingerprints == ["E:/projectA/.worktrees/coding-run"] * 2


def test_coding_task_worktree_preparation_failure_marks_claimed_task_failed(
    monkeypatch,
):
    calls: list[tuple] = []

    class FakeGraph:
        def claim(self, task_id: str, owner: str):
            calls.append(("claim", task_id, owner))
            return SimpleNamespace(worktree="E:/projectA/.worktrees/coding-run")

        def get_upstream_artifacts(self, _task_id: str):
            return []

        def fail(self, task_id: str, reason: str):
            calls.append(("fail", task_id, reason))

    class ExecutorMustNotStart:
        def __init__(self, **_kwargs):
            raise AssertionError("executor must not start without thread_data")

    config = SubagentConfig(
        name="code-analyzer",
        description="Analyze code",
        system_prompt="Analyze code",
        timeout_seconds=10,
    )

    monkeypatch.setattr(task_tool_module, "_token_usage_cache_enabled", lambda _config: False)
    monkeypatch.setattr(task_tool_module, "get_available_subagent_names", lambda: ["code-analyzer"])
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name: config)
    monkeypatch.setattr(task_tool_module, "resolve_runtime_user_id", lambda _runtime: "alice")
    monkeypatch.setattr(
        task_tool_module,
        "create_task_graph",
        lambda _thread_id, *, user_id: FakeGraph(),
    )
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", ExecutorMustNotStart)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])

    coroutine = task_tool_module.task_tool.coroutine
    assert coroutine is not None
    with pytest.raises(RuntimeError, match="thread_data is required"):
        asyncio.run(
            coroutine(
                runtime=_runtime(),
                description="Analyze task",
                prompt="Inspect the code",
                subagent_type="code-analyzer",
                tool_call_id="tool-call-1",
                coding_task_id="task-1",
            )
        )

    assert calls == [
        ("claim", "task-1", "code-analyzer"),
        (
            "fail",
            "task-1",
            "Failed to start subagent: thread_data is required when using a coding worktree",
        ),
    ]
