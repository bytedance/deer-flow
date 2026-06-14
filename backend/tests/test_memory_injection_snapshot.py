"""Tests for the memory-injection provenance snapshot (context observability M1).

``build_injected_memory_snapshot`` produces a minimal, always-on record of what
memory injection placed into the model context — which facts, how big, which
sections, and a content hash. It is computed from the same selection pass as
``format_memory_for_injection``, so the two can never disagree about what was
injected. These tests lock that agreement and the snapshot's shape.
"""

from __future__ import annotations

import hashlib

from deerflow.agents.memory.prompt import (
    InjectedMemorySnapshot,
    build_injected_memory_snapshot,
    format_memory_for_injection,
)


def _sample_memory() -> dict:
    return {
        "user": {
            "workContext": {"summary": "Maintainer on DeerFlow"},
        },
        "history": {
            "recentMonths": {"summary": "Worked on context observability"},
        },
        "facts": [
            {"id": "f-high", "content": "Prefers deterministic fixes", "category": "preference", "confidence": 0.95},
            {"id": "f-mid", "content": "Reviews agent-internals PRs by hand", "category": "behavior", "confidence": 0.8},
            {"id": "f-low", "content": "Uses make targets for checks", "category": "knowledge", "confidence": 0.72},
        ],
    }


def test_snapshot_is_none_when_no_memory():
    assert build_injected_memory_snapshot({}) is None
    assert build_injected_memory_snapshot({"facts": []}) is None


def test_snapshot_captures_selected_facts_and_sections():
    snap = build_injected_memory_snapshot(_sample_memory(), max_tokens=2000)
    assert isinstance(snap, InjectedMemorySnapshot)

    # All three facts fit a generous budget; ordered by confidence (desc).
    assert snap.fact_ids == ("f-high", "f-mid", "f-low")
    assert snap.fact_count == 3
    assert snap.total_facts == 3
    assert set(snap.sections) == {"user_context", "history", "facts"}
    assert snap.max_tokens == 2000
    assert snap.token_count > 0
    assert snap.content_hash.startswith("sha256:")


def test_snapshot_hash_matches_injected_text():
    """Load-bearing invariant: the snapshot's content hash is the hash of the
    exact text ``format_memory_for_injection`` produces for the same input.

    This is what makes the snapshot a faithful record of *what was injected*
    rather than a parallel re-derivation that can drift.
    """
    data = _sample_memory()
    for use_tiktoken in (True, False):
        text = format_memory_for_injection(data, max_tokens=2000, use_tiktoken=use_tiktoken)
        snap = build_injected_memory_snapshot(data, max_tokens=2000, use_tiktoken=use_tiktoken)
        assert snap is not None
        expected = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert snap.content_hash == expected


def test_snapshot_reflects_budget_limited_selection():
    """A tight budget drops low-confidence facts; the snapshot records that
    fewer facts were selected than were available (``fact_count`` < ``total``)."""
    data = _sample_memory()
    snap = build_injected_memory_snapshot(data, max_tokens=60, use_tiktoken=False)
    assert snap is not None
    assert snap.total_facts == 3
    assert snap.fact_count < snap.total_facts
    # The highest-confidence fact is the one that survives the budget.
    assert snap.fact_ids[0] == "f-high"
    # Selected ids are a prefix of the confidence-ranked order.
    assert list(snap.fact_ids) == ["f-high", "f-mid", "f-low"][: snap.fact_count]


def test_snapshot_synthesizes_id_for_facts_without_id():
    data = {"facts": [{"content": "Legacy fact without an id", "category": "context", "confidence": 0.9}]}
    snap = build_injected_memory_snapshot(data, max_tokens=2000)
    assert snap is not None
    assert snap.fact_count == 1
    assert snap.fact_ids[0].startswith("sha1:")


def test_snapshot_sections_track_what_is_present():
    facts_only = {"facts": [{"id": "f1", "content": "only a fact", "category": "context", "confidence": 0.9}]}
    snap = build_injected_memory_snapshot(facts_only, max_tokens=2000)
    assert snap is not None
    assert snap.sections == ("facts",)

    user_only = {"user": {"workContext": {"summary": "just work context"}}}
    snap2 = build_injected_memory_snapshot(user_only, max_tokens=2000)
    assert snap2 is not None
    assert snap2.sections == ("user_context",)
    assert snap2.fact_count == 0
    assert snap2.total_facts == 0


def test_to_event_payload_is_bounded_and_serializable():
    snap = build_injected_memory_snapshot(_sample_memory(), max_tokens=2000)
    assert snap is not None
    payload = snap.to_event_payload()

    assert payload == {
        "schema_version": 1,
        "fact_ids": ["f-high", "f-mid", "f-low"],
        "fact_count": 3,
        "total_facts": 3,
        "sections": list(snap.sections),
        "token_count": snap.token_count,
        "max_tokens": 2000,
        "content_hash": snap.content_hash,
        "truncated": False,
    }
    # The payload must not carry the full injected text — only provenance.
    assert "text" not in payload
    assert "content" not in payload


def test_snapshot_flags_final_truncation_and_keeps_hash_faithful():
    """When the whole-text budget safety-net clips the injection, the snapshot
    flags ``truncated`` and its ``content_hash`` still matches the exact (clipped)
    text — so a consumer is never misled into treating ``fact_ids`` as an exact
    match against the recorded hash.
    """
    # A non-facts section alone far exceeds the tiny budget, forcing the
    # whole-text truncation branch (user/history sections are not budget-limited).
    data = {"user": {"workContext": {"summary": "word " * 2000}}}
    text = format_memory_for_injection(data, max_tokens=50, use_tiktoken=False)
    snap = build_injected_memory_snapshot(data, max_tokens=50, use_tiktoken=False)

    assert snap is not None
    assert snap.truncated is True
    assert text.endswith("\n...")  # sanity: the safety net actually fired
    assert snap.content_hash == "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert snap.to_event_payload()["truncated"] is True


def test_snapshot_not_truncated_within_budget():
    snap = build_injected_memory_snapshot(_sample_memory(), max_tokens=2000)
    assert snap is not None
    assert snap.truncated is False
