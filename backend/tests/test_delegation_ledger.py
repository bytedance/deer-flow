"""Tests for the subagent delegation ledger (parent issue: redundant delegation).

The ledger is a system-maintained record of "subtasks already delegated + their
status", stored in ThreadState (so it survives summarization) and re-injected
into context each model call so the lead stops re-delegating the same work.
"""

from deerflow.agents.thread_state import merge_delegations


def _entry(task_id, status, description="d", subagent_type="general-purpose"):
    return {"task_id": task_id, "description": description, "subagent_type": subagent_type, "status": status}


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
