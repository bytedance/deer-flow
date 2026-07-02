"""Tests for deterministic workflow binding resolution."""

from deerflow.runtime.workflows import WorkflowBindingCandidate, WorkflowBindingStatus, resolve_workflow_binding


def test_explicit_refs_resolve_without_candidates():
    decision = resolve_workflow_binding(
        explicit_thread_id="thread-1",
        explicit_checkpoint_ns="",
        explicit_checkpoint_id="ckpt-1",
    )

    assert decision.status == WorkflowBindingStatus.resolved
    assert decision.reason == "explicit_reference"
    assert decision.thread_id == "thread-1"
    assert decision.checkpoint_ns == ""
    assert decision.checkpoint_id == "ckpt-1"
    assert decision.to_metadata()["status"] == "resolved"


def test_single_candidate_resolves():
    decision = resolve_workflow_binding(
        candidate_bindings=[
            {
                "thread_id": "thread-1",
                "run_id": "run-1",
                "reason": "channel_thread_mapping",
            }
        ]
    )

    assert decision.status == WorkflowBindingStatus.resolved
    assert decision.reason == "channel_thread_mapping"
    assert decision.thread_id == "thread-1"
    assert decision.run_id == "run-1"


def test_duplicate_candidates_dedupe_to_resolved():
    candidate = WorkflowBindingCandidate(thread_id="thread-1", reason="active_thread")
    decision = resolve_workflow_binding(candidate_bindings=[candidate, candidate])

    assert decision.status == WorkflowBindingStatus.resolved
    assert len(decision.candidates) == 1


def test_multiple_candidates_are_ambiguous():
    decision = resolve_workflow_binding(
        candidate_bindings=[
            {"thread_id": "thread-1", "reason": "reply_thread"},
            {"thread_id": "thread-2", "reason": "active_run"},
        ]
    )

    assert decision.status == WorkflowBindingStatus.ambiguous
    assert decision.reason == "multiple_candidates"
    assert decision.thread_id is None
    assert len(decision.candidates) == 2


def test_no_candidates_unresolved():
    decision = resolve_workflow_binding()

    assert decision.status == WorkflowBindingStatus.unresolved
    assert decision.reason == "no_candidate"
