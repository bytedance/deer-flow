"""Tests for lead agent model-name resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.agents.lead_agent.agent import _runtime_model_spec_from_model_name, make_lead_agent


def test_runtime_model_spec_from_provider_style_model_name() -> None:
    result = _runtime_model_spec_from_model_name("anthropic:claude-sonnet-4-6:thinking")
    assert result == {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "tier": "thinking",
    }


def test_runtime_model_spec_from_provider_style_without_tier() -> None:
    result = _runtime_model_spec_from_model_name("openai:gpt-5.2")
    assert result == {
        "provider": "openai",
        "model_id": "gpt-5.2",
    }


def test_runtime_model_spec_from_provider_style_with_tier_and_effort() -> None:
    result = _runtime_model_spec_from_model_name("openai:gpt-5.2:reasoning-high:xhigh")
    assert result == {
        "provider": "openai",
        "model_id": "gpt-5.2",
        "tier": "reasoning-high",
        "thinking_effort": "xhigh",
    }


def test_runtime_model_spec_ignores_config_style_name() -> None:
    assert _runtime_model_spec_from_model_name("claude-sonnet-4-6") is None


def test_make_lead_agent_builds_runtime_spec_from_model_name() -> None:
    config = {
        "configurable": {
            "model_name": "anthropic:claude-sonnet-4-6:thinking",
            "thinking_enabled": True,
            "user_id": "user-123",
        }
    }

    with patch("src.agents.lead_agent.agent._build_middlewares", return_value=[]):
        with patch("src.agents.lead_agent.agent.apply_prompt_template", return_value="system"):
            with patch("src.agents.lead_agent.agent.create_chat_model", return_value=MagicMock()) as mock_create_chat_model:
                with patch("src.agents.lead_agent.agent.create_agent", return_value=MagicMock()) as mock_create_agent:
                    with patch("src.tools.get_available_tools", return_value=[]):
                        with patch("src.tools.docs.tool_policies.get_tool_usage_policies", return_value=""):
                            make_lead_agent(config)

    assert mock_create_chat_model.call_args.kwargs["runtime_model"] == {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "tier": "thinking",
        "user_id": "user-123",
    }
    assert config["configurable"]["model_spec"] == {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "tier": "thinking",
        "user_id": "user-123",
    }
    mock_create_agent.assert_called_once()


def test_make_lead_agent_injects_thinking_effort_into_runtime_spec() -> None:
    config = {
        "configurable": {
            "model_name": "openai:gpt-5.2",
            "thinking_enabled": True,
            "thinking_effort": "xhigh",
            "user_id": "user-123",
        }
    }

    with patch("src.agents.lead_agent.agent._build_middlewares", return_value=[]):
        with patch("src.agents.lead_agent.agent.apply_prompt_template", return_value="system"):
            with patch("src.agents.lead_agent.agent.create_chat_model", return_value=MagicMock()) as mock_create_chat_model:
                with patch("src.agents.lead_agent.agent.create_agent", return_value=MagicMock()):
                    with patch("src.tools.get_available_tools", return_value=[]):
                        with patch("src.tools.docs.tool_policies.get_tool_usage_policies", return_value=""):
                            make_lead_agent(config)

    runtime_model = mock_create_chat_model.call_args.kwargs["runtime_model"]
    assert runtime_model["provider"] == "openai"
    assert runtime_model["model_id"] == "gpt-5.2"
    assert runtime_model["thinking_effort"] == "xhigh"
