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
    _merge_stream_text,
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


def test_tool_result_without_prior_started_creates_a_completed_row():
    # Defensive: if the tool_started chunks were skipped/missed, a tool result
    # should still surface as a completed card rather than vanish.
    state = initial_state()
    state = reduce(state, ToolResult(tool_call_id="ghost", content="x", is_error=False, tool_name="bash"))
    tools = [r for r in state.rows if r.kind == "tool"]
    assert len(tools) == 1
    assert tools[0].status == "ok"


def test_tool_result_without_call_id_is_ignored():
    state = reduce(initial_state(), ToolResult(tool_call_id="", content="x", is_error=False))
    assert state.rows == ()


# --- streaming robustness: the client can re-emit the same id (values
# re-synthesis) and stream partial tool-call chunks. The reducer must not
# duplicate text or tool cards. ---


def test_assistant_delta_skips_full_resend_of_same_id():
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="Hey there!\nWhat's up?"))
    state = reduce(state, AssistantDelta(id="m1", text="Hey there!\nWhat's up?"))
    assert [r.kind for r in state.rows] == ["assistant"]
    assert state.rows[0].text == "Hey there!\nWhat's up?"


def test_assistant_delta_treats_cumulative_snapshot_as_replace():
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="Hel"))
    state = reduce(state, AssistantDelta(id="m1", text="Hel lo world"))
    assert state.rows[0].text == "Hel lo world"


def test_streaming_id_tracks_active_message_not_reemitted_history():
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="answer one"))
    state = reduce(state, RunEnded())
    assert state.streaming_id is None

    state = reduce(state, RunStarted())
    assert state.streaming_id is None  # new turn: nothing actively streaming yet
    state = reduce(state, AssistantDelta(id="m1", text="answer one"))  # re-emit (no-op)
    assert state.streaming_id is None  # re-emit of history must not mark active
    state = reduce(state, AssistantDelta(id="m2", text="new content"))  # real new content
    assert state.streaming_id == "m2"

    state = reduce(state, RunEnded())
    assert state.streaming_id is None


def test_assistant_resend_of_older_message_updates_in_place_not_duplicated():
    # On a thread with history, the client re-emits every prior message on each
    # new turn. A values snapshot can re-emit an OLDER message's full text AFTER
    # a newer message has already started — the reducer must update the old row
    # by id, not append a verbatim duplicate at the end.
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="First answer."))
    state = reduce(state, UserSubmitted("second question"))
    state = reduce(state, AssistantDelta(id="m2", text="Second answer."))
    state = reduce(state, AssistantDelta(id="m1", text="First answer."))  # re-emit of old m1

    assistants = [r for r in state.rows if r.kind == "assistant"]
    assert [a.text for a in assistants] == ["First answer.", "Second answer."]


def test_tool_started_dedupes_by_call_id():
    state = initial_state()
    state = reduce(state, ToolStarted(tool_call_id="tc1", tool_name="bash", args={"cmd": "l"}))
    state = reduce(state, ToolStarted(tool_call_id="tc1", tool_name="bash", args={"cmd": "ls -la"}))
    tools = [r for r in state.rows if r.kind == "tool"]
    assert len(tools) == 1
    assert "ls -la" in tools[0].detail


def test_tool_started_with_empty_call_id_is_ignored():
    state = initial_state()
    state = reduce(state, ToolStarted(tool_call_id="", tool_name="", args={}))
    assert state.rows == ()


def test_tool_started_fills_name_on_a_later_chunk():
    state = initial_state()
    state = reduce(state, ToolStarted(tool_call_id="tc1", tool_name="", args={}))
    state = reduce(state, ToolStarted(tool_call_id="tc1", tool_name="web_search", args={"query": "x"}))
    tools = [r for r in state.rows if r.kind == "tool"]
    assert len(tools) == 1
    assert tools[0].tool_name == "web_search"
    assert tools[0].title == "Search"


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


# ---------------------------------------------------------------------------
# _merge_stream_text regression: CJK reduplication and repeated-token deltas
# ---------------------------------------------------------------------------


def test_merge_stream_text_cjk_reduplication_not_dropped():
    """Two identical CJK tokens must both accumulate, not collapse to one."""
    assert _merge_stream_text("谢", "谢") == "谢谢"


def test_merge_stream_text_repeated_token_not_dropped():
    """Repeated tokens (e.g. 'go' + 'go') must accumulate."""
    assert _merge_stream_text("go", "go") == "gogo"


def test_merge_stream_text_suffix_matching_tail_not_dropped():
    """A delta equal to the buffer suffix must append, not be dropped."""
    assert _merge_stream_text("hel", "l") == "hell"


def test_merge_stream_text_cumulative_longer_snapshot_still_works():
    """A strictly longer chunk starting with existing is a cumulative re-delivery."""
    assert _merge_stream_text("Hel", "Hel lo world") == "Hel lo world"


def test_merge_stream_text_empty_existing_returns_incoming():
    assert _merge_stream_text("", "Hello") == "Hello"


def test_merge_stream_text_empty_incoming_returns_existing():
    assert _merge_stream_text("Hello", "") == "Hello"


def test_merge_stream_text_newline_split_across_chunks():
    """'\\n\\n' split into two '\\n' deltas must accumulate."""
    assert _merge_stream_text("\n", "\n") == "\n\n"


