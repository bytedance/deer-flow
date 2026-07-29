"""Tests for DeerMem.search (the ABC search implementation).

DeerMem.search is a case-insensitive substring search over stored facts
(stand-in for the planned semantic retrieval). The optional ``category`` kwarg
filters BEFORE the ``top_k`` slice (it is on the ABC signature; the
``memory_search`` tool forwards it). These tests cover the backend's own search.
"""

from types import SimpleNamespace

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem


def _make_fact(content: str, category: str = "context", confidence: float = 0.7) -> dict:
    return {
        "id": f"fact_test_{hash(content) & 0xFFFFFFFF:08x}",
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": "2026-07-09T00:00:00Z",
        "source": "test",
    }


def _deer_mem_with_facts(facts: list[dict]) -> DeerMem:
    """Build a DeerMem whose updater returns the given facts (no disk I/O)."""
    mgr = DeerMem(backend_config=None)
    mgr._updater = SimpleNamespace(get_memory_data=lambda agent_name=None, *, user_id=None: {"facts": facts})
    return mgr


class TestDeerMemSearch:
    """Tests for DeerMem.search."""

    def test_basic_substring_match(self):
        """Should find facts containing the query string (case-insensitive)."""
        facts = [
            _make_fact("User prefers Python", "preference", 0.9),
            _make_fact("User works with TypeScript", "context", 0.7),
            _make_fact("User lives in Beijing", "personal", 0.8),
        ]
        mgr = _deer_mem_with_facts(facts)

        results = mgr.search("python")
        assert len(results) == 1
        assert results[0]["content"] == "User prefers Python"

    def test_case_insensitive(self):
        """Should match regardless of case."""
        mgr = _deer_mem_with_facts([_make_fact("User prefers Python", "preference", 0.9)])

        assert len(mgr.search("PYTHON")) == 1
        assert len(mgr.search("python")) == 1
        assert len(mgr.search("Python")) == 1

    def test_empty_query_returns_empty(self):
        """Should return empty list for empty query, not error."""
        mgr = _deer_mem_with_facts([_make_fact("Some fact")])

        assert mgr.search("") == []
        assert mgr.search("   ") == []

    def test_no_match_returns_empty(self):
        """Should return empty list when nothing matches."""
        mgr = _deer_mem_with_facts([_make_fact("User prefers Python")])

        assert mgr.search("Rust") == []

    def test_sorted_by_confidence_desc(self):
        """Should return results sorted by confidence descending."""
        facts = [
            _make_fact("Fact A", confidence=0.3),
            _make_fact("Fact B", confidence=0.9),
            _make_fact("Fact C", confidence=0.6),
        ]
        mgr = _deer_mem_with_facts(facts)

        results = mgr.search("Fact")
        assert len(results) == 3
        assert results[0]["confidence"] == 0.9
        assert results[1]["confidence"] == 0.6
        assert results[2]["confidence"] == 0.3

    def test_respects_top_k(self):
        """Should return at most ``top_k`` results."""
        facts = [_make_fact(f"Fact {i}", confidence=0.5) for i in range(20)]
        mgr = _deer_mem_with_facts(facts)

        results = mgr.search("Fact", top_k=5)
        assert len(results) == 5

    def test_null_confidence_does_not_crash_sort(self):
        """A fact stored with ``"confidence": null`` (corrupted/hand-edited memory)
        must not break the confidence sort. ``.get("confidence", 0)`` returns the
        stored ``None`` and comparing None with floats raises TypeError; the coerce
        helper defaults null to a finite midpoint instead."""
        null_fact = {
            "id": "fact_null",
            "content": "Fact with null confidence",
            "category": "context",
            "confidence": None,
            "createdAt": "2026-07-09T00:00:00Z",
            "source": "test",
        }
        facts = [
            _make_fact("Fact high", confidence=0.9),
            null_fact,
            _make_fact("Fact low", confidence=0.2),
        ]
        mgr = _deer_mem_with_facts(facts)

        # Must not raise TypeError during the confidence sort.
        results = mgr.search("Fact")

        assert len(results) == 3
        # Highest real confidence still sorts first; null (coerced to 0.5) sits
        # between the 0.9 and 0.2 facts.
        assert results[0]["content"] == "Fact high"
        assert {r["content"] for r in results} == {"Fact high", "Fact with null confidence", "Fact low"}

    def test_non_positive_top_k_returns_empty(self):
        """Should return empty for top_k <= 0 (no negative-slice expansion)."""
        mgr = _deer_mem_with_facts([_make_fact(f"Fact {i}", confidence=0.5) for i in range(3)])

        assert mgr.search("Fact", top_k=0) == []
        assert mgr.search("Fact", top_k=-1) == []

    def test_no_facts_returns_empty(self):
        """Should return empty list when memory has no facts."""
        mgr = _deer_mem_with_facts([])

        assert mgr.search("anything") == []

    def test_non_string_content_is_skipped(self):
        """Facts whose content is not a str are skipped, not crashed on."""
        facts = [
            {"id": "f1", "content": "likes uv", "category": "preference", "confidence": 0.9},
            {"id": "f2", "content": 42, "category": "context", "confidence": 0.5},
            {"id": "f3", "content": None, "category": "context", "confidence": 0.5},
        ]
        mgr = _deer_mem_with_facts(facts)

        results = mgr.search("uv")
        assert len(results) == 1
        assert results[0]["id"] == "f1"

    def test_category_filters_before_top_k_slice(self):
        """category filters BEFORE the top_k slice, so a category-scoped search
        is not starved by higher-confidence facts in other categories."""
        facts = [
            _make_fact("uv fast", "preference", 0.9),
            _make_fact("uv tool", "context", 0.95),
            _make_fact("uv python", "context", 0.9),
            _make_fact("uv rust", "context", 0.85),
        ]
        mgr = _deer_mem_with_facts(facts)

        # top_k=1 without category -> the single highest-confidence fact (context, 0.95)
        assert mgr.search("uv", top_k=1)[0]["category"] == "context"
        # top_k=1 WITH category=preference -> the preference fact (0.9), not
        # starved by the higher-confidence context facts that would otherwise
        # occupy the top_k slice first.
        pref = mgr.search("uv", top_k=1, category="preference")
        assert len(pref) == 1
        assert pref[0]["category"] == "preference"
        assert pref[0]["content"] == "uv fast"

    def test_category_none_returns_all_categories(self):
        """category=None (default) returns facts from all categories."""
        facts = [
            _make_fact("uv a", "preference", 0.9),
            _make_fact("uv b", "context", 0.5),
        ]
        mgr = _deer_mem_with_facts(facts)

        assert len(mgr.search("uv", category=None)) == 2


