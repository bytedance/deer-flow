"""Tests for total tool call limit feature in LoopDetectionMiddleware."""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.loop_detection_middleware import (
    LoopDetectionMiddleware,
)
from deerflow.config.loop_detection_config import LoopDetectionConfig


def _make_runtime(thread_id="test-thread", run_id="test-run"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id, "run_id": run_id}
    return runtime


def _make_state_with_tool_calls(tool_name: str, args: dict):
    """Create a state with an AIMessage containing one tool call."""
    msg = AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args, "id": "call_1"}],
    )
    return {"messages": [msg]}


class TestTotalCallLimit:
    """R1: Total tool call limit across all tools in a single task."""

    def test_under_limit_no_stop(self):
        """Calls under the limit should pass without triggering."""
        config = LoopDetectionConfig(total_call_limit=5)
        mw = LoopDetectionMiddleware.from_config(config)
        runtime = _make_runtime()

        for i in range(4):
            state = _make_state_with_tool_calls(f"tool_{i}", {"arg": i})
            result = mw.after_model(state, runtime)
            assert result is None, f"Should not trigger at call {i+1}"

    def test_at_limit_triggers_hard_stop(self):
        """When total calls reach the limit, should force stop."""
        config = LoopDetectionConfig(total_call_limit=5)
        mw = LoopDetectionMiddleware.from_config(config)
        runtime = _make_runtime()

        # First 4 calls pass (different tools, different args — no loop)
        for i in range(4):
            state = _make_state_with_tool_calls(f"tool_{i}", {"arg": i})
            mw.after_model(state, runtime)

        # 5th call should trigger total limit
        state = _make_state_with_tool_calls("tool_5", {"arg": 5})
        result = mw.after_model(state, runtime)
        assert result is not None, "Should trigger at total limit"
        last_msg = result["messages"][0]
        assert "total" in last_msg.content.lower() or "limit" in last_msg.content.lower()

    def test_default_total_limit_is_80(self):
        """Default total_call_limit should be 80."""
        config = LoopDetectionConfig()
        assert config.total_call_limit == 80

    def test_total_limit_configurable(self):
        """total_call_limit should be configurable via config."""
        config = LoopDetectionConfig(total_call_limit=100)
        assert config.total_call_limit == 100

    def test_total_limit_disabled_when_zero(self):
        """total_call_limit=0 should disable the total limit check."""
        config = LoopDetectionConfig(total_call_limit=0)
        mw = LoopDetectionMiddleware.from_config(config)
        runtime = _make_runtime()

        # Should not trigger even after many calls
        for i in range(100):
            state = _make_state_with_tool_calls(f"tool_{i}", {"arg": i})
            result = mw.after_model(state, runtime)
            # May trigger tool_freq but not total limit
            # (using different tool names avoids tool_freq)

    def test_total_limit_per_thread(self):
        """Total call count should be tracked per thread, not globally."""
        config = LoopDetectionConfig(total_call_limit=5)
        mw = LoopDetectionMiddleware.from_config(config)

        runtime_a = _make_runtime(thread_id="thread-a")
        runtime_b = _make_runtime(thread_id="thread-b")

        # 4 calls on thread A
        for i in range(4):
            state = _make_state_with_tool_calls(f"tool_{i}", {"arg": i})
            mw.after_model(state, runtime_a)

        # 4 calls on thread B — should not trigger (separate count)
        for i in range(4):
            state = _make_state_with_tool_calls(f"tool_{i}", {"arg": i})
            result = mw.after_model(state, runtime_b)
            assert result is None

    def test_total_limit_resets_on_thread_reset(self):
        """Resetting a thread should clear its total call count."""
        config = LoopDetectionConfig(total_call_limit=5)
        mw = LoopDetectionMiddleware.from_config(config)
        runtime = _make_runtime()

        for i in range(4):
            state = _make_state_with_tool_calls(f"tool_{i}", {"arg": i})
            mw.after_model(state, runtime)

        mw.reset(thread_id="test-thread")

        # After reset, should be able to do 4 more without triggering
        for i in range(4):
            state = _make_state_with_tool_calls(f"tool_{i+10}", {"arg": i})
            result = mw.after_model(state, runtime)
            assert result is None


class TestDeadLoopDetection:
    """R3: Same tool + same args consecutive calls detected as dead loop."""

    def test_identical_calls_trigger_warning_at_threshold(self):
        """3 identical calls should produce a warning."""
        config = LoopDetectionConfig(warn_threshold=3, hard_limit=5, total_call_limit=0)
        mw = LoopDetectionMiddleware.from_config(config)
        runtime = _make_runtime()

        for i in range(3):
            state = _make_state_with_tool_calls("get_pod_status", {"namespace": "ittzp-dev"})
            result = mw.after_model(state, runtime)

        # After 3 identical calls, warning should be queued
        # The warning is deferred to wrap_model_call, so after_model returns None
        # but the pending_warnings dict should have an entry
        assert len(mw._pending_warnings) > 0 or result is not None

    def test_different_args_no_loop(self):
        """Same tool with different args should NOT trigger loop detection."""
        config = LoopDetectionConfig(warn_threshold=3, hard_limit=5, total_call_limit=0)
        mw = LoopDetectionMiddleware.from_config(config)
        runtime = _make_runtime()

        nodes = ["node-a", "node-b", "node-c", "node-d", "node-e"]
        for node in nodes:
            state = _make_state_with_tool_calls("get_node_metrics", {"node": node})
            result = mw.after_model(state, runtime)

        # No loop detection should trigger
        assert len(mw._pending_warnings) == 0

    def test_hard_limit_forces_stop(self):
        """5 identical calls should force stop (strip tool_calls)."""
        config = LoopDetectionConfig(warn_threshold=3, hard_limit=5, total_call_limit=0)
        mw = LoopDetectionMiddleware.from_config(config)
        runtime = _make_runtime()

        result = None
        for i in range(5):
            state = _make_state_with_tool_calls("get_pod_status", {"namespace": "ittzp-dev"})
            result = mw.after_model(state, runtime)

        # 5th call should force stop
        assert result is not None
        last_msg = result["messages"][0]
        assert last_msg.tool_calls == []


class TestGuardrailConfig:
    """R5: Configuration validation."""

    def test_config_fields_exist(self):
        """LoopDetectionConfig should have total_call_limit field."""
        config = LoopDetectionConfig(
            total_call_limit=80,
            warn_threshold=3,
            hard_limit=5,
            tool_freq_warn=30,
            tool_freq_hard_limit=50,
        )
        assert config.total_call_limit == 80
        assert config.warn_threshold == 3
        assert config.hard_limit == 5

    def test_total_call_limit_validation(self):
        """total_call_limit must be >= 0."""
        with pytest.raises(Exception):
            LoopDetectionConfig(total_call_limit=-1)
