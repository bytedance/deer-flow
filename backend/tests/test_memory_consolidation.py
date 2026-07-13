"""Tests for the memory consolidation feature in the memory updater.

Covers:
- Candidate selection (category fragmentation threshold)
- Trigger conditions (min facts, enabled flag)
- Prompt section formatting
- Consolidation apply in _apply_updates (guardrails, observability)
- Normalization of factsToConsolidate from LLM responses
- Integration with _prepare_update_prompt
"""

from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.updater import (
    MemoryUpdater,
    _build_consolidation_section,
    _normalize_memory_update_data,
    _select_consolidation_candidates,
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
) -> dict:
    return {
        "id": fact_id,
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": "2026-01-01T00:00:00Z",
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


# ── _select_consolidation_candidates ──────────────────────────────────────


class TestSelectConsolidationCandidates:
    def test_empty_facts(self):
        memory = _make_memory([])
        config = _memory_config(consolidation_min_facts=8)
        assert _select_consolidation_candidates(memory, config) == {}

    def test_below_threshold(self):
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(5)])
        config = _memory_config(consolidation_min_facts=8)
        assert _select_consolidation_candidates(memory, config) == {}

    def test_at_threshold(self):
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(8)])
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert "knowledge" in result
        assert len(result["knowledge"]) == 8

    def test_above_threshold(self):
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(12)])
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert "knowledge" in result
        assert len(result["knowledge"]) == 12

    def test_multiple_categories(self):
        facts = [_make_fact(f"k_{i}", category="knowledge") for i in range(10)] + [_make_fact(f"p_{i}", category="preference") for i in range(9)] + [_make_fact(f"c_{i}", category="context") for i in range(3)]
        memory = _make_memory(facts)
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert "knowledge" in result
        assert "preference" in result
        assert "context" not in result  # only 3, below threshold

    def test_non_dict_facts_skipped(self):
        memory = _make_memory(
            [_make_fact(f"fact_{i}", category="knowledge") for i in range(8)] + ["not a dict", 42]  # type: ignore[list-item]
        )
        config = _memory_config(consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert len(result.get("knowledge", [])) == 8


# ── Trigger conditions ────────────────────────────────────────────────────


class TestConsolidationTriggerConditions:
    def test_disabled_means_no_trigger(self):
        config = _memory_config(consolidation_enabled=False)
        assert config.consolidation_enabled is False

    def test_enabled_with_enough_facts(self):
        memory = _make_memory([_make_fact(f"fact_{i}", category="knowledge") for i in range(10)])
        config = _memory_config(consolidation_enabled=True, consolidation_min_facts=8)
        result = _select_consolidation_candidates(memory, config)
        assert len(result) > 0


# ── _build_consolidation_section ──────────────────────────────────────────


class TestBuildConsolidationSection:
    def test_empty_candidates(self):
        assert _build_consolidation_section({}) == ""

    def test_includes_fact_details(self):
        candidates = {
            "knowledge": [
                _make_fact("fact_vue", "User uses Vue.js", "knowledge", 0.95),
                _make_fact("fact_react", "User uses React", "knowledge", 0.85),
            ],
        }
        section = _build_consolidation_section(candidates)
        assert "fact_vue" in section
        assert "User uses Vue.js" in section
        assert "0.95" in section
        assert "consolidation_candidates" in section

    def test_multiple_categories(self):
        candidates = {
            "knowledge": [_make_fact(f"k_{i}", category="knowledge") for i in range(3)],
            "preference": [_make_fact(f"p_{i}", category="preference") for i in range(3)],
        }
        section = _build_consolidation_section(candidates)
        assert 'category="knowledge"' in section
        assert 'category="preference"' in section
        assert "Memory Consolidation" in section

    def test_html_special_chars_in_content_are_escaped(self):
        """Fact content with XML tags or quotes is HTML-escaped so it cannot
        break the surrounding prompt structure."""
        candidates = {
            "knowledge": [
                _make_fact("fact_x", 'Like <b>bold</b> & "quotes"', "knowledge", 0.9),
                _make_fact("fact_y", "normal content", "knowledge", 0.8),
            ],
        }
        section = _build_consolidation_section(candidates)
        assert "<b>" not in section
        assert "&lt;b&gt;" in section
        assert "&amp;" in section
        assert "&quot;" in section

    def test_closing_tag_in_content_is_escaped(self):
        """A closing </consolidation_candidates> tag in content must not
        prematurely end the prompt XML block."""
        candidates = {
            "knowledge": [
                _make_fact("fact_a", "</consolidation_candidates><evil>injected</evil>", "knowledge", 0.9),
                _make_fact("fact_b", "normal", "knowledge", 0.8),
            ],
        }
        section = _build_consolidation_section(candidates)
        assert "</consolidation_candidates><evil>" not in section
        assert "&lt;/consolidation_candidates&gt;" in section

    def test_special_chars_in_category_attribute_are_escaped(self):
        """A category name with a quote character must not break the XML
        attribute value in the prompt."""
        candidates = {
            'pref"erences': [_make_fact(f"f_{i}", category='pref"erences') for i in range(3)],
        }
        section = _build_consolidation_section(candidates)
        assert 'category="pref"erences"' not in section
        assert "pref&quot;erences" in section


# ── _normalize_memory_update_data with factsToConsolidate ─────────────────


class TestNormalizeFactsToConsolidate:
    def test_valid_entries(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {
                        "content": "User is a full-stack engineer",
                        "category": "knowledge",
                        "confidence": 0.9,
                    },
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert len(result["factsToConsolidate"]) == 1
        assert result["factsToConsolidate"][0]["sourceIds"] == ["fact_a", "fact_b"]
        assert result["factsToConsolidate"][0]["consolidated"]["content"] == "User is a full-stack engineer"

    def test_missing_key(self):
        data = {"user": {}, "history": {}, "newFacts": [], "factsToRemove": [], "staleFactsToRemove": []}
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_non_list_ignored(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": "not a list",
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_single_source_skipped(self):
        """Consolidation with < 2 sources is not real consolidation."""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_only"],
                    "consolidated": {"content": "should be skipped", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_empty_content_skipped(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "  ", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []

    def test_non_dict_consolidated_skipped(self):
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": "just a string",
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == []


# ── _apply_updates with consolidation ─────────────────────────────────────


class TestApplyUpdatesConsolidation:
    def test_consolidation_removes_sources_adds_merged(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_a", "User uses React", "knowledge", 0.9),
                _make_fact("fact_b", "User uses Python", "knowledge", 0.85),
                _make_fact("fact_c", "User uses PostgreSQL", "knowledge", 0.8),
                _make_fact("fact_keep", "User likes music", "preference", 0.7),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b", "fact_c"],
                    "consolidated": {
                        "content": "Full-stack: React frontend, Python backend, PostgreSQL",
                        "category": "knowledge",
                        "confidence": 0.9,
                    },
                },
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                consolidation_min_facts=3,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # 3 sources removed, 1 consolidated added, fact_keep preserved
        assert len(result["facts"]) == 2
        remaining_ids = {f["id"] for f in result["facts"]}
        assert "fact_keep" in remaining_ids
        assert "fact_a" not in remaining_ids
        assert "fact_b" not in remaining_ids
        assert "fact_c" not in remaining_ids
        consolidated = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(consolidated) == 1
        assert "Full-stack" in consolidated[0]["content"]
        assert consolidated[0]["consolidatedFrom"] == ["fact_a", "fact_b", "fact_c"]

    def test_max_groups_cap(self):
        """Only consolidation_max_groups_per_cycle groups are processed."""
        updater = MemoryUpdater()
        facts = [_make_fact(f"f_{i}", f"Fact {i}", "knowledge", 0.8) for i in range(10)]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {"sourceIds": ["f_0", "f_1"], "consolidated": {"content": "Group 1", "category": "knowledge", "confidence": 0.8}},
                {"sourceIds": ["f_2", "f_3"], "consolidated": {"content": "Group 2", "category": "knowledge", "confidence": 0.8}},
                {"sourceIds": ["f_4", "f_5"], "consolidated": {"content": "Group 3", "category": "knowledge", "confidence": 0.8}},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                consolidation_max_groups_per_cycle=2,  # cap at 2
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # Only first 2 groups processed: 4 sources removed, 2 consolidated added
        consolidated = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(consolidated) == 2

    def test_nonexistent_source_id_refused(self):
        """LLM hallucinating a non-existent fact ID is silently rejected."""
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_a", "Fact A", "knowledge", 0.9),
                _make_fact("fact_b", "Fact B", "knowledge", 0.8),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_hallucinated"],
                    "consolidated": {"content": "Should not apply", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, consolidation_enabled=True, consolidation_min_facts=2, consolidation_max_sources=8),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # Nothing consolidated, original facts preserved
        assert len(result["facts"]) == 2

    def test_over_max_sources_refused(self):
        """Groups exceeding consolidation_max_sources are rejected."""
        updater = MemoryUpdater()
        facts = [_make_fact(f"f_{i}", f"Fact {i}", "knowledge", 0.8) for i in range(10)]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": [f"f_{i}" for i in range(10)],  # 10 sources, cap is 5
                    "consolidated": {"content": "Over-merged", "category": "knowledge", "confidence": 0.8},
                },
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, consolidation_enabled=True, consolidation_max_sources=5),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # Nothing consolidated
        assert len(result["facts"]) == 10

    def test_double_consume_prevented(self):
        """A fact ID used in one group cannot be reused in another."""
        updater = MemoryUpdater()
        current_memory = _make_memory(
            [
                _make_fact("fact_a", "A", "knowledge", 0.9),
                _make_fact("fact_b", "B", "knowledge", 0.8),
                _make_fact("fact_c", "C", "knowledge", 0.7),
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {"sourceIds": ["fact_a", "fact_b"], "consolidated": {"content": "AB", "category": "knowledge", "confidence": 0.9}},
                {"sourceIds": ["fact_b", "fact_c"], "consolidated": {"content": "BC", "category": "knowledge", "confidence": 0.8}},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, consolidation_enabled=True, consolidation_min_facts=3, consolidation_max_groups_per_cycle=3, consolidation_max_sources=8),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # First group succeeds (fact_a, fact_b consumed), second skipped (fact_b already consumed)
        consolidated = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(consolidated) == 1
        assert consolidated[0]["content"] == "AB"

    def test_consolidation_with_staleness_and_contradiction(self):
        """All three removal paths (contradiction, staleness, consolidation) work together."""
        updater = MemoryUpdater()
        from datetime import UTC, datetime, timedelta

        old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat().replace("+00:00", "Z")
        current_memory = _make_memory(
            [
                {"id": "fact_contradicted", "content": "Old claim", "category": "knowledge", "confidence": 0.7, "createdAt": old_date, "source": "test"},
                {"id": "fact_stale", "content": "Stale fact", "category": "knowledge", "confidence": 0.6, "createdAt": old_date, "source": "test"},
                {"id": "fact_a", "content": "React", "category": "knowledge", "confidence": 0.9, "createdAt": old_date, "source": "test"},
                {"id": "fact_b", "content": "Python", "category": "knowledge", "confidence": 0.85, "createdAt": old_date, "source": "test"},
            ]
        )
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": ["fact_contradicted"],
            "staleFactsToRemove": [{"id": "fact_stale", "reason": "outdated"}],
            "factsToConsolidate": [
                {"sourceIds": ["fact_a", "fact_b"], "consolidated": {"content": "React + Python", "category": "knowledge", "confidence": 0.9}},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                consolidation_min_facts=2,
                staleness_max_removals_per_cycle=10,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # contradiction removed fact_contradicted, staleness removed fact_stale,
        # consolidation merged fact_a + fact_b into 1
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "React + Python"


# ── Regression tests for reviewer findings ────────────────────────────────


class TestReviewerFindings:
    def test_duplicate_source_ids_rejected(self):
        """#1: ["f1","f1"] must not bypass the ≥2-distinct-sources check."""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_a"],
                    "consolidated": {"content": "Rewritten", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"] == [], "duplicate IDs should collapse to 1 and be rejected"

    def test_protected_category_not_selected(self):
        """#4: staleness_protected_categories must be exempt from consolidation candidates."""
        correction_facts = [_make_fact(f"c_{i}", category="correction") for i in range(10)]
        knowledge_facts = [_make_fact(f"k_{i}", category="knowledge") for i in range(10)]
        memory = _make_memory(correction_facts + knowledge_facts)
        config = _memory_config(consolidation_min_facts=8, consolidation_enabled=True)
        result = _select_consolidation_candidates(memory, config)
        assert "correction" not in result, "protected category must not appear in consolidation candidates"
        assert "knowledge" in result

    def test_count_attribute_capped_at_max_sources(self):
        """#3: count= must reflect the number of facts shown, not the full category size."""
        big_group = [_make_fact(f"f_{i}", category="knowledge") for i in range(20)]
        candidates = {"knowledge": big_group}
        section = _build_consolidation_section(candidates, max_groups=3, max_sources=8)
        # The XML attribute count must be 8 (shown), not 20 (total)
        assert 'count="8"' in section
        assert 'count="20"' not in section

    def test_category_stripped_in_normalization(self):
        """#5: padded/empty category must be normalised, not stored verbatim."""
        data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Merged", "category": "  knowledge  ", "confidence": 0.9},
                },
                {
                    "sourceIds": ["fact_c", "fact_d"],
                    "consolidated": {"content": "Also merged", "category": "   ", "confidence": 0.85},
                },
            ],
        }
        result = _normalize_memory_update_data(data)
        assert result["factsToConsolidate"][0]["consolidated"]["category"] == "knowledge"
        assert result["factsToConsolidate"][1]["consolidated"]["category"] == "context"

    def test_consolidation_runs_after_trim(self):
        """#2: sources trimmed away before consolidation must be rejected, not deleted."""
        updater = MemoryUpdater()
        # 3 low-confidence facts that consolidation wants to merge
        facts = [
            _make_fact("low_a", "Low conf A", "knowledge", 0.71),
            _make_fact("low_b", "Low conf B", "knowledge", 0.71),
            # 1 fact that will survive the trim
            _make_fact("high_keep", "High conf fact", "preference", 0.99),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [
                # 2 high-confidence new facts that push us to max_facts=3,
                # forcing the trim to evict low_a and low_b
                {"content": "New high 1", "category": "knowledge", "confidence": 0.98},
                {"content": "New high 2", "category": "knowledge", "confidence": 0.97},
            ],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["low_a", "low_b"],
                    "consolidated": {"content": "Merged low", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=3,
                consolidation_enabled=True,
                consolidation_min_facts=2,
                fact_confidence_threshold=0.7,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # After trim: high_keep(0.99) + new_high_1(0.98) + new_high_2(0.97) = 3 facts.
        # low_a and low_b were evicted by the trim, so consolidation is rejected
        # (source IDs no longer exist) — neither low_a/low_b nor "Merged low" appear.
        ids = {f["id"] for f in result["facts"]}
        contents = {f["content"] for f in result["facts"]}
        assert "Merged low" not in contents, "consolidated fact must not appear when sources were trimmed"
        assert "Low conf A" not in contents, "evicted source must not reappear"
        assert "Low conf B" not in contents, "evicted source must not reappear"
        assert len(result["facts"]) == 3
        assert "high_keep" in ids

    def test_source_error_propagated(self):
        """#6: sourceError from source facts must be carried into the consolidated fact."""
        updater = MemoryUpdater()
        facts = [
            {**_make_fact("fact_a", "Fact A", "knowledge", 0.9), "sourceError": "Agent used wrong approach"},
            _make_fact("fact_b", "Fact B", "knowledge", 0.85),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Merged AB", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, consolidation_enabled=True, consolidation_min_facts=2, consolidation_max_groups_per_cycle=3, consolidation_max_sources=8),
        ):
            result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1
        assert merged[0].get("sourceError") == "Agent used wrong approach"

    def test_protected_category_rejected_at_apply_time(self):
        """P1: correction facts proposed by LLM slip must be rejected at apply time."""
        updater = MemoryUpdater()
        # correction category has consolidation_min_facts-1 facts (below threshold),
        # but we give the LLM a chance to propose them anyway (simulating a slip).
        # We need ≥ consolidation_min_facts correction facts to even appear in
        # allowed_source_ids — so we put them BELOW threshold to confirm they're blocked.
        correction_facts = [{**_make_fact(f"corr_{i}", f"Correction {i}", "correction", 0.95), "sourceError": "wrong approach"} for i in range(3)]
        current_memory = _make_memory(correction_facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["corr_0", "corr_1"],
                    "consolidated": {"content": "Merged corrections", "category": "correction", "confidence": 0.95},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                consolidation_min_facts=8,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        # All 3 correction facts must survive untouched
        assert len(result["facts"]) == 3
        ids = {f["id"] for f in result["facts"]}
        assert "corr_0" in ids and "corr_1" in ids and "corr_2" in ids
        assert all(f.get("source") != "consolidation" for f in result["facts"])

    def test_confidence_cap_and_threshold_gate(self):
        """P2a: LLM-returned confidence is capped at max source confidence; result below threshold is rejected."""
        updater = MemoryUpdater()
        facts = [
            _make_fact("fact_a", "Fact A", "knowledge", 0.75),
            _make_fact("fact_b", "Fact B", "knowledge", 0.75),
        ]
        current_memory = _make_memory(facts)

        # Case 1: LLM returns conf=1.0, sources max at 0.75 → capped to 0.75
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Merged", "category": "knowledge", "confidence": 1.0},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                fact_confidence_threshold=0.7,
                consolidation_min_facts=2,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1, "merge should succeed"
        assert merged[0]["confidence"] == 0.75, "confidence must be capped at max source confidence"

        # Case 2: sources max at 0.65, below fact_confidence_threshold=0.7 → rejected
        facts2 = [
            _make_fact("fact_c", "Fact C", "knowledge", 0.65),
            _make_fact("fact_d", "Fact D", "knowledge", 0.60),
        ]
        current_memory2 = _make_memory(facts2)
        update_data2 = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_c", "fact_d"],
                    "consolidated": {"content": "Below threshold", "category": "knowledge", "confidence": 1.0},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                fact_confidence_threshold=0.7,
                consolidation_min_facts=2,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result2 = updater._apply_updates(current_memory2, update_data2)

        # Both source facts must survive untouched — consolidation was rejected
        assert len(result2["facts"]) == 2
        assert all(f.get("source") != "consolidation" for f in result2["facts"])

    def test_apply_gate_consolidation_disabled(self):
        """P2b: factsToConsolidate present but consolidation_enabled=False → nothing merged at apply time."""
        updater = MemoryUpdater()
        facts = [
            _make_fact("fact_a", "Fact A", "knowledge", 0.9),
            _make_fact("fact_b", "Fact B", "knowledge", 0.85),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    "consolidated": {"content": "Should not merge", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=False,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        assert len(result["facts"]) == 2, "both source facts must survive when consolidation is disabled"
        assert all(f.get("source") != "consolidation" for f in result["facts"])

    def test_consolidation_enabled_defaults_to_false(self):
        """Finding 1: consolidation is opt-in — default must be False to avoid lossy mutations on first deploy."""
        from deerflow.config.memory_config import MemoryConfig

        assert MemoryConfig().consolidation_enabled is False

    def test_null_confidence_renders_consistently_with_cap(self):
        """Finding 2: a fact with confidence=None must show the same value in the prompt as in the confidence cap."""
        null_fact = {**_make_fact("fact_null", "null conf fact", "knowledge"), "confidence": None}
        other_fact = _make_fact("fact_b", "normal fact", "knowledge", 0.9)

        # Prompt rendering must use _coerce_source_confidence default (0.5), not 0.0
        section = _build_consolidation_section({"knowledge": [null_fact, other_fact]})
        assert "0.50" in section, "null confidence must render as 0.50 (coerced default), not 0.00"
        assert "0.00" not in section

        # Apply-time cap must also use 0.5 for the null-confidence source
        updater = MemoryUpdater()
        current_memory = _make_memory([null_fact, other_fact])
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_null", "fact_b"],
                    # LLM returns 1.0; cap = max(0.5, 0.9) = 0.9
                    "consolidated": {"content": "Merged", "category": "knowledge", "confidence": 1.0},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                fact_confidence_threshold=0.5,
                consolidation_enabled=True,
                consolidation_min_facts=2,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1, "merge should succeed"
        # cap = max(coerce(null)=0.5, coerce(0.9)=0.9) = 0.9; LLM conf 1.0 capped → 0.9
        assert merged[0]["confidence"] == pytest.approx(0.9)

    def test_consolidated_created_at_tracks_newest_source(self):
        """Finding 3: createdAt must equal the newest source's createdAt (not now) to preserve staleness eligibility."""
        updater = MemoryUpdater()
        older_date = "2025-01-01T00:00:00Z"
        newer_date = "2026-03-15T12:00:00Z"
        facts = [
            {**_make_fact("fact_old", "Old fact", "knowledge", 0.9), "createdAt": older_date},
            {**_make_fact("fact_new", "New fact", "knowledge", 0.85), "createdAt": newer_date},
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_old", "fact_new"],
                    "consolidated": {"content": "Old and new merged", "category": "knowledge", "confidence": 0.9},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                consolidation_min_facts=2,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1
        # createdAt must be the newest source's date — staleness clock not reset
        assert merged[0]["createdAt"] == newer_date, "createdAt must equal newest source's date"
        # consolidatedAt must be present as an audit field
        assert "consolidatedAt" in merged[0], "consolidatedAt must be set for auditability"
        # consolidatedAt should be more recent than the source dates
        assert merged[0]["consolidatedAt"] > newer_date

    def test_confidence_fallback_to_max_source_when_llm_omits_field(self):
        """Finding 5: when LLM omits confidence field entirely, merged fact uses max_source_conf."""
        updater = MemoryUpdater()
        facts = [
            _make_fact("fact_a", "Fact A", "knowledge", 0.85),
            _make_fact("fact_b", "Fact B", "knowledge", 0.75),
        ]
        current_memory = _make_memory(facts)
        update_data = {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "factsToConsolidate": [
                {
                    "sourceIds": ["fact_a", "fact_b"],
                    # LLM omits the confidence field entirely
                    "consolidated": {"content": "Merged without confidence", "category": "knowledge"},
                },
            ],
        }
        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(
                max_facts=100,
                consolidation_enabled=True,
                consolidation_min_facts=2,
                consolidation_max_groups_per_cycle=3,
                consolidation_max_sources=8,
            ),
        ):
            result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1, "merge should succeed"
        # fallback: max(coerce(0.85), coerce(0.75)) = 0.85
        assert merged[0]["confidence"] == pytest.approx(0.85)


# ── Integration: _prepare_update_prompt ────────────────────────────────────


class TestPrepareUpdatePromptConsolidation:
    def test_consolidation_section_included_when_triggered(self):
        updater = MemoryUpdater()
        facts = [_make_fact(f"fact_{i}", f"Knowledge {i}", "knowledge", 0.8) for i in range(10)]
        memory = _make_memory(facts)

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        config = _memory_config(
            enabled=True,
            consolidation_enabled=True,
            consolidation_min_facts=8,
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
        assert "Memory Consolidation" in prompt
        assert "consolidation_candidates" in prompt

    def test_consolidation_section_omitted_when_not_triggered(self):
        updater = MemoryUpdater()
        memory = _make_memory([_make_fact("fact_only", category="knowledge")])

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        config = _memory_config(
            enabled=True,
            consolidation_enabled=True,
            consolidation_min_facts=8,
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
        assert "Memory Consolidation" not in prompt

    def test_consolidation_section_omitted_when_disabled(self):
        updater = MemoryUpdater()
        facts = [_make_fact(f"fact_{i}", category="knowledge") for i in range(20)]
        memory = _make_memory(facts)

        msg = MagicMock()
        msg.type = "human"
        msg.content = "Hello"

        config = _memory_config(
            enabled=True,
            consolidation_enabled=False,
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
        assert "Memory Consolidation" not in prompt