# ---------------------------------------------------------------------------
# Issue #4495 relevance-aware retrieval - backend search tests
# ---------------------------------------------------------------------------


class TestDeerMemRelevanceSearch:
    """Strategy='relevance' changes to DeerMem.search."""

    def _activate_relevance(
        self,
        monkeypatch,
        *,
        relevance_weight: float = 0.7,
        confidence_weight: float = 0.3,
        diversity_weight: float = 0.0,
        duplicate_threshold: float = 0.7,
    ) -> None:
        from deerflow.config.memory_config import MemoryConfig

        config = MemoryConfig(
            retrieval_strategy="relevance",
            retrieval_relevance_weight=relevance_weight,
            retrieval_confidence_weight=confidence_weight,
            retrieval_diversity_weight=diversity_weight,
            retrieval_duplicate_threshold=duplicate_threshold,
        )
        monkeypatch.setattr("deerflow.config.memory_config.get_memory_config", lambda: config)

    def test_legacy_strategy_unchanged_confidence_rank(self, monkeypatch) -> None:
        """strategy=legacy must produce byte-identical results to before the
        retrieval-strategy code was added: only confidence matters for the
        sort order, even when the query only matches one fact's content."""
        from deerflow.config.memory_config import MemoryConfig

        config = MemoryConfig(retrieval_strategy="legacy")
        monkeypatch.setattr("deerflow.config.memory_config.get_memory_config", lambda: config)
        facts = [
            _make_fact("uv python rust go tool", confidence=0.3),  # matches "uv" but low conf
            _make_fact("unrelated fact about database", confidence=0.95),
        ]
        mgr = _deer_mem_with_facts(facts)
        results = mgr.search("uv", top_k=5)
        assert len(results) == 1
        assert results[0]["content"] == "uv python rust go tool"
        # Confidence descending still holds when multiple results match the query.
        more_facts = [
            _make_fact("uv A", confidence=0.2),
            _make_fact("uv B both", confidence=0.9),
            _make_fact("uv C match", confidence=0.5),
        ]
        mgr2 = _deer_mem_with_facts(more_facts)
        results = mgr2.search("uv")
        assert [r["confidence"] for r in results] == [0.9, 0.5, 0.2]

    def test_relevance_boosts_query_matched_fact_above_high_confidence_stale(self, monkeypatch) -> None:
        """strategy=relevance with high relevance_weight: facts whose content
        shares many tokens with the search query rank above high-confidence
        facts whose content matches only the bare query substring."""
        self._activate_relevance(monkeypatch, relevance_weight=0.8, confidence_weight=0.2)
        facts = [
            # High confidence but zero lexical match for "pool debugging" query
            # besides the single token "uv" that is shared by everything.
            _make_fact("uv unrelated fact about migrations", confidence=0.98),
            # Low confidence but shares two strong query tokens with the
            # search query (pool + debugging).
            _make_fact("uv sqlalchemy pool for debugging connection leaks", confidence=0.4),
        ]
        mgr = _deer_mem_with_facts(facts)
        results = mgr.search("sqlalchemy pool debugging")
        assert len(results) == 2
        # Token-relevant result ranks first despite the large confidence gap.
        assert results[0]["confidence"] == 0.4
        assert results[0]["content"].startswith("uv sqlalchemy pool")

    def test_relevance_category_filtering_before_ranking(self, monkeypatch) -> None:
        """The category argument still filters BEFORE relevance ranking and
        before top_k — preserved legacy contract, explicitly listed in issue
        #4495 as required behaviour."""
        self._activate_relevance(monkeypatch)
        facts = [
            _make_fact("postgres migration in detail detail", "knowledge", 0.99),
            _make_fact("db migrate database schema detail", "context", 0.3),
            _make_fact("db migration detail detail", "knowledge", 0.2),
        ]
        mgr = _deer_mem_with_facts(facts)
        # top_k=1 + category=context: must return the context fact even
        # though the two knowledge facts have higher confidence AND higher
        # relevance (both share more tokens w/ the query "migration detail").
        res = mgr.search("migration detail", category="context", top_k=1)
        assert len(res) == 1
        assert res[0]["category"] == "context"

    def test_relevance_diversity_penalty_duplicate_suppression(self, monkeypatch) -> None:
        """With diversity_weight>0, a very high overlap duplicate receives a
        penalty that demotes it below a dissimilar fact it would otherwise
        outrank on composite+confidence alone."""
        self._activate_relevance(
            monkeypatch,
            relevance_weight=0.4,
            confidence_weight=0.1,
            diversity_weight=0.5,
            duplicate_threshold=0.5,
        )
        facts = [
            _make_fact("python postgres connection psycopg2 pool setup", confidence=0.95),
            # Near-duplicate of fact 0
            _make_fact(
                "python postgres connection psycopg2 connection pool setup",
                confidence=0.9,
            ),
            # Dissimilar fact on same query tokens
            _make_fact(
                "django debug toolbar postgres queries enable sqlalchemy echo",
                confidence=0.55,
            ),
        ]
        mgr = _deer_mem_with_facts(facts)
        results = mgr.search("postgres psycopg2 connection pool")
        # The unique echo/toolbar fact must rank above the duplicate if the
        # duplicate received a diversity penalty. Assert that it is not at
        # position 2 directly after the duplicate unless the echo/toolbar
        # fact was penalised too (it is dissimilar to fact 0).
        contents = [r["content"] for r in results]
        echo_idx = contents.index("django debug toolbar postgres queries enable sqlalchemy echo")
        duplicate_idx = contents.index("python postgres connection psycopg2 connection pool setup")
        # The unique fact must come before the later duplicate when the
        # duplicate's diversity penalty is strong enough to outweigh its
        # confidence advantage (0.9 vs 0.55).
        assert echo_idx < duplicate_idx

    def test_retrieval_top_k_global_cap_applied_before_caller_top_k(self, monkeypatch) -> None:
        """If retrieval_top_k (global operator cap) is set and is strictly
        lower than the caller's top_k, then retrieval_top_k wins so an
        operator can trim results globally without touching individual tool
        call sites."""
        from deerflow.config.memory_config import MemoryConfig

        config = MemoryConfig(
            retrieval_strategy="relevance",
            retrieval_relevance_weight=0.7,
            retrieval_confidence_weight=0.3,
            retrieval_top_k=2,
        )
        monkeypatch.setattr("deerflow.config.memory_config.get_memory_config", lambda: config)
        facts = [_make_fact(f"postgres detail {i}", confidence=0.9 - 0.05 * i) for i in range(8)]
        mgr = _deer_mem_with_facts(facts)
        results = mgr.search("postgres", top_k=10)
        # Caller asked for 10 but global retrieval_top_k caps at 2.
        assert len(results) == 2


