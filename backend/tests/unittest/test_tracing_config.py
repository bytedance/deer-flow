"""Tests for deerflow.config.tracing_config."""

from __future__ import annotations

import pytest

from deerflow.config import tracing_config as tracing_module


def _reset_tracing_cache() -> None:
    tracing_module._tracing_config = None


@pytest.fixture(autouse=True)
def clear_tracing_env(monkeypatch):
    for name in (
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_TRACING",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGCHAIN_PROJECT",
        "LANGSMITH_ENDPOINT",
        "LANGCHAIN_ENDPOINT",
        "LANGFUSE_TRACING",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    _reset_tracing_cache()
    yield
    _reset_tracing_cache()


def test_prefers_langsmith_env_names(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "smith-project")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://smith.example.com")

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.langsmith.enabled is True
    assert cfg.langsmith.api_key == "lsv2_key"
    assert cfg.langsmith.project == "smith-project"
    assert cfg.langsmith.endpoint == "https://smith.example.com"
    assert tracing_module.is_tracing_enabled() is True
    assert tracing_module.get_enabled_tracing_providers() == ["langsmith"]


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

    assert cfg.langsmith.enabled is True
    assert cfg.langsmith.api_key == "legacy-key"
    assert cfg.langsmith.project == "legacy-project"
    assert cfg.langsmith.endpoint == "https://legacy.example.com"
    assert tracing_module.is_tracing_enabled() is True
    assert tracing_module.get_enabled_tracing_providers() == ["langsmith"]


def test_langsmith_tracing_false_overrides_langchain_tracing_v2_true(monkeypatch):
    """LANGSMITH_TRACING=false must win over LANGCHAIN_TRACING_V2=true."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "some-key")

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.langsmith.enabled is False
    assert tracing_module.is_tracing_enabled() is False
    assert tracing_module.get_enabled_tracing_providers() == []


def test_defaults_when_project_not_set(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "yes")
    monkeypatch.setenv("LANGSMITH_API_KEY", "key")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.langsmith.project == "deer-flow"


def test_langfuse_config_is_loaded(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.langfuse.enabled is True
    assert cfg.langfuse.public_key == "pk-lf-test"
    assert cfg.langfuse.secret_key == "sk-lf-test"
    assert cfg.langfuse.host == "https://langfuse.example.com"
    assert tracing_module.get_enabled_tracing_providers() == ["langfuse"]


def test_dual_provider_config_is_loaded(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_key")
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    _reset_tracing_cache()
    cfg = tracing_module.get_tracing_config()

    assert cfg.langsmith.is_configured is True
    assert cfg.langfuse.is_configured is True
    assert tracing_module.is_tracing_enabled() is True
    assert tracing_module.get_enabled_tracing_providers() == ["langsmith", "langfuse"]


def test_langfuse_enabled_requires_public_and_secret_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    _reset_tracing_cache()

    assert tracing_module.get_tracing_config().is_configured is False
    assert tracing_module.get_enabled_tracing_providers() == []
    assert tracing_module.get_tracing_config().explicitly_enabled_providers == ["langfuse"]

    with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
        tracing_module.validate_enabled_tracing_providers()
