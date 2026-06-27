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
