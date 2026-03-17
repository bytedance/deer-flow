"""Tests for view_image tool inclusion when scientific_vision is enabled."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.sandbox_config import SandboxConfig

tools_module = importlib.import_module("src.tools.tools")


def _make_model(name: str, *, supports_vision: bool) -> ModelConfig:
    return ModelConfig(
        name=name,
        display_name=name,
        description=None,
        use="langchain_openai:ChatOpenAI",
        model=name,
        supports_thinking=False,
        supports_vision=supports_vision,
    )


def _make_app_config(models: list[ModelConfig]) -> AppConfig:
    return AppConfig(
        models=models,
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
    )


def test_includes_view_image_when_scientific_vision_enabled(monkeypatch):
    app_config = _make_app_config([_make_model("text-model", supports_vision=False)])
    monkeypatch.setattr(tools_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_scientific_vision_config", lambda: SimpleNamespace(enabled=True))

    tools = tools_module.get_available_tools(include_mcp=False, model_name="text-model", subagent_enabled=False)

    assert any(getattr(t, "name", None) == "view_image" for t in tools)


def test_does_not_include_view_image_when_disabled_and_no_vision(monkeypatch):
    app_config = _make_app_config([_make_model("text-model", supports_vision=False)])
    monkeypatch.setattr(tools_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_scientific_vision_config", lambda: SimpleNamespace(enabled=False))

    tools = tools_module.get_available_tools(include_mcp=False, model_name="text-model", subagent_enabled=False)

    assert not any(getattr(t, "name", None) == "view_image" for t in tools)
