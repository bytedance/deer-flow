"""Tests for research runtime tool inclusion."""

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


def test_includes_research_runtime_tools_by_default(monkeypatch):
    app_config = _make_app_config([_make_model("text-model", supports_vision=False)])
    monkeypatch.setattr(tools_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(tools_module, "get_scientific_vision_config", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(tools_module, "get_scientific_data_config", lambda: SimpleNamespace(enabled=False))

    tools = tools_module.get_available_tools(include_mcp=False, model_name="text-model", subagent_enabled=False)
    names = {getattr(t, "name", None) for t in tools}

    assert "research_project" in names
    assert "research_fulltext_ingest" in names
    assert "academic_eval" in names
