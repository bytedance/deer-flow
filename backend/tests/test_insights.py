"""Tests for the insights feedback loop system."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from deerflow.insights.analytics import FeedbackAggregator
from deerflow.insights.cache import JsonFileInsightsCache
from deerflow.insights.improvement import ImprovementEngine
from deerflow.insights.kb_candidate_store import KBCandidateStore
from deerflow.insights.knowledge_extractor import ClosureKnowledgeExtractor
from deerflow.insights.memory_integration import FeedbackMemoryIntegration
from deerflow.insights.models import (
    ClosureMetrics,
    FeedbackTrend,
    ImprovementEvidence,
    ImprovementSuggestion,
    KBCandidate,
)
from deerflow.persistence.agent.usage_model import AgentUsageRow
from deerflow.persistence.base import Base
from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.models.closure_ticket import ClosureTicketEventRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory SQLite async engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(async_engine):
    """Create an async session factory."""
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def insights_cache(temp_dir):
    """Create a JSON file insights cache."""
    return JsonFileInsightsCache(base_dir=temp_dir)


@pytest.fixture
def kb_candidate_store(temp_dir):
    """Create a KB candidates store."""
    return KBCandidateStore(base_dir=temp_dir)


class TestFeedbackAggregator:
    """Tests for FeedbackAggregator with dual JOIN paths."""

    @pytest.mark.asyncio
    async def test_aggregate_with_dual_join(
        self, session_factory, insights_cache
    ):
        """Test aggregation with ThreadMetaRow for tenant isolation and AgentUsageRow for agent correlation."""
        aggregator = FeedbackAggregator(session_factory, insights_cache)
        tenant_id = "test-tenant"

        async with session_factory() as session:
            thread = ThreadMetaRow(
                thread_id="thread-1",
                tenant_id=tenant_id,
                created_at=datetime.now(UTC),
            )
            session.add(thread)

            usage = AgentUsageRow(
                tenant_id=tenant_id,
                agent_name="test-agent",
                user_id="user-1",
                run_id="run-1",
                token_input=100,
                token_output=200,
                used_at=datetime.now(UTC),
            )
            session.add(usage)

            feedback = FeedbackRow(
                feedback_id="feedback-1",
                thread_id="thread-1",
                run_id="run-1",
                user_id="user-1",
                rating=1,
                comment="Great response!",
                created_at=datetime.now(UTC),
            )
            session.add(feedback)
            await session.commit()

        trends = await aggregator.aggregate(tenant_id=tenant_id, window_days=7)

        assert len(trends) == 1
        trend = trends[0]
        assert trend.agent_name == "test-agent"
        assert trend.positive_count == 1
        assert trend.negative_count == 0
        assert trend.positive_ratio == 1.0

    @pytest.mark.asyncio
    async def test_aggregate_with_orphan_run_id(
        self, session_factory, insights_cache
    ):
        """Test aggregation when feedback has a run_id with no matching AgentUsageRow."""
        aggregator = FeedbackAggregator(session_factory, insights_cache)
        tenant_id = "test-tenant"

        async with session_factory() as session:
            thread = ThreadMetaRow(
                thread_id="thread-2",
                tenant_id=tenant_id,
                created_at=datetime.now(UTC),
            )
            session.add(thread)

            # Feedback with a run_id that has no corresponding AgentUsageRow
            feedback = FeedbackRow(
                feedback_id="feedback-2",
                thread_id="thread-2",
                run_id="run-orphan",
                user_id="user-1",
                rating=-1,
                comment="No agent response",
                created_at=datetime.now(UTC),
            )
            session.add(feedback)
            await session.commit()

        trends = await aggregator.aggregate(tenant_id=tenant_id, window_days=7)

        # The orphan run_id produces a NULL agent_name → labelled "unknown"
        assert len(trends) == 1
        assert trends[0].agent_name == "unknown"
        assert trends[0].negative_count == 1

    @pytest.mark.asyncio
    async def test_tenant_isolation_via_thread_meta(
        self, session_factory, insights_cache
    ):
        """Test that tenant isolation uses ThreadMetaRow, not AgentUsageRow."""
        aggregator = FeedbackAggregator(session_factory, insights_cache)
        tenant_a = "tenant-a"
        tenant_b = "tenant-b"

        async with session_factory() as session:
            session.add(ThreadMetaRow(
                thread_id="thread-a",
                tenant_id=tenant_a,
                created_at=datetime.now(UTC),
            ))
            session.add(ThreadMetaRow(
                thread_id="thread-b",
                tenant_id=tenant_b,
                created_at=datetime.now(UTC),
            ))

            # Tenant A: positive feedback
            session.add(FeedbackRow(
                feedback_id="feedback-a",
                thread_id="thread-a",
                run_id="run-a",
                user_id="user-a",
                rating=1,
                created_at=datetime.now(UTC),
            ))

            # Tenant B: negative feedback
            session.add(FeedbackRow(
                feedback_id="feedback-b",
                thread_id="thread-b",
                run_id="run-b",
                user_id="user-b",
                rating=-1,
                created_at=datetime.now(UTC),
            ))
            await session.commit()

        trends_a = await aggregator.aggregate(tenant_id=tenant_a, window_days=7)
        trends_b = await aggregator.aggregate(tenant_id=tenant_b, window_days=7)

        # Tenant A sees only its own positive feedback
        assert len(trends_a) == 1
        assert trends_a[0].positive_count == 1
        assert trends_a[0].negative_count == 0

        # Tenant B sees only its own negative feedback
        assert len(trends_b) == 1
        assert trends_b[0].positive_count == 0
        assert trends_b[0].negative_count == 1


class TestClosureKnowledgeExtractor:
    """Tests for ClosureKnowledgeExtractor."""

    @pytest.mark.asyncio
    async def test_extract_from_event_payloads(
        self, session_factory, kb_candidate_store
    ):
        """Test extraction from submit_verification and verify_close event payloads."""
        extractor = ClosureKnowledgeExtractor()
        tenant_id = "test-tenant"
        ticket_id = "ticket-1"

        submit_event = ClosureTicketEventRow(
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            action="submit_verification",
            actor_id="user-1",
            payload={
                "verification_summary": "Issue resolved by restarting service",
                "evidence": ["log_file_2024-01-01.txt"],
            },
            created_at=datetime.now(UTC),
        )

        close_event = ClosureTicketEventRow(
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            action="verify_close",
            actor_id="user-1",
            payload={"verification_summary": "Confirmed fix"},
            created_at=datetime.now(UTC),
        )

        candidate = await extractor.extract(
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            events=[submit_event, close_event],
        )

        assert candidate is not None
        assert candidate.tenant_id == tenant_id
        assert candidate.ticket_id == ticket_id
        assert "Issue resolved" in candidate.body
        assert candidate.status == "pending_review"

    def test_promote_kb_candidate(self, kb_candidate_store):
        """Test promoting a KB candidate to approved status."""
        tenant_id = "test-tenant"
        ticket_id = "ticket-2"

        candidate = KBCandidate(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            title="Test Resolution",
            body="Resolved by updating config",
            status="pending_review",
            created_at=datetime.now(UTC),
        )
        kb_candidate_store.save(candidate)

        target_kb_id = "kb-123"
        updated = kb_candidate_store.promote(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            target_kb_id=target_kb_id,
        )

        assert updated is not None
        assert updated.status == "approved"
        assert updated.metadata_tags.get("target_kb_id") == target_kb_id
        assert updated.metadata_tags.get("approved_at") is not None


class TestImprovementEngine:
    """Tests for ImprovementEngine."""

    def test_generate_suggestions_from_feedback_trends(self):
        """Test generating improvement suggestions from feedback trends."""
        engine = ImprovementEngine()

        trend = FeedbackTrend(
            agent_name="test-agent",
            positive_count=2,
            negative_count=8,
            positive_ratio=0.2,
            trend_direction="declining",
            window_days=7,
            top_complaints=[("slow", 5), ("error", 3)],
            computed_at=datetime.now(UTC),
        )

        suggestions = engine.generate_suggestions(
            tenant_id="test-tenant",
            feedback_trends=[trend],
            closure_metrics=[],
        )

        assert len(suggestions) >= 1
        suggestion = suggestions[0]
        assert "test-agent" in suggestion.target
        assert suggestion.confidence > 0.0

    def test_deduplication_by_target_and_issue(self):
        """Test that suggestions are deduplicated by (target, issue_pattern)."""
        engine = ImprovementEngine()

        trend1 = FeedbackTrend(
            agent_name="agent-1",
            positive_count=1,
            negative_count=10,
            positive_ratio=0.1,
            trend_direction="declining",
            window_days=7,
            top_complaints=[("error", 8)],
            computed_at=datetime.now(UTC),
        )

        trend2 = FeedbackTrend(
            agent_name="agent-1",
            positive_count=2,
            negative_count=9,
            positive_ratio=0.2,
            trend_direction="declining",
            window_days=14,
            top_complaints=[("error", 7)],
            computed_at=datetime.now(UTC),
        )

        batch1 = engine.generate_suggestions(
            tenant_id="test-tenant",
            feedback_trends=[trend1],
        )
        batch2 = engine.generate_suggestions(
            tenant_id="test-tenant",
            feedback_trends=[trend2],
        )

        deduped = engine.deduplicate(batch1, batch2)

        # Deduplication should collapse suggestions with the same (target, issue_pattern)
        assert len(deduped) >= 1
        # The surviving suggestion should have the higher confidence of the two
        if len(batch1) > 0 and len(batch2) > 0:
            max_conf = max(batch1[0].confidence, batch2[0].confidence)
            assert deduped[0].confidence >= max_conf


class TestFeedbackMemoryIntegration:
    """Tests for FeedbackMemoryIntegration."""

    @pytest.mark.asyncio
    async def test_apply_suggestion_creates_memory_fact(self, insights_cache):
        """Test that applying a suggestion creates a memory fact with source='feedback_loop'."""
        integration = FeedbackMemoryIntegration(insights_cache)

        suggestion = ImprovementSuggestion(
            id="suggestion-1",
            target="agent:test-agent",
            issue_pattern="declining_performance",
            suggestion="Review test-agent performance and optimize response times",
            confidence=0.8,
            evidence=ImprovementEvidence(
                feedback_ids=["feedback-1", "feedback-2"],
                closure_ticket_ids=[],
                metrics={"negative_count": 10, "window_days": 7},
            ),
            status="applied",
            created_at=datetime.now(UTC),
        )

        mock_fact = {
            "id": "fact_abc123",
            "content": f"{suggestion.target}: {suggestion.suggestion}",
            "category": "improvement",
            "confidence": 0.9,
            "source": "feedback_loop",
            "createdAt": datetime.now(UTC).isoformat(),
        }

        with patch(
            "deerflow.agents.memory.updater.create_memory_fact",
            return_value=mock_fact,
        ):
            await integration.on_suggestion_applied(suggestion)

        facts = insights_cache.get("global", "improvement_facts") or []
        assert len(facts) >= 1

        fact = facts[0]
        assert fact["source"] == "feedback_loop"
        assert fact["category"] == "improvement"
        assert fact["confidence"] == 0.9
        assert "test-agent" in fact["content"]
        assert fact["suggestion_id"] == "suggestion-1"


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing code."""

    def test_create_memory_fact_without_source_parameter(self):
        """Test that create_memory_fact() works without source parameter (defaults to 'manual')."""
        from deerflow.agents.memory.updater import create_memory_fact

        mock_memory = {"facts": []}
        with patch(
            "deerflow.agents.memory.updater.get_memory_data",
            return_value=mock_memory,
        ), patch(
            "deerflow.agents.memory.updater._save_memory_to_file",
            return_value=True,
        ):
            result = create_memory_fact(
                content="Test fact",
                category="context",
                confidence=0.7,
            )

        # The function returns the updated memory dict; check the last fact
        facts = result["facts"]
        assert len(facts) == 1
        assert facts[0]["source"] == "manual"
        assert facts[0]["content"] == "Test fact"
        assert facts[0]["category"] == "context"
        assert facts[0]["confidence"] == 0.7

    def test_create_memory_fact_with_source_parameter(self):
        """Test that create_memory_fact() accepts source parameter."""
        from deerflow.agents.memory.updater import create_memory_fact

        mock_memory = {"facts": []}
        with patch(
            "deerflow.agents.memory.updater.get_memory_data",
            return_value=mock_memory,
        ), patch(
            "deerflow.agents.memory.updater._save_memory_to_file",
            return_value=True,
        ):
            result = create_memory_fact(
                content="Improvement fact",
                category="improvement",
                confidence=0.9,
                source="feedback_loop",
            )

        facts = result["facts"]
        assert len(facts) == 1
        assert facts[0]["source"] == "feedback_loop"
        assert facts[0]["content"] == "Improvement fact"
        assert facts[0]["category"] == "improvement"

    def test_client_create_memory_fact_passes_source(self):
        """Test that DeerFlowClient.create_memory_fact() passes source parameter."""
        from deerflow.client import DeerFlowClient

        client = DeerFlowClient()

        mock_memory = {"facts": []}
        with patch(
            "deerflow.agents.memory.updater.get_memory_data",
            return_value=mock_memory,
        ), patch(
            "deerflow.agents.memory.updater._save_memory_to_file",
            return_value=True,
        ):
            result = client.create_memory_fact(
                content="Client test fact",
                category="context",
                confidence=0.6,
                source="feedback_loop",
            )

        facts = result["facts"]
        assert len(facts) == 1
        assert facts[0]["source"] == "feedback_loop"


