"""Tests for the LLMIOTraceMiddleware — opt-in dev tool for tracing model calls.

Covers the three reviewer concerns:
  1. middleware is NOT mounted when enabled=False (default)
  2. middleware IS mounted at position 0 when enabled=True
  3. env var overrides only `enabled`, never the per-section flags
"""

import pytest

from deerflow.agents.lead_agent import agent as lead_agent_module
from deerflow.agents.middlewares.llm_io_trace_middleware import LLMIOTraceMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.llm_io_trace_config import LLMIOTraceConfig


@pytest.fixture
def mock_lead_agent_build(monkeypatch):
    """Stub out heavy lead-agent dependencies so we can call _build_middlewares
    in isolation. The middleware list returned by create_agent is what we
    inspect — every other branch is mocked away.
    """

    def fake_create_agent(*args, **kwargs):
        return kwargs

    monkeypatch.setattr(lead_agent_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: "model")
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "prompt")
    monkeypatch.setattr(lead_agent_module, "load_agent_config", lambda x: None)
    monkeypatch.setattr(lead_agent_module, "_load_enabled_skills_for_tool_policy", lambda *a, **kw: [])
    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda **kwargs: "default-model")
    # get_available_tools is imported into the lead_agent module from deerflow.tools
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    class MockModelConfig:
        supports_thinking = False
        supports_vision = False

    return MockModelConfig


def _build_middlewares_with_config(mock_lead_agent_build, monkeypatch, llm_io_config: LLMIOTraceConfig):
    """Run the lead-agent _build_middlewares under a given llm_io_trace config
    and return the resulting middleware list.
    """
    app_config = AppConfig.model_construct(llm_io_trace=llm_io_config)
    # also stub get_model_config to return a stub
    stub = mock_lead_agent_build
    app_config.get_model_config = lambda name: stub
    return lead_agent_module._build_middlewares(config={"configurable": {}}, model_name="default-model", app_config=app_config)


def test_middleware_not_mounted_by_default(mock_lead_agent_build, monkeypatch):
    """enabled=False (the default) means the middleware is not in the chain at all."""
    config = LLMIOTraceConfig()  # defaults
    assert config.enabled is False
    middlewares = _build_middlewares_with_config(mock_lead_agent_build, monkeypatch, config)
    assert not any(isinstance(m, LLMIOTraceMiddleware) for m in middlewares), "trace middleware should not be mounted when enabled=False"


def test_middleware_mounted_at_index_0_when_enabled(mock_lead_agent_build, monkeypatch):
    """When enabled, the trace middleware is the first to wrap the model call."""
    config = LLMIOTraceConfig(enabled=True)
    middlewares = _build_middlewares_with_config(mock_lead_agent_build, monkeypatch, config)
    trace_mws = [m for m in middlewares if isinstance(m, LLMIOTraceMiddleware)]
    assert len(trace_mws) == 1
    assert middlewares[0] is trace_mws[0]
    # and the injected config is what we passed
    assert trace_mws[0]._config.enabled is True


def test_env_override_only_flips_enabled(mock_lead_agent_build, monkeypatch):
    """DEERFLOW_LLM_IO_TRACE_ENABLED=true flips enabled; per-section flags stay."""
    base = LLMIOTraceConfig(
        enabled=False,
        print_system_prompt=False,
        print_messages=False,  # explicitly off, must stay off
        print_tools=False,
        print_response=False,
    )
    monkeypatch.setenv("DEERFLOW_LLM_IO_TRACE_ENABLED", "true")
    overridden = LLMIOTraceConfig.with_env_override(base)
    assert overridden.enabled is True
    # per-section flags unchanged
    assert overridden.print_system_prompt is False
    assert overridden.print_messages is False
    assert overridden.print_tools is False
    assert overridden.print_response is False

    monkeypatch.setenv("DEERFLOW_LLM_IO_TRACE_ENABLED", "false")
    overridden2 = LLMIOTraceConfig.with_env_override(LLMIOTraceConfig(enabled=True))
    assert overridden2.enabled is False

    monkeypatch.delenv("DEERFLOW_LLM_IO_TRACE_ENABLED", raising=False)
    unchanged = LLMIOTraceConfig.with_env_override(LLMIOTraceConfig(enabled=True))
    assert unchanged.enabled is True
