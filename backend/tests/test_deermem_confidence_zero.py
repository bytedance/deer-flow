"""Regression tests for confidence 0.0 ranking (deer-flow issue #5585).

``confidence: 0.0`` is a valid, persisted value (``_normalize_fact`` accepts the
closed interval [0, 1]), but both ranking read sites coalesced with ``or 0.5``,
which treats ``0.0`` as "absent".  A zero-confidence fact therefore scored the
default weight, tied a 0.5 fact, and — worse — scored differently depending on
which write path indexed it (the low-level engine kept the value, the adapter
did not).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.retrieval import (
    FTS5Retrieval,
    FTS5RetrievalAdapter,
)
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage


def _fact(fid: str, conf: float | None = None) -> dict:
    fact = {
        "id": fid,
        "content": "confidence weight probe",
        "category": "context",
        "createdAt": "2026-07-21T00:00:00Z",
        "source": {"type": "test", "threadId": None},
    }
    if conf is not None:
        fact["confidence"] = conf
    return fact


_SCOPE = {"userId": "alice", "agentName": "agent-a"}


def test_adapter_keeps_zero_confidence_weight(tmp_path: Path) -> None:
    """A 0.0-confidence fact must rank strictly below a 0.5 one via the adapter."""
    adapter = FTS5RetrievalAdapter(tmp_path / "a.sqlite3")
    try:
        for fid, conf in (("zero", 0.0), ("half", 0.5), ("none", None), ("eight", 0.8)):
            adapter.upsert(_fact(fid, conf), scope=_SCOPE, path="")
        scores = {item["fact"]["id"]: item["score"] for item in adapter.search("confidence", scopes=[_SCOPE], top_k=9, mode="fts5", filters=None)}
    finally:
        adapter.close()

    assert scores["zero"] < scores["half"], scores
    assert scores["zero"] < scores["none"], scores
    assert scores["half"] == pytest.approx(scores["none"]), scores
    assert scores["eight"] > scores["half"], scores


def test_adapter_and_engine_agree_on_zero_confidence(tmp_path: Path) -> None:
    """Both write paths must score the identical stored fact identically."""
    adapter = FTS5RetrievalAdapter(tmp_path / "a.sqlite3")
    try:
        for fid, conf in (("zero", 0.0), ("half", 0.5), ("eight", 0.8)):
            adapter.upsert(_fact(fid, conf), scope=_SCOPE, path="")
        adapter_scores = {item["fact"]["id"]: item["score"] for item in adapter.search("confidence", scopes=[_SCOPE], top_k=9, mode="fts5", filters=None)}
    finally:
        adapter.close()

    engine = FTS5Retrieval(tmp_path / "b.sqlite3")
    try:
        for fid, conf in (("zero", 0.0), ("half", 0.5), ("eight", 0.8)):
            engine.index_fact(
                fid,
                "confidence weight probe",
                confidence=conf,
                created_at="2026-07-21T00:00:00Z",
                scope_user='"alice"',
                scope_agent='"agent-a"',
            )
        engine_scores = {result["id"]: result["score"] for result in engine.search("confidence", scope_user='"alice"', scope_agent='"agent-a"')}
    finally:
        engine.close()

    assert adapter_scores["zero"] == pytest.approx(engine_scores["zero"]), (adapter_scores, engine_scores)
    assert adapter_scores["half"] == pytest.approx(engine_scores["half"]), (adapter_scores, engine_scores)
    assert adapter_scores["eight"] == pytest.approx(engine_scores["eight"]), (adapter_scores, engine_scores)


def test_substring_fallback_keeps_zero_confidence(tmp_path: Path) -> None:
    """The no-index fallback must not promote 0.0 to the 0.5 default."""
    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))
    storage.upsert_fact(_fact("zero", 0.0), user_id="alice", agent_name="agent-a")
    storage.upsert_fact(_fact("half", 0.5), user_id="alice", agent_name="agent-a")

    results = storage.search_facts("confidence", scopes=[_SCOPE], top_k=9)
    scores = {item["fact"]["id"]: item["score"] for item in results}

    assert scores["zero"] == 0.0, scores
    assert scores["half"] == pytest.approx(0.5), scores
