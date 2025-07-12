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
    config_dict = {
        "configurable": {
            "max_plan_iterations": None,
            "max_step_num": 0,  # falsy, should be skipped
            "max_search_results": "",
        }
    }
    config = Configuration.from_runnable_config(config_dict)
    # Should fall back to defaults for skipped/falsy values
    assert config.max_plan_iterations == 1
    assert config.max_step_num == 3
    assert config.max_search_results == 3


def test_from_runnable_config_with_no_config():
    config = Configuration.from_runnable_config()
    assert config.max_plan_iterations == 1
    assert config.max_step_num == 3
    assert config.max_search_results == 3
    assert config.resources == []
    assert config.mcp_settings is None
