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
            return_value=_memory_config(max_facts=100, consolidation_max_sources=8),
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
            return_value=_memory_config(max_facts=100, consolidation_max_sources=5),
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
            return_value=_memory_config(max_facts=100, consolidation_max_groups_per_cycle=3, consolidation_max_sources=8),
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
            return_value=_memory_config(max_facts=100, consolidation_max_groups_per_cycle=3, consolidation_max_sources=8),
        ):
            result = updater._apply_updates(current_memory, update_data)

        merged = [f for f in result["facts"] if f.get("source") == "consolidation"]
        assert len(merged) == 1
        assert merged[0].get("sourceError") == "Agent used wrong approach"


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
