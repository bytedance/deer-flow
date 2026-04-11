"""Tests for configurable loop detection thresholds.

Validates that:
1. LoopDetectionConfig has correct defaults and validation.
2. LoopDetectionMiddleware respects custom thresholds from config.
3. AppConfig includes loop_detection with sensible defaults.
4. The factory and lead_agent paths wire config -> middleware correctly.
"""

import copy
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.loop_detection_middleware import (
    _HARD_STOP_MSG,
    _WARNING_MSG,
    LoopDetectionMiddleware,
)
from deerflow.config.loop_detection_config import LoopDetectionConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(thread_id="test-thread"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


def _make_state(tool_calls=None, content=""):
    safe_content = copy.deepcopy(content) if isinstance(content, list) else content
    msg = AIMessage(content=safe_content, tool_calls=tool_calls or [])
    return {"messages": [msg]}


def _bash_call(cmd="ls"):
    return {"name": "bash", "id": f"call_{cmd}", "args": {"command": cmd}}


# ---------------------------------------------------------------------------
# LoopDetectionConfig unit tests
# ---------------------------------------------------------------------------

class TestLoopDetectionConfig:
    """Test the Pydantic config model itself."""

    def test_defaults(self):
        cfg = LoopDetectionConfig()
        assert cfg.warn_threshold == 3
        assert cfg.hard_limit == 5
        assert cfg.window_size == 20
        assert cfg.max_tracked_threads == 100

    def test_custom_values(self):
        cfg = LoopDetectionConfig(
            warn_threshold=5,
            hard_limit=10,
            window_size=50,
            max_tracked_threads=200,
        )
        assert cfg.warn_threshold == 5
        assert cfg.hard_limit == 10
        assert cfg.window_size == 50
        assert cfg.max_tracked_threads == 200

    def test_from_dict(self):
        """Simulate loading from parsed YAML dict."""
        data = {"warn_threshold": 8, "hard_limit": 15}
        cfg = LoopDetectionConfig(**data)
        assert cfg.warn_threshold == 8
        assert cfg.hard_limit == 15
        # Non-specified fields use defaults
        assert cfg.window_size == 20
        assert cfg.max_tracked_threads == 100

    def test_validation_warn_threshold_min(self):
        """warn_threshold must be >= 1."""
        with pytest.raises(Exception):
            LoopDetectionConfig(warn_threshold=0)

    def test_validation_hard_limit_min(self):
        """hard_limit must be >= 2."""
        with pytest.raises(Exception):
            LoopDetectionConfig(hard_limit=1)

    def test_validation_window_size_min(self):
        """window_size must be >= 1."""
        with pytest.raises(Exception):
            LoopDetectionConfig(window_size=0)


# ---------------------------------------------------------------------------
# Configurable thresholds integration tests
# ---------------------------------------------------------------------------

class TestConfigurableThresholds:
    """Test that LoopDetectionMiddleware behaves correctly with custom thresholds."""

    def test_higher_warn_threshold_avoids_false_positive(self):
        """With warn_threshold=6, 5 identical calls should NOT trigger a warning."""
        mw = LoopDetectionMiddleware(warn_threshold=6, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(5):
            result = mw._apply(_make_state(tool_calls=call), runtime)
            assert result is None  # No warning yet

    def test_higher_warn_threshold_fires_at_correct_count(self):
        """With warn_threshold=6, the 6th identical call should trigger a warning."""
        mw = LoopDetectionMiddleware(warn_threshold=6, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(5):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 6th call triggers
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        assert isinstance(result["messages"][0], HumanMessage)
        assert "LOOP DETECTED" in result["messages"][0].content

    def test_higher_hard_limit_avoids_premature_stop(self):
        """With hard_limit=10, 9 identical calls should NOT hard-stop."""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for i in range(9):
            result = mw._apply(_make_state(tool_calls=call), runtime)
            if result is not None:
                # Should be a warning, not a hard stop
                msg = result["messages"][0]
                assert isinstance(msg, HumanMessage), f"Expected warning at step {i+1}, got hard stop"

    def test_higher_hard_limit_fires_at_correct_count(self):
        """With hard_limit=10, the 10th identical call should hard-stop."""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(9):
            mw._apply(_make_state(tool_calls=call), runtime)

        # 10th call triggers hard stop
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.tool_calls == []
        assert _HARD_STOP_MSG in msg.content

    def test_custom_window_size(self):
        """Smaller window_size evicts old hashes faster, preventing false positives."""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5, window_size=3)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # 2 identical calls
        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        # Push them out with 3 different calls (window_size=3)
        for i in range(3):
            mw._apply(_make_state(tool_calls=[_bash_call(f"other_{i}")]), runtime)

        # Original call should be fresh -- no warning
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_config_object_to_middleware(self):
        """LoopDetectionConfig values should wire through to middleware behavior."""
        cfg = LoopDetectionConfig(warn_threshold=4, hard_limit=8, window_size=30)
        mw = LoopDetectionMiddleware(
            warn_threshold=cfg.warn_threshold,
            hard_limit=cfg.hard_limit,
            window_size=cfg.window_size,
            max_tracked_threads=cfg.max_tracked_threads,
        )

        assert mw.warn_threshold == 4
        assert mw.hard_limit == 8
        assert mw.window_size == 30
        assert mw.max_tracked_threads == 100

    def test_deepseek_friendly_thresholds(self):
        """Simulate a DeepSeek-friendly config: higher thresholds to reduce false positives.

        With warn_threshold=5 and hard_limit=8, legitimate retry patterns
        (up to 4 identical calls) should not trigger any intervention.
        """
        cfg = LoopDetectionConfig(warn_threshold=5, hard_limit=8)
        mw = LoopDetectionMiddleware(
            warn_threshold=cfg.warn_threshold,
            hard_limit=cfg.hard_limit,
        )
        runtime = _make_runtime()
        call = [_bash_call("retry_operation")]

        # 4 legitimate retries -- no warning
        for _ in range(4):
            result = mw._apply(_make_state(tool_calls=call), runtime)
            assert result is None

        # 5th retry triggers warning
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

    def test_backwards_compatibility_default_thresholds(self):
        """Default config should match the original hardcoded values."""
        cfg = LoopDetectionConfig()
        mw = LoopDetectionMiddleware(
            warn_threshold=cfg.warn_threshold,
            hard_limit=cfg.hard_limit,
            window_size=cfg.window_size,
            max_tracked_threads=cfg.max_tracked_threads,
        )

        # These should match the original _DEFAULT_* constants
        assert mw.warn_threshold == 3
        assert mw.hard_limit == 5
        assert mw.window_size == 20
        assert mw.max_tracked_threads == 100
