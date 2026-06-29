"""Tests for the staleness review feature in the memory updater.

Covers:
- Candidate selection (age threshold, protected categories)
- Trigger conditions (min candidates, enabled flag)
- Prompt section formatting
- Staleness removal in _apply_updates (safety cap, observability)
- Normalization of staleFactsToRemove from LLM responses
- Integration with _prepare_update_prompt
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.updater import (
    MemoryUpdater,
    _build_staleness_section,
    _normalize_memory_update_data,
    _parse_fact_datetime,
    _select_stale_candidates,
)
from deerflow.config.memory_config import MemoryConfig

# ── Helpers ────────────────────────────────────────────────────────────────


def _memory_config(**overrides: object) -> MemoryConfig:
    config = MemoryConfig()
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _make_fact(
    fact_id: str,
    content: str = "test content",
    category: str = "knowledge",
    confidence: float = 0.9,
    days_ago: int = 100,
) -> dict:
    created = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "id": fact_id,
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": created,
        "source": "thread-test",
    }


def _make_memory(facts: list[dict] | None = None) -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "",
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
        "facts": facts or [],
    }


# ── _parse_fact_datetime ──────────────────────────────────────────────────


class TestParseFactDatetime:
    def test_z_suffix(self):
        result = _parse_fact_datetime("2025-06-01T12:00:00Z")
        assert result is not None
        assert result.year == 2025
        assert result.month == 6

    def test_offset_format(self):
        result = _parse_fact_datetime("2025-06-01T12:00:00+00:00")
        assert result is not None
        assert result.year == 2025

    def test_empty_string(self):
        assert _parse_fact_datetime("") is None

    def test_invalid_format(self):
        assert _parse_fact_datetime("not-a-date") is None

    def test_naive_datetime_gets_utc(self):
        """Naive datetime (no tzinfo) should be treated as UTC, not cause TypeError."""
        result = _parse_fact_datetime("2025-06-01T12:00:00")
        assert result is not None
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0


# ── _select_stale_candidates ──────────────────────────────────────────────


class TestSelectStaleCandidates:
    def test_old_facts_selected(self):
        memory = _make_memory(
            [
                _make_fact("fact_old", days_ago=100),
                _make_fact("fact_new", days_ago=10),
            ]
        )
        config = _memory_config(staleness_age_days=90)
        candidates = _select_stale_candidates(memory, config)
        assert len(candidates) == 1
        assert candidates[0]["id"] == "fact_old"

    def test_protected_category_excluded(self):
        memory = _make_memory(
            [
                _make_fact("fact_correction", category="correction", days_ago=200),
                _make_fact("fact_knowledge", category="knowledge", days_ago=200),
            ]
        )
        config = _memory_config(staleness_age_days=90, staleness_protected_categories=["correction"])
        candidates = _select_stale_candidates(memory, config)
        assert len(candidates) == 1
        assert candidates[0]["id"] == "fact_knowledge"

    def test_custom_protected_categories(self):
        memory = _make_memory(
            [
                _make_fact("fact_goal", category="goal", days_ago=200),
            ]
        )
        config = _memory_config(staleness_age_days=90, staleness_protected_categories=["goal"])
        candidates = _select_stale_candidates(memory, config)
        assert len(candidates) == 0

    def test_no_facts(self):
        memory = _make_memory([])
        config = _memory_config(staleness_age_days=90)
        assert _select_stale_candidates(memory, config) == []

    def test_all_recent(self):
        memory = _make_memory(
            [
                _make_fact("fact_a", days_ago=10),
                _make_fact("fact_b", days_ago=30),
            ]
        )
        config = _memory_config(staleness_age_days=90)
        assert _select_stale_candidates(memory, config) == []


# ── Trigger conditions via _select_stale_candidates + config ─────────────


class TestStalenessTriggerConditions:
    """The old _should_run_staleness_review was removed; trigger logic is now
    inlined in _prepare_update_prompt.  We verify the gating conditions here
    through _select_stale_candidates + config flags directly."""

    def test_disabled_means_no_section(self):
        memory = _make_memory([_make_fact(f"f{i}", days_ago=100) for i in range(5)])
        config = _memory_config(staleness_review_enabled=False, staleness_age_days=90, staleness_min_candidates=3)
        candidates = _select_stale_candidates(memory, config)
        # Even though candidates exist, the caller checks enabled flag first
        assert config.staleness_review_enabled is False
        assert len(candidates) >= config.staleness_min_candidates

    def test_below_min_candidates(self):
        memory = _make_memory([_make_fact("fact_only", days_ago=100)])
        config = _memory_config(staleness_review_enabled=True, staleness_age_days=90, staleness_min_candidates=3)
        candidates = _select_stale_candidates(memory, config)
        assert len(candidates) < config.staleness_min_candidates

    def test_at_min_candidates(self):
        memory = _make_memory([_make_fact(f"fact_{i}", days_ago=100) for i in range(3)])
        config = _memory_config(staleness_review_enabled=True, staleness_age_days=90, staleness_min_candidates=3)
        candidates = _select_stale_candidates(memory, config)
        assert len(candidates) >= config.staleness_min_candidates

    def test_above_min_candidates(self):
        memory = _make_memory([_make_fact(f"fact_{i}", days_ago=100) for i in range(10)])
        config = _memory_config(staleness_review_enabled=True, staleness_age_days=90, staleness_min_candidates=3)
        candidates = _select_stale_candidates(memory, config)
        assert len(candidates) >= config.staleness_min_candidates


# ── _build_staleness_section ──────────────────────────────────────────────


class TestBuildStalenessSection:
    def test_empty_candidates(self):
        assert _build_staleness_section([], 90) == ""

    def test_includes_fact_details(self):
        candidates = [
            _make_fact("fact_vue", "User uses Vue.js", "knowledge", 0.95, days_ago=120),
        ]
        section = _build_staleness_section(candidates, 90)
        assert "fact_vue" in section
        assert "User uses Vue.js" in section
        assert "0.95" in section
        assert "90 days" in section

    def test_multiple_facts(self):
        candidates = [
            _make_fact("fact_a", "Fact A", "knowledge", 0.9, days_ago=100),
            _make_fact("fact_b", "Fact B", "preference", 0.8, days_ago=150),
        ]
        section = _build_staleness_section(candidates, 90)
        assert "fact_a" in section
        assert "fact_b" in section
        assert "<stale_facts>" in section


# ── _apply_updates with staleness removals ─────────────────────────────────


class TestApplyUpdatesStaleness:
    def test_stale_facts_removed(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_keep", "User knows Python", days_ago=100),
                _make_fact("fact_stale", "User uses Vue.js", days_ago=120),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_stale", "reason": "User switched to React"},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, staleness_max_removals_per_cycle=10),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert len(result["facts"]) == 1
        assert result["facts"][0]["id"] == "fact_keep"

    def test_safety_cap_limits_removals(self):
        updater = MemoryUpdater()
        # 5 stale facts, but cap is 2 → only 2 lowest-confidence should be removed
        current_memory = _make_memory(
            [
                _make_fact("fact_high", confidence=0.95, days_ago=100),
                _make_fact("fact_mid", confidence=0.80, days_ago=100),
                _make_fact("fact_low1", confidence=0.70, days_ago=100),
                _make_fact("fact_low2", confidence=0.65, days_ago=100),
                _make_fact("fact_low3", confidence=0.60, days_ago=100),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_high", "reason": "outdated"},
                {"id": "fact_mid", "reason": "outdated"},
                {"id": "fact_low1", "reason": "outdated"},
                {"id": "fact_low2", "reason": "outdated"},
                {"id": "fact_low3", "reason": "outdated"},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, staleness_max_removals_per_cycle=2),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # 5 - 2 = 3 facts remain; the 2 lowest-confidence removed
        assert len(result["facts"]) == 3
        remaining_ids = {f["id"] for f in result["facts"]}
        assert "fact_high" in remaining_ids
        assert "fact_mid" in remaining_ids
        assert "fact_low1" in remaining_ids

    def test_empty_stale_removals_no_effect(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_a", days_ago=100),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert len(result["facts"]) == 1

    def test_missing_stale_removals_key_no_effect(self):
        """When LLM doesn't return staleFactsToRemove, existing behavior is preserved."""
        updater = MemoryUpdater()
        current_memory = _make_memory([_make_fact("fact_a")])
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            # no staleFactsToRemove key
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert len(result["facts"]) == 1

    def test_contradiction_and_staleness_removals_combined(self):
        """Both factsToRemove and staleFactsToRemove work together."""
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_keep", days_ago=10),
                _make_fact("fact_contradicted", days_ago=10),
                _make_fact("fact_stale", days_ago=200),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": ["fact_contradicted"],
            "staleFactsToRemove": [{"id": "fact_stale", "reason": "old"}],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, staleness_max_removals_per_cycle=10),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert len(result["facts"]) == 1
        assert result["facts"][0]["id"] == "fact_keep"

    def test_protected_category_fact_refused_at_apply(self):
        """Regression: LLM hallucinating a correction-category fact id in
        staleFactsToRemove must be silently rejected at the apply layer,
        even though it appears in the serialized prompt JSON."""
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_stale", category="knowledge", days_ago=200),
                _make_fact("fact_correction", category="correction", days_ago=200),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_stale", "reason": "outdated"},
                {"id": "fact_correction", "reason": "LLM slip"},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                staleness_review_enabled=True,
                staleness_age_days=90,
                staleness_min_candidates=1,
                staleness_max_removals_per_cycle=10,
                staleness_protected_categories=["correction"],
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # fact_stale removed, fact_correction kept (protected)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["id"] == "fact_correction"

    def test_non_aged_fact_refused_at_apply(self):
        """Regression: LLM returning a fresh (non-aged) fact id in
        staleFactsToRemove must be silently rejected."""
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_stale", days_ago=200),
                _make_fact("fact_fresh", days_ago=10),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_stale", "reason": "outdated"},
                {"id": "fact_fresh", "reason": "LLM hallucination"},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                staleness_review_enabled=True,
                staleness_age_days=90,
                staleness_min_candidates=1,
                staleness_max_removals_per_cycle=10,
                staleness_protected_categories=["correction"],
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # fact_stale removed, fact_fresh kept (not in candidate set)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["id"] == "fact_fresh"

    def test_guardrail_runs_when_staleness_review_disabled(self):
        """Regression: guardrail must reject invalid ids even when
        staleness_review_enabled=False, so the protection is independent
        of the feature flag and model behavior."""
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_stale", days_ago=200),
                _make_fact("fact_fresh", days_ago=5),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_stale", "reason": "LLM hallucination"},
                {"id": "fact_fresh", "reason": "LLM hallucination"},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                staleness_review_enabled=False,
                staleness_age_days=90,
                staleness_min_candidates=3,
                staleness_max_removals_per_cycle=10,
                staleness_protected_categories=["correction"],
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # Guardrail runs regardless of feature flag:
        # fact_stale is a valid candidate (200 days old) → removed
        # fact_fresh is not a candidate (5 days old) → kept
        assert len(result["facts"]) == 1
        assert result["facts"][0]["id"] == "fact_fresh"


