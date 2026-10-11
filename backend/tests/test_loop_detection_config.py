"""Tests for loop detection configuration."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
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

    def test_accepts_numeric_string_thresholds(self):
        config = LoopDetectionConfig.model_validate(
            {
                "warn_threshold": "10",
                "hard_limit": "20",
                "window_size": "50",
                "max_tracked_threads": "200",
                "tool_freq_warn": "60",
                "tool_freq_hard_limit": "80",
                "tool_freq_overrides": {"bash": {"warn": "150", "hard_limit": "300"}},
            },
        )

        assert config.warn_threshold == 10
        assert config.hard_limit == 20
        assert config.window_size == 50
        assert config.max_tracked_threads == 200
        assert config.tool_freq_warn == 60
        assert config.tool_freq_hard_limit == 80
        assert config.tool_freq_overrides["bash"].warn == 150
        assert config.tool_freq_overrides["bash"].hard_limit == 300

    def test_rejects_zero_thresholds(self):
        with pytest.raises(ValueError):
            LoopDetectionConfig(warn_threshold=0)

        with pytest.raises(ValueError):
            LoopDetectionConfig(hard_limit=0)

        with pytest.raises(ValueError):
            LoopDetectionConfig(tool_freq_warn=0)

        with pytest.raises(ValueError):
            LoopDetectionConfig(tool_freq_hard_limit=0)

    @pytest.mark.parametrize(
        ("payload", "field"),
        [
            ({"warn_threshold": True}, "warn_threshold"),
            ({"warn_threshold": 1, "hard_limit": True}, "hard_limit"),
            ({"window_size": True}, "window_size"),
            ({"max_tracked_threads": True}, "max_tracked_threads"),
            ({"tool_freq_warn": True}, "tool_freq_warn"),
            ({"tool_freq_warn": 1, "tool_freq_hard_limit": True}, "tool_freq_hard_limit"),
            ({"tool_freq_overrides": {"bash": {"warn": True, "hard_limit": 2}}}, "warn"),
            ({"tool_freq_overrides": {"bash": {"warn": 1, "hard_limit": True}}}, "hard_limit"),
        ],
    )
    def test_rejects_boolean_integer_thresholds(self, payload, field):
        with pytest.raises(ValueError, match=field):
            LoopDetectionConfig(**payload)

    def test_rejects_hard_limit_below_warn_threshold(self):
        with pytest.raises(ValueError, match="hard_limit"):
            LoopDetectionConfig(warn_threshold=5, hard_limit=4)

    @pytest.mark.parametrize(
        "payload",
        [
            {"window_size": 3, "warn_threshold": 3, "hard_limit": 5},
            {"window_size": 1, "warn_threshold": 1, "hard_limit": 5},
            {"hard_limit": 21},
            {"window_size": "3", "hard_limit": "5"},
        ],
    )
    def test_rejects_window_that_cannot_reach_identical_call_hard_limit(self, payload):
        with pytest.raises(ValueError, match="window_size must be greater than or equal to hard_limit"):
            LoopDetectionConfig.model_validate(payload)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("async_hooks", [False, True], ids=["sync", "async"])
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"window_size": 5, "warn_threshold": 3, "hard_limit": 5},
            {"window_size": 8, "warn_threshold": 4, "hard_limit": 8},
            {"window_size": 1, "warn_threshold": 1, "hard_limit": 1},
        ],
        ids=["defaults", "exact-window", "custom-limit", "single-call"],
    )
    async def test_accepted_config_stops_identical_calls_at_configured_limit(self, payload, async_hooks):
        config = LoopDetectionConfig.model_validate(payload)
        middleware = LoopDetectionMiddleware.from_config(config)
        runtime = SimpleNamespace(context={"thread_id": "test-thread", "run_id": "test-run"})

        for step in range(1, config.hard_limit + 1):
            # Distinct IDs represent real successive model responses, not replay.
            message = AIMessage(id=f"response-{step}", content="", tool_calls=[{"name": "bash", "args": {"command": "echo repeat"}, "id": f"call-{step}"}])
            state = {"messages": [message]}
            result = await middleware.aafter_model(state, runtime) if async_hooks else middleware.after_model(state, runtime)
            if step < config.hard_limit:
                assert result is None
            else:
                assert result is not None
                assert result["messages"][0].tool_calls == []
        assert middleware.consume_stop_reason("test-run") == "loop_capped"

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
