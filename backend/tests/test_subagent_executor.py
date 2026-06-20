"""Tests for subagent executor async/sync execution paths.

Covers:
- SubagentExecutor.execute() synchronous execution path
- SubagentExecutor._aexecute() asynchronous execution path
- execute_async() routes background work without bouncing through execute()
- Error handling in both sync and async paths
- Async tool support (MCP tools)
- Cooperative cancellation via cancel_event

Note: Due to circular import issues in the main codebase, conftest.py mocks
deerflow.subagents.executor. This test file uses delayed import via fixture to test
the real implementation in isolation.
"""

import asyncio
import importlib
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.skills.types import Skill

# Module names that need to be mocked to break circular imports
_MOCKED_MODULE_NAMES = [
    "deerflow.agents",
    "deerflow.agents.thread_state",
    "deerflow.agents.middlewares",
    "deerflow.agents.middlewares.thread_data_middleware",
    "deerflow.sandbox",
    "deerflow.sandbox.middleware",
    "deerflow.sandbox.security",
    "deerflow.models",
    "deerflow.skills.storage",
]


def _default_app_config():
    return SimpleNamespace(tool_search=SimpleNamespace(enabled=False))


def _patch_default_get_app_config(executor_module):
    executor_module.get_app_config = _default_app_config
    return executor_module


def _clear_stale_executor_package_attr() -> None:
    subagents_pkg = sys.modules.get("deerflow.subagents")
    if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
        delattr(subagents_pkg, "executor")


@pytest.fixture(autouse=True)
def _setup_executor_classes():
    """Set up mocked modules and import real executor classes.

    This fixture runs once per test and yields the executor classes.
    It handles module cleanup to avoid affecting other test files.
    """
    # Save original modules
    original_modules = {name: sys.modules.get(name) for name in _MOCKED_MODULE_NAMES}
    original_executor = sys.modules.get("deerflow.subagents.executor")

    # Remove mocked executor if exists (from conftest.py)
    if "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]
    _clear_stale_executor_package_attr()

    # Set up mocks
    for name in _MOCKED_MODULE_NAMES:
        sys.modules[name] = MagicMock()
    storage_module = ModuleType("deerflow.skills.storage")
    storage_module.get_or_new_skill_storage = lambda **kwargs: SimpleNamespace(load_skills=lambda *, enabled_only: [])
    sys.modules["deerflow.skills.storage"] = storage_module

    # Import real classes inside fixture
    from langchain_core.messages import AIMessage, HumanMessage

    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import (
        SubagentExecutor,
        SubagentResult,
        SubagentStatus,
    )

    executor_module = sys.modules["deerflow.subagents.executor"]

    # Most tests in this module patch _create_agent and exercise executor
    # control flow only. Keep those tests hermetic: CI checkouts do not include
    # the gitignored config.yaml, and deferral-specific tests override this
    # default explicitly.
    _patch_default_get_app_config(executor_module)

    # Store classes in a dict to yield
    classes = {
        "AIMessage": AIMessage,
        "HumanMessage": HumanMessage,
        "SubagentConfig": SubagentConfig,
        "SubagentExecutor": SubagentExecutor,
        "SubagentResult": SubagentResult,
        "SubagentStatus": SubagentStatus,
    }

    yield classes

    # Cleanup: Restore original modules
    for name in _MOCKED_MODULE_NAMES:
        if original_modules[name] is not None:
            sys.modules[name] = original_modules[name]
        elif name in sys.modules:
            del sys.modules[name]

    # Restore executor module (conftest.py mock)
    if original_executor is not None:
        sys.modules["deerflow.subagents.executor"] = original_executor
    elif "deerflow.subagents.executor" in sys.modules:
        del sys.modules["deerflow.subagents.executor"]


# Helper classes that wrap real classes for testing
class MockHumanMessage:
    """Mock HumanMessage for testing - wraps real class from fixture."""

    def __init__(self, content, _classes=None):
        self._content = content
        self._classes = _classes

    def _get_real(self):
        return self._classes["HumanMessage"](content=self._content)


class MockAIMessage:
    """Mock AIMessage for testing - wraps real class from fixture."""

    def __init__(self, content, msg_id=None, _classes=None):
        self._content = content
        self._msg_id = msg_id
        self._classes = _classes

    def _get_real(self):
        msg = self._classes["AIMessage"](content=self._content)
        if self._msg_id:
            msg.id = self._msg_id
        return msg


class NamedTool:
    def __init__(self, name: str):
        self.name = name


def _skill(name: str, allowed_tools: list[str] | None) -> Skill:
    skill_dir = Path(f"/tmp/{name}")
    return Skill(
        name=name,
        description=f"{name} skill",
        license=None,
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path(name),
        category="custom",
        allowed_tools=allowed_tools,
        enabled=True,
    )


