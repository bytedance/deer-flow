"""Tests for subagent configuration, tool filtering, model resolution, and per-user concurrency."""

from __future__ import annotations

import importlib
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage
from langgraph.types import Command

import src.subagents.executor as executor_module
from src.agents.thread_state import merge_subagent_trajectories
from src.subagents.config import SubagentConfig
from src.subagents.executor import (
    SubagentResult,
    SubagentStatus,
    _filter_tools,
    _get_model_name,
    _get_user_semaphore,
    _resolve_thinking_effort,
    _resolve_thinking_enabled,
    _user_semaphores,
    _user_semaphores_lock,
    get_background_task_result,
)

task_tool_module = importlib.import_module("src.tools.builtins.task_tool")


# ---------------------------------------------------------------------------
# SubagentConfig
# ---------------------------------------------------------------------------
class TestSubagentConfig:
    """Tests for SubagentConfig dataclass."""

    def test_defaults(self) -> None:
        config = SubagentConfig(name="test", description="desc", system_prompt="prompt")
        assert config.name == "test"
        assert config.model == "inherit"
        assert config.thinking_enabled == "inherit"
        assert config.thinking_effort == "inherit"
        assert config.max_turns == 50
        assert config.timeout_seconds == 900
        assert config.tools is None
        assert config.disallowed_tools == ["task"]

    def test_custom_values(self) -> None:
        config = SubagentConfig(
            name="custom",
            description="Custom agent",
            system_prompt="Do X",
            tools=["bash", "read_file"],
            disallowed_tools=["task", "write_file"],
            model="gpt-4",
            thinking_enabled=True,
            thinking_effort="high",
            max_turns=10,
            timeout_seconds=300,
        )
        assert config.tools == ["bash", "read_file"]
        assert config.disallowed_tools == ["task", "write_file"]
        assert config.model == "gpt-4"
        assert config.thinking_enabled is True
        assert config.thinking_effort == "high"
        assert config.max_turns == 10
        assert config.timeout_seconds == 300


# ---------------------------------------------------------------------------
# Thinking resolution helpers
# ---------------------------------------------------------------------------
class TestThinkingResolution:
    """Tests for thinking inheritance/override helpers."""

    def test_resolve_thinking_enabled_inherit(self) -> None:
        config = SubagentConfig(name="x", description="x", system_prompt="x", thinking_enabled="inherit")
        assert _resolve_thinking_enabled(config, True) is True
        assert _resolve_thinking_enabled(config, False) is False

    def test_resolve_thinking_enabled_override(self) -> None:
        config_true = SubagentConfig(name="x", description="x", system_prompt="x", thinking_enabled=True)
        config_false = SubagentConfig(name="x", description="x", system_prompt="x", thinking_enabled=False)
        assert _resolve_thinking_enabled(config_true, False) is True
        assert _resolve_thinking_enabled(config_false, True) is False

    def test_resolve_thinking_effort_inherit(self) -> None:
        config = SubagentConfig(name="x", description="x", system_prompt="x", thinking_effort="inherit")
        assert _resolve_thinking_effort(config, "medium") == "medium"
        assert _resolve_thinking_effort(config, None) is None

    def test_resolve_thinking_effort_override(self) -> None:
        config = SubagentConfig(name="x", description="x", system_prompt="x", thinking_effort=" HIGH ")
        assert _resolve_thinking_effort(config, "low") == "high"

    def test_resolve_thinking_effort_none(self) -> None:
        config = SubagentConfig(name="x", description="x", system_prompt="x", thinking_effort=None)
        assert _resolve_thinking_effort(config, "medium") is None


