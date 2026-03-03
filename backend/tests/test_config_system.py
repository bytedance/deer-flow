"""Tests for AppConfig path resolution, env variable injection, singleton lifecycle, and model lookup."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.app_config import (
    AppConfig,
    get_app_config,
    reload_app_config,
    reset_app_config,
    set_app_config,
)


# ---------------------------------------------------------------------------
# resolve_config_path
# ---------------------------------------------------------------------------
class TestResolveConfigPath:
    """Tests for AppConfig.resolve_config_path()."""

    def test_explicit_path_found(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("models: []")
        result = AppConfig.resolve_config_path(str(config_file))
        assert result == config_file

    def test_explicit_path_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="config_path"):
            AppConfig.resolve_config_path(str(tmp_path / "nonexistent.yaml"))

    def test_env_var_path(self, tmp_path: Path) -> None:
        config_file = tmp_path / "custom.yaml"
        config_file.write_text("models: []")
        with patch.dict(os.environ, {"DEER_FLOW_CONFIG_PATH": str(config_file)}):
            result = AppConfig.resolve_config_path()
            assert result == config_file

    def test_env_var_path_not_found(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"DEER_FLOW_CONFIG_PATH": str(tmp_path / "missing.yaml")}):
            with pytest.raises(FileNotFoundError, match="DEER_FLOW_CONFIG_PATH"):
                AppConfig.resolve_config_path()

    def test_cwd_fallback(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text("models: []")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEER_FLOW_CONFIG_PATH", None)
            with patch("os.getcwd", return_value=str(tmp_path)):
                result = AppConfig.resolve_config_path()
                assert result == config_file

    def test_parent_dir_fallback(self, tmp_path: Path) -> None:
        child = tmp_path / "subdir"
        child.mkdir()
        config_file = tmp_path / "config.yaml"
        config_file.write_text("models: []")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEER_FLOW_CONFIG_PATH", None)
            with patch("os.getcwd", return_value=str(child)):
                result = AppConfig.resolve_config_path()
                assert result == config_file

    def test_not_found_anywhere(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEER_FLOW_CONFIG_PATH", None)
            with patch("os.getcwd", return_value=str(tmp_path)):
                with pytest.raises(FileNotFoundError, match="config.yaml"):
                    AppConfig.resolve_config_path()


# ---------------------------------------------------------------------------
# resolve_env_variables
# ---------------------------------------------------------------------------
class TestResolveEnvVariables:
    """Tests for AppConfig.resolve_env_variables()."""

    def test_resolves_string(self) -> None:
        with patch.dict(os.environ, {"MY_KEY": "secret"}):
            result = AppConfig.resolve_env_variables("$MY_KEY")
            assert result == "secret"

    def test_missing_env_var_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="MISSING_VAR"):
                AppConfig.resolve_env_variables("$MISSING_VAR")

    def test_non_env_string_passthrough(self) -> None:
        result = AppConfig.resolve_env_variables("plain-string")
        assert result == "plain-string"

    def test_resolves_in_dict(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "resolved"}):
            result = AppConfig.resolve_env_variables({"api_key": "$API_KEY", "name": "test"})
            assert result == {"api_key": "resolved", "name": "test"}

    def test_resolves_in_list(self) -> None:
        with patch.dict(os.environ, {"VAL": "found"}):
            result = AppConfig.resolve_env_variables(["$VAL", "literal"])
            assert result == ["found", "literal"]

    def test_resolves_nested(self) -> None:
        with patch.dict(os.environ, {"KEY": "val"}):
            result = AppConfig.resolve_env_variables({"outer": {"inner": "$KEY"}})
            assert result == {"outer": {"inner": "val"}}

    def test_non_string_passthrough(self) -> None:
        assert AppConfig.resolve_env_variables(42) == 42
        assert AppConfig.resolve_env_variables(True) is True
        assert AppConfig.resolve_env_variables(None) is None


# ---------------------------------------------------------------------------
# Singleton lifecycle
# ---------------------------------------------------------------------------
class TestConfigSingleton:
    """Tests for get_app_config, set_app_config, reset_app_config."""

    def setup_method(self) -> None:
        reset_app_config()

    def teardown_method(self) -> None:
        reset_app_config()

    def test_set_and_get(self) -> None:
        config = AppConfig(models=[], sandbox={"use": "src.sandbox.local:LocalSandboxProvider"})
        set_app_config(config)
        assert get_app_config() is config

    def test_reset_clears_cache(self) -> None:
        config = AppConfig(models=[], sandbox={"use": "src.sandbox.local:LocalSandboxProvider"})
        set_app_config(config)
        reset_app_config()
        # Next call would try to load from file, so we patch that
        with patch.object(AppConfig, "from_file", return_value=config):
            result = get_app_config()
            assert result is config

    def test_reload_replaces_instance(self, tmp_path: Path) -> None:
        config1 = AppConfig(models=[], sandbox={"use": "src.sandbox.local:LocalSandboxProvider"})
        set_app_config(config1)
        config2 = AppConfig(models=[], sandbox={"use": "src.sandbox.local:LocalSandboxProvider"})
        with patch.object(AppConfig, "from_file", return_value=config2):
            result = reload_app_config()
            assert result is config2
            assert get_app_config() is config2


# ---------------------------------------------------------------------------
# get_model_config / get_tool_config
# ---------------------------------------------------------------------------
class TestConfigLookups:
    """Tests for model/tool config lookup methods."""

    def _config_with_models(self) -> AppConfig:
        config = AppConfig(
            models=[
                {"name": "gpt-4", "use": "langchain_openai.ChatOpenAI", "model": "gpt-4"},
                {"name": "claude-3", "use": "langchain_anthropic.ChatAnthropic", "model": "claude-3"},
            ],
            tools=[
                {"name": "bash", "group": "core", "use": "src.tools:bash_tool"},
                {"name": "python", "group": "core", "use": "src.tools:python_tool"},
            ],
            sandbox={"use": "src.sandbox.local:LocalSandboxProvider"},
        )
        return config

    def test_get_model_config_found(self) -> None:
        config = self._config_with_models()
        result = config.get_model_config("gpt-4")
        assert result is not None
        assert result.name == "gpt-4"

    def test_get_model_config_not_found(self) -> None:
        config = self._config_with_models()
        assert config.get_model_config("nonexistent") is None

    def test_get_tool_config_found(self) -> None:
        config = self._config_with_models()
        result = config.get_tool_config("bash")
        assert result is not None
        assert result.name == "bash"

    def test_get_tool_config_not_found(self) -> None:
        config = self._config_with_models()
        assert config.get_tool_config("nonexistent") is None
