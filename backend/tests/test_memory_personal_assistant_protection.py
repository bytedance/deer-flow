"""Deterministic unit tests for DeerMem Personal Assistant Category Protection in Eviction.

Addresses Totoro's technical reviews:
1. Diagnosis 1 (Root cause isolation):
   Pinpoints that personal profile loss in multi-turn dialogues occurs exclusively
   at storage capacity eviction (eviction.py), NOT in retrieval.py.
2. Diagnosis 2 (Bidirectional lifecycle verification):
   - Positive path: Profile facts (preference/identity) survive capacity starvation from chat clutter.
   - Negative path 1 (Explicit removal): If a user removes a profile fact, it is deleted cleanly
     and cannot resurrect via capacity reservation.
   - Negative path 2 (Contradiction replacement): If a user updates/replaces an enduring profile,
     the old fact is discarded and the new fact takes over without being shadowed by the old.
3. Backward compatibility:
   Default configuration retains historical hybrid-v1 and confidence behavior byte-for-byte.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.eviction import (
    EVICTION_POLICY_CONFIDENCE,
    EVICTION_POLICY_HYBRID_V1,
    select_facts_for_capacity,
)
from deerflow.agents.memory.backends.deermem.deermem.core.prompt import format_memory_for_injection
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def _fact(
    fact_id: str,
    *,
    content: str | None = None,
    confidence: float,
    category: str = "context",
    created_at: str = "2026-08-01T00:00:00Z",
    confirmed_at: str | None = None,
) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "id": fact_id,
        "content": content or fact_id,
        "category": category,
        "confidence": confidence,
        "createdAt": created_at,
    }
    if confirmed_at is not None:
        fact["lastConfirmedAt"] = confirmed_at
    return fact


# ==============================================================================
# 1. DIAGNOSIS 1: REPRODUCTION CASE PINPOINTING ROOT CAUSE IN EVICTION
# ==============================================================================


def test_reproduction_root_cause_is_eviction_starvation_not_retrieval() -> None:
    """Proves that profile amnesia is caused by eviction discarding facts from storage.

    Scenario:
    - 1 enduring health profile fact (peanut allergy, confidence=0.85, 60 days old)
    - 10 casual chatter context facts (confidence=0.90, recent)
    - Storage capacity cap = 10 facts.
    """
    allergy_fact = _fact(
        "profile_allergy",
        content="用户对花生及花生油严重过敏（过敏性休克风险，严禁任何花生及其衍生物成分）",
        confidence=0.85,
        category="preference",
        created_at="2026-08-15T00:00:00Z",
    )
    context_facts = [_fact(f"context_{i}", content=f"近期普通闲聊工作琐碎信息 #{i}", confidence=0.90, category="context") for i in range(1, 11)]
    all_facts = [allergy_fact, *context_facts]

    # Baseline (main behavior): Both confidence and hybrid-v1 evict the allergy fact
    decision_conf = select_facts_for_capacity(all_facts, max_facts=10, policy=EVICTION_POLICY_CONFIDENCE, now=NOW)
    kept_conf_ids = {f["id"] for f in decision_conf.kept}
    assert "profile_allergy" not in kept_conf_ids, "Baseline confidence policy must drop the allergy fact"

    decision_hybrid_default = select_facts_for_capacity(
        all_facts,
        max_facts=10,
        policy=EVICTION_POLICY_HYBRID_V1,
        now=NOW,
    )
    kept_hybrid_ids = {f["id"] for f in decision_hybrid_default.kept}
    assert "profile_allergy" not in kept_hybrid_ids, "Baseline hybrid-v1 must drop the allergy fact without category quota"

    # Once evicted, injection formatting cannot restore it
    injected_before = format_memory_for_injection({"facts": decision_hybrid_default.kept}, max_tokens=1000)
    assert "花生" not in injected_before
    assert "过敏" not in injected_before

    # Narrow Fix (eviction category reservation only):
    decision_protected = select_facts_for_capacity(
        all_facts,
        max_facts=10,
        policy=EVICTION_POLICY_HYBRID_V1,
        correction_reserved_fraction=0.20,
        correction_reserved_max=5,
        reserved_categories=["correction", "preference", "identity", "constraint"],
        decay_exempt_categories=["preference", "identity", "constraint"],
        now=NOW,
    )
    kept_protected_ids = {f["id"] for f in decision_protected.kept}
    assert "profile_allergy" in kept_protected_ids, "With category reservation, allergy fact survives in storage"

    # And thus naturally enters prompt injection without touching retrieval.py!
    injected_after = format_memory_for_injection({"facts": decision_protected.kept}, max_tokens=1000)
    assert "花生及花生油严重过敏" in injected_after


# ==============================================================================
# 2. DIAGNOSIS 2: BIDIRECTIONAL LIFECYCLE VERIFICATION (NEGATIVE PATHS)
# ==============================================================================


def test_bidirectional_lifecycle_explicit_removal_is_permanent(tmp_path: Path) -> None:
    """Verifies negative path 1: If a user explicitly removes a profile fact,

    it is deleted cleanly from storage and CANNOT be resurrected by category reservation.
    """
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
        max_facts=10,
        fact_eviction_policy="hybrid-v1",
        eviction_reserved_categories=["correction", "preference", "identity"],
        eviction_decay_exempt_categories=["preference", "identity"],
    )
    storage = FileMemoryStorage(config)
    updater = MemoryUpdater(config, storage=storage)

    # Initial state: user has a protected preference fact
    allergy_fact = _fact(
        "pref_allergy_001",
        content="用户对花生严重过敏",
        confidence=0.85,
        category="preference",
    )
    storage.save({"version": "1.0", "facts": [allergy_fact]}, "default", user_id="u1")

    # Verify fact is stored
    stored = storage.load("default", user_id="u1").get("facts", [])
    assert any(f["id"] == "pref_allergy_001" for f in stored)

    # User later explicitly removes it ("I am no longer allergic to peanuts")
    update_data = {
        "newFacts": [
            {
                "content": "用户近期已完成医学脱敏治疗",
                "category": "context",
                "confidence": 0.90,
                "scope": "user",
                "durability": "durable",
                "authority": "descriptive",
            }
        ],
        "factsToRemove": [
            {
                "id": "pref_allergy_001",
                "scope": "user",
                "reason": "User completed desensitization therapy",
            }
        ],
    }

    current = storage.load("default", user_id="u1")
    updated = updater._apply_updates(
        current,
        update_data,
        thread_id="t1",
        agent_name="default",
        user_id="u1",
    )
    storage.save(updated, "default", user_id="u1")

    # Assert: The removed preference fact is GONE from storage
    updated_facts = storage.load("default", user_id="u1").get("facts", [])
    updated_ids = {f["id"] for f in updated_facts}
    assert "pref_allergy_001" not in updated_ids, "Explicitly removed fact must NOT survive in storage"
    assert any("脱敏治疗" in f["content"] for f in updated_facts)


def test_bidirectional_lifecycle_contradiction_replacement_supersedes_old(tmp_path: Path) -> None:
    """Verifies negative path 2: If a user updates/replaces an enduring profile fact,

    the old fact is discarded and the new fact inherits protection, preventing the old from shadowing the new.
    """
    config = DeerMemConfig(
        storage_path=str(tmp_path),
        retrieval_adapter="",
        max_facts=10,
        fact_eviction_policy="hybrid-v1",
        eviction_reserved_categories=["correction", "preference", "identity"],
        eviction_decay_exempt_categories=["preference", "identity"],
    )
    storage = FileMemoryStorage(config)
    updater = MemoryUpdater(config, storage=storage)

    # Step 1: User initially establishes bash script preference 90 days ago
    old_pref = _fact(
        "pref_lang_bash",
        content="用户偏好所有脚本使用 Bash 编写",
        confidence=0.85,
        category="preference",
        created_at="2026-07-01T00:00:00Z",
    )
    storage.save({"version": "1.0", "facts": [old_pref]}, "default", user_id="u1")

    # Step 2: User changes their mind: switches preference to Python 3.12
    update_data = {
        "newFacts": [
            {
                "content": "用户偏好所有脚本使用 Python 3.12 编写",
                "category": "preference",
                "confidence": 0.90,
                "scope": "user",
                "durability": "durable",
                "authority": "descriptive",
            }
        ],
        "factsToRemove": [
            {
                "id": "pref_lang_bash",
                "scope": "user",
                "reason": "User switched preference from Bash to Python 3.12",
                "replacementFactIndex": 0,
            }
        ],
    }

    current = storage.load("default", user_id="u1")
    updated = updater._apply_updates(
        current,
        update_data,
        thread_id="t1",
        agent_name="default",
        user_id="u1",
    )
    storage.save(updated, "default", user_id="u1")

    facts_after_step2 = storage.load("default", user_id="u1").get("facts", [])
    step2_ids = {f["id"] for f in facts_after_step2}
    assert "pref_lang_bash" not in step2_ids, "Old superseded preference must be removed"
    assert any("Python 3.12" in f["content"] for f in facts_after_step2), "New preference must be stored"

    # Step 3: Now flood memory with casual context facts to trigger capacity eviction (cap=10)
    flood_update = {
        "newFacts": [
            {
                "content": f"今日工作闲聊碎碎念 #{i}",
                "category": "context",
                "confidence": 0.92,
                "scope": "user",
                "durability": "durable",
                "authority": "descriptive",
            }
            for i in range(1, 15)
        ]
    }
    current_before_flood = storage.load("default", user_id="u1")
    flooded = updater._apply_updates(
        current_before_flood,
        flood_update,
        thread_id="t1",
        agent_name="default",
        user_id="u1",
    )
    storage.save(flooded, "default", user_id="u1")

    final_facts = storage.load("default", user_id="u1").get("facts", [])
    assert len(final_facts) <= 10, "Total facts must respect max_facts=10"
    # Old bash fact must still be dead
    assert not any("Bash" in f["content"] for f in final_facts)
    # New python fact must survive thanks to category reservation
    assert any("Python 3.12" in f["content"] for f in final_facts), "New preference must survive eviction via reserved quota"


# ==============================================================================
# 3. BACKWARD COMPATIBILITY
# ==============================================================================


def test_deermem_config_defaults_maintain_strict_backward_compatibility(tmp_path: Path) -> None:
    """Verifies that default config values preserve exact historical behavior."""
    default_config = DeerMemConfig()
    assert default_config.eviction_reserved_categories == ["correction"]
    assert default_config.eviction_decay_exempt_categories == []

    # Under defaults, a non-correction fact is never reserved
    facts = [_fact(f"c_{i}", confidence=0.95, category="context") for i in range(12)]
    facts.append(_fact("vital_pref", confidence=0.80, category="preference", created_at="2026-01-01T00:00:00Z"))

    storage = FileMemoryStorage(default_config)
    updater = MemoryUpdater(default_config, storage=storage)

    updater._config.max_facts = 10
    kept_capped, _, _ = updater._select_for_capacity(facts, agent_name="default", user_id="u1")
    kept_ids = {f["id"] for f in kept_capped}
    assert "vital_pref" not in kept_ids, "Under defaults, preference is not protected from eviction"


def test_decay_exemption_defends_against_malformed_facts_without_timestamps() -> None:
    """Verifies that decay_exempt does not grant non-zero freshness to malformed facts lacking valid timestamps."""
    from deerflow.agents.memory.backends.deermem.deermem.core.eviction import _confirmation_freshness

    # Fact with neither createdAt nor lastConfirmedAt
    corrupted_fact = {"id": "bad_fact", "category": "preference", "confidence": 0.8}
    score_normal = _confirmation_freshness(corrupted_fact, now=NOW, half_life_days=90, decay_exempt=False)
    score_exempt = _confirmation_freshness(corrupted_fact, now=NOW, half_life_days=90, decay_exempt=True)
    assert score_normal == 0.0
    assert score_exempt == 0.0, "Corrupted fact must not receive 0.5 freshness just because it is exempt"

    # Fact with invalid date strings
    invalid_fact = {"id": "bad_date", "category": "preference", "createdAt": "invalid-timestamp"}
    assert _confirmation_freshness(invalid_fact, now=NOW, half_life_days=90, decay_exempt=True) == 0.0

    # Fact with only createdAt receives 0.5 unpenalized
    valid_created = {"id": "valid_created", "category": "preference", "createdAt": "2026-08-01T00:00:00Z"}
    assert _confirmation_freshness(valid_created, now=NOW, half_life_days=90, decay_exempt=True) == 0.5

    # Fact with lastConfirmedAt receives 1.0 unpenalized
    valid_confirmed = {"id": "valid_confirmed", "category": "preference", "lastConfirmedAt": "2026-08-01T00:00:00Z"}
    assert _confirmation_freshness(valid_confirmed, now=NOW, half_life_days=90, decay_exempt=True) == 1.0
