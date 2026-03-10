"""Tests for src.config.tracing_config."""

from __future__ import annotations

from src.config import tracing_config as tracing_module


def _reset_tracing_cache() -> None:
    tracing_module._tracing_config = None


def test_prefers_langsmith_env_names(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "smith-project")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://smith.example.com")

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.enabled is True
    assert cfg.api_key == "lsv2_key"
    assert cfg.project == "smith-project"
    assert cfg.endpoint == "https://smith.example.com"
    assert tracing_module.is_tracing_enabled() is True


def test_falls_back_to_langchain_env_names(monkeypatch):
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "legacy-key")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "legacy-project")
    monkeypatch.setenv("LANGCHAIN_ENDPOINT", "https://legacy.example.com")

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.enabled is True
    assert cfg.api_key == "legacy-key"
    assert cfg.project == "legacy-project"
    assert cfg.endpoint == "https://legacy.example.com"
    assert tracing_module.is_tracing_enabled() is True


def test_defaults_when_project_not_set(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "yes")
    monkeypatch.setenv("LANGSMITH_API_KEY", "key")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.project == "deer-flow"
