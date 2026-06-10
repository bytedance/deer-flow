"""Tests for the tool_search (deferred tool loading) config + prompt section.

Catalog search, setup assembly, the Command-writing tool_search tool, and the
filter middleware are covered by:
- tests/test_deferred_catalog.py
- tests/test_deferred_setup.py
- tests/test_deferred_filter_middleware.py
- tests/test_thread_state_promoted.py
"""

from deerflow.config.tool_search_config import ToolSearchConfig, load_tool_search_config_from_dict
from deerflow.tools.builtins.tool_search import get_deferred_tools_prompt_section


class TestToolSearchConfig:
    def test_default_disabled(self):
        assert ToolSearchConfig().enabled is False

    def test_enabled(self):
        assert ToolSearchConfig(enabled=True).enabled is True

    def test_load_from_dict(self):
        assert load_tool_search_config_from_dict({"enabled": True}).enabled is True

    def test_load_from_empty_dict(self):
        assert load_tool_search_config_from_dict({}).enabled is False


class TestDeferredToolsPromptSection:
    def test_empty_without_names(self):
        assert get_deferred_tools_prompt_section() == ""

    def test_empty_with_empty_frozenset(self):
        assert get_deferred_tools_prompt_section(deferred_names=frozenset()) == ""

    def test_lists_sorted_names(self):
        out = get_deferred_tools_prompt_section(deferred_names=frozenset({"b_tool", "a_tool"}))
        assert out == "<available-deferred-tools>\na_tool\nb_tool\n</available-deferred-tools>"
