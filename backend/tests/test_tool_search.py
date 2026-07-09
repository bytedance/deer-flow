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
        assert ToolSearchConfig().auto_promote_top_k == 3

    def test_enabled(self):
        assert ToolSearchConfig(enabled=True).enabled is True

    def test_auto_promote_top_k_is_clamped(self):
        assert ToolSearchConfig(auto_promote_top_k=0).auto_promote_top_k == 1
        assert ToolSearchConfig(auto_promote_top_k=99).auto_promote_top_k == 5

    def test_load_from_dict(self):
        loaded = load_tool_search_config_from_dict({"enabled": True, "auto_promote_top_k": 4})
        assert loaded.enabled is True
        assert loaded.auto_promote_top_k == 4

    def test_load_from_empty_dict(self):
        assert load_tool_search_config_from_dict({}).enabled is False
        assert load_tool_search_config_from_dict({}).auto_promote_top_k == 3


class TestConfigExampleToolSearchSection:
    """Guard the documented ``tool_search`` block in config.example.yaml.

    The example file is the first-run template (``cp config.example.yaml
    config.yaml``); a malformed indentation there breaks the whole file for
    every downstream consumer, so pin that it parses and carries the PR2 field.
    """

    def _load_example(self):
        import os

        import yaml

        example_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.example.yaml")
        if not os.path.exists(example_path):
            return None
        with open(example_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_config_example_parses(self):
        # A raw yaml.safe_load raises on malformed indentation; asserting a
        # dict result pins that the whole template stays parseable.
        data = self._load_example()
        if data is None:
            return
        assert isinstance(data, dict)

    def test_config_example_tool_search_block(self):
        data = self._load_example()
        if data is None:
            return
        tool_search = data.get("tool_search")
        assert isinstance(tool_search, dict)
        assert tool_search.get("enabled") is False
        assert tool_search.get("auto_promote_top_k") == 3


class TestDeferredToolsPromptSection:
    def test_empty_without_names(self):
        assert get_deferred_tools_prompt_section() == ""

    def test_empty_with_empty_frozenset(self):
        assert get_deferred_tools_prompt_section(deferred_names=frozenset()) == ""

    def test_lists_sorted_names(self):
        out = get_deferred_tools_prompt_section(deferred_names=frozenset({"b_tool", "a_tool"}))
        assert out == "<available-deferred-tools>\na_tool\nb_tool\n</available-deferred-tools>"