async def async_iterator(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def classes(_setup_executor_classes):
    """Provide access to executor classes."""
    return _setup_executor_classes


@pytest.fixture
def base_config(classes):
    """Return a basic subagent config for testing."""
    return classes["SubagentConfig"](
        name="test-agent",
        description="Test agent",
        system_prompt="You are a test agent.",
        max_turns=10,
        timeout_seconds=60,
    )


@pytest.fixture
def mock_agent():
    """Return a properly configured mock agent with async stream."""
    agent = MagicMock()
    agent.astream = MagicMock()
    return agent


def _module(name: str, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


# Helper to create real message objects
class _MsgHelper:
    """Helper to create real message objects from fixture classes."""

    def __init__(self, classes):
        self.classes = classes

    def human(self, content):
        return self.classes["HumanMessage"](content=content)

    def ai(self, content, msg_id=None):
        msg = self.classes["AIMessage"](content=content)
        if msg_id:
            msg.id = msg_id
        return msg


@pytest.fixture
def msg(classes):
    """Provide message factory."""
    return _MsgHelper(classes)


# -----------------------------------------------------------------------------
# Agent Construction Tests
# -----------------------------------------------------------------------------


class TestAgentConstruction:
    """Test _create_agent() wiring before execution starts."""

    def test_create_agent_threads_explicit_app_config_to_model_and_middlewares(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Explicit app_config must flow into both model and middleware factories."""
        import deerflow.config as config_module
        from deerflow.subagents import executor as executor_module

        SubagentExecutor = classes["SubagentExecutor"]

        app_config = SimpleNamespace(models=[SimpleNamespace(name="default-model")])
        model = object()
        middlewares = [object()]
        agent = object()
        captured: dict[str, dict] = {}

        def fake_get_app_config():
            raise AssertionError("ambient get_app_config() must not be used when app_config is explicit")

        def fake_create_chat_model(**kwargs):
            captured["model"] = kwargs
            return model

        def fake_build_subagent_runtime_middlewares(**kwargs):
            captured["middlewares"] = kwargs
            return middlewares

        def fake_create_agent(**kwargs):
            captured["agent"] = kwargs
            return agent

        monkeypatch.setattr(config_module, "get_app_config", fake_get_app_config)
        monkeypatch.setattr(
            executor_module,
            "create_chat_model",
            fake_create_chat_model,
        )
        monkeypatch.setattr(executor_module, "create_agent", fake_create_agent)
        monkeypatch.setitem(
            sys.modules,
            "deerflow.agents.middlewares.tool_error_handling_middleware",
            _module(
                "deerflow.agents.middlewares.tool_error_handling_middleware",
                build_subagent_runtime_middlewares=fake_build_subagent_runtime_middlewares,
            ),
        )

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            app_config=app_config,
            parent_model="parent-model",
        )

        result = executor._create_agent()

        assert result is agent
        assert captured["model"] == {
            "name": "parent-model",
            "thinking_enabled": False,
            "app_config": app_config,
            # attach_tracing=False pairs with graph-root tracing callbacks
            # injected in _aexecute (see TestSubagentTracingWiring). Without
            # this the subagent would emit both a model-level trace and a
            # graph-level trace per call.
            "attach_tracing": False,
        }
        assert captured["middlewares"] == {
            "app_config": app_config,
            "model_name": "parent-model",
            "lazy_init": True,
            "deferred_setup": None,
        }
        assert captured["agent"]["model"] is model
        assert captured["agent"]["middleware"] is middlewares
        assert captured["agent"]["tools"] == []
        assert captured["agent"]["system_prompt"] is None  # system_prompt is merged into initial state messages

    @pytest.mark.anyio
    async def test_load_skill_messages_uses_explicit_app_config_for_skill_storage(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ):
        """Explicit app_config must be threaded into subagent skill storage lookup."""
        SubagentExecutor = classes["SubagentExecutor"]

        app_config = SimpleNamespace(models=[SimpleNamespace(name="default-model")])
        skill_dir = tmp_path / "demo-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("Use demo skill", encoding="utf-8")
        captured: dict[str, object] = {}

        def fake_get_or_new_skill_storage(*, app_config=None):
            captured["app_config"] = app_config
            return SimpleNamespace(load_skills=lambda *, enabled_only: [SimpleNamespace(name="demo-skill", skill_file=skill_file)])

        monkeypatch.setattr(sys.modules["deerflow.skills.storage"], "get_or_new_skill_storage", fake_get_or_new_skill_storage)

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            app_config=app_config,
            thread_id="test-thread",
        )

        skills = await executor._load_skills()
        messages = await executor._load_skill_messages(skills)

        assert captured["app_config"] is app_config
        assert len(messages) == 1
        assert "Use demo skill" in messages[0].content

    @pytest.mark.anyio
    async def test_build_initial_state_consolidates_system_prompt_and_skills(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ):
        """_build_initial_state merges system_prompt and skills into one SystemMessage."""
        SubagentExecutor = classes["SubagentExecutor"]

        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("Skill instructions here", encoding="utf-8")

        monkeypatch.setattr(
            sys.modules["deerflow.skills.storage"],
            "get_or_new_skill_storage",
            lambda *, app_config=None: SimpleNamespace(load_skills=lambda *, enabled_only: [SimpleNamespace(name="my-skill", skill_file=skill_file, allowed_tools=None)]),
        )

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        state, _final_tools, _deferred_setup = await executor._build_initial_state("Do the task")

        messages = state["messages"]
        # Should have exactly 2 messages: one combined SystemMessage + one HumanMessage
        assert len(messages) == 2

        from langchain_core.messages import HumanMessage, SystemMessage

        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        # SystemMessage should contain both the system_prompt and skill content
        assert base_config.system_prompt in messages[0].content
        assert "Skill instructions here" in messages[0].content
        # HumanMessage should be the task
        assert messages[1].content == "Do the task"

    @pytest.mark.anyio
    async def test_build_initial_state_no_skills_only_system_prompt(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """_build_initial_state works when there are no skills."""
        SubagentExecutor = classes["SubagentExecutor"]

        monkeypatch.setattr(
            sys.modules["deerflow.skills.storage"],
            "get_or_new_skill_storage",
            lambda *, app_config=None: SimpleNamespace(load_skills=lambda *, enabled_only: []),
        )

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        state, _final_tools, _deferred_setup = await executor._build_initial_state("Do the task")

        messages = state["messages"]
        from langchain_core.messages import HumanMessage, SystemMessage

        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert base_config.system_prompt in messages[0].content
        assert isinstance(messages[1], HumanMessage)

    @pytest.mark.anyio
    async def test_build_initial_state_no_system_prompt_with_skills(
        self,
        classes,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ):
        """_build_initial_state works when there is no system_prompt but there are skills."""
        SubagentConfig = classes["SubagentConfig"]

        config = SubagentConfig(
            name="test-agent",
            description="Test agent",
            system_prompt=None,
            max_turns=10,
            timeout_seconds=60,
        )

        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("Skill content", encoding="utf-8")

        monkeypatch.setattr(
            sys.modules["deerflow.skills.storage"],
            "get_or_new_skill_storage",
            lambda *, app_config=None: SimpleNamespace(load_skills=lambda *, enabled_only: [SimpleNamespace(name="my-skill", skill_file=skill_file, allowed_tools=None)]),
        )

        SubagentExecutor = classes["SubagentExecutor"]
        executor = SubagentExecutor(config=config, tools=[], thread_id="test-thread")

        state, _final_tools, _deferred_setup = await executor._build_initial_state("Do the task")

        messages = state["messages"]
        from langchain_core.messages import HumanMessage, SystemMessage

        assert len(messages) == 2
        assert isinstance(messages[0], SystemMessage)
        assert "Skill content" in messages[0].content
        assert isinstance(messages[1], HumanMessage)

    @pytest.mark.anyio
    async def test_build_initial_state_defers_mcp_tools_when_tool_search_enabled(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """tool_search enabled + a surviving MCP tool: _build_initial_state appends
        the tool_search tool, withholds the MCP schema, and injects the
        <available-deferred-tools> section into the SystemMessage."""
        from langchain_core.tools import tool as as_tool

        from deerflow.subagents import executor as executor_module
        from deerflow.tools.mcp_metadata import tag_mcp_tool

        SubagentExecutor = classes["SubagentExecutor"]

        monkeypatch.setattr(
            sys.modules["deerflow.skills.storage"],
            "get_or_new_skill_storage",
            lambda *, app_config=None: SimpleNamespace(load_skills=lambda *, enabled_only: []),
        )
        monkeypatch.setattr(executor_module, "get_app_config", lambda: SimpleNamespace(tool_search=SimpleNamespace(enabled=True)))

        @as_tool
        def mcp_calc(expression: str) -> str:
            "Evaluate arithmetic."
            return expression

        executor = SubagentExecutor(config=base_config, tools=[tag_mcp_tool(mcp_calc)], thread_id="test-thread")

        state, final_tools, deferred_setup = await executor._build_initial_state("Do the task")

        assert "tool_search" in [t.name for t in final_tools]
        assert deferred_setup.deferred_names == frozenset({"mcp_calc"})

        system_message = state["messages"][0]
        assert "<available-deferred-tools>" in system_message.content
        assert "mcp_calc" in system_message.content
        # The base system_prompt is still present alongside the injected section.
        assert base_config.system_prompt in system_message.content

    @pytest.mark.anyio
    async def test_build_initial_state_no_deferral_when_tool_search_disabled(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """tool_search disabled: no tool_search tool, no section - pure no-op even
        with an MCP-tagged tool present."""
        from langchain_core.tools import tool as as_tool

        from deerflow.subagents import executor as executor_module
        from deerflow.tools.mcp_metadata import tag_mcp_tool

        SubagentExecutor = classes["SubagentExecutor"]

        monkeypatch.setattr(
            sys.modules["deerflow.skills.storage"],
            "get_or_new_skill_storage",
            lambda *, app_config=None: SimpleNamespace(load_skills=lambda *, enabled_only: []),
        )
        monkeypatch.setattr(executor_module, "get_app_config", lambda: SimpleNamespace(tool_search=SimpleNamespace(enabled=False)))

        @as_tool
        def mcp_calc(expression: str) -> str:
            "Evaluate arithmetic."
            return expression

        executor = SubagentExecutor(config=base_config, tools=[tag_mcp_tool(mcp_calc)], thread_id="test-thread")

        state, final_tools, deferred_setup = await executor._build_initial_state("Do the task")

        assert "tool_search" not in [t.name for t in final_tools]
        assert deferred_setup.deferred_names == frozenset()
        assert "<available-deferred-tools>" not in state["messages"][0].content

    @pytest.mark.anyio
    async def test_build_initial_state_deferral_respects_tool_policy_and_tool_search_is_infra(
        self,
        classes,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Adversarial-review follow-up (#3341): tool_search is appended AFTER the
        subagent tool-policy filter, mirroring the lead's intentional decision
        (test_tool_search_appended_after_policy_but_never_exposes_denied_tool).
        Lock the safe-by-construction property:

        - an MCP tool denied by ``disallowed_tools`` never enters the deferred
          catalog, so tool_search can never promote/expose it;
        - tool_search itself is infrastructure: naming it in ``disallowed_tools``
          does not remove it, because its catalog derives from the already-
          filtered list and carries no access the policy didn't already grant.
        """
        from langchain_core.tools import tool as as_tool

        from deerflow.subagents import executor as executor_module
        from deerflow.tools.mcp_metadata import tag_mcp_tool

        SubagentConfig = classes["SubagentConfig"]
        SubagentExecutor = classes["SubagentExecutor"]

        monkeypatch.setattr(
            sys.modules["deerflow.skills.storage"],
            "get_or_new_skill_storage",
            lambda *, app_config=None: SimpleNamespace(load_skills=lambda *, enabled_only: []),
        )
        monkeypatch.setattr(executor_module, "get_app_config", lambda: SimpleNamespace(tool_search=SimpleNamespace(enabled=True)))

        @as_tool
        def active_tool(x: str) -> str:
            "active"
            return x

        @as_tool
        def mcp_allowed(x: str) -> str:
            "allowed mcp tool"
            return x

        @as_tool
        def mcp_denied(x: str) -> str:
            "denied mcp tool"
            return x

        config = SubagentConfig(
            name="test-agent",
            description="Test agent",
            system_prompt="You are a test agent.",
            max_turns=10,
            timeout_seconds=60,
            disallowed_tools=["mcp_denied", "tool_search"],
        )
        executor = SubagentExecutor(
            config=config,
            tools=[active_tool, tag_mcp_tool(mcp_allowed), tag_mcp_tool(mcp_denied)],
            thread_id="test-thread",
        )

        _state, final_tools, deferred_setup = await executor._build_initial_state("Do the task")

        names = {t.name for t in final_tools}
        # The policy-denied MCP tool is gone and never reaches the catalog.
        assert "mcp_denied" not in names
        assert "mcp_denied" not in deferred_setup.deferred_names
        assert deferred_setup.deferred_names == frozenset({"mcp_allowed"})
        # tool_search is infra: present despite being named in disallowed_tools.
        assert "tool_search" in names

    def test_create_agent_threads_deferred_setup_to_middlewares(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """A deferred setup passed to _create_agent flows into the subagent
        middleware factory (so DeferredToolFilterMiddleware can attach)."""
        from deerflow.subagents import executor as executor_module
        from deerflow.tools.builtins.tool_search import DeferredToolSetup

        SubagentExecutor = classes["SubagentExecutor"]
        app_config = SimpleNamespace(models=[SimpleNamespace(name="default-model")])
        captured: dict[str, object] = {}

        def fake_build_subagent_runtime_middlewares(**kwargs):
            captured["middlewares"] = kwargs
            return [object()]

        monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: object())
        monkeypatch.setattr(executor_module, "create_agent", lambda **kwargs: object())
        monkeypatch.setitem(
            sys.modules,
            "deerflow.agents.middlewares.tool_error_handling_middleware",
            _module(
                "deerflow.agents.middlewares.tool_error_handling_middleware",
                build_subagent_runtime_middlewares=fake_build_subagent_runtime_middlewares,
            ),
        )

        deferred_setup = DeferredToolSetup(object(), frozenset({"mcp_calc"}), "hash123")
        executor = SubagentExecutor(config=base_config, tools=[], app_config=app_config, parent_model="parent-model")

        executor._create_agent(tools=[], deferred_setup=deferred_setup)

        assert captured["middlewares"]["deferred_setup"] is deferred_setup


# -----------------------------------------------------------------------------
# Async Execution Path Tests
# -----------------------------------------------------------------------------


class TestAsyncExecutionPath:
    """Test _aexecute() async execution path."""

    @pytest.mark.anyio
    async def test_aexecute_success(self, classes, base_config, mock_agent, msg):
        """Test successful async execution returns completed result."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        final_message = msg.ai("Task completed successfully", "msg-1")
        final_state = {
            "messages": [
                msg.human("Do something"),
                final_message,
            ]
        }
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
            trace_id="test-trace",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Do something")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Task completed successfully"
        assert result.error is None
        assert result.started_at is not None
        assert result.completed_at is not None

    @pytest.mark.anyio
    async def test_aexecute_collects_ai_messages(self, classes, base_config, mock_agent, msg):
        """Test that AI messages are collected during streaming."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        msg1 = msg.ai("First response", "msg-1")
        msg2 = msg.ai("Second response", "msg-2")

        chunk1 = {"messages": [msg.human("Task"), msg1]}
        chunk2 = {"messages": [msg.human("Task"), msg1, msg2]}

        mock_agent.astream = lambda *args, **kwargs: async_iterator([chunk1, chunk2])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert len(result.ai_messages) == 2
        assert result.ai_messages[0]["id"] == "msg-1"
        assert result.ai_messages[1]["id"] == "msg-2"

    @pytest.mark.anyio
    async def test_aexecute_handles_duplicate_messages(self, classes, base_config, mock_agent, msg):
        """Test that duplicate AI messages are not added."""
        SubagentExecutor = classes["SubagentExecutor"]

        msg1 = msg.ai("Response", "msg-1")

        # Same message appears in multiple chunks
        chunk1 = {"messages": [msg.human("Task"), msg1]}
        chunk2 = {"messages": [msg.human("Task"), msg1]}

        mock_agent.astream = lambda *args, **kwargs: async_iterator([chunk1, chunk2])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert len(result.ai_messages) == 1

    @pytest.mark.anyio
    async def test_aexecute_handles_list_content(self, classes, base_config, mock_agent, msg):
        """Test handling of list-type content in AIMessage."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        final_message = msg.ai([{"text": "Part 1"}, {"text": "Part 2"}])
        final_state = {
            "messages": [
                msg.human("Task"),
                final_message,
            ]
        }
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert "Part 1" in result.result
        assert "Part 2" in result.result

    @pytest.mark.anyio
    async def test_aexecute_handles_agent_exception(self, classes, base_config, mock_agent):
        """Test that exceptions during execution are caught and returned as FAILED."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        mock_agent.astream.side_effect = Exception("Agent error")

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.FAILED
        assert "Agent error" in result.error
        assert result.completed_at is not None

    @pytest.mark.anyio
    async def test_aexecute_no_final_state(self, classes, base_config, mock_agent):
        """Test handling when no final state is returned."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        mock_agent.astream = lambda *args, **kwargs: async_iterator([])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "No response generated"

    @pytest.mark.anyio
    async def test_aexecute_no_ai_message_in_state(self, classes, base_config, mock_agent, msg):
        """Test fallback when no AIMessage found in final state."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        final_state = {"messages": [msg.human("Task")]}
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        # Should fallback to string representation of last message
        assert result.status == SubagentStatus.COMPLETED
        assert "Task" in result.result

    @pytest.mark.anyio
    async def test_aexecute_passes_at_most_one_system_message_to_agent(
        self,
        classes,
        base_config,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ):
        """Regression: messages sent to agent.astream must contain at most one
        SystemMessage and it must be the first message.

        This catches any regression where system_prompt would be re-injected
        via create_agent() (e.g. system_prompt not passed as None) and appear
        as a second SystemMessage, which providers like vLLM and Xinference
        reject with "System message must be at the beginning."
        """
        from langchain_core.messages import AIMessage, SystemMessage

        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        # Set up a skill so both system_prompt AND skill content are present,
        # maximising the chance of catching a double-SystemMessage regression.
        skill_dir = tmp_path / "regression-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Skill instruction text", encoding="utf-8")

        monkeypatch.setattr(
            sys.modules["deerflow.skills.storage"],
            "get_or_new_skill_storage",
            lambda *, app_config=None: SimpleNamespace(load_skills=lambda *, enabled_only: [SimpleNamespace(name="regression-skill", skill_file=skill_dir / "SKILL.md", allowed_tools=None)]),
        )

        captured_states: list[dict] = []

        async def capturing_astream(state, **kwargs):
            captured_states.append(state)
            yield {"messages": [AIMessage(content="Done", id="msg-1")]}

        mock_agent = MagicMock()
        mock_agent.astream = capturing_astream

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Do something")

        assert result.status == SubagentStatus.COMPLETED
        assert len(captured_states) == 1, "astream should be called exactly once"
        initial_messages = captured_states[0]["messages"]

        system_messages = [m for m in initial_messages if isinstance(m, SystemMessage)]
        assert len(system_messages) <= 1, f"Expected at most 1 SystemMessage but got {len(system_messages)}: {system_messages}"
        if system_messages:
            assert initial_messages[0] is system_messages[0], "SystemMessage must be the first message in the conversation"
            # The consolidated SystemMessage must carry both the system_prompt
            # and all skill content; nothing should be split across two messages.
            assert base_config.system_prompt in system_messages[0].content
            assert "Skill instruction text" in system_messages[0].content


class TestSkillAllowedTools:
    @pytest.mark.anyio
    async def test_skill_allowed_tools_union_filters_agent_tools(self, classes, base_config, mock_agent, msg):
        SubagentExecutor = classes["SubagentExecutor"]

        final_state = {"messages": [msg.human("Task"), msg.ai("Done", "msg-1")]}
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])
        tools = [NamedTool("bash"), NamedTool("read_file"), NamedTool("web_search")]
        executor = SubagentExecutor(config=base_config, tools=tools, thread_id="test-thread")

        async def load_skills():
            return [_skill("a", ["bash"]), _skill("b", ["read_file"])]

        with patch.object(executor, "_load_skills", load_skills), patch.object(executor, "_create_agent", return_value=mock_agent) as create_agent_mock:
            await executor._aexecute("Task")

        create_agent_mock.assert_called_once()
        assert [tool.name for tool in create_agent_mock.call_args.args[0]] == ["bash", "read_file"]
        assert [tool.name for tool in executor.tools] == ["bash", "read_file", "web_search"]

    @pytest.mark.anyio
    async def test_all_missing_allowed_tools_preserves_legacy_allow_all(self, classes, base_config, mock_agent, msg):
        SubagentExecutor = classes["SubagentExecutor"]

        final_state = {"messages": [msg.human("Task"), msg.ai("Done", "msg-1")]}
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])
        tools = [NamedTool("bash"), NamedTool("read_file"), NamedTool("web_search")]
        executor = SubagentExecutor(config=base_config, tools=tools, thread_id="test-thread")

        async def load_skills():
            return [_skill("legacy-a", None), _skill("legacy-b", None)]

        with patch.object(executor, "_load_skills", load_skills), patch.object(executor, "_create_agent", return_value=mock_agent) as create_agent_mock:
            await executor._aexecute("Task")

        assert [tool.name for tool in create_agent_mock.call_args.args[0]] == ["bash", "read_file", "web_search"]
        assert [tool.name for tool in executor.tools] == ["bash", "read_file", "web_search"]

    @pytest.mark.anyio
    async def test_mixed_missing_allowed_tools_does_not_disable_explicit_restrictions(self, classes, base_config, mock_agent, msg):
        SubagentExecutor = classes["SubagentExecutor"]

        final_state = {"messages": [msg.human("Task"), msg.ai("Done", "msg-1")]}
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])
        tools = [NamedTool("bash"), NamedTool("read_file"), NamedTool("web_search")]
        executor = SubagentExecutor(config=base_config, tools=tools, thread_id="test-thread")

        async def load_skills():
            return [_skill("legacy", None), _skill("restricted", ["bash"])]

        with patch.object(executor, "_load_skills", load_skills), patch.object(executor, "_create_agent", return_value=mock_agent) as create_agent_mock:
            await executor._aexecute("Task")

        assert [tool.name for tool in create_agent_mock.call_args.args[0]] == ["bash"]
        assert [tool.name for tool in executor.tools] == ["bash", "read_file", "web_search"]

    @pytest.mark.anyio
    async def test_mixed_missing_allowed_tools_order_does_not_disable_explicit_restrictions(self, classes, base_config, mock_agent, msg):
        SubagentExecutor = classes["SubagentExecutor"]

        final_state = {"messages": [msg.human("Task"), msg.ai("Done", "msg-1")]}
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])
        tools = [NamedTool("bash"), NamedTool("read_file"), NamedTool("web_search")]
        executor = SubagentExecutor(config=base_config, tools=tools, thread_id="test-thread")

        async def load_skills():
            return [_skill("restricted", ["bash"]), _skill("legacy", None)]

        with patch.object(executor, "_load_skills", load_skills), patch.object(executor, "_create_agent", return_value=mock_agent) as create_agent_mock:
            await executor._aexecute("Task")

        assert [tool.name for tool in create_agent_mock.call_args.args[0]] == ["bash"]
        assert [tool.name for tool in executor.tools] == ["bash", "read_file", "web_search"]

    @pytest.mark.anyio
    async def test_empty_allowed_tools_contributes_no_tools(self, classes, base_config, mock_agent, msg, caplog):
        SubagentExecutor = classes["SubagentExecutor"]

        final_state = {"messages": [msg.human("Task"), msg.ai("Done", "msg-1")]}
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])
        tools = [NamedTool("bash"), NamedTool("read_file"), NamedTool("web_search")]
        executor = SubagentExecutor(config=base_config, tools=tools, thread_id="test-thread")

        async def load_skills():
            return [_skill("empty", []), _skill("reader", ["read_file"])]

        with patch.object(executor, "_load_skills", load_skills), patch.object(executor, "_create_agent", return_value=mock_agent) as create_agent_mock, caplog.at_level("INFO"):
            await executor._aexecute("Task")

        assert [tool.name for tool in create_agent_mock.call_args.args[0]] == ["read_file"]
        assert [tool.name for tool in executor.tools] == ["bash", "read_file", "web_search"]
        assert "declared empty allowed-tools" in caplog.text

    @pytest.mark.anyio
    async def test_skill_load_failure_fails_without_creating_agent(self, classes, base_config, mock_agent):
        SubagentExecutor = classes["SubagentExecutor"]
        executor = SubagentExecutor(config=base_config, tools=[NamedTool("bash")], thread_id="test-thread")

        async def load_skills():
            raise RuntimeError("skill storage unavailable")

        with patch.object(executor, "_load_skills", load_skills), patch.object(executor, "_create_agent", return_value=mock_agent) as create_agent_mock:
            result = await executor._aexecute("Task")

        assert result.status == classes["SubagentStatus"].FAILED
        assert result.error == "skill storage unavailable"
        create_agent_mock.assert_not_called()