class TestRetrievalWeightNormalization:
    """MemoryConfig retrieval weights ratio-normalize to sum=1 at validation."""

    def test_default_weights_sum_to_one(self) -> None:
        from deerflow.config.memory_config import MemoryConfig

        cfg = MemoryConfig()
        total = cfg.retrieval_relevance_weight + cfg.retrieval_confidence_weight + cfg.retrieval_diversity_weight
        assert abs(total - 1.0) < 1e-9

    def test_large_int_ratio_weights_normalise(self) -> None:
        from deerflow.config.memory_config import MemoryConfig

        cfg = MemoryConfig(
            retrieval_relevance_weight=60,
            retrieval_confidence_weight=40,
            retrieval_diversity_weight=0,
        )
        assert abs(cfg.retrieval_relevance_weight - 0.6) < 1e-9
        assert abs(cfg.retrieval_confidence_weight - 0.4) < 1e-9
        assert cfg.retrieval_diversity_weight == 0.0

    def test_all_zero_weights_fall_back_confidence_only(self) -> None:
        """If every weight is 0 (user disables everything explicitly) the
        validator maps it to confidence-only. This prevents NaN composites
        downstream (0/0 division)."""
        from deerflow.config.memory_config import MemoryConfig

        cfg = MemoryConfig(
            retrieval_relevance_weight=0,
            retrieval_confidence_weight=0,
            retrieval_diversity_weight=0,
        )
        assert cfg.retrieval_relevance_weight == 0.0
        assert cfg.retrieval_confidence_weight == 1.0
        assert cfg.retrieval_diversity_weight == 0.0

    def test_negative_weights_clamp_to_zero(self) -> None:
        """Pydantic ge=0 on each weight clamps negatives at validation time;
        we verify at runtime to ensure downstream scores never see negative
        weight multiplication."""
        import pytest
        from pydantic import ValidationError

        from deerflow.config.memory_config import MemoryConfig

        with pytest.raises(ValidationError):
            MemoryConfig(retrieval_relevance_weight=-0.1)
