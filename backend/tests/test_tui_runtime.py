"""Tests for the runtime bridge: StreamEvent -> reducer actions.

The translation layer is pure and is exercised here against real
``StreamEvent`` objects plus a fake client, with no Textual involved.
"""

from deerflow.client import StreamEvent
from deerflow.tui.runtime import stream_actions, translate
from deerflow.tui.view_state import (
    AssistantDelta,
    AssistantError,
    RunEnded,
    RunStarted,
    ThreadTitle,
    ToolResult,
    ToolStarted,
    initial_state,
    reduce,
)


def test_translate_ai_text_delta():
    event = StreamEvent(type="messages-tuple", data={"type": "ai", "content": "Hello", "id": "m1"})
    actions = translate(event)
    assert actions == [AssistantDelta(id="m1", text="Hello")]


def test_translate_ai_tool_call_emits_tool_started_not_empty_delta():
    event = StreamEvent(
        type="messages-tuple",
        data={
            "type": "ai",
            "content": "",
            "id": "m1",
            "tool_calls": [{"name": "read_file", "args": {"path": "a.py"}, "id": "t1"}],
        },
    )
    actions = translate(event)
    assert actions == [ToolStarted(tool_call_id="t1", tool_name="read_file", args={"path": "a.py"})]


def test_translate_ai_content_blocks_list_extracts_text():
    event = StreamEvent(
        type="messages-tuple",
        data={"type": "ai", "content": [{"type": "text", "text": "abc"}, {"type": "text", "text": "def"}], "id": "m9"},
    )
    actions = translate(event)
    assert actions == [AssistantDelta(id="m9", text="abcdef")]


def test_translate_tool_call_with_none_id_yields_empty_id():
    # Some providers' first tool-call chunk has id=None; it must coerce to "" (not
    # "None"), so the empty-id guard in the reducer drops the noise chunk.
    event = StreamEvent(
        type="messages-tuple",
        data={"type": "ai", "content": "", "id": "m1", "tool_calls": [{"id": None, "name": None, "args": {}}]},
    )
    assert translate(event) == [ToolStarted(tool_call_id="", tool_name="", args={})]


def test_translate_tool_result_with_none_id_yields_empty_id():
    event = StreamEvent(type="messages-tuple", data={"type": "tool", "content": "x", "name": None, "tool_call_id": None})
    assert translate(event) == [ToolResult(tool_call_id="", content="x", is_error=False, tool_name="")]


def test_translate_tool_result_with_error_status():
    event = StreamEvent(
        type="messages-tuple",
        data={"type": "tool", "content": "boom", "name": "bash", "tool_call_id": "t1", "status": "error"},
    )
    actions = translate(event)
    assert actions == [ToolResult(tool_call_id="t1", content="boom", is_error=True, tool_name="bash")]


def test_translate_end_event_carries_usage():
    usage = {"input_tokens": 3, "output_tokens": 7, "total_tokens": 10}
    actions = translate(StreamEvent(type="end", data={"usage": usage}))
    assert actions == [RunEnded(usage=usage)]


def test_translate_values_surfaces_title_only():
    assert translate(StreamEvent(type="values", data={"title": "My Thread", "messages": []})) == [ThreadTitle(title="My Thread")]
    assert translate(StreamEvent(type="values", data={"title": None, "messages": []})) == []
    assert translate(StreamEvent(type="custom", data={"anything": 1})) == []


class _FakeClient:
    def __init__(self, events):
        self._events = events
        self.calls = []

    def stream(self, message, *, thread_id=None, **kwargs):
        self.calls.append((message, thread_id))
        yield from self._events


def test_stream_actions_brackets_with_run_started_and_ended():
    client = _FakeClient(
        [
            StreamEvent(type="messages-tuple", data={"type": "ai", "content": "Hi", "id": "m1"}),
            StreamEvent(type="end", data={"usage": {"total_tokens": 5}}),
        ]
    )
    actions = list(stream_actions(client, "hello", thread_id="th-1"))
    assert isinstance(actions[0], RunStarted)
    assert isinstance(actions[-1], RunEnded)
    assert client.calls == [("hello", "th-1")]


def test_stream_actions_reduces_to_expected_transcript():
    client = _FakeClient(
        [
            StreamEvent(type="messages-tuple", data={"type": "ai", "content": "Let me look. ", "id": "m1"}),
            StreamEvent(
                type="messages-tuple",
                data={"type": "ai", "content": "", "id": "m1", "tool_calls": [{"name": "read_file", "args": {"path": "a.py"}, "id": "t1"}]},
            ),
            StreamEvent(type="messages-tuple", data={"type": "tool", "content": "file body", "name": "read_file", "tool_call_id": "t1"}),
            StreamEvent(type="messages-tuple", data={"type": "ai", "content": "Done.", "id": "m2"}),
            StreamEvent(type="end", data={"usage": {"total_tokens": 9}}),
        ]
    )
    state = initial_state()
    for action in stream_actions(client, "go"):
        state = reduce(state, action)

    kinds = [r.kind for r in state.rows]
    assert kinds == ["assistant", "tool", "assistant"]
    assert state.rows[0].text == "Let me look. "
    assert state.rows[1].status == "ok"
    assert state.rows[2].text == "Done."
    assert state.streaming is False
    assert state.usage == {"total_tokens": 9}


class _BoomClient:
    def stream(self, message, *, thread_id=None, **kwargs):
        yield StreamEvent(type="messages-tuple", data={"type": "ai", "content": "partial", "id": "m1"})
        raise RuntimeError("model down")


def test_stream_actions_surfaces_exception_as_error_then_ends():
    actions = list(stream_actions(_BoomClient(), "go"))
    assert any(isinstance(a, AssistantError) and "model down" in a.text for a in actions)
    assert isinstance(actions[-1], RunEnded)
