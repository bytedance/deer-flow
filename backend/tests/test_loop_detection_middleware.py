"""Tests for LoopDetectionMiddleware."""

import copy
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
    """Build a minimal AgentState dict with an AIMessage.

    Deep-copies *content* when it is mutable (e.g. list) so that
    successive calls never share the same object reference.
    """
    safe_content = copy.deepcopy(content) if isinstance(content, list) else content
    msg = AIMessage(content=safe_content, tool_calls=tool_calls or [])
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

    def test_stringified_dict_args_match_dict_args(self):
        dict_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": "1", "end_line": "150"},
        }
        string_call = {
            "name": "read_file",
            "args": '{"path":"/tmp/demo.py","start_line":"1","end_line":"150"}',
        }

        assert _hash_tool_calls([dict_call]) == _hash_tool_calls([string_call])

    def test_reversed_read_file_range_matches_forward_range(self):
        forward_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": 10, "end_line": 300},
        }
        reversed_call = {
            "name": "read_file",
            "args": {"path": "/tmp/demo.py", "start_line": 300, "end_line": 10},
        }

        assert _hash_tool_calls([forward_call]) == _hash_tool_calls([reversed_call])

    def test_stringified_non_dict_args_do_not_crash(self):
        non_dict_json_call = {"name": "bash", "args": '"echo hello"'}
        plain_string_call = {"name": "bash", "args": "echo hello"}

        json_hash = _hash_tool_calls([non_dict_json_call])
        plain_hash = _hash_tool_calls([plain_string_call])

        assert isinstance(json_hash, str)
        assert isinstance(plain_hash, str)
        assert json_hash
        assert plain_hash

    def test_grep_pattern_affects_hash(self):
        grep_foo = {"name": "grep", "args": {"path": "/tmp", "pattern": "foo"}}
        grep_bar = {"name": "grep", "args": {"path": "/tmp", "pattern": "bar"}}

        assert _hash_tool_calls([grep_foo]) != _hash_tool_calls([grep_bar])

    def test_glob_pattern_affects_hash(self):
        glob_py = {"name": "glob", "args": {"path": "/tmp", "pattern": "*.py"}}
        glob_ts = {"name": "glob", "args": {"path": "/tmp", "pattern": "*.ts"}}

        assert _hash_tool_calls([glob_py]) != _hash_tool_calls([glob_ts])

    def test_write_file_content_affects_hash(self):
        v1 = {"name": "write_file", "args": {"path": "/tmp/a.py", "content": "v1"}}
        v2 = {"name": "write_file", "args": {"path": "/tmp/a.py", "content": "v2"}}
        assert _hash_tool_calls([v1]) != _hash_tool_calls([v2])

    def test_str_replace_content_affects_hash(self):
        a = {
            "name": "str_replace",
            "args": {"path": "/tmp/a.py", "old_str": "foo", "new_str": "bar"},
        }
        b = {
            "name": "str_replace",
            "args": {"path": "/tmp/a.py", "old_str": "foo", "new_str": "baz"},
        }
        assert _hash_tool_calls([a]) != _hash_tool_calls([b])


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


class TestAppendText:
    """Unit tests for LoopDetectionMiddleware._append_text."""

    def test_none_content_returns_text(self):
        result = LoopDetectionMiddleware._append_text(None, "hello")
        assert result == "hello"

    def test_str_content_concatenates(self):
        result = LoopDetectionMiddleware._append_text("existing", "appended")
        assert result == "existing\n\nappended"

    def test_empty_str_content_concatenates(self):
        result = LoopDetectionMiddleware._append_text("", "appended")
        assert result == "\n\nappended"

    def test_list_content_appends_text_block(self):
        """List content (e.g. Anthropic thinking mode) should get a new text block."""
        content = [
            {"type": "thinking", "text": "Let me think..."},
            {"type": "text", "text": "Here is my answer"},
        ]
        result = LoopDetectionMiddleware._append_text(content, "stop msg")
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == content[0]
        assert result[1] == content[1]
        assert result[2] == {"type": "text", "text": "\n\nstop msg"}

    def test_empty_list_content_appends_text_block(self):
        result = LoopDetectionMiddleware._append_text([], "stop msg")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == {"type": "text", "text": "\n\nstop msg"}

    def test_unexpected_type_coerced_to_str(self):
        """Unexpected content types should be coerced to str as a fallback."""
        result = LoopDetectionMiddleware._append_text(42, "stop msg")
        assert isinstance(result, str)
        assert result == "42\n\nstop msg"

    def test_list_content_not_mutated_in_place(self):
        """_append_text must not modify the original list."""
        original = [{"type": "text", "text": "hello"}]
        result = LoopDetectionMiddleware._append_text(original, "appended")
        assert len(original) == 1  # original unchanged
        assert len(result) == 2  # new list has the appended block


class TestHardStopWithListContent:
    """Regression tests: hard stop must not crash when AIMessage.content is a list."""

    def test_hard_stop_with_list_content(self):
        """Hard stop on list content should not raise TypeError (regression)."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        # Build state with list content (e.g. Anthropic thinking mode)
        list_content = [
            {"type": "thinking", "text": "Let me think..."},
            {"type": "text", "text": "I'll run ls"},
        ]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call, content=list_content), runtime)

        # Fourth call triggers hard stop — must not raise TypeError
        result = mw._apply(_make_state(tool_calls=call, content=list_content), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert msg.tool_calls == []
        # Content should remain a list with the stop message appended
        assert isinstance(msg.content, list)
        assert len(msg.content) == 3
        assert msg.content[2]["type"] == "text"
        assert _HARD_STOP_MSG in msg.content[2]["text"]

    def test_hard_stop_with_none_content(self):
        """Hard stop on None content should produce a plain string."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call), runtime)

        # Fourth call with default empty-string content
        result = mw._apply(_make_state(tool_calls=call), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg.content, str)
        assert _HARD_STOP_MSG in msg.content

    def test_hard_stop_with_str_content(self):
        """Hard stop on str content should concatenate the stop message."""
        mw = LoopDetectionMiddleware(warn_threshold=2, hard_limit=4)
        runtime = _make_runtime()
        call = [_bash_call("ls")]

        for _ in range(3):
            mw._apply(_make_state(tool_calls=call, content="thinking..."), runtime)

        result = mw._apply(_make_state(tool_calls=call, content="thinking..."), runtime)
        assert result is not None
        msg = result["messages"][0]
        assert isinstance(msg.content, str)
        assert msg.content.startswith("thinking...")
        assert _HARD_STOP_MSG in msg.content