# ── _normalize_memory_update_data with staleFactsToRemove ─────────────────


class TestNormalizeStaleFactsToRemove:
    def test_valid_entries(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [
                {"id": "fact_a", "reason": "User moved offices"},
                {"id": "fact_b", "reason": "Tech stack changed"},
            ],
        }
        result = _normalize_memory_update_data(data)
        assert len(result["staleFactsToRemove"]) == 2
        assert result["staleFactsToRemove"][0]["id"] == "fact_a"
        assert result["staleFactsToRemove"][1]["reason"] == "Tech stack changed"

    def test_missing_key(self):
        data = {"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}
        result = _normalize_memory_update_data(data)
        assert result["staleFactsToRemove"] == []

    def test_non_list_ignored(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": "not a list",
        }
        result = _normalize_memory_update_data(data)
        assert result["staleFactsToRemove"] == []

    def test_non_dict_entries_skipped(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": ["just a string", 42, {"id": "fact_ok", "reason": "valid"}],
        }
        result = _normalize_memory_update_data(data)
        assert len(result["staleFactsToRemove"]) == 1
        assert result["staleFactsToRemove"][0]["id"] == "fact_ok"

    def test_empty_id_skipped(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [{"id": "", "reason": "no id"}],
        }
        result = _normalize_memory_update_data(data)
        assert result["staleFactsToRemove"] == []

    def test_non_string_reason_defaulted(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [{"id": "fact_a", "reason": 123}],
        }
        result = _normalize_memory_update_data(data)
        assert result["staleFactsToRemove"][0]["reason"] == ""

    def test_missing_reason_defaulted(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [{"id": "fact_a"}],
        }
        result = _normalize_memory_update_data(data)
        assert result["staleFactsToRemove"][0]["reason"] == ""


# ── Integration: _prepare_update_prompt ────────────────────────────────────


class TestPrepareUpdatePromptStaleness:
    def test_staleness_section_included_when_triggered(self):
        updater = MemoryUpdater()
        old_facts = [_make_fact(f"fact_{i}", days_ago=100) for i in range(5)]
        memory = _make_memory(old_facts)

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello, I'm using React now"

        config = _memory_config(
            enabled=True,
            staleness_review_enabled=True,
            staleness_age_days=90,
            staleness_min_candidates=3,
        )

        with (
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=config),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=memory),
        ):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Staleness Review" in prompt
        assert "<stale_facts>" in prompt

    def test_staleness_section_omitted_when_not_triggered(self):
        updater = MemoryUpdater()
        memory = _make_memory([])  # no facts at all

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        config = _memory_config(
            enabled=True,
            staleness_review_enabled=True,
            staleness_age_days=90,
            staleness_min_candidates=3,
        )

        with (
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=config),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=memory),
        ):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Staleness Review" not in prompt
        assert "<stale_facts>" not in prompt

    def test_staleness_section_omitted_when_disabled(self):
        updater = MemoryUpdater()
        old_facts = [_make_fact(f"fact_{i}", days_ago=200) for i in range(10)]
        memory = _make_memory(old_facts)

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        config = _memory_config(
            enabled=True,
            staleness_review_enabled=False,
        )

        with (
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=config),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=memory),
        ):
            result = updater._prepare_update_prompt(
                messages=[msg],
                agent_name=None,
                correction_detected=False,
                reinforcement_detected=False,
            )

        assert result is not None
        _, prompt = result
        assert "Staleness Review" not in prompt