# -----------------------------------------------------------------------------
# Sync Execution Path Tests
# -----------------------------------------------------------------------------


class TestSyncExecutionPath:
    """Test execute() synchronous execution path with asyncio.run()."""

    def test_execute_runs_async_in_event_loop(self, classes, base_config, mock_agent, msg):
        """Test that execute() runs _aexecute() in a new event loop via asyncio.run()."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        final_message = msg.ai("Sync result", "msg-1")
        final_state = {
            "messages": [
                msg.human("Task"),
                final_message,
            ]
        }
        mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = executor.execute("Task")

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Sync result"

    def test_execute_in_thread_pool_context(self, classes, base_config, msg):
        """Test that execute() works correctly when called from a thread pool.

        This simulates the real-world usage where execute() is called from
        a worker thread outside the main event loop.
        """
        from concurrent.futures import ThreadPoolExecutor

        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        final_message = msg.ai("Thread pool result", "msg-1")
        final_state = {
            "messages": [
                msg.human("Task"),
                final_message,
            ]
        }

        def run_in_thread():
            mock_agent = MagicMock()
            mock_agent.astream = lambda *args, **kwargs: async_iterator([final_state])

            executor = SubagentExecutor(
                config=base_config,
                tools=[],
                thread_id="test-thread",
            )

            with patch.object(executor, "_create_agent", return_value=mock_agent):
                return executor.execute("Task")

        # Execute in thread pool to simulate sync execution outside the main loop.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run_in_thread)
            result = future.result(timeout=5)

        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Thread pool result"

    @pytest.mark.anyio
    async def test_execute_in_running_event_loop_calls_isolated_loop_directly(self, classes, base_config, mock_agent, msg):
        """Test that execute() calls the isolated-loop helper directly in a running loop."""
        from deerflow.runtime.user_context import (
            get_effective_user_id,
            reset_current_user,
            set_current_user,
        )

        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        caller_thread = threading.current_thread().name
        isolated_helper_threads = []
        execution_threads = []
        effective_user_ids = []
        final_state = {
            "messages": [
                msg.human("Task"),
                msg.ai("Async loop result", "msg-1"),
            ]
        }

        async def mock_astream(*args, **kwargs):
            execution_threads.append(threading.current_thread().name)
            effective_user_ids.append(get_effective_user_id())
            yield final_state

        mock_agent.astream = mock_astream

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        original_isolated_execute = executor._execute_in_isolated_loop

        def tracked_isolated_execute(task, result_holder=None):
            isolated_helper_threads.append(threading.current_thread().name)
            return original_isolated_execute(task, result_holder)

        token = set_current_user(SimpleNamespace(id="alice"))
        try:
            with patch.object(executor, "_create_agent", return_value=mock_agent):
                with patch.object(executor, "_execute_in_isolated_loop", side_effect=tracked_isolated_execute) as isolated:
                    result = executor.execute("Task")
        finally:
            reset_current_user(token)

        assert isolated.call_count == 1
        assert isolated_helper_threads == [caller_thread]
        assert execution_threads
        assert execution_threads == ["subagent-persistent-loop"]
        assert effective_user_ids == ["alice"]
        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "Async loop result"

    @pytest.mark.anyio
    async def test_execute_in_running_event_loop_reuses_persistent_isolated_loop(self, classes, base_config, mock_agent, msg):
        """Regression: repeated isolated executions should reuse one long-lived loop."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]
        execution_loops = []

        final_state = {
            "messages": [
                msg.human("Task"),
                msg.ai("Async loop result", "msg-1"),
            ]
        }

        async def mock_astream(*args, **kwargs):
            execution_loops.append(asyncio.get_running_loop())
            yield final_state

        mock_agent.astream = mock_astream

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            first = executor.execute("Task 1")
            second = executor.execute("Task 2")

        assert first.status == SubagentStatus.COMPLETED
        assert second.status == SubagentStatus.COMPLETED
        assert len(execution_loops) == 2
        assert execution_loops[0] is execution_loops[1]
        assert execution_loops[0].is_running()

    def test_execute_handles_asyncio_run_failure(self, classes, base_config):
        """Test handling when asyncio.run() itself fails."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_aexecute") as mock_aexecute:
            mock_aexecute.side_effect = Exception("Asyncio run error")

            result = executor.execute("Task")

        assert result.status == SubagentStatus.FAILED
        assert "Asyncio run error" in result.error
        assert result.completed_at is not None

    def test_execute_with_result_holder(self, classes, base_config, mock_agent, msg):
        """Test execute() updates provided result_holder in real-time."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        msg1 = msg.ai("Step 1", "msg-1")
        chunk1 = {"messages": [msg.human("Task"), msg1]}

        mock_agent.astream = lambda *args, **kwargs: async_iterator([chunk1])

        # Pre-create result holder (as done in execute_async)
        result_holder = SubagentResult(
            task_id="predefined-id",
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = executor.execute("Task", result_holder=result_holder)

        # Should be the same object
        assert result is result_holder
        assert result.task_id == "predefined-id"
        assert result.status == SubagentStatus.COMPLETED


# -----------------------------------------------------------------------------
# Async Tool Support Tests (MCP Tools)
# -----------------------------------------------------------------------------


class TestAsyncToolSupport:
    """Test that async-only tools (like MCP tools) work correctly."""

    @pytest.mark.anyio
    async def test_async_tool_called_in_astream(self, classes, base_config, msg):
        """Test that async tools are properly awaited in astream.

        This verifies the fix for: async MCP tools not being executed properly
        because they were being called synchronously.
        """
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        async_tool_calls = []

        async def mock_async_tool(*args, **kwargs):
            async_tool_calls.append("called")
            await asyncio.sleep(0.01)  # Simulate async work
            return {"result": "async tool result"}

        mock_agent = MagicMock()

        # Simulate agent that calls async tools during streaming
        async def mock_astream(*args, **kwargs):
            await mock_async_tool()
            yield {
                "messages": [
                    msg.human("Task"),
                    msg.ai("Done", "msg-1"),
                ]
            }

        mock_agent.astream = mock_astream

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task")

        assert len(async_tool_calls) == 1
        assert result.status == SubagentStatus.COMPLETED

    def test_sync_execute_with_async_tools(self, classes, base_config, msg):
        """Test that sync execute() properly runs async tools via asyncio.run()."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        async_tool_calls = []

        async def mock_async_tool():
            async_tool_calls.append("called")
            await asyncio.sleep(0.01)
            return {"result": "async result"}

        mock_agent = MagicMock()

        async def mock_astream(*args, **kwargs):
            await mock_async_tool()
            yield {
                "messages": [
                    msg.human("Task"),
                    msg.ai("Done", "msg-1"),
                ]
            }

        mock_agent.astream = mock_astream

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = executor.execute("Task")

        assert len(async_tool_calls) == 1
        assert result.status == SubagentStatus.COMPLETED


# -----------------------------------------------------------------------------
# Thread Safety Tests
# -----------------------------------------------------------------------------


class TestThreadSafety:
    """Test thread safety of executor operations."""

    @pytest.fixture
    def executor_module(self, _setup_executor_classes):
        """Import the executor module with real classes."""
        executor = importlib.import_module("deerflow.subagents.executor")

        return _patch_default_get_app_config(importlib.reload(executor))

    def test_multiple_executors_in_parallel(self, classes, base_config, msg):
        """Test multiple executors running in parallel via thread pool."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        results = []

        def execute_task(task_id: int):
            def make_astream(*args, **kwargs):
                return async_iterator(
                    [
                        {
                            "messages": [
                                msg.human(f"Task {task_id}"),
                                msg.ai(f"Result {task_id}", f"msg-{task_id}"),
                            ]
                        }
                    ]
                )

            mock_agent = MagicMock()
            mock_agent.astream = make_astream

            executor = SubagentExecutor(
                config=base_config,
                tools=[],
                thread_id=f"thread-{task_id}",
            )

            with patch.object(executor, "_create_agent", return_value=mock_agent):
                return executor.execute(f"Task {task_id}")

        # Execute multiple tasks in parallel
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(execute_task, i) for i in range(5)]
            for future in as_completed(futures):
                results.append(future.result())

        assert len(results) == 5
        for result in results:
            assert result.status == SubagentStatus.COMPLETED
            assert "Result" in result.result

    def test_terminal_status_is_published_after_payload_fields(self, executor_module, monkeypatch):
        """Readers must not observe terminal status before terminal payload is complete."""
        SubagentResult = executor_module.SubagentResult
        SubagentStatus = executor_module.SubagentStatus

        now_entered = threading.Event()
        release_now = threading.Event()
        completed_at = datetime(2026, 5, 1, 12, 0, 0)
        writer_errors: list[BaseException] = []

        class BlockingDateTime:
            @staticmethod
            def now():
                now_entered.set()
                release_now.wait(timeout=5)
                return completed_at

        monkeypatch.setattr(executor_module, "datetime", BlockingDateTime)

        result = SubagentResult(
            task_id="test-terminal-publication-order",
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,
        )
        token_usage_records = [
            {
                "source_run_id": "run-1",
                "caller": "subagent:test-agent",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            }
        ]

        def set_terminal():
            try:
                assert result.try_set_terminal(
                    SubagentStatus.COMPLETED,
                    result="done",
                    token_usage_records=token_usage_records,
                )
            except BaseException as exc:
                writer_errors.append(exc)

        writer = threading.Thread(target=set_terminal)
        writer.start()

        assert now_entered.wait(timeout=3), "try_set_terminal did not reach completed_at assignment"
        assert result.completed_at is None
        assert result.status == SubagentStatus.RUNNING
        assert result.token_usage_records == token_usage_records

        release_now.set()
        writer.join(timeout=3)

        assert not writer.is_alive(), "try_set_terminal did not finish"
        assert writer_errors == []
        assert result.completed_at == completed_at
        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "done"
        assert result.token_usage_records == token_usage_records


