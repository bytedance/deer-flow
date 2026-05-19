"""Tests for RagDecisionEvent."""

from __future__ import annotations

import json

from deerflow.rag.decisions import KB_DECISION_KEY, RagDecisionEvent


def test_decision_event_serializes_to_json() -> None:
    e = RagDecisionEvent(
        outcome="injected",
        reason="found 3 chunks",
        source="middleware",
        query="什么是 deerflow",
        selected_kb_ids=["kb-1", "kb-2"],
        accessible_kb_ids=["kb-1"],
        chunks_returned=3,
        chunks_injected=3,
        score_strategy="absolute",
    )
    payload = e.to_dict()
    json_str = json.dumps(payload, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert parsed["outcome"] == "injected"
    assert parsed["selected_kb_ids"] == ["kb-1", "kb-2"]
    assert parsed["accessible_kb_ids"] == ["kb-1"]
    assert parsed["chunks_injected"] == 3


def test_decision_event_defaults_are_safe_for_minimal_construction() -> None:
    e = RagDecisionEvent(outcome="disabled", reason="rag.enabled=false", source="middleware")
    payload = e.to_dict()
    assert payload["selected_kb_ids"] == []
    assert payload["accessible_kb_ids"] == []
    assert payload["chunks_returned"] == 0
    assert payload["timed_out_kb_ids"] == []
    assert isinstance(payload["timestamp"], str)
    assert payload["timestamp"].endswith("+00:00") or payload["timestamp"].endswith("Z")


def test_decision_key_is_namespaced() -> None:
    """Make sure additional_kwargs key is unlikely to collide."""
    assert KB_DECISION_KEY == "knowledge_base_decision"
