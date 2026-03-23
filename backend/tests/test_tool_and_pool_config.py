"""Tests for tool config and subagent pool size configuration.

Covers:
- get_max_content_chars() with valid, invalid, and missing config values
- SubagentsAppConfig scheduler_pool_size / execution_pool_size fields
"""

from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.subagents_config import (
    SubagentsAppConfig,
    get_subagents_app_config,
    load_subagents_config_from_dict,
)
from deerflow.config.tool_config import (
    _DEFAULT_MAX_CONTENT_CHARS,
    ToolConfig,
    get_max_content_chars,
)

# ---------------------------------------------------------------------------
# get_max_content_chars()
# ---------------------------------------------------------------------------


class TestGetMaxContentChars:
    """Tests for get_max_content_chars() including ValueError/TypeError handling."""

    def _mock_app_config_with_extra(self, extra: dict):
        """Return a mock AppConfig whose get_tool_config returns a ToolConfig with given model_extra."""
        tool = ToolConfig(name="web_fetch", group="web", use="dummy:tool", **extra)
        app_config = MagicMock()
        app_config.get_tool_config.return_value = tool
        return app_config

    def test_returns_default_when_tool_not_configured(self):
        app_config = MagicMock()
        app_config.get_tool_config.return_value = None
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == _DEFAULT_MAX_CONTENT_CHARS

    def test_returns_default_when_key_absent(self):
        app_config = self._mock_app_config_with_extra({})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == _DEFAULT_MAX_CONTENT_CHARS

    def test_returns_configured_int_value(self):
        app_config = self._mock_app_config_with_extra({"max_content_chars": 8192})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == 8192

    def test_returns_configured_string_value(self):
        """YAML may parse a bare number as string; int() should handle it."""
        app_config = self._mock_app_config_with_extra({"max_content_chars": "32768"})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == 32768

    def test_falls_back_on_invalid_string(self):
        """A malformed value like 'abc' should not crash — returns default."""
        app_config = self._mock_app_config_with_extra({"max_content_chars": "not_a_number"})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == _DEFAULT_MAX_CONTENT_CHARS

    def test_falls_back_on_none_value(self):
        """max_content_chars explicitly set to None should not crash."""
        app_config = self._mock_app_config_with_extra({"max_content_chars": None})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == _DEFAULT_MAX_CONTENT_CHARS

    def test_falls_back_on_empty_string(self):
        app_config = self._mock_app_config_with_extra({"max_content_chars": ""})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == _DEFAULT_MAX_CONTENT_CHARS

    def test_clamps_zero_to_one(self):
        """A zero value should be clamped to 1."""
        app_config = self._mock_app_config_with_extra({"max_content_chars": 0})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == 1

    def test_clamps_negative_to_one(self):
        """A negative value should be clamped to 1."""
        app_config = self._mock_app_config_with_extra({"max_content_chars": -100})
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == 1

    def test_respects_tool_name_parameter(self):
        """get_tool_config is called with the provided tool_name."""
        app_config = MagicMock()
        app_config.get_tool_config.return_value = None
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            get_max_content_chars("custom_fetcher")
            app_config.get_tool_config.assert_called_once_with("custom_fetcher")

    def test_handles_none_model_extra(self):
        """model_extra can be None in Pydantic v2 — should not crash."""
        app_config = MagicMock()
        tool = MagicMock()
        tool.model_extra = None
        app_config.get_tool_config.return_value = tool
        with patch("deerflow.config.tool_config.get_app_config", return_value=app_config):
            assert get_max_content_chars() == _DEFAULT_MAX_CONTENT_CHARS


# ---------------------------------------------------------------------------
# SubagentsAppConfig – scheduler_pool_size / execution_pool_size
# ---------------------------------------------------------------------------


class TestPoolSizeDefaults:
    """Tests for scheduler_pool_size and execution_pool_size fields."""

    def test_default_scheduler_pool_size(self):
        config = SubagentsAppConfig()
        assert config.scheduler_pool_size == 3

    def test_default_execution_pool_size(self):
        config = SubagentsAppConfig()
        assert config.execution_pool_size == 3

    def test_custom_scheduler_pool_size(self):
        config = SubagentsAppConfig(scheduler_pool_size=5)
        assert config.scheduler_pool_size == 5

    def test_custom_execution_pool_size(self):
        config = SubagentsAppConfig(execution_pool_size=10)
        assert config.execution_pool_size == 10

    def test_rejects_zero_scheduler_pool_size(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(scheduler_pool_size=0)

    def test_rejects_negative_scheduler_pool_size(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(scheduler_pool_size=-1)

    def test_rejects_zero_execution_pool_size(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(execution_pool_size=0)

    def test_rejects_negative_execution_pool_size(self):
        with pytest.raises(ValueError):
            SubagentsAppConfig(execution_pool_size=-1)

    def test_minimum_valid_pool_sizes(self):
        config = SubagentsAppConfig(scheduler_pool_size=1, execution_pool_size=1)
        assert config.scheduler_pool_size == 1
        assert config.execution_pool_size == 1


class TestPoolSizeLoadFromDict:
    """Tests that pool sizes survive load_subagents_config_from_dict round-trip."""

    def teardown_method(self):
        load_subagents_config_from_dict({})

    def test_load_custom_pool_sizes(self):
        load_subagents_config_from_dict({"scheduler_pool_size": 8, "execution_pool_size": 12})
        cfg = get_subagents_app_config()
        assert cfg.scheduler_pool_size == 8
        assert cfg.execution_pool_size == 12

    def test_load_empty_dict_uses_default_pool_sizes(self):
        load_subagents_config_from_dict({})
        cfg = get_subagents_app_config()
        assert cfg.scheduler_pool_size == 3
        assert cfg.execution_pool_size == 3

    def test_load_partial_pool_size(self):
        load_subagents_config_from_dict({"scheduler_pool_size": 6})
        cfg = get_subagents_app_config()
        assert cfg.scheduler_pool_size == 6
        assert cfg.execution_pool_size == 3  # default preserved