class TestLLMEnrichment:
    """Tests for ImprovementEngine.enrich_with_llm()."""

    @pytest.mark.asyncio
    async def test_enrich_with_llm_rewrites_suggestions(self):
        """Test that LLM enrichment rewrites suggestion text."""
        engine = ImprovementEngine(model_name="test-model")

        suggestions = [
            ImprovementSuggestion(
                id="sug-1",
                target="agent:test-agent",
                issue_pattern="declining_feedback",
                suggestion="Template text for suggestion 1",
                confidence=0.7,
                status="pending",
                created_at=datetime.now(UTC),
            ),
            ImprovementSuggestion(
                id="sug-2",
                target="agent:test-agent",
                issue_pattern="complaint:slow",
                suggestion="Template text for suggestion 2",
                confidence=0.6,
                status="pending",
                created_at=datetime.now(UTC),
            ),
        ]

        mock_response = MagicMock()
        mock_response.content = (
            "1. Investigate the declining feedback trend for test-agent\n"
            "2. Optimize response times to address slow complaints"
        )

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "deerflow.models.create_chat_model",
            return_value=mock_model,
        ):
            enriched = await engine.enrich_with_llm(suggestions)

        assert len(enriched) == 2
        assert "Investigate" in enriched[0].suggestion
        assert "Optimize" in enriched[1].suggestion
        # Original template text should be replaced
        assert "Template text" not in enriched[0].suggestion
        assert "Template text" not in enriched[1].suggestion

    @pytest.mark.asyncio
    async def test_enrich_with_llm_falls_back_on_failure(self):
        """Test that LLM enrichment falls back to template text on failure."""
        engine = ImprovementEngine(model_name="test-model")

        suggestions = [
            ImprovementSuggestion(
                id="sug-1",
                target="agent:test-agent",
                issue_pattern="declining_feedback",
                suggestion="Template text fallback",
                confidence=0.7,
                status="pending",
                created_at=datetime.now(UTC),
            ),
        ]

        with patch(
            "deerflow.models.create_chat_model",
            side_effect=ValueError("Model not found"),
        ):
            enriched = await engine.enrich_with_llm(suggestions)

        assert len(enriched) == 1
        assert enriched[0].suggestion == "Template text fallback"

    @pytest.mark.asyncio
    async def test_enrich_with_llm_skips_when_no_model(self):
        """Test that LLM enrichment is skipped when no model is configured."""
        engine = ImprovementEngine(model_name=None)

        suggestions = [
            ImprovementSuggestion(
                id="sug-1",
                target="agent:test-agent",
                issue_pattern="declining_feedback",
                suggestion="Template text unchanged",
                confidence=0.7,
                status="pending",
                created_at=datetime.now(UTC),
            ),
        ]

        enriched = await engine.enrich_with_llm(suggestions)

        assert len(enriched) == 1
        assert enriched[0].suggestion == "Template text unchanged"

    @pytest.mark.asyncio
    async def test_enrich_with_llm_handles_empty_suggestions(self):
        """Test that LLM enrichment handles empty suggestion list."""
        engine = ImprovementEngine(model_name="test-model")

        enriched = await engine.enrich_with_llm([])

        assert enriched == []

    @pytest.mark.asyncio
    async def test_enrich_with_llm_strips_index_prefix(self):
        """Test that LLM enrichment strips index prefixes from response lines."""
        engine = ImprovementEngine(model_name="test-model")

        suggestions = [
            ImprovementSuggestion(
                id="sug-1",
                target="agent:test-agent",
                issue_pattern="declining_feedback",
                suggestion="Original text",
                confidence=0.7,
                status="pending",
                created_at=datetime.now(UTC),
            ),
        ]

        mock_response = MagicMock()
        mock_response.content = "1) Rewritten suggestion without index"

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "deerflow.models.create_chat_model",
            return_value=mock_model,
        ):
            enriched = await engine.enrich_with_llm(suggestions)

        assert len(enriched) == 1
        assert enriched[0].suggestion == "Rewritten suggestion without index"