def test_merge_stream_text_genuine_delta_append():
    """Normal deltas that don't overlap still append."""
    assert _merge_stream_text("Hello ", "world") == "Hello world"


# ---------------------------------------------------------------------------
# Empty/missing-id assistant deltas: some providers/paths never stamp
# per-chunk ids (runtime._as_str coerces a missing id to ""). Matching by id
# like the normal path would fold EVERY id-less turn into whichever id-less
# row happened to exist first, since "" is shared across turns -- unlike a
# genuine id. These pin the fix: an empty id always keys off the CURRENT
# turn (never a stale row from an earlier turn), while still coalescing
# multiple id-less chunks that legitimately arrive within one turn.
# ---------------------------------------------------------------------------


def test_assistant_delta_empty_id_starts_new_row_per_turn_not_merged_with_prior_turn():
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="First turn answer."))
    state = reduce(state, RunEnded())

    state = reduce(state, UserSubmitted("second question"))
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="Second turn answer."))
    state = reduce(state, RunEnded())

    assistants = [r for r in state.rows if r.kind == "assistant"]
    # Pre-fix: both turns share id="" so the second folds into the first via
    # the whole-transcript id scan, losing "First turn answer." entirely.
    assert len(assistants) == 2
    assert assistants[0].text == "First turn answer."
    assert assistants[1].text == "Second turn answer."


def test_assistant_delta_empty_id_coalesces_multiple_chunks_within_same_turn():
    """An id-less provider still streams token by token; chunks within ONE
    turn must accumulate into a single row, not fragment into many."""
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="Hel"))
    state = reduce(state, AssistantDelta(id="", text="lo"))
    state = reduce(state, AssistantDelta(id="", text=" world"))
    state = reduce(state, RunEnded())

    assistants = [r for r in state.rows if r.kind == "assistant"]
    assert len(assistants) == 1
    assert assistants[0].text == "Hello world"


def test_assistant_delta_empty_id_starts_fresh_row_after_interleaved_tool_call():
    """An empty id has no signal to distinguish "same message, paused for a
    tool call" from "a new message that happens to also be id-less" -- unlike
    a genuine id, which naturally changes across a tool round-trip (a new
    AIMessage gets a new id; see
    test_assistant_delta_with_new_id_after_tool_creates_separate_row). Once a
    tool card has been appended, the previous anonymous row is no longer the
    transcript tail, so the next empty-id delta must start a NEW row rather
    than reach backward past the tool card and silently prepend text that
    arrived after the tool ran."""
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="Let me check. "))
    state = reduce(state, ToolStarted(tool_call_id="t1", tool_name="bash", args={}))
    state = reduce(state, ToolResult(tool_call_id="t1", content="ok", is_error=False))
    state = reduce(state, AssistantDelta(id="", text="Done."))
    state = reduce(state, RunEnded())

    kinds = [r.kind for r in state.rows]
    assert kinds == ["assistant", "tool", "assistant"]
    assistants = [r for r in state.rows if r.kind == "assistant"]
    assert [a.text for a in assistants] == ["Let me check. ", "Done."]


def test_assistant_delta_empty_id_coalesces_consecutive_chunks_before_a_tool_call():
    """Multiple id-less chunks with NOTHING interleaved (the realistic
    per-token streaming case) still coalesce into one row up until a tool
    card breaks the streak."""
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="Let me "))
    state = reduce(state, AssistantDelta(id="", text="check. "))
    state = reduce(state, ToolStarted(tool_call_id="t1", tool_name="bash", args={}))
    state = reduce(state, ToolResult(tool_call_id="t1", content="ok", is_error=False))
    state = reduce(state, RunEnded())

    kinds = [r.kind for r in state.rows]
    assert kinds == ["assistant", "tool"]
    assistants = [r for r in state.rows if r.kind == "assistant"]
    assert assistants[0].text == "Let me check. "


def test_assistant_delta_empty_id_does_not_disturb_legitimate_id_sequence():
    """A normal, non-empty id sequence must keep coalescing correctly even
    after the transcript has already seen an earlier, unrelated empty-id
    turn (proves the two code paths -- id-keyed vs. anonymous -- don't
    interfere with each other)."""
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="anonymous turn"))
    state = reduce(state, RunEnded())

    state = reduce(state, UserSubmitted("question"))
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="m1", text="Hel"))
    state = reduce(state, AssistantDelta(id="m1", text="lo"))
    state = reduce(state, RunEnded())

    assistants = [r for r in state.rows if r.kind == "assistant"]
    assert [a.text for a in assistants] == ["anonymous turn", "Hello"]


def test_assistant_delta_empty_id_resend_within_turn_is_noop():
    """Same multi-char no-op re-send semantics apply to the anonymous path."""
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="Hey there!"))
    state = reduce(state, AssistantDelta(id="", text="Hey there!"))
    assistants = [r for r in state.rows if r.kind == "assistant"]
    assert len(assistants) == 1
    assert assistants[0].text == "Hey there!"


def test_clear_rows_resets_anonymous_streaming_index():
    """A stale anonymous-row index must not resurrect after ClearRows."""
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="before clear"))
    state = reduce(state, ClearRows())
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="", text="after clear"))

    assistants = [r for r in state.rows if r.kind == "assistant"]
    assert len(assistants) == 1
    assert assistants[0].text == "after clear"