# -----------------------------------------------------------------------------
# Cleanup Background Task Tests
# -----------------------------------------------------------------------------


class TestCleanupBackgroundTask:
    """Test cleanup_background_task function for race condition prevention."""

    @pytest.fixture
    def executor_module(self, _setup_executor_classes):
        """Import the executor module with real classes."""
        # Re-import to get the real module with cleanup_background_task
        executor = importlib.import_module("deerflow.subagents.executor")

        return _patch_default_get_app_config(importlib.reload(executor))

    def test_cleanup_removes_terminal_completed_task(self, executor_module, classes):
        """Test that cleanup removes a COMPLETED task."""
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        # Add a completed task
        task_id = "test-completed-task"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.COMPLETED,
            result="done",
            completed_at=datetime.now(),
        )
        executor_module._background_tasks[task_id] = result

        # Cleanup should remove it
        executor_module.cleanup_background_task(task_id)

        assert task_id not in executor_module._background_tasks

    def test_cleanup_removes_terminal_failed_task(self, executor_module, classes):
        """Test that cleanup removes a FAILED task."""
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        task_id = "test-failed-task"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.FAILED,
            error="error",
            completed_at=datetime.now(),
        )
        executor_module._background_tasks[task_id] = result

        executor_module.cleanup_background_task(task_id)

        assert task_id not in executor_module._background_tasks

    def test_cleanup_removes_terminal_timed_out_task(self, executor_module, classes):
        """Test that cleanup removes a TIMED_OUT task."""
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        task_id = "test-timedout-task"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.TIMED_OUT,
            error="timeout",
            completed_at=datetime.now(),
        )
        executor_module._background_tasks[task_id] = result

        executor_module.cleanup_background_task(task_id)

        assert task_id not in executor_module._background_tasks

    def test_cleanup_skips_running_task(self, executor_module, classes):
        """Test that cleanup does NOT remove a RUNNING task.

        This prevents race conditions where task_tool calls cleanup
        while the background executor is still updating the task.
        """
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        task_id = "test-running-task"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )
        executor_module._background_tasks[task_id] = result

        executor_module.cleanup_background_task(task_id)

        # Should still be present because it's RUNNING
        assert task_id in executor_module._background_tasks

    def test_cleanup_skips_pending_task(self, executor_module, classes):
        """Test that cleanup does NOT remove a PENDING task."""
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        task_id = "test-pending-task"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.PENDING,
        )
        executor_module._background_tasks[task_id] = result

        executor_module.cleanup_background_task(task_id)

        assert task_id in executor_module._background_tasks

    def test_cleanup_handles_unknown_task_gracefully(self, executor_module):
        """Test that cleanup doesn't raise for unknown task IDs."""
        # Should not raise
        executor_module.cleanup_background_task("nonexistent-task")

    def test_cleanup_removes_task_with_completed_at_even_if_running(self, executor_module, classes):
        """Test that cleanup removes task if completed_at is set, even if status is RUNNING.

        This is a safety net: if completed_at is set, the task is considered done
        regardless of status.
        """
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        task_id = "test-completed-at-task"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,  # Status not terminal
            completed_at=datetime.now(),  # But completed_at is set
        )
        executor_module._background_tasks[task_id] = result

        executor_module.cleanup_background_task(task_id)

        # Should be removed because completed_at is set
        assert task_id not in executor_module._background_tasks


