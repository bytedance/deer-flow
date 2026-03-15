"""Tests for graceful environment variable handling in AppConfig."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.app_config import AppConfig
from src.config.extensions_config import ExtensionsConfig


class TestResolveEnvVariablesGraceful:
    def test_resolves_existing_env_var(self):
        with patch.dict(os.environ, {"TEST_KEY": "test_value"}):
            result = AppConfig.resolve_env_variables("$TEST_KEY")
            assert result == "test_value"

    def test_returns_none_for_missing_env_var(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("NONEXISTENT_KEY", None)
            result = AppConfig.resolve_env_variables("$NONEXISTENT_KEY")
            assert result is None

    def test_passes_through_non_env_strings(self):
        result = AppConfig.resolve_env_variables("plain_string")
        assert result == "plain_string"

    def test_resolves_dict_recursively(self):
        with patch.dict(os.environ, {"MY_KEY": "resolved"}):
            config = {"api_key": "$MY_KEY", "name": "test"}
            result = AppConfig.resolve_env_variables(config)
            assert result["api_key"] == "resolved"
            assert result["name"] == "test"

    def test_returns_none_in_dict_for_missing_var(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MISSING_VAR", None)
            config = {"api_key": "$MISSING_VAR", "name": "test"}
            result = AppConfig.resolve_env_variables(config)
            assert result["api_key"] is None
            assert result["name"] == "test"

    def test_resolves_list_recursively(self):
        with patch.dict(os.environ, {"KEY1": "val1"}):
            config = ["$KEY1", "literal"]
            result = AppConfig.resolve_env_variables(config)
            assert result == ["val1", "literal"]

    def test_nested_dict_in_list(self):
        with patch.dict(os.environ, {"NESTED": "yes"}):
            config = [{"key": "$NESTED"}, "plain"]
            result = AppConfig.resolve_env_variables(config)
            assert result[0]["key"] == "yes"
            assert result[1] == "plain"

    def test_non_string_values_pass_through(self):
        assert AppConfig.resolve_env_variables(42) == 42
        assert AppConfig.resolve_env_variables(True) is True
        assert AppConfig.resolve_env_variables(None) is None
        assert AppConfig.resolve_env_variables(3.14) == 3.14

    def test_from_file_empty_yaml_raises_validation_error_not_type_error(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")

        with (
            patch.object(AppConfig, "resolve_config_path", return_value=config_file),
            patch.object(ExtensionsConfig, "from_file", return_value=ExtensionsConfig()),
            pytest.raises(Exception) as exc_info,
        ):
            AppConfig.from_file()

        assert not isinstance(exc_info.value, TypeError)
