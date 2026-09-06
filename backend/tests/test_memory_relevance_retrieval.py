"""Tests for the optional relevance-aware retrieval strategy (issue #4495).

The strategy is opt-in via DeerMem-private config
(``retrieval_relevance_enabled``) and must never change the default
confidence-based behavior. Coverage:

- deterministic lexical relevance + confidence scoring;
- greedy MMR diversity selection;
- ``DeerMem.search`` relevance mode (including related facts without a
  literal substring match);
- prompt-injection fact ordering under a query;
- the DynamicContextMiddleware -> ``_get_memory_context`` query wiring.
"""

from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.relevance import (
    build_idf,
    diversify,
    lexical_relevance,
    rank_facts,
    tokenize,
)
from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware


def _make_fact(content: str, category: str = "context", confidence: float = 0.7) -> dict:
    return {
        "id": f"fact_test_{hash(content) & 0xFFFFFFFF:08x}",
        "content": content,
        "category": category,
        "confidence": confidence,
        "createdAt": "2026-07-09T00:00:00Z",
        "source": "test",
    }


def _deer_mem_with_facts(facts: list[dict], backend_config: dict | None = None) -> DeerMem:
    """Build a DeerMem whose updater returns the given facts (no disk I/O)."""
    mgr = DeerMem(backend_config=backend_config)
    mgr._updater = SimpleNamespace(get_memory_data=lambda agent_name=None, *, user_id=None: {"facts": facts})
    return mgr


# ---------------------------------------------------------------------------
# Lexical relevance scoring
# ---------------------------------------------------------------------------


class TestLexicalRelevance:
    def test_overlapping_content_scores_higher_than_unrelated(self):
        query = "database migration"
        related = lexical_relevance(query, "Migrations are managed with alembic and a PostgreSQL database")
        unrelated = lexical_relevance(query, "User prefers cooking Italian food on weekends")
        assert related > unrelated

    def test_zero_for_no_overlap(self):
        assert lexical_relevance("python", "User lives in Beijing") == 0.0

    def test_case_insensitive(self):
        assert lexical_relevance("PYTHON", "User prefers Python") > 0.0

    def test_substring_signal_without_word_boundaries(self):
        """CJK / unsegmented content: containment still contributes relevance."""
        assert lexical_relevance("Python", "我喜欢Python编程") > 0.0

    def test_empty_query_scores_zero(self):
        assert lexical_relevance("", "anything") == 0.0
        assert lexical_relevance("   ", "anything") == 0.0


class TestIdf:
    def test_common_tokens_are_downweighted(self):
        corpus = [
            tokenize("database migration conventions"),
            tokenize("database backup schedule"),
            tokenize("database replica lag"),
            tokenize("the database is used everywhere"),
        ]
        idf = build_idf(corpus)
        assert idf["migration"] > idf["database"]


class TestRankFacts:
    def test_combines_relevance_and_confidence(self):
        facts = [
            _make_fact("User prefers concise answers", confidence=0.95),
            _make_fact("Migrations are managed with alembic", confidence=0.5),
        ]
        ranked = rank_facts(facts, "database migration", relevance_weight=0.7)
        assert ranked[0]["content"] == "Migrations are managed with alembic"

    def test_pure_confidence_when_relevance_weight_is_zero(self):
        facts = [
            _make_fact("Low", confidence=0.2),
            _make_fact("High", confidence=0.9),
        ]
        ranked = rank_facts(facts, "high", relevance_weight=0.0)
        assert [f["content"] for f in ranked] == ["High", "Low"]

    def test_does_not_mutate_input(self):
        facts = [
            _make_fact("Migrations are managed with alembic", confidence=0.5),
            _make_fact("User prefers concise answers", confidence=0.95),
        ]
        snapshot = [dict(f) for f in facts]
        rank_facts(facts, "database migration", relevance_weight=0.7)
        assert facts == snapshot


# ---------------------------------------------------------------------------
# Diversity
# ---------------------------------------------------------------------------