# -----------------------------------------------------------------------------
# Cooperative Cancellation Tests
# -----------------------------------------------------------------------------


class TestCooperativeCancellation:
    """Test cooperative cancellation via cancel_event."""

    @pytest.fixture
    def executor_module(self, _setup_executor_classes):
        """Import the executor module with real classes."""
        executor = importlib.import_module("deerflow.subagents.executor")

        return _patch_default_get_app_config(importlib.reload(executor))

    @pytest.mark.anyio
    async def test_aexecute_cancelled_before_streaming(self, classes, base_config, mock_agent, msg):
        """Test that _aexecute returns CANCELLED when cancel_event is set before streaming."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        # The agent should never be called
        call_count = 0

        async def mock_astream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield {"messages": [msg.human("Task"), msg.ai("Done", "msg-1")]}

        mock_agent.astream = mock_astream

        # Pre-create result holder with cancel_event already set
        result_holder = SubagentResult(
            task_id="cancel-before",
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )
        result_holder.cancel_event.set()

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task", result_holder=result_holder)

        assert result.status == SubagentStatus.CANCELLED
        assert result.error == "Cancelled by user"
        assert result.completed_at is not None
        assert call_count == 0  # astream was never entered

    @pytest.mark.anyio
    async def test_aexecute_cancelled_mid_stream(self, classes, base_config, msg):
        """Test that _aexecute returns CANCELLED when cancel_event is set during streaming."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        cancel_event = threading.Event()

        async def mock_astream(*args, **kwargs):
            yield {"messages": [msg.human("Task"), msg.ai("Partial", "msg-1")]}
            # Simulate cancellation during streaming
            cancel_event.set()
            yield {"messages": [msg.human("Task"), msg.ai("Should not appear", "msg-2")]}

        mock_agent = MagicMock()
        mock_agent.astream = mock_astream

        result_holder = SubagentResult(
            task_id="cancel-mid",
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )
        result_holder.cancel_event = cancel_event

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
        )

        with patch.object(executor, "_create_agent", return_value=mock_agent):
            result = await executor._aexecute("Task", result_holder=result_holder)

        assert result.status == SubagentStatus.CANCELLED
        assert result.error == "Cancelled by user"
        assert result.completed_at is not None

    def test_request_cancel_sets_event(self, executor_module, classes):
        """Test that request_cancel_background_task sets the cancel_event."""
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        task_id = "test-cancel-event"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.RUNNING,
            started_at=datetime.now(),
        )
        executor_module._background_tasks[task_id] = result

        assert not result.cancel_event.is_set()

        executor_module.request_cancel_background_task(task_id)

        assert result.cancel_event.is_set()

    def test_request_cancel_nonexistent_task_is_noop(self, executor_module):
        """Test that requesting cancellation on a nonexistent task does not raise."""
        executor_module.request_cancel_background_task("nonexistent-task")

    def test_execute_async_runs_without_calling_execute(self, executor_module, classes, base_config):
        """Regression: execute_async should not route through execute()/asyncio.run()."""
        import concurrent.futures

        SubagentExecutor = classes["SubagentExecutor"]
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        def run_inline(fn, *args, **kwargs):
            future = concurrent.futures.Future()
            try:
                future.set_result(fn(*args, **kwargs))
            except Exception as exc:
                future.set_exception(exc)
            return future

        async def fake_aexecute(task, result_holder=None):
            result = result_holder or SubagentResult(
                task_id="inline-task",
                trace_id="test-trace",
                status=SubagentStatus.RUNNING,
            )
            result.status = SubagentStatus.COMPLETED
            result.result = f"done: {task}"
            result.completed_at = datetime.now()
            return result

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
            trace_id="test-trace",
        )

        with (
            patch.object(executor_module._scheduler_pool, "submit", side_effect=run_inline),
            patch.object(executor, "_aexecute", side_effect=fake_aexecute),
            patch.object(executor, "execute", side_effect=AssertionError("execute() should not be called by execute_async")),
        ):
            task_id = executor.execute_async("Task")

        result = executor_module._background_tasks.get(task_id)
        assert result is not None
        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "done: Task"
        assert result.error is None

    def test_execute_async_propagates_user_context_to_isolated_loop(self, executor_module, classes, base_config):
        """Regression: background subagent execution must keep request user context."""
        import concurrent.futures

        from deerflow.runtime.user_context import (
            get_effective_user_id,
            reset_current_user,
            set_current_user,
        )

        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        async def fake_aexecute(task, result_holder=None):
            result = result_holder
            result.status = SubagentStatus.COMPLETED
            result.result = get_effective_user_id()
            result.completed_at = datetime.now()
            return result

        executor = SubagentExecutor(
            config=base_config,
            tools=[],
            thread_id="test-thread",
            trace_id="test-trace",
        )

        scheduler = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        token = set_current_user(SimpleNamespace(id="alice"))
        try:
            with (
                patch.object(executor_module, "_scheduler_pool", scheduler),
                patch.object(executor, "_aexecute", side_effect=fake_aexecute),
                patch.object(executor, "execute", side_effect=AssertionError("execute() should not be called by execute_async")),
            ):
                task_id = executor.execute_async("Task")
                executor_module._scheduler_pool.shutdown(wait=True)
        finally:
            reset_current_user(token)
            scheduler.shutdown(wait=False, cancel_futures=True)

        result = executor_module._background_tasks.get(task_id)
        assert result is not None
        assert result.status == SubagentStatus.COMPLETED
        assert result.result == "alice"
        assert result.error is None

    def test_timeout_does_not_overwrite_cancelled(self, executor_module, classes, base_config, msg):
        """Test that the real timeout handler does not overwrite CANCELLED status.

        This exercises the actual execute_async → run_task → FuturesTimeoutError
        code path in executor.py.  We make execute() block so the timeout fires
        deterministically, pre-set the task to CANCELLED, and verify the RUNNING
        guard preserves it.  Uses threading.Event for synchronisation instead of
        wall-clock sleeps.
        """
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        short_config = classes["SubagentConfig"](
            name="test-agent",
            description="Test agent",
            system_prompt="You are a test agent.",
            max_turns=10,
            timeout_seconds=0.05,  # 50ms – just enough for the future to time out
        )

        # Synchronisation primitives
        execute_entered = threading.Event()  # signals that _aexecute() has started
        run_task_done = threading.Event()  # signals that run_task() has finished

        # A blocking _aexecute() replacement so we control the timing exactly.
        async def blocking_aexecute(task, result_holder=None):
            execute_entered.set()
            await asyncio.Event().wait()

        executor = SubagentExecutor(
            config=short_config,
            tools=[],
            thread_id="test-thread",
            trace_id="test-trace",
        )

        # Wrap _scheduler_pool.submit so we know when run_task finishes
        original_scheduler_submit = executor_module._scheduler_pool.submit

        def tracked_submit(fn, *args, **kwargs):
            def wrapper():
                try:
                    fn(*args, **kwargs)
                finally:
                    run_task_done.set()

            return original_scheduler_submit(wrapper)

        with patch.object(executor, "_aexecute", side_effect=blocking_aexecute), patch.object(executor_module._scheduler_pool, "submit", tracked_submit):
            task_id = executor.execute_async("Task")

            # Wait until _aexecute() is entered on the persistent loop.
            assert execute_entered.wait(timeout=3), "_aexecute() was never called"

            # Set CANCELLED on the result before the timeout handler runs.
            # The 50ms timeout will fire while execute() is blocked.
            with executor_module._background_tasks_lock:
                executor_module._background_tasks[task_id].status = SubagentStatus.CANCELLED
                executor_module._background_tasks[task_id].error = "Cancelled by user"
                executor_module._background_tasks[task_id].completed_at = datetime.now()

            # Wait for run_task to finish — the FuturesTimeoutError handler has
            # now executed and (should have) left CANCELLED intact.
            assert run_task_done.wait(timeout=5), "run_task() did not finish"

        result = executor_module._background_tasks.get(task_id)
        assert result is not None
        # The RUNNING guard in the FuturesTimeoutError handler must have
        # preserved CANCELLED instead of overwriting with TIMED_OUT.
        assert result.status.value == SubagentStatus.CANCELLED.value
        assert result.error == "Cancelled by user"
        assert result.completed_at is not None

    def test_late_completion_after_timeout_does_not_overwrite_timed_out(self, executor_module, classes, msg):
        """Late completion from the execution worker must not overwrite TIMED_OUT."""
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentStatus = classes["SubagentStatus"]

        short_config = classes["SubagentConfig"](
            name="test-agent",
            description="Test agent",
            system_prompt="You are a test agent.",
            max_turns=10,
            timeout_seconds=0.05,
        )

        first_chunk_seen = threading.Event()
        finish_stream = threading.Event()
        execution_done = threading.Event()

        async def mock_astream(*args, **kwargs):
            yield {"messages": [msg.human("Task"), msg.ai("late completion", "msg-late")]}
            first_chunk_seen.set()
            deadline = asyncio.get_running_loop().time() + 5
            while not finish_stream.is_set():
                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.001)

        mock_agent = MagicMock()
        mock_agent.astream = mock_astream

        executor = SubagentExecutor(
            config=short_config,
            tools=[],
            thread_id="test-thread",
            trace_id="test-trace",
        )
        original_aexecute = executor._aexecute

        async def tracked_aexecute(task, result_holder=None):
            try:
                return await original_aexecute(task, result_holder)
            finally:
                execution_done.set()

        with patch.object(executor, "_create_agent", return_value=mock_agent), patch.object(executor, "_aexecute", tracked_aexecute):
            task_id = executor.execute_async("Task")
            assert first_chunk_seen.wait(timeout=3), "stream did not yield initial chunk"

            result = executor_module._background_tasks[task_id]
            assert result.cancel_event.wait(timeout=3), "timeout handler did not request cancellation"
            assert result.status.value == SubagentStatus.TIMED_OUT.value
            timed_out_error = result.error
            timed_out_completed_at = result.completed_at

            finish_stream.set()
            assert execution_done.wait(timeout=3), "execution worker did not finish"

        result = executor_module._background_tasks.get(task_id)
        assert result is not None
        assert result.status.value == SubagentStatus.TIMED_OUT.value
        assert result.result is None
        assert result.error == timed_out_error
        assert result.completed_at == timed_out_completed_at

    def test_cleanup_removes_cancelled_task(self, executor_module, classes):
        """Test that cleanup removes a CANCELLED task (terminal state)."""
        SubagentResult = classes["SubagentResult"]
        SubagentStatus = classes["SubagentStatus"]

        task_id = "test-cancelled-cleanup"
        result = SubagentResult(
            task_id=task_id,
            trace_id="test-trace",
            status=SubagentStatus.CANCELLED,
            error="Cancelled by user",
            completed_at=datetime.now(),
        )
        executor_module._background_tasks[task_id] = result

        executor_module.cleanup_background_task(task_id)

        assert task_id not in executor_module._background_tasks


