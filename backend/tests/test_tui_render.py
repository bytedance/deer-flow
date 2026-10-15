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


def test_finalized_assistant_renders_markdown():
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="**bold** text\n\n## A Heading\n\n- item one"))
    out = _render_to_text(render_transcript(state))
    # Markdown is rendered: the syntax markers are consumed, the content remains.
    assert "bold" in out
    assert "**bold**" not in out
    assert "A Heading" in out
    assert "## A Heading" not in out
    assert "item one" in out


def test_actively_streaming_assistant_stays_plain():
    state = initial_state()
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="m1", text="**partial heading ##"))
    out = _render_to_text(render_transcript(state))
    # The streaming row must NOT be markdown-rendered (avoids reflow jumpiness).
    assert "**partial heading ##" in out


def test_prior_message_stays_markdown_when_a_followup_run_starts():
    # Regression: sending a follow-up must NOT revert a finalized markdown answer
    # to raw text. Between RunStarted and the new answer's first delta (and during
    # the client's re-emit of prior messages), the previous answer is the last
    # assistant row — it must still render as Markdown.
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="**bold answer**"))
    state = reduce(state, RunEnded())
    state = reduce(state, UserSubmitted("follow up"))
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="m1", text="**bold answer**"))  # re-emit, no new answer yet

    out = _render_to_text(render_transcript(state))
    assert "**bold answer**" not in out  # still Markdown-rendered
    assert "bold answer" in out


def test_only_the_actively_streaming_message_is_plain():
    state = initial_state()
    state = reduce(state, AssistantDelta(id="m1", text="**done**"))
    state = reduce(state, RunEnded())
    state = reduce(state, RunStarted())
    state = reduce(state, AssistantDelta(id="m2", text="**streaming now"))

    out = _render_to_text(render_transcript(state))
    assert "**streaming now" in out  # active m2 stays plain
    assert "**done**" not in out  # finalized m1 stays Markdown
    assert "done" in out


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
    out = _render_to_text(render_header(model="claude", thread_label="new", cwd="/tmp/proj", skills=3))
    assert "DeerFlow" in out
    assert "claude" in out
    assert "/tmp/proj" in out
