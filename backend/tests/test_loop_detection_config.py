"""Tests for loop detection configuration."""

import pytest

from deerflow.config.loop_detection_config import LoopDetectionConfig


class TestLoopDetectionConfig:
    def test_defaults_match_middleware_defaults(self):
        config = LoopDetectionConfig()

        assert config.enabled is True
        assert config.warn_threshold == 3
        assert config.hard_limit == 5
        assert config.window_size == 20
        assert config.max_tracked_threads == 100
        assert config.tool_freq_warn == 30
        assert config.tool_freq_hard_limit == 50

    def test_accepts_custom_values(self):
        config = LoopDetectionConfig(
            enabled=False,
            warn_threshold=10,
            hard_limit=20,
            window_size=50,
            max_tracked_threads=200,
            tool_freq_warn=60,
            tool_freq_hard_limit=80,
        )

        assert config.enabled is False
        assert config.warn_threshold == 10
        assert config.hard_limit == 20
        assert config.window_size == 50
        assert config.max_tracked_threads == 200
        assert config.tool_freq_warn == 60
        assert config.tool_freq_hard_limit == 80

    def test_rejects_zero_thresholds(self):
        with pytest.raises(ValueError):
            LoopDetectionConfig(warn_threshold=0)

        with pytest.raises(ValueError):
            LoopDetectionConfig(hard_limit=0)

        with pytest.raises(ValueError):
            LoopDetectionConfig(tool_freq_warn=0)

        with pytest.raises(ValueError):
            LoopDetectionConfig(tool_freq_hard_limit=0)

    def test_rejects_hard_limit_below_warn_threshold(self):
        with pytest.raises(ValueError, match="hard_limit"):
            LoopDetectionConfig(warn_threshold=5, hard_limit=4)

    def test_rejects_tool_freq_hard_limit_below_warn_threshold(self):
        with pytest.raises(ValueError, match="tool_freq_hard_limit"):
            LoopDetectionConfig(tool_freq_warn=5, tool_freq_hard_limit=4)

    def test_tool_freq_override_valid(self):
        config = LoopDetectionConfig(tool_freq_overrides={"bash": {"warn": 150, "hard_limit": 300}})
        override = config.tool_freq_overrides["bash"]
        assert override.warn == 150
        assert override.hard_limit == 300

    def test_tool_freq_override_rejects_zero_warn(self):
        with pytest.raises(ValueError):
            LoopDetectionConfig(tool_freq_overrides={"bash": {"warn": 0, "hard_limit": 10}})

    def test_tool_freq_override_rejects_hard_limit_below_warn(self):
        with pytest.raises(ValueError, match="hard_limit"):
            LoopDetectionConfig(tool_freq_overrides={"bash": {"warn": 100, "hard_limit": 50}})
