"""Tests for the tool_search (deferred tool loading) feature."""

import json
import sys

import pytest
from langchain_core.tools import tool as langchain_tool

from deerflow.config.tool_search_config import ToolSearchConfig, load_tool_search_config_from_dict
from deerflow.tools.builtins.tool_search import (
    DeferredToolRegistry,
    get_deferred_registry,
    reset_deferred_registry,
    set_deferred_registry,
)

# ── Fixtures ──


def _make_mock_tool(name: str, description: str):
    """Create a minimal LangChain tool for testing."""

    @langchain_tool(name)
    def mock_tool(arg: str) -> str:
        """Mock tool."""
        return f"{name}: {arg}"

    mock_tool.description = description
    return mock_tool


@pytest.fixture
def registry():
    """Create a fresh DeferredToolRegistry with test tools."""
    reg = DeferredToolRegistry()
    reg.register(_make_mock_tool("github_create_issue", "Create a new issue in a GitHub repository"))
    reg.register(_make_mock_tool("github_list_repos", "List repositories for a GitHub user"))
    reg.register(_make_mock_tool("slack_send_message", "Send a message to a Slack channel"))
    reg.register(_make_mock_tool("slack_list_channels", "List available Slack channels"))
    reg.register(_make_mock_tool("sentry_list_issues", "List issues from Sentry error tracking"))
    reg.register(_make_mock_tool("database_query", "Execute a SQL query against the database"))
    return reg


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton before/after each test."""
    reset_deferred_registry()
    yield
    reset_deferred_registry()


# ── ToolSearchConfig Tests ──


class TestToolSearchConfig:
    def test_default_disabled(self):
        config = ToolSearchConfig()
        assert config.enabled is False

    def test_enabled(self):
        config = ToolSearchConfig(enabled=True)
        assert config.enabled is True

    def test_load_from_dict(self):
        config = load_tool_search_config_from_dict({"enabled": True})
        assert config.enabled is True

    def test_load_from_empty_dict(self):
        config = load_tool_search_config_from_dict({})
        assert config.enabled is False


# ── DeferredToolRegistry Tests ──


class TestDeferredToolRegistry:
    def test_register_and_len(self, registry):
        assert len(registry) == 6

    def test_entries(self, registry):
        names = [e.name for e in registry.entries]
        assert "github_create_issue" in names
        assert "slack_send_message" in names

    def test_search_select_single(self, registry):
        results = registry.search("select:github_create_issue")
        assert len(results) == 1
        assert results[0].name == "github_create_issue"

    def test_search_select_multiple(self, registry):
        results = registry.search("select:github_create_issue,slack_send_message")
        names = {t.name for t in results}
        assert names == {"github_create_issue", "slack_send_message"}

    def test_search_select_nonexistent(self, registry):
        results = registry.search("select:nonexistent_tool")
        assert results == []

    def test_search_plus_keyword(self, registry):
        results = registry.search("+github")
        names = {t.name for t in results}
        assert names == {"github_create_issue", "github_list_repos"}

    def test_search_plus_keyword_with_ranking(self, registry):
        results = registry.search("+github issue")
        assert len(results) == 2
        # "github_create_issue" should rank higher (has "issue" in name)
        assert results[0].name == "github_create_issue"

    def test_search_regex_keyword(self, registry):
        results = registry.search("slack")
        names = {t.name for t in results}
        assert "slack_send_message" in names
        assert "slack_list_channels" in names

    def test_search_regex_description(self, registry):
        results = registry.search("SQL")
        assert len(results) == 1
        assert results[0].name == "database_query"

    def test_search_regex_case_insensitive(self, registry):
        results = registry.search("GITHUB")
        assert len(results) == 2

    def test_search_invalid_regex_falls_back_to_literal(self, registry):
        # "[" is invalid regex, should be escaped and used as literal
        results = registry.search("[")
        assert results == []

    def test_search_name_match_ranks_higher(self, registry):
        # "issue" appears in both github_create_issue (name) and sentry_list_issues (name+desc)
        results = registry.search("issue")
        names = [t.name for t in results]
        # Both should be found (both have "issue" in name)
        assert "github_create_issue" in names
        assert "sentry_list_issues" in names

    def test_search_max_results(self):
        reg = DeferredToolRegistry()
        for i in range(10):
            reg.register(_make_mock_tool(f"tool_{i}", f"Tool number {i}"))
        results = reg.search("tool")
        assert len(results) <= 5  # MAX_RESULTS = 5

    def test_search_empty_registry(self):
        reg = DeferredToolRegistry()
        assert reg.search("anything") == []

    def test_empty_registry_len(self):
        reg = DeferredToolRegistry()
        assert len(reg) == 0


# ── Singleton Tests ──


class TestSingleton:
    def test_default_none(self):
        assert get_deferred_registry() is None

    def test_set_and_get(self, registry):
        set_deferred_registry(registry)
        assert get_deferred_registry() is registry

    def test_reset(self, registry):
        set_deferred_registry(registry)
        reset_deferred_registry()
        assert get_deferred_registry() is None

    def test_contextvar_isolation_across_contexts(self, registry):
        """P2: Each async context gets its own independent registry value."""
        import contextvars

        reg_a = DeferredToolRegistry()
        reg_a.register(_make_mock_tool("tool_a", "Tool A"))

        reg_b = DeferredToolRegistry()
        reg_b.register(_make_mock_tool("tool_b", "Tool B"))

        seen: dict[str, object] = {}

        def run_in_context_a():
            set_deferred_registry(reg_a)
            seen["ctx_a"] = get_deferred_registry()

        def run_in_context_b():
            set_deferred_registry(reg_b)
            seen["ctx_b"] = get_deferred_registry()

        ctx_a = contextvars.copy_context()
        ctx_b = contextvars.copy_context()
        ctx_a.run(run_in_context_a)
        ctx_b.run(run_in_context_b)

        # Each context got its own registry, neither bleeds into the other
        assert seen["ctx_a"] is reg_a
        assert seen["ctx_b"] is reg_b
        # The current context is unchanged
        assert get_deferred_registry() is None


# ── tool_search Tool Tests ──


class TestToolSearchTool:
    def test_no_registry(self):
        from deerflow.tools.builtins.tool_search import tool_search

        result = tool_search.invoke({"query": "github"})
        assert result == "No deferred tools available."

    def test_no_match(self, registry):
        from deerflow.tools.builtins.tool_search import tool_search

        set_deferred_registry(registry)
        result = tool_search.invoke({"query": "nonexistent_xyz_tool"})
        assert "No tools found matching" in result

    def test_returns_valid_json(self, registry):
        from deerflow.tools.builtins.tool_search import tool_search

        set_deferred_registry(registry)
        result = tool_search.invoke({"query": "select:github_create_issue"})
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "github_create_issue"

    def test_returns_openai_function_format(self, registry):
        from deerflow.tools.builtins.tool_search import tool_search

        set_deferred_registry(registry)
        result = tool_search.invoke({"query": "select:slack_send_message"})
        parsed = json.loads(result)
        func_def = parsed[0]
        # OpenAI function format should have these keys
        assert "name" in func_def
        assert "description" in func_def
        assert "parameters" in func_def

    def test_keyword_search_returns_json(self, registry):
        from deerflow.tools.builtins.tool_search import tool_search

        set_deferred_registry(registry)
        result = tool_search.invoke({"query": "github"})
        parsed = json.loads(result)
        assert len(parsed) == 2
        names = {d["name"] for d in parsed}
        assert names == {"github_create_issue", "github_list_repos"}


# ── Prompt Section Tests ──


class TestDeferredToolsPromptSection:
    @pytest.fixture(autouse=True)
    def _mock_app_config(self, monkeypatch):
        """Provide a minimal AppConfig mock so tests don't need config.yaml."""
        from unittest.mock import MagicMock

        from deerflow.config.tool_search_config import ToolSearchConfig

        mock_config = MagicMock()
        mock_config.tool_search = ToolSearchConfig()  # disabled by default
        monkeypatch.setattr("deerflow.config.get_app_config", lambda: mock_config)

    def test_empty_when_disabled(self):
        from deerflow.agents.lead_agent.prompt import get_deferred_tools_prompt_section

        # tool_search.enabled defaults to False
        section = get_deferred_tools_prompt_section()
        assert section == ""

    def test_empty_when_enabled_but_no_registry(self, monkeypatch):
        from deerflow.agents.lead_agent.prompt import get_deferred_tools_prompt_section
        from deerflow.config import get_app_config

        monkeypatch.setattr(get_app_config().tool_search, "enabled", True)
        section = get_deferred_tools_prompt_section()
        assert section == ""

    def test_empty_when_enabled_but_empty_registry(self, monkeypatch):
        from deerflow.agents.lead_agent.prompt import get_deferred_tools_prompt_section
        from deerflow.config import get_app_config

        monkeypatch.setattr(get_app_config().tool_search, "enabled", True)
        set_deferred_registry(DeferredToolRegistry())
        section = get_deferred_tools_prompt_section()
        assert section == ""

    def test_lists_tool_names(self, registry, monkeypatch):
        from deerflow.agents.lead_agent.prompt import get_deferred_tools_prompt_section
        from deerflow.config import get_app_config

        monkeypatch.setattr(get_app_config().tool_search, "enabled", True)
        set_deferred_registry(registry)
        section = get_deferred_tools_prompt_section()
        assert "<available-deferred-tools>" in section
        assert "</available-deferred-tools>" in section
        assert "github_create_issue" in section
        assert "slack_send_message" in section
        assert "sentry_list_issues" in section
        # Should only have names, no descriptions
        assert "Create a new issue" not in section


