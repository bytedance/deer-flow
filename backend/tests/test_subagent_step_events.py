"""Tests for the pure subagent step-payload builder (issue #3779).

``build_subagent_step`` turns a captured subagent message dict (the
``model_dump()`` of an AIMessage or ToolMessage) into the compact,
serializable step payload that is both streamed (``task_running``) and
persisted (``subagent.step`` run events). It is a pure function so it can
be unit-tested without the executor/graph.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.subagents.step_events import (
    SUBAGENT_EVENT_CATEGORY,
    SUBAGENT_STEP_MAX_CHARS,
    build_subagent_step,
    capture_new_step_messages,
    capture_step_message,
    subagent_run_event,
    truncate_step_text,
)


def test_ai_message_becomes_ai_step_with_tool_calls():
    message = {
        "type": "ai",
        "id": "ai-1",
        "content": "Let me search the web.",
        "tool_calls": [
            {"name": "web_search", "args": {"query": "deerflow"}, "id": "call_1", "type": "tool_call"},
        ],
    }

    step = build_subagent_step(message, task_id="call_task", message_index=1)

    assert step["task_id"] == "call_task"
    assert step["message_index"] == 1
    assert step["kind"] == "ai"
    assert step["text"] == "Let me search the web."
    assert step["truncated"] is False
    assert step["tool_calls"] == [{"name": "web_search", "args": {"query": "deerflow"}}]
    assert "tool_name" not in step


def test_tool_message_becomes_tool_step_with_output():
    message = {
        "type": "tool",
        "id": "tool-1",
        "name": "web_search",
        "tool_call_id": "call_1",
        "content": "Result: DeerFlow is a LangGraph super-agent.",
    }

    step = build_subagent_step(message, task_id="call_task", message_index=2)

    assert step["kind"] == "tool"
    assert step["tool_name"] == "web_search"
    assert step["text"] == "Result: DeerFlow is a LangGraph super-agent."
    assert step["truncated"] is False
    assert "tool_calls" not in step


def test_long_tool_output_is_truncated_and_flagged():
    big = "x" * (SUBAGENT_STEP_MAX_CHARS + 500)
    message = {"type": "tool", "name": "read_file", "content": big}

    step = build_subagent_step(message, task_id="t", message_index=3, max_chars=SUBAGENT_STEP_MAX_CHARS)

    assert step["truncated"] is True
    assert len(step["text"]) == SUBAGENT_STEP_MAX_CHARS


def test_list_content_blocks_are_flattened_to_text():
    message = {
        "type": "ai",
        "content": [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ],
        "tool_calls": [],
    }

    step = build_subagent_step(message, task_id="t", message_index=1)

    assert "first" in step["text"]
    assert "second" in step["text"]
    assert step["tool_calls"] == []


def test_ai_text_is_also_truncated():
    big = "y" * (SUBAGENT_STEP_MAX_CHARS + 10)
    message = {"type": "ai", "content": big, "tool_calls": []}

    step = build_subagent_step(message, task_id="t", message_index=1, max_chars=SUBAGENT_STEP_MAX_CHARS)

    assert step["truncated"] is True
    assert len(step["text"]) == SUBAGENT_STEP_MAX_CHARS


def test_truncate_step_text_helper():
    assert truncate_step_text("abc", 10) == ("abc", False)
    assert truncate_step_text("abcdef", 3) == ("abc", True)


def test_capture_ai_message_appends_dict():
    captured: list[dict] = []
    seen: set[str] = set()

    appended = capture_step_message(AIMessage(content="hi", id="ai-1"), captured, seen)

    assert appended is True
    assert len(captured) == 1
    assert captured[0]["type"] == "ai"


def test_capture_tool_message_is_now_captured():
    # Regression for #3779: tool outputs (ToolMessage) used to be dropped,
    # so "what each step produced" never reached the UI/store.
    captured: list[dict] = []
    seen: set[str] = set()

    appended = capture_step_message(
        ToolMessage(content="search results", tool_call_id="call_1", name="web_search", id="tool-1"),
        captured,
        seen,
    )

    assert appended is True
    assert captured[0]["type"] == "tool"
    assert captured[0]["name"] == "web_search"


def test_capture_dedupes_by_id():
    captured: list[dict] = []
    seen: set[str] = set()
    msg = AIMessage(content="hi", id="ai-1")

    assert capture_step_message(msg, captured, seen) is True
    assert capture_step_message(msg, captured, seen) is False
    assert len(captured) == 1


def test_capture_ignores_human_message():
    captured: list[dict] = []
    seen: set[str] = set()

    appended = capture_step_message(HumanMessage(content="user input", id="h-1"), captured, seen)

    assert appended is False
    assert captured == []


def test_none_content_flattens_to_empty_string():
    # A tool-call-only AI turn can carry content=None; it must render as "" (not
    # the literal "None"), matching the shared message_content_to_text guard.
    message = {"type": "ai", "content": None, "tool_calls": []}

    step = build_subagent_step(message, task_id="t", message_index=1)

    assert step["text"] == ""


def test_ai_step_caps_large_tool_call_args():
    # Regression for #3779: build_subagent_step capped `text` but copied
    # `tool_calls[].args` verbatim, so a write_file/bash call carrying a big
    # payload produced an unbounded persisted row. Args must now be capped too.
    big_payload = "F" * (SUBAGENT_STEP_MAX_CHARS + 4096)
    message = {
        "type": "ai",
        "content": "writing the file",
        "tool_calls": [
            {"name": "write_file", "args": {"path": "/mnt/out.txt", "content": big_payload}},
        ],
    }

    step = build_subagent_step(message, task_id="t", message_index=1, max_chars=SUBAGENT_STEP_MAX_CHARS)

    call = step["tool_calls"][0]
    assert call["name"] == "write_file"
    assert call["args_truncated"] is True
    # The serialized args are bounded by the same cap the text field uses.
    assert isinstance(call["args"], str)
    assert len(call["args"]) == SUBAGENT_STEP_MAX_CHARS


def test_ai_step_keeps_small_tool_call_args_structured():
    message = {
        "type": "ai",
        "content": "searching",
        "tool_calls": [{"name": "web_search", "args": {"query": "deerflow"}}],
    }

    step = build_subagent_step(message, task_id="t", message_index=1)

    call = step["tool_calls"][0]
    assert call["args"] == {"query": "deerflow"}
    assert "args_truncated" not in call


def test_capture_new_step_messages_captures_full_multi_tool_tail():
    # Regression for #3779: a single super-step can append several ToolMessages
    # (one per tool call in a multi-tool turn). Capturing only messages[-1]
    # dropped all but the last; the tail walk must capture every new message.
    captured: list[dict] = []
    seen: set[str] = set()

    # Chunk 1: human + one AIMessage requesting 3 tool calls.
    chunk1 = [
        HumanMessage(content="do work", id="h-1"),
        AIMessage(content="running tools", id="ai-1"),
    ]
    processed = capture_new_step_messages(chunk1, captured, seen, 0)
    assert processed == 2
    assert [c["id"] for c in captured] == ["ai-1"]

    # Chunk 2: values-mode re-yields the whole history plus 3 new ToolMessages
    # appended in one super-step.
    chunk2 = chunk1 + [
        ToolMessage(content="r1", tool_call_id="c1", name="web_search", id="tool-1"),
        ToolMessage(content="r2", tool_call_id="c2", name="read_file", id="tool-2"),
        ToolMessage(content="r3", tool_call_id="c3", name="web_search", id="tool-3"),
    ]
    processed = capture_new_step_messages(chunk2, captured, seen, processed)

    assert processed == 5
    # All three tool outputs survive, not just the last.
    assert [c["id"] for c in captured] == ["ai-1", "tool-1", "tool-2", "tool-3"]


def test_capture_new_step_messages_is_noop_on_values_reyield():
    # stream_mode="values" re-yields the same trailing message with unchanged
    # length; re-processing must not duplicate captures.
    captured: list[dict] = []
    seen: set[str] = set()
    messages = [AIMessage(content="hi", id="ai-1")]

    processed = capture_new_step_messages(messages, captured, seen, 0)
    assert processed == 1
    # Same list handed back (no growth) — cursor already at the end.
    processed = capture_new_step_messages(messages, captured, seen, processed)
    assert processed == 1
    assert len(captured) == 1


def test_run_event_for_task_started():
    record = subagent_run_event({"type": "task_started", "task_id": "call_1", "description": "research X"})

    assert record["event_type"] == "subagent.start"
    assert record["category"] == SUBAGENT_EVENT_CATEGORY
    assert record["metadata"]["task_id"] == "call_1"
    assert record["content"]["description"] == "research X"


def test_run_event_for_task_running_carries_step_payload():
    chunk = {
        "type": "task_running",
        "task_id": "call_1",
        "message": {"type": "tool", "name": "web_search", "content": "results"},
        "message_index": 2,
    }

    record = subagent_run_event(chunk)

    assert record["event_type"] == "subagent.step"
    assert record["category"] == SUBAGENT_EVENT_CATEGORY
    assert record["metadata"] == {"task_id": "call_1", "message_index": 2}
    assert record["content"] == build_subagent_step(chunk["message"], task_id="call_1", message_index=2)


def test_run_event_for_terminal_status():
    record = subagent_run_event({"type": "task_completed", "task_id": "call_1", "result": "done"})

    assert record["event_type"] == "subagent.end"
    assert record["content"]["status"] == "completed"
    assert record["content"]["result"] == "done"

    failed = subagent_run_event({"type": "task_failed", "task_id": "call_1", "error": "boom"})
    assert failed["content"]["status"] == "failed"
    assert failed["content"]["error"] == "boom"


def test_run_event_terminal_result_is_truncated():
    big = "z" * (SUBAGENT_STEP_MAX_CHARS + 100)
    record = subagent_run_event({"type": "task_completed", "task_id": "c1", "result": big})

    assert len(record["content"]["result"]) == SUBAGENT_STEP_MAX_CHARS
    assert record["content"]["result_truncated"] is True


def test_run_event_ignores_non_task_chunks():
    assert subagent_run_event({"type": "something_else"}) is None
    assert subagent_run_event({"no_type": True}) is None
    assert subagent_run_event("not-a-dict") is None
