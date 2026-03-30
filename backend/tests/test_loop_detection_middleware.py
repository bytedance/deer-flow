"""Tests for LoopDetectionMiddleware."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.agents.middlewares.loop_detection_middleware import (
    _HARD_STOP_MSG,
    LoopDetectionMiddleware,
    _hash_tool_calls,
)


def _make_runtime(thread_id="test-thread"):
    """Build a minimal Runtime mock with context."""
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id}
    return runtime


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

    def test_ignores_description_only_differences(self):
        a = _hash_tool_calls(
            [
                {
                    "name": "read_file",
                    "args": {
                        "description": "check the uploaded spreadsheet",
                        "path": "/mnt/user-data/uploads/report.md",
                    },
                }
            ]
        )
        b = _hash_tool_calls(
            [
                {
                    "name": "read_file",
                    "args": {
                        "description": "read the markdown conversion again",
                        "path": "/mnt/user-data/uploads/report.md",
                    },
                }
            ]
        )
        assert a == b


class TestLoopDetection:
    def test_no_tool_calls_returns_none(self):
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        state = {"messages": [AIMessage(content="hello")]}
        result = mw._apply(state, runtime)
        assert result is None

    def test_below_threshold_returns_none(self):
        mw = LoopDetectionMiddleware(warn_threshold=3)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # First two identical calls — no warning
        for _ in range(2):
            result = mw._apply(_make_state(tool_calls=call), runtime)
            assert result is None

    def test_warn_at_threshold(self):
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Third identical call triggers warning
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
        assert "LOOP DETECTED" in msgs[0].content

    def test_warn_only_injected_once(self):
        """Warning for the same hash should only be injected once per thread."""
        mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # First two — no warning
        for _ in range(2):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Third — warning injected
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

        # Fourth — warning already injected, should return None
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_hard_stop_at_limit(self):
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Fourth call triggers hard stop
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 1
        # Hard stop strips tool_calls
        assert isinstance(msgs[0], AIMessage)
        assert msgs[0].tool_calls == []
        assert _HARD_STOP_MSG in msgs[0].content

    def test_different_calls_dont_trigger(self):
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = _make_runtime()

        # Each call is different
        for i in range(10):
            result = mw._apply(_make_state(tool_calls=[_bash_call(f"cmd_{i}")]), runtime)
            assert result is None

    def test_description_only_variations_still_trigger_loop_detection(self):
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()

        first = [
            {
                "name": "read_file",
                "id": "call_1",
                "args": {
                    "description": "inspect the converted excel file",
                    "path": "/mnt/user-data/uploads/budget.md",
                },
            }
        ]
        second = [
            {
                "name": "read_file",
                "id": "call_2",
                "args": {
                    "description": "retry reading the upload",
                    "path": "/mnt/user-data/uploads/budget.md",
                },
            }
        ]

        assert mw._apply(_make_state(tool_calls=first), runtime) is None
        result = mw._apply(_make_state(tool_calls=second), runtime)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

    def test_window_sliding(self):
        mw = LoopDetectionMiddleware(warn_threshold=3, window_size=5)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # Fill with 2 identical calls
        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        # Push them out of the window with different calls
        for i in range(5):
            mw._apply(_make_state(tool_calls=[_bash_call(f"other_{i}")]), runtime)

        # Now the original call should be fresh again — no warning
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_reset_clears_state(self):
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        mw._apply(_make_state(tool_calls=call), runtime)
        mw._apply(_make_state(tool_calls=call), runtime)

        # Would trigger warning, but reset first
        mw.reset()
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is None

    def test_non_ai_message_ignored(self):
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        state = {"messages": [SystemMessage(content="hello")]}
        result = mw._apply(state, runtime)
        assert result is None

    def test_empty_messages_ignored(self):
        mw = LoopDetectionMiddleware()
        runtime = _make_runtime()
        result = mw._apply({"messages": []}, runtime)
        assert result is None

    def test_thread_id_from_runtime_context(self):
        """Thread ID should come from runtime.context, not state."""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime_a = _make_runtime("thread-A")
        runtime_b = _make_runtime("thread-B")
        call = [_bash_call("ls")]

        # One call on thread A
        mw._apply(_make_state(tool_calls=call), runtime_a)
        # One call on thread B
        mw._apply(_make_state(tool_calls=call), runtime_b)

        # Second call on thread A — triggers warning (2 >= warn_threshold)
        result = mw._apply(_make_state(tool_calls=call), runtime_a)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

        # Second call on thread B — also triggers (independent tracking)
        result = mw._apply(_make_state(tool_calls=call), runtime_b)
        assert result is not None
        assert "LOOP DETECTED" in result["messages"][0].content

    def test_lru_eviction(self):
        """Old threads should be evicted when max_tracked_threads is exceeded."""
        mw = LoopDetectionMiddleware(warn_threshold=2, max_tracked_threads=3)
        call = [_bash_call("ls")]

        # Fill up 3 threads
        for i in range(3):
            runtime = _make_runtime(f"thread-{i}")
            mw._apply(_make_state(tool_calls=call), runtime)

        # Add a 4th thread — should evict thread-0
        runtime_new = _make_runtime("thread-new")
        mw._apply(_make_state(tool_calls=call), runtime_new)

        assert "thread-0" not in mw._history
        assert "thread-new" in mw._history
        assert len(mw._history) == 3

    def test_thread_safe_mutations(self):
        """Verify lock is used for mutations (basic structural test)."""
        mw = LoopDetectionMiddleware()
        # The middleware should have a lock attribute
        assert hasattr(mw, "_lock")
        assert isinstance(mw._lock, type(mw._lock))

    def test_fallback_thread_id_when_missing(self):
        """When runtime context has no thread_id, should use 'default'."""
        mw = LoopDetectionMiddleware(warn_threshold=2)
        runtime = MagicMock()
        runtime.context = {}
        call = [_bash_call("ls")]

        mw._apply(_make_state(tool_calls=call), runtime)
        assert "default" in mw._history


class TestNormalizeToolArgs:
    """Direct unit tests for the _normalize_tool_args helper."""

    def test_description_key_is_stripped(self):
        from deerflow.agents.middlewares.loop_detection_middleware import _normalize_tool_args

        result = _normalize_tool_args({"description": "some prompt text", "path": "/tmp/file.txt"})
        assert "description" not in result
        assert result["path"] == "/tmp/file.txt"

    def test_non_semantic_keys_preserved(self):
        from deerflow.agents.middlewares.loop_detection_middleware import _normalize_tool_args

        result = _normalize_tool_args({"command": "ls -la", "timeout": 30})
        assert result == {"command": "ls -la", "timeout": 30}

    def test_empty_args_returns_empty_dict(self):
        from deerflow.agents.middlewares.loop_detection_middleware import _normalize_tool_args

        assert _normalize_tool_args({}) == {}

    def test_args_with_only_description_returns_empty_dict(self):
        from deerflow.agents.middlewares.loop_detection_middleware import _normalize_tool_args

        result = _normalize_tool_args({"description": "I should be stripped"})
        assert result == {}

    def test_multiple_semantic_keys_all_retained(self):
        from deerflow.agents.middlewares.loop_detection_middleware import _normalize_tool_args

        result = _normalize_tool_args(
            {"description": "noise", "path": "/tmp/a.txt", "encoding": "utf-8", "start_line": 1}
        )
        assert result == {"path": "/tmp/a.txt", "encoding": "utf-8", "start_line": 1}


class TestHashToolCallsAdditional:
    """Additional hash stability tests not covered in the base TestHashToolCalls class."""

    def test_missing_args_key_treated_as_empty(self):
        # Tool call dict without 'args' should not raise
        a = _hash_tool_calls([{"name": "bash"}])
        b = _hash_tool_calls([{"name": "bash", "args": {}}])
        assert a == b

    def test_missing_name_key_treated_as_empty_string(self):
        a = _hash_tool_calls([{"args": {"path": "/tmp"}}])
        b = _hash_tool_calls([{"name": "", "args": {"path": "/tmp"}}])
        assert a == b

    def test_multiple_tools_with_descriptions_stripped(self):
        a = _hash_tool_calls(
            [
                {"name": "read_file", "args": {"description": "first pass", "path": "/a.txt"}},
                {"name": "bash", "args": {"description": "run it", "command": "echo hi"}},
            ]
        )
        b = _hash_tool_calls(
            [
                {"name": "read_file", "args": {"description": "second pass", "path": "/a.txt"}},
                {"name": "bash", "args": {"description": "re-run", "command": "echo hi"}},
            ]
        )
        assert a == b
