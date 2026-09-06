"""Capacity-eviction policy tests for DeerMem facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.eviction import (
    EVICTION_POLICY_CONFIDENCE,
    EVICTION_POLICY_HYBRID_V1,
    select_facts_for_capacity,
)
from deerflow.agents.memory.backends.deermem.deermem.core.paths import (
    agent_eviction_audit_path,
    agent_usage_path,
)
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _fact(
    fact_id: str,
    *,
    confidence: float,
    created_at: str = "2026-08-01T00:00:00Z",
    category: str = "preference",
    confirmed_at: str | None = None,
) -> dict[str, object]:
    fact: dict[str, object] = {
        "id": fact_id,
        "content": fact_id,
        "category": category,
        "confidence": confidence,
        "createdAt": created_at,
    }
    if confirmed_at is not None:
        fact["lastConfirmedAt"] = confirmed_at
    return fact


def test_confidence_policy_preserves_existing_ranking() -> None:
    facts = [
        _fact("low", confidence=0.6),
        _fact("high", confidence=0.9),
        _fact("mid", confidence=0.7),
    ]

    decision = select_facts_for_capacity(
        facts,
        max_facts=2,
        policy=EVICTION_POLICY_CONFIDENCE,
        now=NOW,
    )

    assert [fact["id"] for fact in decision.kept] == ["high", "mid"]
    assert [item.fact_id for item in decision.evicted] == ["low"]
    assert decision.policy == EVICTION_POLICY_CONFIDENCE


def test_confidence_policy_coerces_non_float_confidence() -> None:
    facts = [
        {"id": "a", "confidence": None},
        {"id": "b", "confidence": "0.9"},
        {"id": "c", "confidence": 0.8},
        {"id": "d", "confidence": "high"},
    ]

    decision = select_facts_for_capacity(
        facts,
        max_facts=2,
        policy=EVICTION_POLICY_CONFIDENCE,
        now=NOW,
    )

    assert [fact["id"] for fact in decision.kept] == ["b", "c"]


@pytest.mark.parametrize(
    "policy",
    [EVICTION_POLICY_CONFIDENCE, EVICTION_POLICY_HYBRID_V1],
)
@pytest.mark.parametrize("max_facts", [2, 10])
def test_capacity_policy_preserves_input_order_at_or_below_cap(
    policy: str,
    max_facts: int,
) -> None:
    facts = [
        _fact("low", confidence=0.6),
        _fact("high", confidence=0.9),
    ]

    decision = select_facts_for_capacity(
        facts,
        max_facts=max_facts,
        policy=policy,
        now=NOW,
    )

    assert decision.kept == facts
    assert decision.evicted == []


def test_hybrid_policy_keeps_recently_confirmed_fact_over_stale_high_confidence() -> None:
    facts = [
        _fact(
            "stale_high",
            confidence=0.9,
            created_at="2026-02-14T00:00:00Z",
        ),
        _fact(
            "recent_confirmed",
            confidence=0.7,
            created_at="2026-01-01T00:00:00Z",
            confirmed_at="2026-08-06T00:00:00Z",
        ),
    ]

    decision = select_facts_for_capacity(
        facts,
        max_facts=1,
        policy=EVICTION_POLICY_HYBRID_V1,
        now=NOW,
    )

    assert [fact["id"] for fact in decision.kept] == ["recent_confirmed"]
    evicted = decision.evicted[0]
    assert evicted.fact_id == "stale_high"
    assert evicted.components["confidence"] == pytest.approx(0.9)
    assert evicted.components["confirmationFreshness"] < 0.13


def test_hybrid_policy_uses_bounded_access_heat() -> None:
    facts = [
        _fact("recalled", confidence=0.7),
        _fact("unused", confidence=0.75),
    ]
    usage = {
        "recalled": {
            "accessHeat": 100_000,
            "lastAccessedAt": "2026-08-13T00:00:00Z",
        }
    }

    decision = select_facts_for_capacity(
        facts,
        max_facts=1,
        policy=EVICTION_POLICY_HYBRID_V1,
        usage=usage,
        now=NOW,
    )

    assert [fact["id"] for fact in decision.kept] == ["recalled"]
    assert decision.scores["recalled"].components["accessHeat"] == pytest.approx(1.0)


def test_hybrid_policy_reserves_bounded_correction_capacity() -> None:
    facts = [
        *[_fact(f"preference_{index}", confidence=0.99 - index / 100) for index in range(10)],
        _fact("correction", confidence=0.1, category="correction"),
    ]

    decision = select_facts_for_capacity(
        facts,
        max_facts=10,
        policy=EVICTION_POLICY_HYBRID_V1,
        now=NOW,
    )

    kept_ids = {fact["id"] for fact in decision.kept}
    assert "correction" in kept_ids
    assert len(kept_ids) == 10
    assert decision.reserved_correction_slots == 1


def test_hybrid_policy_releases_unused_correction_slots() -> None:
    facts = [_fact(f"preference_{index}", confidence=0.9 - index / 100) for index in range(11)]

    decision = select_facts_for_capacity(
        facts,
        max_facts=10,
        policy=EVICTION_POLICY_HYBRID_V1,
        now=NOW,
    )

    assert len(decision.kept) == 10
    assert decision.reserved_correction_slots == 0


def test_hybrid_policy_handles_malformed_timestamps() -> None:
    fact = _fact("malformed", confidence=0.8, created_at="not-a-date", confirmed_at="also-not-a-date")

    decision = select_facts_for_capacity(
        [fact, _fact("valid", confidence=0.7)],
        max_facts=1,
        policy=EVICTION_POLICY_HYBRID_V1,
        now=NOW,
    )

    assert len(decision.kept) == 1
    assert decision.scores["malformed"].components["confirmationFreshness"] == 0.0


def test_hybrid_policy_config_is_opt_in() -> None:
    default = DeerMemConfig()
    hybrid = DeerMemConfig(fact_eviction_policy=EVICTION_POLICY_HYBRID_V1)

    assert default.fact_eviction_policy == EVICTION_POLICY_CONFIDENCE
    assert hybrid.fact_eviction_policy == EVICTION_POLICY_HYBRID_V1
    assert hybrid.eviction_confidence_weight == pytest.approx(0.65)
    assert hybrid.eviction_confirmation_weight == pytest.approx(0.25)
    assert hybrid.eviction_access_weight == pytest.approx(0.10)


def test_file_storage_records_decayed_access_heat_without_touching_fact(tmp_path) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path), retrieval_adapter="")
    storage = FileMemoryStorage(config)
    memory_path = storage._get_memory_file_path("default", user_id="u")
    first = datetime(2026, 8, 1, tzinfo=UTC)
    second = datetime(2026, 8, 31, tzinfo=UTC)
    assert storage.save(
        {"version": "1.0", "facts": [_fact("fact_a", confidence=0.8)]},
        "default",
        user_id="u",
    )

    storage.record_fact_accesses(["fact_a"], agent_name="default", user_id="u", accessed_at=first)
    storage.record_fact_accesses(["fact_a"], agent_name="default", user_id="u", accessed_at=second)

    usage = storage.get_fact_usage(agent_name="default", user_id="u")
    assert usage["fact_a"]["accessHeat"] == pytest.approx(1.5)
    assert usage["fact_a"]["accessCount"] == 2
    assert agent_usage_path(memory_path, "default").is_file()


def test_file_storage_writes_bounded_metadata_only_eviction_audit(tmp_path) -> None:
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
        eviction_audit_max_entries=1,
    )
    storage = FileMemoryStorage(config)
    memory_path = storage._get_memory_file_path("default", user_id="u")
    decision = select_facts_for_capacity(
        [_fact("kept", confidence=0.9), _fact("evicted", confidence=0.1)],
        max_facts=1,
        policy=EVICTION_POLICY_HYBRID_V1,
        now=NOW,
    )

    storage.record_capacity_eviction(
        decision,
        max_facts=1,
        agent_name="default",
        user_id="u",
        occurred_at=NOW,
    )
    storage.record_capacity_eviction(
        decision,
        max_facts=1,
        agent_name="default",
        user_id="u",
        occurred_at=NOW,
    )

    events = json.loads(agent_eviction_audit_path(memory_path, "default").read_text())
    assert len(events) == 1
    assert events[0]["evicted"][0]["factId"] == "evicted"
    assert "content" not in json.dumps(events[0])


def test_clear_fact_metadata_recomputes_shadow_disagreement(tmp_path) -> None:
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
    )
    storage = FileMemoryStorage(config)
    memory_path = storage._get_memory_file_path("default", user_id="u")
    facts = [
        _fact("always_kept", confidence=1.0, confirmed_at="2026-08-13T00:00:00Z"),
        _fact("stale_high", confidence=0.9, created_at="2025-01-01T00:00:00Z"),
        _fact("recent_low", confidence=0.6, confirmed_at="2026-08-13T00:00:00Z"),
        _fact("common_loser", confidence=0.1, created_at="2025-01-01T00:00:00Z"),
    ]
    actual = select_facts_for_capacity(
        facts,
        max_facts=2,
        policy=EVICTION_POLICY_CONFIDENCE,
        now=NOW,
    )
    shadow = select_facts_for_capacity(
        facts,
        max_facts=2,
        policy=EVICTION_POLICY_HYBRID_V1,
        now=NOW,
    )
    storage.record_capacity_eviction(
        actual,
        max_facts=2,
        agent_name="default",
        user_id="u",
        occurred_at=NOW,
        shadow_decision=shadow,
    )

    storage.clear_fact_metadata(
        agent_name="default",
        user_id="u",
        fact_ids=["recent_low", "stale_high"],
    )

    events = json.loads(agent_eviction_audit_path(memory_path, "default").read_text())
    assert {item["factId"] for item in events[0]["evicted"]} == {"common_loser"}
    assert set(events[0]["shadow"]["wouldEvict"]) == {"common_loser"}
    assert events[0]["shadow"]["disagrees"] is False


def test_delete_fact_tolerates_malformed_eviction_audit(tmp_path) -> None:
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
    )
    storage = FileMemoryStorage(config)
    storage.upsert_fact(
        _fact("victim", confidence=0.8),
        agent_name="default",
        user_id="u",
    )
    memory_path = storage._get_memory_file_path("default", user_id="u")
    audit_path = agent_eviction_audit_path(memory_path, "default")
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            [
                {
                    "reason": "capacity",
                    "evicted": None,
                    "shadow": {"wouldEvict": ["victim"], "disagrees": True},
                }
            ]
        )
    )

    storage.delete_fact("victim", agent_name="default", user_id="u")

    assert storage.get_fact("victim", agent_name="default", user_id="u") is None
    assert not audit_path.exists()


def test_clear_fact_metadata_sanitizes_malformed_audit_fields(tmp_path) -> None:
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
    )
    storage = FileMemoryStorage(config)
    memory_path = storage._get_memory_file_path("default", user_id="u")
    audit_path = agent_eviction_audit_path(memory_path, "default")
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            [
                {
                    "reason": "capacity",
                    "evicted": [
                        {"factId": "keep"},
                        {"factId": "removed"},
                        {"factId": []},
                        "invalid",
                    ],
                    "shadow": {
                        "wouldEvict": ["keep", "removed", {"invalid": True}],
                        "disagrees": True,
                    },
                },
                {
                    "reason": "capacity",
                    "evicted": [{"factId": "keep_without_shadow"}],
                    "shadow": {"wouldEvict": None, "disagrees": True},
                },
            ]
        )
    )

    storage.clear_fact_metadata(
        agent_name="default",
        user_id="u",
        fact_ids=["removed"],
    )

    events = json.loads(audit_path.read_text())
    assert events[0]["evicted"] == [{"factId": "keep"}]
    assert events[0]["shadow"] == {
        "wouldEvict": ["keep"],
        "disagrees": False,
    }
    assert events[1]["evicted"] == [{"factId": "keep_without_shadow"}]
    assert "shadow" not in events[1]
