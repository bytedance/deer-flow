"""Smoke tests for the pure Rich renderers — they must render without error
and include the expected text."""

from rich.console import Console

from deerflow.tui.render import render_header, render_status, render_transcript
from deerflow.tui.view_state import (
    AssistantDelta,
    RunEnded,
    RunStarted,
    SystemMessage,
    ToolResult,
    ToolStarted,
    UserSubmitted,
    initial_state,
    reduce,
)


def _render_to_text(renderable) -> str:
    console = Console(width=100, no_color=True)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_render_empty_transcript_shows_hint():
    out = _render_to_text(render_transcript(initial_state()))
    assert "Type a message" in out


def test_render_transcript_includes_all_row_kinds():
    state = initial_state()
    state = reduce(state, UserSubmitted("hello there"))
    state = reduce(state, AssistantDelta(id="m1", text="hi back"))
    state = reduce(state, ToolStarted(tool_call_id="t1", tool_name="read_file", args={"path": "a.py"}))
    state = reduce(state, ToolResult(tool_call_id="t1", content="file body", is_error=False))
    state = reduce(state, SystemMessage("a note"))

    out = _render_to_text(render_transcript(state))
    assert "hello there" in out
    assert "hi back" in out
    assert "Read" in out and "a.py" in out
    assert "file body" in out
    assert "a note" in out


def test_render_status_ready_and_working():
    ready = _render_to_text(render_status(initial_state(), model="gpt", thread_label="new"))
    assert "ready" in ready

    state = reduce(initial_state(), RunStarted())
    working = _render_to_text(render_status(state, model="gpt", thread_label="new", spinner="*"))
    assert "working" in working


def test_render_status_shows_token_usage():
    state = reduce(initial_state(), RunEnded(usage={"total_tokens": 42}))
    out = _render_to_text(render_status(state, model="gpt", thread_label="t1"))
    assert "42 tok" in out


def test_render_header_includes_model_and_cwd():
    out = _render_to_text(render_header(model="claude", thread_label="new", cwd="/tmp/proj", skills=3, tools=9))
    assert "DeerFlow" in out
    assert "claude" in out
    assert "/tmp/proj" in out
