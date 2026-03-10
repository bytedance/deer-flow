"""Tests for LoopDetectionMiddleware."""

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from src.agents.middlewares.loop_detection_middleware import (
    LoopDetectionMiddleware,
    _hash_tool_calls,
    _HARD_STOP_MSG,
    _WARNING_MSG,
)


def _make_state(tool_calls=None, content=""):
    """Build a minimal AgentState dict with an AIMessage."""
    msg = AIMessage(content=content, tool_calls=tool_calls or [])
    return {"messages": [msg]}


def _bash_call(cmd="ls"):
    return {"name": "bash", "id": f"call_{cmd}", "args": {"command": cmd}}


class TestHashToolCalls:
    def test_same_calls_same_hash(self):
        a = _hash_tool_calls([_bash_call("ls")])
        b = _hash_tool_calls([_bash_call("ls")])
        assert a == b

    def test_different_calls_different_hash(self):
        a = _hash_tool_calls([_bash_call("ls")])
        b = _hash_tool_calls([_bash_call("pwd")])
        assert a != b

    def test_order_independent(self):
        a = _hash_tool_calls([_bash_call("ls"), {"name": "read_file", "args": {"path": "/tmp"}}])
        b = _hash_tool_calls([{"name": "read_file", "args": {"path": "/tmp"}}, _bash_call("ls")])
        assert a == b

    def test_empty_calls(self):
        h = _hash_tool_calls([])
        assert isinstance(h, str)
        assert len(h) > 0


class TestLoopDetection:
    def test_no_tool_calls_returns_none(self):
        mw = LoopDetectionMiddleware()
        state = {"messages": [AIMessage(content="hello")]}
        result = mw._apply(state)
        assert result is None

    def test_below_threshold_returns_none(self):
        mw = LoopDetectionMiddleware(warn_threshold=3)
        call = [_bash_call("ls")]

        # First two identical calls — no warning
        for _ in range(2):
            result = mw._apply(_make_state(tool_calls=call))
            assert result is None

    def test_warn_at_threshold(self):
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
        call = [_bash_call("ls")]

        for _ in range(2):
            mw._apply(_make_state(tool_calls=call))

        # Third identical call triggers warning
        result = mw._apply(_make_state(tool_calls=call))
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], SystemMessage)
        assert "LOOP DETECTED" in msgs[0].content

    def test_hard_stop_at_limit(self):
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call))

        # Fourth call triggers hard stop
        result = mw._apply(_make_state(tool_calls=call))
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        # Hard stop strips tool_calls
        assert isinstance(msgs[0], AIMessage)
        assert msgs[0].tool_calls == []
        assert _HARD_STOP_MSG in msgs[0].content

    def test_different_calls_dont_trigger(self):
        mw = LoopDetectionMiddleware(warn_threshold=2)

        # Each call is different
        for i in range(10):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]))
            assert result is None

    def test_window_sliding(self):
        mw = LoopDetectionMiddleware(warn_threshold=3, window_size=5)
        call = [_bash_call("ls")]

        # Fill with 2 identical calls
        mw._apply(_make_state(tool_calls=call))
        mw._apply(_make_state(tool_calls=call))

        # Push them out of the window with different calls
        for i in range(5):
            mw._apply(_make_state(tool_calls=[_bash_call(f"other_{i}")]))

        # Now the original call should be fresh again — no warning
        result = mw._apply(_make_state(tool_calls=call))
        assert result is None

    def test_reset_clears_state(self):
        mw = LoopDetectionMiddleware(warn_threshold=2)
        call = [_bash_call("ls")]

        mw._apply(_make_state(tool_calls=call))
        mw._apply(_make_state(tool_calls=call))

        # Would trigger warning, but reset first
        mw.reset()
        result = mw._apply(_make_state(tool_calls=call))
        assert result is None

    def test_non_ai_message_ignored(self):
        mw = LoopDetectionMiddleware()
        state = {"messages": [SystemMessage(content="hello")]}
        result = mw._apply(state)
        assert result is None

    def test_empty_messages_ignored(self):
        mw = LoopDetectionMiddleware()
        result = mw._apply({"messages": []})
        assert result is None
