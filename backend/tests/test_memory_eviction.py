"""Capacity-eviction policy tests for DeerMem facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

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
from deerflow.agents.memory.backends.deermem.deermem.core.prompt import format_memory_for_injection
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater, _select_stale_candidates

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


def test_confidence_policy_scores_duplicate_fact_ids_per_record() -> None:
    """Duplicate ids must not collide: rank and audit each record by its own score."""
    facts = [
        _fact("dup", confidence=0.9),
        _fact("dup", confidence=0.1),
        _fact("other", confidence=0.5),
    ]

    decision = select_facts_for_capacity(
        facts,
        max_facts=1,
        policy=EVICTION_POLICY_CONFIDENCE,
        now=NOW,
    )

    # The highest-confidence record wins even though its id repeats.
    assert [fact["id"] for fact in decision.kept] == ["dup"]
    assert decision.kept[0]["confidence"] == 0.9
    assert [item.fact_id for item in decision.evicted] == ["dup", "other"]
    assert [item.score for item in decision.evicted] == [0.1, 0.5]
    # Public contract unchanged: scores stays keyed by fact_id (last write wins).
    assert decision.scores["dup"].value == pytest.approx(0.1)
    assert set(decision.scores) == {"dup", "other"}


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


@pytest.mark.parametrize("confirmed", [False, True])
def test_hybrid_expanded_reserve_preserves_corrections_and_audit(tmp_path, confirmed: bool) -> None:
    old_timestamp = (NOW - timedelta(days=90)).isoformat()
    facts = [
        *[_fact(f"preference_{index}", confidence=0.85, created_at=old_timestamp) for index in range(12)],
        *[
            _fact(
                f"correction_{index}",
                confidence=0.85,
                category=category,
                created_at=old_timestamp,
                confirmed_at=old_timestamp if confirmed else None,
            )
            for index, category in enumerate(("correction", " CORRECTION "))
        ],
        *[_fact(f"context_{index}", confidence=0.90, category="context", created_at=NOW.isoformat()) for index in range(90)],
    ]
    decision = select_facts_for_capacity(
        facts,
        max_facts=100,
        policy=EVICTION_POLICY_HYBRID_V1,
        reserved_categories=["preference", "correction"],
        decay_exempt_categories=["preference"],
        now=NOW,
    )

    assert len(decision.kept) == 100
    assert {"correction_0", "correction_1"} <= {fact["id"] for fact in decision.kept}
    assert sum(fact["category"] == "preference" for fact in decision.kept) == 8
    assert decision.reserved_correction_slots == 2

    storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path), retrieval_adapter=""))
    storage.record_capacity_eviction(decision, max_facts=100, agent_name="default", user_id="u", occurred_at=NOW)
    memory_path = storage._get_memory_file_path("default", user_id="u")
    events = json.loads(agent_eviction_audit_path(memory_path, "default").read_text(encoding="utf-8"))
    assert events[0]["reservedCorrectionSlots"] == 2


@pytest.mark.parametrize("reserved_categories", [[], ["preference"]])
def test_hybrid_reserve_honors_explicit_correction_exclusion(reserved_categories: list[str]) -> None:
    facts = [
        *[_fact(f"context_{index}", confidence=0.99, category="context") for index in range(10)],
        _fact("preference", confidence=0.20),
        _fact("correction", confidence=0.10, category="correction"),
    ]
    decision = select_facts_for_capacity(
        facts,
        max_facts=10,
        policy=EVICTION_POLICY_HYBRID_V1,
        reserved_categories=reserved_categories,
        now=NOW,
    )

    kept_ids = {fact["id"] for fact in decision.kept}
    assert len(kept_ids) == 10
    assert "correction" not in kept_ids
    assert ("preference" in kept_ids) == bool(reserved_categories)
    assert decision.reserved_correction_slots == 0


def test_hybrid_reserve_rescues_at_risk_fact_when_top_winners_exceed_slots() -> None:
    # Mirrors #8194 review example: 3 preferences in top 10, intervening contexts
    # at ranks #4..#14, and 1 vital preference at rank #15 (plus a lower junk one).
    facts = [
        *[_fact(f"top_pref_{i}", confidence=0.98 - i * 0.01, category="preference") for i in range(3)],
        *[_fact(f"context_{i}", confidence=0.90 - i * 0.01, category="context") for i in range(11)],
        _fact("endangered_vital_pref", confidence=0.70, category="preference"),
        _fact("junk_low_pref", confidence=0.10, category="preference"),
    ]

    decision = select_facts_for_capacity(
        facts,
        max_facts=10,
        policy=EVICTION_POLICY_HYBRID_V1,
        reserved_categories=["preference"],
        now=NOW,
    )

    kept_ids = {fact["id"] for fact in decision.kept}
    evicted_ids = {item.fact_id for item in decision.evicted}
    assert kept_ids == {"top_pref_0", "top_pref_1", "top_pref_2", *(f"context_{i}" for i in range(6)), "endangered_vital_pref"}
    assert evicted_ids == {"context_6", "context_7", "context_8", "context_9", "context_10", "junk_low_pref"}
    assert decision.reserved_correction_slots == 0


@pytest.mark.parametrize(
    ("align_all_knobs", "expected_stale", "expected_injected"),
    [
        (False, True, False),
        (True, False, True),
    ],
)
def test_end_to_end_protection_requires_eviction_staleness_and_injection_knobs(
    align_all_knobs: bool,
    expected_stale: bool,
    expected_injected: bool,
) -> None:
    now = datetime.now(UTC)
    aged_ts = (now - timedelta(days=120)).isoformat()
    recent_ts = now.isoformat()
    cfg = DeerMemConfig(
        max_facts=10,
        fact_eviction_policy=EVICTION_POLICY_HYBRID_V1,
        eviction_reserved_categories=["correction", "preference"],
        staleness_protected_categories=["correction", "preference"] if align_all_knobs else ["correction"],
        guaranteed_categories=["correction", "preference"] if align_all_knobs else ["correction"],
    )
    vital = _fact(
        "vital_pref",
        confidence=0.70,
        category="preference",
        created_at=aged_ts,
    )
    vital["content"] = "User has a severe peanut allergy and must avoid all peanut ingredients"
    clutter = []
    for i in range(10):
        item = _fact(
            f"context_{i}",
            confidence=0.90,
            category="context",
            created_at=recent_ts,
        )
        item["content"] = f"Routine recent project note #{i} covering sprint tasks and build status"
        clutter.append(item)

    eviction = select_facts_for_capacity(
        [vital, *clutter],
        max_facts=cfg.max_facts,
        policy=cfg.fact_eviction_policy,
        reserved_categories=cfg.eviction_reserved_categories,
        now=now,
    )
    assert any(fact["id"] == "vital_pref" for fact in eviction.kept)

    stale_ids = {fact["id"] for fact in _select_stale_candidates({"facts": eviction.kept}, cfg)}
    assert ("vital_pref" in stale_ids) is expected_stale

    injected = format_memory_for_injection(
        {"facts": eviction.kept},
        max_tokens=60,
        use_tiktoken=False,
        guaranteed_categories=cfg.guaranteed_categories,
        guaranteed_token_budget=cfg.guaranteed_token_budget,
    )
    assert ("severe peanut allergy" in injected) is expected_injected


def test_hybrid_reserve_stays_bounded_across_repeated_writes(tmp_path) -> None:
    # Regression for #8331 review: writing 10 lower-scoring corrections one by
    # one into a full 10-context store must keep the 1-slot reserve bounded at
    # 9 contexts + 1 correction so a subsequent high-scoring context still lands.
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
        max_facts=10,
        fact_eviction_policy=EVICTION_POLICY_HYBRID_V1,
    )
    storage = FileMemoryStorage(config)
    updater = MemoryUpdater(config, storage=storage)

    for i in range(10):
        _, fact_id = updater.create_memory_fact(
            f"High-scoring context fact {i}",
            category="context",
            confidence=0.95,
            agent_name="default",
            user_id="u",
        )
        assert fact_id is not None

    for i in range(10):
        updater.create_memory_fact(
            f"Lower-scoring correction fact {i}",
            category="correction",
            confidence=0.20,
            agent_name="default",
            user_id="u",
        )

    mid_facts = storage.load("default", user_id="u")["facts"]
    assert len(mid_facts) == 10
    assert sum(fact["category"] == "context" for fact in mid_facts) == 9
    assert sum(fact["category"] == "correction" for fact in mid_facts) == 1

    _, new_ctx_id = updater.create_memory_fact(
        "Subsequent higher-scoring context fact",
        category="context",
        confidence=0.98,
        agent_name="default",
        user_id="u",
    )
    assert new_ctx_id is not None
    final_facts = storage.load("default", user_id="u")["facts"]
    assert any(fact["id"] == new_ctx_id for fact in final_facts)
    assert sum(fact["category"] == "context" for fact in final_facts) == 9
    assert sum(fact["category"] == "correction" for fact in final_facts) == 1


def test_hybrid_tail_reserve_stays_bounded_with_high_scoring_winners_across_writes(tmp_path) -> None:
    # Even when 3 high-scoring preferences already win top-10 slots, repeated
    # low-scoring preference writes can only occupy the 1 tail-reserve slot.
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
        max_facts=10,
        fact_eviction_policy=EVICTION_POLICY_HYBRID_V1,
        eviction_reserved_categories=["preference"],
    )
    storage = FileMemoryStorage(config)
    updater = MemoryUpdater(config, storage=storage)

    for i in range(3):
        updater.create_memory_fact(f"Top preference {i}", category="preference", confidence=0.98 - i * 0.01, agent_name="default", user_id="u")
    for i in range(7):
        updater.create_memory_fact(f"High context {i}", category="context", confidence=0.90, agent_name="default", user_id="u")
    for i in range(5):
        updater.create_memory_fact(f"Low preference {i}", category="preference", confidence=0.50 - i * 0.05, agent_name="default", user_id="u")

    facts = storage.load("default", user_id="u")["facts"]
    assert len(facts) == 10
    assert sum(fact["category"] == "context" for fact in facts) == 6
    assert sum(fact["category"] == "preference" for fact in facts) == 4
    assert any(fact["content"] == "Low preference 0" for fact in facts)


@pytest.mark.parametrize(
    ("facts", "max_facts", "reserved_categories", "fraction", "reserved_max", "expected_kept", "expected_correction_slots"),
    [
        # Same-tier protected pool: never evict a higher-scored preference to rescue a lower-scored preference.
        (
            [*[_fact(f"pref_{i}", confidence=0.9 - i * 0.05, category="preference") for i in range(4)]],
            3,
            ["preference"],
            0.5,
            5,
            {"pref_0", "pref_1", "pref_2"},
            0,
        ),
        # Correction outranks other reserved categories when no unprotected victim exists.
        (
            [*[_fact(f"pref_{i}", confidence=0.9 - i * 0.05, category="preference") for i in range(3)], _fact("corr_low", confidence=0.1, category="correction")],
            3,
            ["correction", "preference"],
            0.5,
            5,
            {"pref_0", "pref_1", "corr_low"},
            1,
        ),
        # Within a 1-slot tail reserve, correction priority takes the single slot while top context stays.
        (
            [_fact("ctx_high", confidence=0.95, category="context"), _fact("pref_low", confidence=0.80, category="preference"), _fact("corr_below", confidence=0.10, category="correction")],
            2,
            ["correction", "preference"],
            0.5,
            5,
            {"ctx_high", "corr_below"},
            1,
        ),
        # With 2 tail-reserve slots, both correction and preference outlast an unprotected higher-scored context in the tail.
        (
            [_fact("ctx_0", confidence=0.98, category="context"), _fact("ctx_1", confidence=0.95, category="context"), _fact("pref_low", confidence=0.80, category="preference"), _fact("corr_below", confidence=0.10, category="correction")],
            3,
            ["correction", "preference"],
            0.5,
            5,
            {"ctx_0", "pref_low", "corr_below"},
            1,
        ),
        # Natural winner correction does not consume reserve budget or inflate reserved_correction_slots.
        (
            [_fact("corr_top", confidence=0.99, category="correction"), _fact("ctx_1", confidence=0.90, category="context"), _fact("pref_below", confidence=0.50, category="preference")],
            2,
            ["correction", "preference"],
            0.5,
            5,
            {"corr_top", "pref_below"},
            0,
        ),
        # Zero reserve budget (fraction=0 or max=0 or empty list) rescues nothing.
        (
            [_fact("ctx_0", confidence=0.95, category="context"), _fact("ctx_1", confidence=0.90, category="context"), _fact("corr_below", confidence=0.10, category="correction")],
            2,
            ["correction"],
            0.0,
            5,
            {"ctx_0", "ctx_1"},
            0,
        ),
        (
            [_fact("ctx_0", confidence=0.95, category="context"), _fact("ctx_1", confidence=0.90, category="context"), _fact("corr_below", confidence=0.10, category="correction")],
            2,
            ["correction"],
            0.5,
            0,
            {"ctx_0", "ctx_1"},
            0,
        ),
        (
            [_fact("ctx_0", confidence=0.95, category="context"), _fact("ctx_1", confidence=0.90, category="context"), _fact("corr_below", confidence=0.10, category="correction")],
            2,
            ["  "],
            0.5,
            5,
            {"ctx_0", "ctx_1"},
            0,
        ),
    ],
)
def test_hybrid_reserve_priority_and_budget_matrix(
    facts: list[dict[str, Any]],
    max_facts: int,
    reserved_categories: list[str],
    fraction: float,
    reserved_max: int,
    expected_kept: set[str],
    expected_correction_slots: int,
) -> None:
    decision = select_facts_for_capacity(
        facts,
        max_facts=max_facts,
        policy=EVICTION_POLICY_HYBRID_V1,
        correction_reserved_fraction=fraction,
        correction_reserved_max=reserved_max,
        reserved_categories=reserved_categories,
        now=NOW,
    )
    assert {fact["id"] for fact in decision.kept} == expected_kept
    assert decision.reserved_correction_slots == expected_correction_slots


@pytest.mark.parametrize("argument", ["reserved_categories", "decay_exempt_categories"])
def test_eviction_rejects_bare_string_category_arguments(argument: str) -> None:
    with pytest.raises(TypeError, match=argument):
        select_facts_for_capacity([], max_facts=10, policy=EVICTION_POLICY_HYBRID_V1, **{argument: "preference"})


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