class TestSubagentThinkingRuntime:
    """Tests for subagent runtime thinking propagation."""

    def test_executor_applies_subagent_effort_override(self, monkeypatch) -> None:
        captured: dict = {}

        def _fake_create_chat_model(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(executor_module, "create_chat_model", _fake_create_chat_model)
        monkeypatch.setattr(executor_module, "create_agent", lambda **kwargs: MagicMock())

        config = SubagentConfig(
            name="x",
            description="x",
            system_prompt="x",
            model="inherit",
            thinking_enabled="inherit",
            thinking_effort="high",
        )
        executor = executor_module.SubagentExecutor(
            config=config,
            tools=[],
            parent_model_spec={"provider": "openai", "model_id": "gpt-5.2", "thinking_effort": "low"},
            parent_thinking_enabled=True,
            parent_thinking_effort="low",
        )

        executor._create_agent()

        assert captured["thinking_enabled"] is True
        assert captured["runtime_model"]["thinking_effort"] == "high"

    def test_executor_inherits_parent_effort(self, monkeypatch) -> None:
        captured: dict = {}

        def _fake_create_chat_model(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(executor_module, "create_chat_model", _fake_create_chat_model)
        monkeypatch.setattr(executor_module, "create_agent", lambda **kwargs: MagicMock())

        config = SubagentConfig(
            name="x",
            description="x",
            system_prompt="x",
            model="inherit",
            thinking_enabled="inherit",
            thinking_effort="inherit",
        )
        executor = executor_module.SubagentExecutor(
            config=config,
            tools=[],
            parent_model_spec={"provider": "anthropic", "model_id": "claude-sonnet-4-6"},
            parent_thinking_enabled=True,
            parent_thinking_effort="medium",
        )

        executor._create_agent()

        assert captured["thinking_enabled"] is True
        assert captured["runtime_model"]["thinking_effort"] == "medium"


# ---------------------------------------------------------------------------
# SubagentResult
# ---------------------------------------------------------------------------
class TestSubagentResult:
    """Tests for SubagentResult dataclass."""

    def test_defaults(self) -> None:
        result = SubagentResult(task_id="t1", trace_id="tr1", status=SubagentStatus.PENDING)
        assert result.result is None
        assert result.error is None
        assert result.ai_messages == []
        assert result.trajectory_messages == []
        assert result.token_usage == {"input_tokens": 0, "output_tokens": 0}

    def test_status_enum(self) -> None:
        assert SubagentStatus.PENDING.value == "pending"
        assert SubagentStatus.RUNNING.value == "running"
        assert SubagentStatus.COMPLETED.value == "completed"
        assert SubagentStatus.FAILED.value == "failed"
        assert SubagentStatus.TIMED_OUT.value == "timed_out"


# ---------------------------------------------------------------------------
# _filter_tools
# ---------------------------------------------------------------------------
class TestFilterTools:
    """Tests for _filter_tools()."""

    def _make_tools(self, names: list[str]) -> list:
        tools = []
        for name in names:
            t = MagicMock()
            t.name = name
            tools.append(t)
        return tools

    def test_no_filters(self) -> None:
        tools = self._make_tools(["bash", "read_file", "task"])
        result = _filter_tools(tools, allowed=None, disallowed=None)
        assert len(result) == 3

    def test_allowlist_only(self) -> None:
        tools = self._make_tools(["bash", "read_file", "task", "write_file"])
        result = _filter_tools(tools, allowed=["bash", "read_file"], disallowed=None)
        assert [t.name for t in result] == ["bash", "read_file"]

    def test_denylist_only(self) -> None:
        tools = self._make_tools(["bash", "read_file", "task"])
        result = _filter_tools(tools, allowed=None, disallowed=["task"])
        assert [t.name for t in result] == ["bash", "read_file"]

    def test_allowlist_and_denylist(self) -> None:
        tools = self._make_tools(["bash", "read_file", "task", "write_file"])
        result = _filter_tools(tools, allowed=["bash", "task"], disallowed=["task"])
        assert [t.name for t in result] == ["bash"]

    def test_empty_allowlist(self) -> None:
        tools = self._make_tools(["bash", "read_file"])
        result = _filter_tools(tools, allowed=[], disallowed=None)
        assert result == []

    def test_empty_denylist(self) -> None:
        tools = self._make_tools(["bash", "read_file"])
        result = _filter_tools(tools, allowed=None, disallowed=[])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _get_model_name
# ---------------------------------------------------------------------------
class TestGetModelName:
    """Tests for _get_model_name()."""

    def test_inherit(self) -> None:
        config = SubagentConfig(name="x", description="x", system_prompt="x", model="inherit")
        assert _get_model_name(config, "gpt-4") == "gpt-4"

    def test_inherit_none_parent(self) -> None:
        config = SubagentConfig(name="x", description="x", system_prompt="x", model="inherit")
        assert _get_model_name(config, None) is None

    def test_explicit_model(self) -> None:
        config = SubagentConfig(name="x", description="x", system_prompt="x", model="claude-3")
        assert _get_model_name(config, "gpt-4") == "claude-3"


# ---------------------------------------------------------------------------
# _get_user_semaphore
# ---------------------------------------------------------------------------
class TestGetUserSemaphore:
    """Tests for per-user concurrency semaphore."""

    def setup_method(self) -> None:
        """Clear semaphore cache before each test."""
        with _user_semaphores_lock:
            _user_semaphores.clear()

    def test_creates_new_semaphore(self) -> None:
        sem = _get_user_semaphore("user1")
        assert isinstance(sem, threading.Semaphore)

    def test_returns_same_semaphore(self) -> None:
        sem1 = _get_user_semaphore("user1")
        sem2 = _get_user_semaphore("user1")
        assert sem1 is sem2

    def test_different_users_different_semaphores(self) -> None:
        sem1 = _get_user_semaphore("user1")
        sem2 = _get_user_semaphore("user2")
        assert sem1 is not sem2

    def test_updates_last_used_time(self) -> None:
        _get_user_semaphore("user1")
        time.sleep(0.01)
        _get_user_semaphore("user1")
        with _user_semaphores_lock:
            _, last_used = _user_semaphores["user1"]
        assert last_used > 0


# ---------------------------------------------------------------------------
# get_background_task_result
# ---------------------------------------------------------------------------
class TestGetBackgroundTaskResult:
    """Tests for get_background_task_result()."""

    def test_returns_none_for_unknown(self) -> None:
        assert get_background_task_result("nonexistent") is None


class TestSubagentTrajectoryState:
    """Tests for subagent trajectory state reducer and persistence path."""

    def test_merge_subagent_trajectories(self) -> None:
        existing = {
            "t1": {"task_id": "t1", "status": "completed", "messages": []},
        }
        new = {
            "t2": {"task_id": "t2", "status": "failed", "messages": []},
        }
        merged = merge_subagent_trajectories(existing, new)
        assert set(merged.keys()) == {"t1", "t2"}

    def test_task_tool_returns_command_with_subagent_trajectory(self, monkeypatch) -> None:
        writes: list[dict] = []

        monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _name: SubagentConfig(name="general-purpose", description="x", system_prompt="x"))
        monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
        monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: writes.append)
        monkeypatch.setattr(task_tool_module, "add_subagent_usage", lambda *_args, **_kwargs: None)

        class FakeExecutor:
            def __init__(self, **_kwargs):
                pass

            def execute_async(self, _prompt: str, task_id: str | None = None, user_id: str | None = None) -> str:
                assert user_id == "user-1"
                return task_id or "task-1"

        monkeypatch.setattr(task_tool_module, "SubagentExecutor", FakeExecutor)

        import src.tools as tools_module

        monkeypatch.setattr(tools_module, "get_available_tools", lambda **_kwargs: [])

        completed = SubagentResult(
            task_id="tool-call-1",
            trace_id="trace-1",
            status=SubagentStatus.COMPLETED,
            result="done",
        )
        completed.trajectory_messages = [
            {
                "type": "ai",
                "id": "ai-1",
                "additional_kwargs": {"reasoning_content": "thinking..."},
                "tool_calls": [{"id": "tc1", "name": "bash", "args": {"command": "ls"}}],
            },
            {
                "type": "tool",
                "tool_call_id": "tc1",
                "content": "README.md",
            },
        ]
        monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: completed)

        runtime = SimpleNamespace(
            state={"sandbox": None, "thread_data": None},
            context={"thread_id": "thread-1", "user_id": "user-1"},
            config={
                "metadata": {"model_name": "openai:gpt-5.2", "trace_id": "trace-1"},
                "configurable": {"thinking_enabled": True, "thinking_effort": "high"},
            },
        )

        result = task_tool_module.task_tool.func(  # type: ignore[union-attr]
            runtime=runtime,
            description="research",
            prompt="collect evidence",
            subagent_type="general-purpose",
            tool_call_id="tool-call-1",
        )

        assert isinstance(result, Command)
        update = result.update
        assert isinstance(update, dict)
        assert "subagent_trajectories" in update
        trajectory = update["subagent_trajectories"]["tool-call-1"]
        assert trajectory["status"] == "completed"
        assert len(trajectory["messages"]) == 2
        assert trajectory["messages"][0]["additional_kwargs"]["reasoning_content"] == "thinking..."
        assert trajectory["messages"][1]["type"] == "tool"

        messages = update["messages"]
        assert isinstance(messages, list)
        assert isinstance(messages[0], ToolMessage)
        assert "Task Succeeded. Result: done" in messages[0].content
