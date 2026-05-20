"""Tests for ExtensionsConfig.resolve_env_variables — list-value expansion."""

import pytest

from deerflow.config.extensions_config import ExtensionsConfig


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "resolved-token")
    monkeypatch.setenv("TEST_HOST", "example.com")


def test_string_in_list_expanded():
    config = {"args": ["--token", "$TEST_TOKEN"]}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["args"] == ["--token", "resolved-token"]


def test_plain_string_in_list_unchanged():
    config = {"args": ["--verbose", "--no-cache"]}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["args"] == ["--verbose", "--no-cache"]


def test_missing_env_var_in_list_becomes_empty_string(monkeypatch):
    monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
    config = {"args": ["--key", "$DOES_NOT_EXIST"]}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["args"] == ["--key", ""]


def test_dict_inside_list_still_recursed():
    config = {"items": [{"header": "$TEST_TOKEN"}, {"plain": "value"}]}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["items"] == [{"header": "resolved-token"}, {"plain": "value"}]


def test_top_level_string_value_expanded():
    config = {"api_key": "$TEST_TOKEN"}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["api_key"] == "resolved-token"


def test_nested_dict_string_expanded():
    config = {"auth": {"token": "$TEST_TOKEN", "host": "$TEST_HOST"}}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["auth"] == {"token": "resolved-token", "host": "example.com"}


def test_mixed_list_with_multiple_vars():
    config = {"args": ["--host", "$TEST_HOST", "--token", "$TEST_TOKEN", "--debug"]}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["args"] == ["--host", "example.com", "--token", "resolved-token", "--debug"]


def test_non_string_scalars_in_list_unchanged():
    config = {"ports": [8080, 9090, True]}
    result = ExtensionsConfig.resolve_env_variables(config)
    assert result["ports"] == [8080, 9090, True]
