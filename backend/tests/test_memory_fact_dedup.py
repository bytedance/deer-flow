"""Tests for the deterministic near-duplicate fact gate (issue #5252).

The gate is opt-in via DeerMem-private config (``fact_dedup_enabled``) and
must never change the default behavior. A proposed NEW fact whose bounded
token-Jaccard similarity to an existing fact in the same user/agent scope
AND category reaches ``fact_dedup_similarity_threshold`` merges into that
fact (existing id/content/createdAt kept, confidence raised to the maximum,
source refreshed only on a confidence increase) instead of being appended.

Test construction mirrors ``tests/test_memory_scope_gate.py``: a real
``MemoryUpdater`` with an in-memory storage and ``_apply_updates`` driven
directly, no LLM, no network.
"""

from __future__ import annotations

import copy
import logging

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater, _fact_content_similarity, _fact_content_tokens


def _memory(facts: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": copy.deepcopy(facts or []),
    }


class _Storage(MemoryStorage):
    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, object]:
        return _memory()

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, object]:
        return self.load(agent_name, user_id=user_id)

    def save(
        self,
        memory_data: dict[str, object],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        return True


def _updater(**config_overrides: object) -> MemoryUpdater:
    config = DeerMemConfig()
    for key, value in config_overrides.items():
        setattr(config, key, value)
    return MemoryUpdater(config, _Storage(), llm=None)


def _fact(content: str, **overrides: object) -> dict[str, object]:
    fact: dict[str, object] = {
        "content": content,
        "category": "preference",
        "confidence": 0.9,
        "scope": "user",
        "durability": "durable",
        "authority": "descriptive",
    }
    fact.update(overrides)
    return fact


def _stored_fact(fact_id: str, content: str, **overrides: object) -> dict[str, object]:
    fact: dict[str, object] = {
        "id": fact_id,
        "content": content,
        "category": "preference",
        "confidence": 0.9,
        "createdAt": "2026-01-01T00:00:00Z",
        "source": "thread-old",
    }
    fact.update(overrides)
    return fact


def _update(new_facts: list[dict[str, object]]) -> dict[str, object]:
    return {"user": {}, "history": {}, "newFacts": new_facts}


class TestFactDedupGate:
    def test_default_config_keeps_near_duplicate_facts(self):
        updater = _updater()
        current = _memory([_stored_fact("fact_old", "User prefers concise answers in chat")])

        result = updater._apply_updates(current, _update([_fact("User prefers concise answers in chat, short form")]))

        assert len(result["facts"]) == 2

    def test_enabled_merges_paraphrased_fact(self):
        updater = _updater(fact_dedup_enabled=True)
        current = _memory([_stored_fact("fact_old", "User prefers concise answers in chat")])
        metrics: dict[str, object] = {}

        result = updater._apply_updates(
            current,
            _update([_fact("User prefers concise answers in chat, short form", confidence=0.95)]),
            metrics=metrics,
        )

        assert len(result["facts"]) == 1
        merged = result["facts"][0]
        assert merged["id"] == "fact_old"
        assert merged["content"] == "User prefers concise answers in chat"
        assert merged["createdAt"] == "2026-01-01T00:00:00Z"
        assert merged["confidence"] == 0.95
        assert merged["source"] == "unknown"  # refreshed from the proposed fact's thread
        assert metrics.get("facts_merged_dedup") == 1

    def test_merge_keeps_higher_existing_confidence(self):
        updater = _updater(fact_dedup_enabled=True)
        current = _memory([_stored_fact("fact_old", "User prefers concise answers in chat", confidence=0.98)])

        result = updater._apply_updates(
            current,
            _update([_fact("User prefers concise answers in chat, short form", confidence=0.8)]),
        )

        assert len(result["facts"]) == 1
        assert result["facts"][0]["confidence"] == 0.98

    def test_different_category_does_not_merge(self):
        updater = _updater(fact_dedup_enabled=True)
        current = _memory([_stored_fact("fact_old", "User prefers concise answers in chat")])

        result = updater._apply_updates(
            current,
            _update([_fact("User prefers concise answers in chat, short form", category="project")]),
        )

        assert len(result["facts"]) == 2

    def test_unrelated_content_below_threshold_does_not_merge(self):
        updater = _updater(fact_dedup_enabled=True)
        current = _memory([_stored_fact("fact_old", "User prefers concise answers in chat")])

        result = updater._apply_updates(
            current,
            _update([_fact("User works on database migrations")]),
        )

        assert len(result["facts"]) == 2

    def test_threshold_is_respected(self):
        updater = _updater(fact_dedup_enabled=True, fact_dedup_similarity_threshold=0.9)
        current = _memory([_stored_fact("fact_old", "User prefers concise answers in chat")])

        result = updater._apply_updates(
            current,
            _update([_fact("User prefers concise answers in chat, short form")]),
        )

        # 6/8 = 0.75 token-Jaccard is below the configured 0.9 threshold.
        assert len(result["facts"]) == 2

    def test_exact_duplicate_still_skipped_without_merge_metrics(self):
        updater = _updater(fact_dedup_enabled=True)
        current = _memory([_stored_fact("fact_old", "User prefers concise answers in chat")])
        metrics: dict[str, object] = {}

        result = updater._apply_updates(
            current,
            _update([_fact("User prefers concise answers in chat")]),
            metrics=metrics,
        )

        assert len(result["facts"]) == 1
        assert "facts_merged_dedup" not in metrics


class TestFactDedupConfig:
    def test_defaults_keep_legacy_behavior(self):
        config = DeerMemConfig()
        assert config.fact_dedup_enabled is False
        assert config.fact_dedup_similarity_threshold == 0.7

    def test_backend_config_accepts_new_knobs(self):
        config = DeerMemConfig.from_backend_config(
            {
                "fact_dedup_enabled": True,
                "fact_dedup_similarity_threshold": 0.8,
            }
        )
        assert config.fact_dedup_enabled is True
        assert config.fact_dedup_similarity_threshold == 0.8


@pytest.mark.parametrize("paired", [True, False])
def test_correction_is_not_merged_into_removal_target(paired):
    old = "User prefers email notifications over sms for weekly reports"
    new = "User prefers push notifications over sms for weekly reports"
    current = _memory([_stored_fact("fact_B", old, confidence=0.5)])
    update = _update([_fact(new, confidence=0.95)])
    removal = {"id": "fact_B", "scope": "user", "reason": "Preference changed"}
    if paired:
        removal["replacementFactIndex"] = 0
    update["factsToRemove"] = [removal]
    metrics = {}

    result = _updater(fact_dedup_enabled=True)._apply_updates(current, update, thread_id="correction", metrics=metrics)

    assert len(result["facts"]) == 1
    assert result["facts"][0]["content"] == new
    assert result["facts"][0]["id"] != "fact_B"
    assert result["facts"][0]["source"] == "correction"
    assert metrics.get("facts_merged_dedup", 0) == 0


def test_paired_replacement_is_not_merged_into_another_similar_fact():
    other = "User prefers email notifications over sms for weekly reports"
    current = _memory(
        [
            _stored_fact("fact_B", "User previously disabled all notifications"),
            _stored_fact("fact_other", other),
        ]
    )
    new = "User prefers push notifications over sms for weekly reports"
    update = _update([_fact(new, confidence=0.95)])
    update["factsToRemove"] = [{"id": "fact_B", "scope": "user", "reason": "Changed", "replacementFactIndex": 0}]

    result = _updater(fact_dedup_enabled=True)._apply_updates(current, update)

    assert {fact["content"] for fact in result["facts"]} == {other, new}
    assert all(fact["id"] != "fact_B" for fact in result["facts"])


def test_stale_removal_proposal_is_not_strengthened_when_guard_keeps_it():
    old = _stored_fact("fact_old", "User prefers concise answers in chat")
    update = _update([_fact("User prefers concise answers in chat, short form", confidence=0.95)])
    # Configure preferences as protected from staleness removal. A proposal
    # still must not become evidence strengthening the proposed target.
    update["staleFactsToRemove"] = [{"id": "fact_old", "reason": "Outdated"}]

    result = _updater(fact_dedup_enabled=True, staleness_protected_categories=["preference"])._apply_updates(_memory([old]), update)

    assert len(result["facts"]) == 2
    assert next(fact for fact in result["facts"] if fact["id"] == "fact_old") == old


@pytest.mark.parametrize("confidence", [0.8, 0.98])
def test_nonincreasing_confidence_preserves_source_and_confirmation(confidence):
    old = _stored_fact("fact_old", "User prefers concise answers in chat", confidence=0.98, lastConfirmedAt="2026-01-02T00:00:00Z", confirmationCount=2)
    result = _updater(fact_dedup_enabled=True)._apply_updates(
        _memory([old]),
        _update([_fact("User prefers concise answers in chat, short form", confidence=confidence)]),
        thread_id="restatement",
    )
    assert result["facts"] == [old]


def test_merge_logs_metadata_at_info_without_fact_text(caplog):
    old = "User prefers concise answers in chat"
    new = old + ", short form"
    with caplog.at_level(logging.INFO):
        _updater(fact_dedup_enabled=True)._apply_updates(_memory([_stored_fact("fact_old", old)]), _update([_fact(new, confidence=0.95)]))
    assert "Near-duplicate fact merge proposed" in caplog.text
    assert "fact_old" in caplog.text
    assert "proposal_index=0" in caplog.text
    assert old not in caplog.text
    assert new not in caplog.text


def test_mixed_script_facts_retain_different_cities():
    old = "Prefers Python, 用户在北京"
    new = "Prefers Python, 用户在上海"
    result = _updater(fact_dedup_enabled=True)._apply_updates(_memory([_stored_fact("fact_old", old)]), _update([_fact(new)]))
    assert len(result["facts"]) == 2
    assert _fact_content_similarity(old, new) < 0.7


def test_tokenizer_combines_words_and_cjk_bigrams():
    assert _fact_content_tokens("Prefers Python, 用户在北京") == ["prefers", "python", "用户", "户在", "在北", "北京"]
    assert _fact_content_tokens("用户 北京") == ["用户", "户北", "北京"]
    assert _fact_content_similarity("用户 北京", "北京 用户") < 0.7
    assert _fact_content_tokens("中") == ["中"]


@pytest.mark.parametrize("override", [{"scope": "thread"}, {"confidence": 0.1}])
def test_rejected_replacement_does_not_delete_or_strengthen_original(override):
    old = _stored_fact("fact_B", "User prefers email notifications over sms for weekly reports", confidence=0.8)
    update = _update([_fact("User prefers push notifications over sms for weekly reports", **override)])
    update["factsToRemove"] = [{"id": "fact_B", "scope": "user", "reason": "Changed", "replacementFactIndex": 0}]
    result = _updater(fact_dedup_enabled=True)._apply_updates(_memory([old]), update)
    assert result["facts"] == [old]


@pytest.mark.parametrize("confirmed", [False, True])
def test_merge_preserves_deterministic_confirmation_gate(confirmed):
    old = _stored_fact("fact_old", "User prefers concise answers in chat", lastConfirmedAt="2026-01-02T00:00:00Z", confirmationCount=2)
    update = _update([_fact("User prefers concise answers in chat, short form", confidence=0.95)])
    update["factsToReinforce"] = [{"id": "fact_old", "scope": "user", "reason": "Restated"}]
    result = _updater(fact_dedup_enabled=True, fact_eviction_shadow_enabled=True)._apply_updates(
        _memory([old]),
        update,
        signals=frozenset({"reinforcement"}) if confirmed else frozenset(),
    )
    merged = result["facts"][0]
    assert merged["confidence"] == 0.95
    assert merged["confirmationCount"] == (3 if confirmed else 2)
    assert (merged["lastConfirmedAt"] != old["lastConfirmedAt"]) is confirmed