# ── DeferredToolFilterMiddleware Tests ──


class TestDeferredToolFilterMiddleware:
    @pytest.fixture(autouse=True)
    def _ensure_middlewares_package(self):
        """Remove mock entries injected by test_subagent_executor.py.

        That file replaces deerflow.agents and deerflow.agents.middlewares with
        MagicMock objects in sys.modules (session-scoped) to break circular imports.
        We must clear those mocks so real submodule imports work.
        """
        from unittest.mock import MagicMock

        mock_keys = [
            "deerflow.agents",
            "deerflow.agents.middlewares",
            "deerflow.agents.middlewares.deferred_tool_filter_middleware",
        ]
        for key in mock_keys:
            if isinstance(sys.modules.get(key), MagicMock):
                del sys.modules[key]

    def test_filters_deferred_tools(self, registry):
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        set_deferred_registry(registry)
        middleware = DeferredToolFilterMiddleware()

        # Build a mock tools list: 2 active + 1 deferred
        active_tool = _make_mock_tool("my_active_tool", "An active tool")
        deferred_tool = registry.entries[0].tool  # github_create_issue

        class FakeRequest:
            def __init__(self, tools):
                self.tools = tools

            def override(self, **kwargs):
                return FakeRequest(kwargs.get("tools", self.tools))

        request = FakeRequest(tools=[active_tool, deferred_tool])
        filtered = middleware._filter_tools(request)

        assert len(filtered.tools) == 1
        assert filtered.tools[0].name == "my_active_tool"

    def test_no_op_when_no_registry(self):
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        middleware = DeferredToolFilterMiddleware()
        active_tool = _make_mock_tool("my_tool", "A tool")

        class FakeRequest:
            def __init__(self, tools):
                self.tools = tools

            def override(self, **kwargs):
                return FakeRequest(kwargs.get("tools", self.tools))

        request = FakeRequest(tools=[active_tool])
        filtered = middleware._filter_tools(request)

        assert len(filtered.tools) == 1
        assert filtered.tools[0].name == "my_tool"

    def test_preserves_dict_tools(self, registry):
        """Dict tools (provider built-ins) should not be filtered."""
        from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware

        set_deferred_registry(registry)
        middleware = DeferredToolFilterMiddleware()

        dict_tool = {"type": "function", "function": {"name": "some_builtin"}}
        active_tool = _make_mock_tool("my_active_tool", "Active")

        class FakeRequest:
            def __init__(self, tools):
                self.tools = tools

            def override(self, **kwargs):
                return FakeRequest(kwargs.get("tools", self.tools))

        request = FakeRequest(tools=[dict_tool, active_tool])
        filtered = middleware._filter_tools(request)

        # dict_tool has no .name attr → getattr returns None → not in deferred_names → kept
        assert len(filtered.tools) == 2
