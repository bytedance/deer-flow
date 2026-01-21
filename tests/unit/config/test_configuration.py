# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import sys
import types

from src.config.configuration import Configuration

# Patch sys.path so relative import works

# Patch Resource for import
mock_resource = type("Resource", (), {})

# Patch src.rag.retriever.Resource for import

module_name = "src.rag.retriever"
if module_name not in sys.modules:
    retriever_mod = types.ModuleType(module_name)
    retriever_mod.Resource = mock_resource
    sys.modules[module_name] = retriever_mod

# Relative import of Configuration


def test_default_configuration():
    config = Configuration()
    assert config.resources == []
    assert config.max_plan_iterations == 1
    assert config.max_step_num == 3
    assert config.max_search_results == 3
    assert config.mcp_settings is None


def test_from_runnable_config_with_config_dict(monkeypatch):
    config_dict = {
        "configurable": {
            "max_plan_iterations": 5,
            "max_step_num": 7,
            "max_search_results": 10,
            "mcp_settings": {"foo": "bar"},
        }
    }
    config = Configuration.from_runnable_config(config_dict)
    assert config.max_plan_iterations == 5
    assert config.max_step_num == 7
    assert config.max_search_results == 10
    assert config.mcp_settings == {"foo": "bar"}


def test_from_runnable_config_with_env_override(monkeypatch):
    monkeypatch.setenv("MAX_PLAN_ITERATIONS", "9")
    monkeypatch.setenv("MAX_STEP_NUM", "11")
    config_dict = {
        "configurable": {
            "max_plan_iterations": 2,
            "max_step_num": 3,
            "max_search_results": 4,
        }
    }
    config = Configuration.from_runnable_config(config_dict)
    # Environment variables take precedence and are strings
    assert config.max_plan_iterations == "9"
    assert config.max_step_num == "11"
    assert config.max_search_results == 4  # not overridden
    # Clean up
    monkeypatch.delenv("MAX_PLAN_ITERATIONS")
    monkeypatch.delenv("MAX_STEP_NUM")


def test_from_runnable_config_with_none_and_falsy(monkeypatch):
    """Test that None values are skipped but falsy values (0, False, empty string) are preserved."""
    config_dict = {
        "configurable": {
            "max_plan_iterations": None,  # None should be skipped, use default
            "max_step_num": 0,  # 0 is valid, should be preserved
            "max_search_results": "",  # Empty string should be preserved
        }
    }
    config = Configuration.from_runnable_config(config_dict)
    # None values should fall back to defaults
    assert config.max_plan_iterations == 1
    # Falsy but valid values should be preserved
    assert config.max_step_num == 0
    assert config.max_search_results == ""


def test_from_runnable_config_with_no_config():
    config = Configuration.from_runnable_config()
    assert config.max_plan_iterations == 1
    assert config.max_step_num == 3
    assert config.max_search_results == 3
    assert config.resources == []
    assert config.mcp_settings is None


def test_from_runnable_config_with_boolean_false_values():
    """Test that boolean False values are correctly preserved and not filtered out.
    
    This is a regression test for the bug where False values were treated as falsy
    and filtered out, causing fields to revert to their default values.
    """
    config_dict = {
        "configurable": {
            "enable_web_search": False,  # Should be preserved as False, not revert to True
            "enable_deep_thinking": False,  # Should be preserved as False
            "enforce_web_search": False,  # Should be preserved as False
            "enforce_researcher_search": False,  # Should be preserved as False
            "max_plan_iterations": 5,  # Control: non-falsy value
        }
    }
    config = Configuration.from_runnable_config(config_dict)
    
    # Assert that False values are preserved
    assert config.enable_web_search is False, "enable_web_search should be False, not default True"
    assert config.enable_deep_thinking is False, "enable_deep_thinking should be False"
    assert config.enforce_web_search is False, "enforce_web_search should be False"
    assert config.enforce_researcher_search is False, "enforce_researcher_search should be False, not default True"
    
    # Control: verify non-falsy values still work
    assert config.max_plan_iterations == 5


def test_from_runnable_config_with_boolean_true_values():
    """Test that boolean True values work correctly (control test)."""
    config_dict = {
        "configurable": {
            "enable_web_search": True,
            "enable_deep_thinking": True,
            "enforce_web_search": True,
        }
    }
    config = Configuration.from_runnable_config(config_dict)
    
    assert config.enable_web_search is True
    assert config.enable_deep_thinking is True
    assert config.enforce_web_search is True

def test_get_recursion_limit_default(monkeypatch):
    from src.config.configuration import get_recursion_limit

    monkeypatch.delenv("AGENT_RECURSION_LIMIT", raising=False)
    result = get_recursion_limit()
    assert result == 25


def test_get_recursion_limit_custom_default(monkeypatch):
    from src.config.configuration import get_recursion_limit

    monkeypatch.delenv("AGENT_RECURSION_LIMIT", raising=False)
    result = get_recursion_limit(50)
    assert result == 50


def test_get_recursion_limit_from_env(monkeypatch):
    from src.config.configuration import get_recursion_limit

    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "100")
    result = get_recursion_limit()
    assert result == 100


def test_get_recursion_limit_invalid_env_value(monkeypatch):
    from src.config.configuration import get_recursion_limit

    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "invalid")
    result = get_recursion_limit()
    assert result == 25


def test_get_recursion_limit_negative_env_value(monkeypatch):
    from src.config.configuration import get_recursion_limit

    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "-5")
    result = get_recursion_limit()
    assert result == 25


def test_get_recursion_limit_zero_env_value(monkeypatch):
    from src.config.configuration import get_recursion_limit

    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "0")
    result = get_recursion_limit()
    assert result == 25
