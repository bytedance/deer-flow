"""Tests for the subagent delegation ledger (parent issue: redundant delegation).

The ledger is a system-maintained record of "subtasks already delegated + their
status", stored in ThreadState (so it survives summarization) and re-injected
into context each model call so the lead stops re-delegating the same work.
"""

from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.delegation_ledger_middleware import (
    extract_delegations,
    format_delegation_block,
)
from deerflow.agents.thread_state import merge_delegations


def _entry(task_id, status, description="d", subagent_type="general-purpose"):
    return {"task_id": task_id, "description": description, "subagent_type": subagent_type, "status": status}


def _task_call(task_id, description, subagent_type="general-purpose"):
    return {"name": "task", "args": {"description": description, "subagent_type": subagent_type}, "id": task_id, "type": "tool_call"}


def test_merge_upserts_by_task_id_preserving_order():
    existing = [_entry("a", "in_progress"), _entry("b", "in_progress")]
    new = [_entry("b", "completed"), _entry("c", "in_progress")]

    merged = merge_delegations(existing, new)

    assert [e["task_id"] for e in merged] == ["a", "b", "c"]
    assert next(e for e in merged if e["task_id"] == "b")["status"] == "completed"


def test_merge_does_not_downgrade_terminal_status():
    existing = [_entry("a", "completed")]
    new = [_entry("a", "in_progress")]

    merged = merge_delegations(existing, new)

    assert merged[0]["status"] == "completed"


def test_merge_handles_none_inputs():
    assert merge_delegations(None, None) == []
    assert merge_delegations(None, [_entry("a", "in_progress")])[0]["task_id"] == "a"
    assert merge_delegations([_entry("a", "in_progress")], None)[0]["task_id"] == "a"


def test_extract_records_dispatch_as_in_progress():
    msgs = [AIMessage(content="", tool_calls=[_task_call("call_1", "Research A")])]

    entries = extract_delegations(msgs)

    assert entries == [{"task_id": "call_1", "description": "Research A", "subagent_type": "general-purpose", "status": "in_progress"}]


def test_extract_updates_status_from_tool_message_kwarg():
    msgs = [
        AIMessage(content="", tool_calls=[_task_call("call_1", "Research A")]),
        ToolMessage(content="Task Succeeded. Result: ok", tool_call_id="call_1", additional_kwargs={"subagent_status": "completed"}),
    ]

    entries = extract_delegations(msgs)

    assert entries[0]["status"] == "completed"


def test_extract_falls_back_to_parsing_content_when_kwarg_absent():
    msgs = [
        AIMessage(content="", tool_calls=[_task_call("call_1", "Research A")]),
        ToolMessage(content="Task failed. Error: boom", tool_call_id="call_1"),
    ]

    entries = extract_delegations(msgs)

    assert entries[0]["status"] == "failed"


def test_extract_ignores_non_task_tool_calls():
    msgs = [AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "x", "type": "tool_call"}])]

    assert extract_delegations(msgs) == []


def test_extract_preserves_dispatch_order_across_batches():
    msgs = [
        AIMessage(content="", tool_calls=[_task_call("call_1", "A"), _task_call("call_2", "B")]),
        AIMessage(content="", tool_calls=[_task_call("call_3", "C")]),
    ]

    assert [e["task_id"] for e in extract_delegations(msgs)] == ["call_1", "call_2", "call_3"]


def test_format_block_lists_entries_and_returns_none_when_empty():
    assert format_delegation_block([]) is None

    block = format_delegation_block(
        [
            {"task_id": "call_1", "description": "Research A", "subagent_type": "general-purpose", "status": "completed"},
            {"task_id": "call_2", "description": "Research B", "subagent_type": "general-purpose", "status": "in_progress"},
        ]
    )

    assert "<system-reminder>" in block
    assert "Research A" in block and "completed" in block
    assert "Research B" in block and "in_progress" in block
    assert "re-delegate" in block.lower() or "already delegated" in block.lower()
