"""Tests for subagent configuration, tool filtering, model resolution, and per-user concurrency."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from src.subagents.config import SubagentConfig
from src.subagents.executor import (
    SubagentResult,
    SubagentStatus,
    _filter_tools,
    _get_model_name,
    _get_user_semaphore,
    _user_semaphores,
    _user_semaphores_lock,
    get_background_task_result,
)


# ---------------------------------------------------------------------------
# SubagentConfig
# ---------------------------------------------------------------------------
class TestSubagentConfig:
    """Tests for SubagentConfig dataclass."""

    def test_defaults(self) -> None:
        config = SubagentConfig(name="test", description="desc", system_prompt="prompt")
        assert config.name == "test"
        assert config.model == "inherit"
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
            max_turns=10,
            timeout_seconds=300,
        )
        assert config.tools == ["bash", "read_file"]
        assert config.disallowed_tools == ["task", "write_file"]
        assert config.model == "gpt-4"
        assert config.max_turns == 10
        assert config.timeout_seconds == 300


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