class TestDiversify:
    def test_promotes_distinct_fact_over_near_duplicate(self):
        facts = [
            _make_fact("Use ruff for linting"),
            _make_fact("Use ruff for linting"),
            _make_fact("Deploys go through GitHub Actions"),
        ]
        ranked = rank_facts(facts, "linting", relevance_weight=0.7)
        scored = [(1.0 - index * 0.1, fact) for index, fact in enumerate(ranked)]
        picked = diversify(scored, similarity_weight=0.5, limit=2)
        contents = [fact["content"] for fact in picked]
        assert contents[0] == "Use ruff for linting"
        assert "Deploys go through GitHub Actions" in contents
        assert len(contents) == 2

    def test_identity_when_similarity_weight_is_zero(self):
        facts = [
            _make_fact("Use ruff for linting"),
            _make_fact("Deploys go through GitHub Actions"),
        ]
        ranked = rank_facts(facts, "linting", relevance_weight=0.7)
        scored = [(1.0 - index * 0.1, fact) for index, fact in enumerate(ranked)]
        picked = diversify(scored, similarity_weight=0.0)
        assert [f["content"] for f in picked] == [f["content"] for f in ranked]


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestRelevanceConfig:
    def test_defaults_keep_legacy_behavior(self):
        config = DeerMemConfig()
        assert config.retrieval_relevance_enabled is False
        assert config.retrieval_relevance_weight == 0.5
        assert config.retrieval_diversity_weight == 0.0

    def test_backend_config_accepts_new_knobs(self):
        config = DeerMemConfig.from_backend_config(
            {
                "retrieval_relevance_enabled": True,
                "retrieval_relevance_weight": 0.8,
                "retrieval_diversity_weight": 0.4,
            }
        )
        assert config.retrieval_relevance_enabled is True
        assert config.retrieval_relevance_weight == 0.8
        assert config.retrieval_diversity_weight == 0.4


# ---------------------------------------------------------------------------
# DeerMem.search with relevance mode
# ---------------------------------------------------------------------------


class TestRelevanceSearch:
    def test_returns_related_fact_without_literal_substring(self):
        facts = [
            _make_fact("Database migrations are handled with alembic", "project", 0.4),
            _make_fact("User prefers concise answers", "preference", 0.9),
        ]
        mgr = _deer_mem_with_facts(
            facts,
            backend_config={
                "retrieval_relevance_enabled": True,
                "retrieval_adapter": "",
                "retrieval_relevance_weight": 0.7,
            },
        )

        results = mgr.search("how do I add a database migration", top_k=5)
        assert results[0]["content"] == "Database migrations are handled with alembic"
        assert len(results) == 2  # every fact in scope competes, not only substring matches

    def test_relevance_outweighs_confidence(self):
        facts = [
            _make_fact("User prefers concise answers", "preference", 0.9),
            _make_fact("Migrations are managed with alembic", "project", 0.4),
        ]
        mgr = _deer_mem_with_facts(
            facts,
            backend_config={
                "retrieval_relevance_enabled": True,
                "retrieval_adapter": "",
                "retrieval_relevance_weight": 0.7,
            },
        )

        results = mgr.search("database migration", top_k=5)
        assert results[0]["content"] == "Migrations are managed with alembic"

    def test_respects_category_filter_and_top_k(self):
        facts = [_make_fact(f"Database fact {index}", "project", 0.5) for index in range(6)] + [_make_fact("Unrelated preference", "preference", 0.9)]
        mgr = _deer_mem_with_facts(
            facts,
            backend_config={"retrieval_relevance_enabled": True, "retrieval_adapter": ""},
        )

        results = mgr.search("database", top_k=3, category="project")
        assert len(results) == 3
        assert all(fact["category"] == "project" for fact in results)

    def test_diversity_dedups_near_duplicates(self):
        facts = [
            _make_fact("Use ruff for linting", confidence=0.9),
            _make_fact("Use ruff for linting", confidence=0.8),
            _make_fact("CI lints on every pull request", confidence=0.7),
        ]
        mgr = _deer_mem_with_facts(
            facts,
            backend_config={
                "retrieval_relevance_enabled": True,
                "retrieval_adapter": "",
                "retrieval_diversity_weight": 0.5,
            },
        )

        results = mgr.search("linting", top_k=2)
        assert len(results) == 2
        assert "CI lints on every pull request" in [fact["content"] for fact in results]

    def test_legacy_behavior_unchanged_when_disabled(self):
        facts = [
            _make_fact("Fact A", confidence=0.3),
            _make_fact("Fact B", confidence=0.9),
        ]
        mgr = _deer_mem_with_facts(facts)  # default config

        results = mgr.search("Fact", top_k=5)
        assert [fact["confidence"] for fact in results] == [0.9, 0.3]

    def test_legacy_empty_result_without_substring_match_when_disabled(self):
        facts = [_make_fact("The project uses PostgreSQL for persistence")]
        mgr = _deer_mem_with_facts(facts)

        assert mgr.search("database migration", top_k=5) == []


