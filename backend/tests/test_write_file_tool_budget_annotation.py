"""Tests for write_file tool budget annotation and assembly isolation.

Verifies fixes for reviewer findings on PR #5569:
- [P1] Guarded max_tokens extraction avoiding AttributeError on ModelConfig without max_tokens
- [P2] Cloning write_file tool to preserve module-level singleton immutability across assemblies
  and prevent cross-model guidance leakage.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from deerflow.config.app_config import AppConfig, ModelConfig, SandboxConfig, ToolConfig
from deerflow.sandbox.tools import write_file_tool
from deerflow.tools.tools import (
    _clone_tool_with_description,
    _extract_max_tokens,
    get_available_tools,
)


def test_extract_max_tokens_various_inputs():
    """Verify _extract_max_tokens safely handles all expected and edge-case inputs."""
    # None and empty
    assert _extract_max_tokens(None) is None

    # ModelConfig with and without max_tokens
    mc_without = ModelConfig(name="test", model="m", use="u")
    assert _extract_max_tokens(mc_without) is None

    mc_with = ModelConfig(name="test", model="m", use="u", max_tokens=4096)
    assert _extract_max_tokens(mc_with) == 4096

    mc_zero = ModelConfig(name="test", model="m", use="u", max_tokens=0)
    assert _extract_max_tokens(mc_zero) is None

    mc_neg = ModelConfig(name="test", model="m", use="u", max_tokens=-100)
    assert _extract_max_tokens(mc_neg) is None

    # Dictionaries
    assert _extract_max_tokens({}) is None
    assert _extract_max_tokens({"max_tokens": 2048}) == 2048
    assert _extract_max_tokens({"max_tokens": "8192"}) == 8192
    assert _extract_max_tokens({"max_tokens": None}) is None
    assert _extract_max_tokens({"max_tokens": 0}) is None

    # SimpleNamespace
    assert _extract_max_tokens(SimpleNamespace()) is None
    assert _extract_max_tokens(SimpleNamespace(max_tokens=1024)) == 1024

    # Booleans (must NOT be treated as 1 or 0)
    assert _extract_max_tokens({"max_tokens": True}) is None
    assert _extract_max_tokens({"max_tokens": False}) is None
    assert _extract_max_tokens(SimpleNamespace(max_tokens=True)) is None

    # Floats
    assert _extract_max_tokens({"max_tokens": 4096.0}) == 4096

    # Unparseable strings
    assert _extract_max_tokens({"max_tokens": "unlimited"}) is None

    # MagicMock (in Python unittest.mock, int(MagicMock()) defaults to 1; must be rejected)
    mock_without = MagicMock(spec=[])
    assert _extract_max_tokens(mock_without) is None

    mock_with = MagicMock()
    mock_with.max_tokens = 8000
    assert _extract_max_tokens(mock_with) == 8000


def test_clone_tool_with_description_preserves_singleton():
    """Verify _clone_tool_with_description returns an isolated copy and keeps original unchanged."""
    original_desc = write_file_tool.description
    assert "CUSTOM_TEST_BUDGET" not in original_desc

    cloned = _clone_tool_with_description(write_file_tool, original_desc + "\n\nCUSTOM_TEST_BUDGET")

    assert "CUSTOM_TEST_BUDGET" in cloned.description
    assert write_file_tool.description == original_desc
    assert cloned.name == write_file_tool.name
    assert cloned.func is write_file_tool.func
    assert cloned.coroutine is write_file_tool.coroutine
    assert cloned.args_schema is write_file_tool.args_schema
    assert isinstance(cloned, BaseModel)


def _build_minimal_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        tools=[
            ToolConfig(name="write_file", group="file:write", use="deerflow.sandbox.tools:write_file_tool"),
        ],
    )


def test_get_available_tools_with_model_config_lacking_max_tokens():
    """Verify get_available_tools does not raise AttributeError when max_tokens is omitted."""
    model_without_max_tokens = ModelConfig(name="capped-model", model="m", use="u")
    config = _build_minimal_app_config([model_without_max_tokens])

    tools = get_available_tools(model_name="capped-model", app_config=config, include_mcp=False)
    write_tool = next((t for t in tools if t.name == "write_file"), None)
    assert write_tool is not None
    assert "PER-RESPONSE BUDGET:" not in write_tool.description


def test_write_file_singleton_remains_unmutated_across_assemblies():
    """Verify write_file_tool process singleton is never mutated during tool assembly."""
    baseline_desc = write_file_tool.description

    model_with_budget = ModelConfig(name="budget-model", model="m", use="u", max_tokens=4096)
    config = _build_minimal_app_config([model_with_budget])

    tools = get_available_tools(model_name="budget-model", app_config=config, include_mcp=False)
    assembled_write_file = next(t for t in tools if t.name == "write_file")

    assert "PER-RESPONSE BUDGET: your output limit is 4096 tokens" in assembled_write_file.description
    # The process-wide singleton must remain pristine
    assert write_file_tool.description == baseline_desc
    assert "PER-RESPONSE BUDGET:" not in write_file_tool.description


def test_repeated_assembly_cross_model_isolation():
    """Verify consecutive tool assemblies for different models do not leak guidance or duplicate notes."""
    baseline_desc = write_file_tool.description

    model_4k = ModelConfig(name="model-4k", model="m", use="u", max_tokens=4096)
    model_32k = ModelConfig(name="model-32k", model="m", use="u", max_tokens=32768)
    model_none = ModelConfig(name="model-none", model="m", use="u")
    config = _build_minimal_app_config([model_4k, model_32k, model_none])

    # Assembly 1: 4K model
    tools_4k = get_available_tools(model_name="model-4k", app_config=config, include_mcp=False)
    wf_4k = next(t for t in tools_4k if t.name == "write_file")
    assert "your output limit is 4096 tokens" in wf_4k.description
    assert "32768" not in wf_4k.description
    assert write_file_tool.description == baseline_desc

    # Assembly 2: 32K model (must not carry 4096 note)
    tools_32k = get_available_tools(model_name="model-32k", app_config=config, include_mcp=False)
    wf_32k = next(t for t in tools_32k if t.name == "write_file")
    assert "your output limit is 32768 tokens" in wf_32k.description
    assert "4096" not in wf_32k.description
    assert wf_32k.description.count("PER-RESPONSE BUDGET:") == 1
    assert write_file_tool.description == baseline_desc

    # Assembly 3: model without max_tokens (must have NO budget note at all)
    tools_none = get_available_tools(model_name="model-none", app_config=config, include_mcp=False)
    wf_none = next(t for t in tools_none if t.name == "write_file")
    assert "PER-RESPONSE BUDGET:" not in wf_none.description
    assert wf_none.description == baseline_desc
    assert write_file_tool.description == baseline_desc


@pytest.mark.parametrize(
    ("profile_overrides", "agent_settings", "thinking_enabled", "bootstrap", "expected"),
    [
        ({}, {"max_tokens": 1024}, False, False, 1024),
        ({"when_thinking_enabled": {"max_tokens": 1024}}, {}, True, False, 1024),
        ({"when_thinking_disabled": {"max_tokens": 1024}}, {}, False, False, 1024),
        ({"when_thinking_enabled": {"max_tokens": 1024}}, {"max_tokens": 2048}, True, False, 1024),
        ({"when_thinking_disabled": {"max_tokens": None}}, {}, False, False, None),
        ({"when_thinking_enabled": {"max_tokens": 1024}}, {}, True, True, 1024),
        ({"when_thinking_disabled": {"max_tokens": 1024}}, {}, False, True, 1024),
    ],
    ids=["custom-agent", "thinking-on", "thinking-off", "thinking-over-agent", "uncapped", "bootstrap-thinking-on", "bootstrap-thinking-off"],
)
def test_lead_write_file_budget_matches_constructed_model(monkeypatch, profile_overrides, agent_settings, thinking_enabled, bootstrap, expected):
    """Exercise real model and tool assembly, including override precedence."""
    from deerflow.agents.lead_agent import agent as lead_agent_module
    from deerflow.config.agents_config import AgentConfig
    from deerflow.config.extensions_config import ExtensionsConfig

    model = ModelConfig(
        name="budget-model",
        model="budget-model",
        use="langchain_openai:ChatOpenAI",
        api_key="test-key",
        max_tokens=32768,
        supports_thinking=True,
        **profile_overrides,
    )
    app_config = _build_minimal_app_config([model])
    agent_config = AgentConfig(name="researcher", model="budget-model", model_settings=agent_settings)
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda *args, **kwargs: agent_config)
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "build_middlewares", lambda *args, **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "system prompt")
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda *args, **kwargs: ExtensionsConfig())

    graph = lead_agent_module._make_lead_agent(
        {"context": {"agent_name": "researcher", "thinking_enabled": thinking_enabled, "is_bootstrap": bootstrap}},
        app_config=app_config,
    )

    assert graph["model"].max_tokens == expected
    write_tool = next(tool for tool in graph["tools"] if tool.name == "write_file")
    if expected is None:
        assert "PER-RESPONSE BUDGET:" not in write_tool.description
    else:
        assert f"your output limit is {expected} tokens" in write_tool.description
        assert "32768 tokens" not in write_tool.description
    assert "PER-RESPONSE BUDGET:" not in write_file_tool.description
