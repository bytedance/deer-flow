"""Legacy YAML model selectors must build the configured host model, offline."""

from copy import deepcopy

import pytest
import yaml

from deerflow.agents.memory import get_memory_manager, reset_memory_manager
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.memory_config import get_memory_config, set_memory_config


@pytest.mark.parametrize("legacy_name", ["memory-model", None, ""])
@pytest.mark.parametrize("explicit_model", [False, True])
def test_legacy_yaml_builds_memory_model_with_profile_settings(tmp_path, monkeypatch, legacy_name, explicit_model):
    previous_memory = get_memory_config()
    reset_memory_manager()
    reset_app_config()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "config.yaml"))
    extensions = tmp_path / "extensions_config.json"
    extensions.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    profile = {
        "name": "memory-model",
        "use": "langchain_openai:ChatOpenAI",
        "model": "gpt-4o-mini",
        "api_key": "test-profile-key",
        "base_url": "https://profile.invalid/v1",
        "temperature": 0.23,
    }
    backend = {"storage_path": str(tmp_path / "memory"), "token_counting": "char"}
    if explicit_model:
        backend["model"] = {
            "model": "explicit-wire-model",
            "api_key": "test-explicit-key",
            "base_url": "https://explicit.invalid/v1",
            "temperature": 0.41,
        }
    # A non-default selector must not silently fall back to the first profile.
    models = [profile]
    if legacy_name:
        models.insert(0, {**profile, "name": "default-model", "model": "wrong-default-model"})
    document = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": models,
        "memory": {"model_name": legacy_name, "backend_config": backend},
    }
    original = deepcopy(document)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    try:
        config = get_app_config()
        # This traverses YAML validation, singleton publication and the real
        # backend/factory/SDK constructors; it makes no provider requests.
        manager = get_memory_manager()
        llm = manager._llm
        assert llm is not None
        assert llm.model_name == ("explicit-wire-model" if explicit_model else "gpt-4o-mini")
        assert llm.openai_api_key.get_secret_value() == ("test-explicit-key" if explicit_model else "test-profile-key")
        assert llm.openai_api_base == ("https://explicit.invalid/v1" if explicit_model else "https://profile.invalid/v1")
        assert llm.temperature == (0.41 if explicit_model else 0.23)
        assert manager.backend_config == config.memory.backend_config
        assert yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) == original
    finally:
        reset_memory_manager()
        reset_app_config()
        set_memory_config(previous_memory)