# -----------------------------------------------------------------------------
# Subagent Tracing Wiring
# -----------------------------------------------------------------------------
#
# Regression coverage for the asymmetry fix: subagent runs must mirror the
# lead agent pattern so a single subagent execution produces one trace with
# the parent thread's session_id and user_id, not an isolated top-level trace.
# Three things must hold simultaneously:
#   1. ``build_tracing_callbacks()`` is appended to ``run_config["callbacks"]``
#      so the Langfuse handler sees ``on_chain_start(parent_run_id=None)`` and
#      actually promotes ``langfuse_*`` metadata onto the root trace.
#   2. ``inject_langfuse_metadata(run_config, ...)`` carries the parent
#      thread_id (-> session_id) and the captured user_id (-> user_id).
#   3. The subagent's model is built with ``attach_tracing=False`` so the
#      model-level handler does not double-count (covered separately by
#      ``test_create_agent_threads_explicit_app_config_to_model_and_middlewares``).


class _FakeStreamAgent:
    """Stand-in agent that records the ``config`` passed to ``astream``.

    Yields no chunks so ``_aexecute`` takes the ``final_state is None`` path
    and finishes without exercising message-handling code that is unrelated
    to the tracing wiring under test.
    """

    def __init__(self) -> None:
        self.captured_config: dict | None = None
        self.captured_context: dict | None = None

    async def astream(self, state, *, config, context, stream_mode):  # noqa: ARG002 - signature parity
        self.captured_config = config
        self.captured_context = context
        return
        yield  # pragma: no cover - make this an async generator


