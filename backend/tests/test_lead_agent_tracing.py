"""Tests that Langfuse tracing callback is injected at the invocation root config."""

from __future__ import annotations

from deerflow.agents.lead_agent import agent as lead_agent_module
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


def _make_app_config() -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="alpha",
                display_name="alpha",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="alpha",
                supports_thinking=False,
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )


def _patch_common(monkeypatch):
    import deerflow.tools as tools_module

    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: _make_app_config())
    monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(lead_agent_module, "_build_middlewares", lambda config, model_name, agent_name=None: [])
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: object())


def _base_config() -> dict:
    return {
        "configurable": {
            "model_name": "alpha",
            "thinking_enabled": False,
            "is_plan_mode": False,
            "subagent_enabled": False,
        }
    }


def test_make_lead_agent_injects_langfuse_into_invocation_callbacks(monkeypatch):
    sentinel = object()
    _patch_common(monkeypatch)
    monkeypatch.setattr(lead_agent_module, "build_langfuse_handler", lambda: sentinel)

    config = _base_config()
    lead_agent_module.make_lead_agent(config)

    assert sentinel in config["callbacks"]


def test_make_lead_agent_appends_to_existing_callbacks(monkeypatch):
    sentinel = object()
    pre_existing = object()
    _patch_common(monkeypatch)
    monkeypatch.setattr(lead_agent_module, "build_langfuse_handler", lambda: sentinel)

    config = _base_config()
    config["callbacks"] = [pre_existing]
    lead_agent_module.make_lead_agent(config)

    assert config["callbacks"] == [pre_existing, sentinel]


def test_make_lead_agent_no_op_when_langfuse_disabled(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(lead_agent_module, "build_langfuse_handler", lambda: None)

    config = _base_config()
    lead_agent_module.make_lead_agent(config)

    assert "callbacks" not in config or not config["callbacks"]


def test_make_lead_agent_injects_in_bootstrap_branch(monkeypatch):
    sentinel = object()
    _patch_common(monkeypatch)
    monkeypatch.setattr(lead_agent_module, "build_langfuse_handler", lambda: sentinel)

    config = _base_config()
    config["configurable"]["is_bootstrap"] = True
    lead_agent_module.make_lead_agent(config)

    assert sentinel in config["callbacks"]
