"""Tests for the pure TUI view-state reducer.

The reducer is the testable heart of the TUI: a pure function mapping
(state, action) -> state, with no Textual / rendering dependency.
"""

from deerflow.tui.view_state import (
    AssistantDelta,
    AssistantError,
    ClearRows,
    RunEnded,
    RunStarted,
    SystemMessage,
    ToolResult,
    ToolStarted,
    UserSubmitted,
    initial_state,
    reduce,
)


def test_user_submitted_appends_user_row():
    state = reduce(initial_state(), UserSubmitted("hello world"))
    assert len(state.rows) == 1
    row = state.rows[0]
    assert row.kind == "user"
    assert row.text == "hello world"


def test_run_started_and_ended_toggle_streaming_and_store_usage():
    state = reduce(initial_state(), RunStarted())
    assert state.streaming is True

    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    state = reduce(state, RunEnded(usage=usage))
    assert state.streaming is False
    assert state.usage == usage


def test_assistant_delta_creates_then_extends_same_id_row():
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="Hel"))
    state = reduce(state, AssistantDelta(id="m1", text="lo"))
    assert len(state.rows) == 1
    assert state.rows[0].kind == "assistant"
    assert state.rows[0].text == "Hello"
    assert state.rows[0].id == "m1"


def test_assistant_delta_with_new_id_after_tool_creates_separate_row():
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="thinking"))
    state = reduce(state, ToolStarted(tool_call_id="t1", tool_name="read_file", args={"path": "a.py"}))
    state = reduce(state, ToolResult(tool_call_id="t1", content="ok", is_error=False))
    state = reduce(state, AssistantDelta(id="m2", text="done"))

    kinds = [r.kind for r in state.rows]
    assert kinds == ["assistant", "tool", "assistant"]
    assert state.rows[0].text == "thinking"
    assert state.rows[2].text == "done"


def test_tool_started_appends_running_row_and_result_marks_ok():
    state = initial_state()
    state = reduce(state, ToolStarted(tool_call_id="t1", tool_name="read_file", args={"path": "x.py"}))
    assert state.rows[0].kind == "tool"
    assert state.rows[0].status == "running"
    assert state.rows[0].tool_name == "read_file"

    state = reduce(state, ToolResult(tool_call_id="t1", content="file body", is_error=False))
    assert state.rows[0].status == "ok"
    assert "file body" in state.rows[0].result


def test_tool_result_with_error_marks_error_status():
    state = initial_state()
    state = reduce(state, ToolStarted(tool_call_id="t1", tool_name="bash", args={}))
    state = reduce(state, ToolResult(tool_call_id="t1", content="boom", is_error=True))
    assert state.rows[0].status == "error"


def test_tool_result_for_unknown_call_id_is_ignored():
    state = initial_state()
    state = reduce(state, ToolResult(tool_call_id="ghost", content="x", is_error=False))
    assert state.rows == ()


def test_assistant_error_appends_error_row():
    state = reduce(initial_state(), AssistantError("model exploded"))
    assert state.rows[0].kind == "assistant"
    assert state.rows[0].error is True
    assert state.rows[0].text == "model exploded"


def test_system_message_appends_with_tone():
    state = reduce(initial_state(), SystemMessage("heads up", tone="error"))
    assert state.rows[0].kind == "system"
    assert state.rows[0].tone == "error"


def test_clear_rows_empties_transcript():
    state = initial_state()
    state = reduce(state, UserSubmitted("hi"))
    state = reduce(state, ClearRows())
    assert state.rows == ()


def test_reduce_is_pure_does_not_mutate_input_state():
    state = reduce(initial_state(), UserSubmitted("first"))
    before_len = len(state.rows)
    # Reducing again must not mutate the previous state object.
    _ = reduce(state, UserSubmitted("second"))
    assert len(state.rows) == before_len