class TestSubagentTracingWiring:
    """Verify the subagent graph-root tracing wiring matches the lead agent."""

    @pytest.fixture
    def executor_module(self, _setup_executor_classes):
        executor = importlib.import_module("deerflow.subagents.executor")
        return _patch_default_get_app_config(importlib.reload(executor))

    @pytest.fixture(autouse=True)
    def _clear_langfuse_env(self, monkeypatch):
        """Reset tracing config and env between tests so monkeypatched env
        vars do not leak across tests in this class or the rest of the suite.
        """
        from deerflow.config.tracing_config import reset_tracing_config

        for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
            monkeypatch.delenv(name, raising=False)
        reset_tracing_config()
        yield
        reset_tracing_config()

    def _make_executor(self, classes, *, user_id=None, name="general-purpose", parent_model="test-model"):
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentConfig = classes["SubagentConfig"]
        config = SubagentConfig(
            name=name,
            description="Tracing test agent",
            system_prompt="You are a tracing test agent.",
            max_turns=5,
            timeout_seconds=30,
        )
        return SubagentExecutor(
            config=config,
            tools=[],
            parent_model=parent_model,
            thread_id="thread-trace-1",
            trace_id="trace-1",
            user_id=user_id,
        )

    @pytest.mark.anyio
    async def test_aexecute_appends_tracing_callbacks_to_run_config(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """``build_tracing_callbacks()`` output must be appended (not replace)
        to the existing callbacks so the SubagentTokenCollector keeps working.
        """
        SubagentStatus = classes["SubagentStatus"]

        sentinel_handler = object()
        monkeypatch.setattr(executor_module, "build_tracing_callbacks", lambda: [sentinel_handler])

        executor = self._make_executor(classes, user_id="alice")
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        result = await executor._aexecute("do something")

        assert fake_agent.captured_config is not None
        callbacks = fake_agent.captured_config.get("callbacks") or []
        assert sentinel_handler in callbacks, "tracing handler must reach run_config['callbacks']"
        # SubagentTokenCollector must survive the append (graph-root tracing
        # cannot displace the token-accounting callback).
        assert len(callbacks) >= 2, "existing callbacks must be preserved when tracing is injected"
        assert result.status.value == SubagentStatus.COMPLETED.value

    @pytest.mark.anyio
    async def test_aexecute_injects_langfuse_session_user_and_trace_name(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """When Langfuse is enabled, ``run_config['metadata']`` must carry the
        parent thread_id (-> session_id), the constructor-supplied user_id, and
        a ``subagent:<name>`` trace name so the subagent trace groups under
        the parent thread's session card.
        """
        monkeypatch.setenv("LANGFUSE_TRACING", "true")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        from deerflow.config.tracing_config import reset_tracing_config

        reset_tracing_config()

        class _Sentinel:
            pass

        sentinel = _Sentinel()
        monkeypatch.setattr(executor_module, "build_tracing_callbacks", lambda: [sentinel])

        executor = self._make_executor(classes, user_id="alice", name="general_purpose")
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        await executor._aexecute("do something")

        metadata = (fake_agent.captured_config or {}).get("metadata") or {}
        assert metadata.get("langfuse_session_id") == "thread-trace-1", "subagent trace must inherit parent thread_id as session_id"
        assert metadata.get("langfuse_user_id") == "alice", "subagent trace must carry the user_id captured at task_tool layer"
        # Underscores are normalized to hyphens so the trace name matches the
        # lead-agent naming shape.
        assert metadata.get("langfuse_trace_name") == "subagent:general-purpose"
        tags = metadata.get("langfuse_tags") or []
        assert any(t.startswith("model:") for t in tags), "model tag must be emitted for cost attribution"

    @pytest.mark.anyio
    async def test_aexecute_skips_langfuse_metadata_when_disabled(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """When Langfuse is not in the enabled providers, ``inject_langfuse_metadata``
        must be a no-op and ``run_config['metadata']`` must not carry langfuse_*
        keys. LangSmith-only deployments are unaffected.
        """
        monkeypatch.setattr(executor_module, "build_tracing_callbacks", lambda: [])

        executor = self._make_executor(classes, user_id="alice")
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        await executor._aexecute("do something")

        metadata = (fake_agent.captured_config or {}).get("metadata") or {}
        for key in ("langfuse_session_id", "langfuse_user_id", "langfuse_trace_name", "langfuse_tags"):
            assert key not in metadata, f"{key} must be absent when Langfuse is disabled"

    @pytest.mark.anyio
    async def test_user_id_defaults_when_not_supplied(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """When ``user_id`` is None at construction (parent did not capture
        one), the tracing layer must fall back to DEFAULT_USER_ID so the
        Langfuse Users page still groups the trace.
        """
        monkeypatch.setenv("LANGFUSE_TRACING", "true")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        from deerflow.config.tracing_config import reset_tracing_config

        reset_tracing_config()
        monkeypatch.setattr(executor_module, "build_tracing_callbacks", lambda: [object()])

        executor = self._make_executor(classes, user_id=None)
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        await executor._aexecute("do something")

        metadata = (fake_agent.captured_config or {}).get("metadata") or {}
        # DEFAULT_USER_ID is "default" (see deerflow.runtime.user_context).
        assert metadata.get("langfuse_user_id") == "default"

    @pytest.mark.anyio
    async def test_trace_name_falls_back_when_config_name_empty(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """A subagent config without ``name`` must still produce a non-empty
        trace name so Langfuse does not render the trace as unnamed.
        """
        monkeypatch.setenv("LANGFUSE_TRACING", "true")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        from deerflow.config.tracing_config import reset_tracing_config

        reset_tracing_config()
        monkeypatch.setattr(executor_module, "build_tracing_callbacks", lambda: [object()])

        SubagentExecutor = classes["SubagentExecutor"]
        SubagentConfig = classes["SubagentConfig"]
        config = SubagentConfig(
            name="",  # empty name exercises the fallback branch
            description="No name",
            system_prompt="",
            max_turns=5,
            timeout_seconds=30,
        )
        executor = SubagentExecutor(
            config=config,
            tools=[],
            thread_id="thread-trace-2",
            trace_id="trace-2",
        )
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        await executor._aexecute("do something")

        metadata = (fake_agent.captured_config or {}).get("metadata") or {}
        assert metadata.get("langfuse_trace_name") == "subagent"

    @pytest.mark.anyio
    async def test_environment_tag_emitted_from_deer_flow_env(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """``DEER_FLOW_ENV`` must surface as an ``env:<value>`` tag so Langfuse
        cost aggregation can split traces by deployment environment.
        """
        monkeypatch.setenv("LANGFUSE_TRACING", "true")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.setenv("DEER_FLOW_ENV", "staging")
        from deerflow.config.tracing_config import reset_tracing_config

        reset_tracing_config()
        monkeypatch.setattr(executor_module, "build_tracing_callbacks", lambda: [object()])

        executor = self._make_executor(classes, user_id="alice")
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        await executor._aexecute("do something")

        metadata = (fake_agent.captured_config or {}).get("metadata") or {}
        tags = metadata.get("langfuse_tags") or []
        assert "env:staging" in tags

    async def _noop_build_initial_state(self, task):  # noqa: ARG002 - signature parity
        """Return a minimal state tuple so ``_aexecute`` reaches ``astream``
        without loading skills, MCP tools, or the real config.
        """
        from langchain_core.messages import HumanMessage

        return ({"messages": [HumanMessage(content=task)]}, [], None)


class TestSubagentGuardrailAttribution:
    """GuardrailMiddleware runs on subagents too, so the authenticated runtime
    context captured at the lead-agent layer must reach the subagent's own
    ``astream`` context — otherwise delegated tool calls are evaluated with
    ``user_role=None`` and role-aware policy silently mis-attributes them.
    """

    @pytest.fixture
    def executor_module(self, _setup_executor_classes):
        executor = importlib.import_module("deerflow.subagents.executor")
        return _patch_default_get_app_config(importlib.reload(executor))

    def _make_executor(
        self,
        classes,
        *,
        user_id=None,
        user_role=None,
        oauth_provider=None,
        oauth_id=None,
        run_id=None,
        name="general-purpose",
        parent_model="test-model",
    ):
        SubagentExecutor = classes["SubagentExecutor"]
        SubagentConfig = classes["SubagentConfig"]
        config = SubagentConfig(
            name=name,
            description="Guardrail attribution test agent",
            system_prompt="You are a guardrail attribution test agent.",
            max_turns=5,
            timeout_seconds=30,
        )
        return SubagentExecutor(
            config=config,
            tools=[],
            parent_model=parent_model,
            thread_id="thread-attrib-1",
            trace_id="trace-attrib-1",
            user_id=user_id,
            user_role=user_role,
            oauth_provider=oauth_provider,
            oauth_id=oauth_id,
            run_id=run_id,
        )

    @pytest.mark.anyio
    async def test_aexecute_propagates_attribution_to_subagent_context(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """The authenticated runtime context captured at task_tool must reach
        the subagent's ``astream`` context so GuardrailMiddleware sees the
        same identity/attribution as the lead agent.
        """
        executor = self._make_executor(
            classes,
            user_id="alice",
            user_role="admin",
            oauth_provider="keycloak",
            oauth_id="subj-123",
            run_id="run-42",
        )
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        await executor._aexecute("do something")

        context = fake_agent.captured_context
        assert context is not None, "subagent context must be passed to astream"
        assert context.get("user_id") == "alice"
        assert context.get("user_role") == "admin"
        assert context.get("oauth_provider") == "keycloak"
        assert context.get("oauth_id") == "subj-123"
        assert context.get("run_id") == "run-42"
        assert context.get("is_subagent") is True

    @pytest.mark.anyio
    async def test_aexecute_context_defaults_to_none_when_attribution_absent(
        self,
        classes,
        executor_module,
        monkeypatch,
    ):
        """When no authenticated context is propagated (e.g. internal-auth
        runs), the subagent context still carries the attribution keys as
        None so GuardrailRequest fields stay None rather than KeyError-ing.
        """
        executor = self._make_executor(classes)
        fake_agent = _FakeStreamAgent()
        monkeypatch.setattr(executor, "_build_initial_state", self._noop_build_initial_state)
        monkeypatch.setattr(executor, "_create_agent", lambda *a, **kw: fake_agent)

        await executor._aexecute("do something")

        context = fake_agent.captured_context
        assert context is not None
        assert context.get("user_role") is None
        assert context.get("oauth_provider") is None
        assert context.get("oauth_id") is None
        assert context.get("run_id") is None

    async def _noop_build_initial_state(self, task):  # noqa: ARG002 - signature parity
        from langchain_core.messages import HumanMessage

        return ({"messages": [HumanMessage(content=task)]}, [], None)