# ---------------------------------------------------------------------------
# Prompt injection with query-aware ranking
# ---------------------------------------------------------------------------


class TestInjectionRelevance:
    def _injection_args(self, **overrides):
        args = {
            "max_tokens": 300,
            "use_tiktoken": False,
            "guaranteed_categories": None,
            "guaranteed_token_budget": 500,
        }
        args.update(overrides)
        return args

    def test_relevance_reranks_facts_under_token_budget(self):
        from deerflow.agents.memory.backends.deermem.deermem.core.prompt import (
            format_memory_for_injection,
        )

        facts = [
            _make_fact("User prefers concise answers", "preference", 0.95),
            _make_fact("Migrations are managed with alembic", "project", 0.4),
        ]
        memory_data = {"facts": facts}

        legacy = format_memory_for_injection(
            memory_data,
            **self._injection_args(max_tokens=20),
        )
        relevance = format_memory_for_injection(
            memory_data,
            query="how do I add a database migration",
            relevance_weight=0.7,
            **self._injection_args(max_tokens=20),
        )

        assert "concise answers" in legacy
        assert "alembic" in relevance
        assert "alembic" not in legacy

    def test_query_none_preserves_legacy_order(self):
        from deerflow.agents.memory.backends.deermem.deermem.core.prompt import (
            format_memory_for_injection,
        )

        facts = [
            _make_fact("User prefers concise answers", "preference", 0.95),
            _make_fact("Migrations are managed with alembic", "project", 0.4),
            _make_fact("User lives in Beijing", "personal", 0.8),
        ]
        memory_data = {"facts": facts}

        legacy = format_memory_for_injection(memory_data, **self._injection_args())
        with_query_none = format_memory_for_injection(memory_data, query=None, relevance_weight=0.7, **self._injection_args())
        assert legacy == with_query_none


class TestGetContextQuery:
    def test_get_context_uses_query_when_enabled(self):
        facts = [
            _make_fact("User prefers concise answers", "preference", 0.95),
            _make_fact("Migrations are managed with alembic", "project", 0.4),
        ]
        mgr = _deer_mem_with_facts(
            facts,
            backend_config={"retrieval_relevance_enabled": True, "retrieval_relevance_weight": 0.7},
        )

        body = mgr.get_context("user-1", agent_name="assistant", query="how do I add a database migration")
        assert "alembic" in body

    def test_get_context_without_query_keeps_confidence_order(self):
        facts = [
            _make_fact("User prefers concise answers", "preference", 0.95),
            _make_fact("Migrations are managed with alembic", "project", 0.4),
        ]
        enabled = _deer_mem_with_facts(
            facts,
            backend_config={"retrieval_relevance_enabled": True},
        )
        disabled = _deer_mem_with_facts(facts)

        assert enabled.get_context("user-1", agent_name="assistant") == disabled.get_context("user-1", agent_name="assistant")


# ---------------------------------------------------------------------------
# Middleware wiring
# ---------------------------------------------------------------------------


class TestMiddlewareQueryWiring:
    def test_first_turn_passes_current_query_to_memory_context(self):
        from unittest import mock

        mw = DynamicContextMiddleware()
        state = {
            "messages": [
                HumanMessage(content="how do I add a database migration", id="msg-1"),
            ]
        }

        with (
            mock.patch(
                "deerflow.agents.lead_agent.prompt._get_memory_context",
                return_value="",
            ) as get_context,
            mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
        ):
            mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
            mw.before_agent(state, SimpleNamespace(context={}))

        get_context.assert_called_once()
        assert get_context.call_args.kwargs.get("query") == "how do I add a database migration"

    def test_multimodal_content_yields_text_query(self):
        from unittest import mock

        mw = DynamicContextMiddleware()
        state = {
            "messages": [
                HumanMessage(
                    content=[
                        {"type": "text", "text": "how do I "},
                        {"type": "text", "text": "add a database migration"},
                    ],
                    id="msg-1",
                ),
            ]
        }

        with (
            mock.patch(
                "deerflow.agents.lead_agent.prompt._get_memory_context",
                return_value="",
            ) as get_context,
            mock.patch("deerflow.agents.middlewares.dynamic_context_middleware.datetime") as mock_dt,
        ):
            mock_dt.now.return_value.strftime.return_value = "2026-05-08, Friday"
            mw.before_agent(state, SimpleNamespace(context={}))

        assert get_context.call_args.kwargs.get("query") == "how do I add a database migration"
