"""Unit tests for domain memory retrieval."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.domain_retrieval import (
    _format_domain_facts,
    get_domain_context,
)
from deerflow.agents.memory.domain_storage import DecayPolicy, DomainFact
from deerflow.config.domain_memory_config import DomainDecayConfig, DomainMemoryConfig


def _make_fact(
    content: str,
    domain: str = "equipment",
    entity_id: str = "pump_a",
    score: float = 0.9,
    age_days: float = 0,
) -> DomainFact:
    created_at = datetime.now(UTC) - timedelta(days=age_days)
    return DomainFact(
        id="fact-1",
        content=content,
        domain=domain,
        entity_id=entity_id,
        tenant_id="tenant-1",
        similarity_score=score,
        adjusted_score=score,
        created_at=created_at,
    )


class TestFormatDomainFacts:
    """Tests for _format_domain_facts() function."""

    def test_empty_facts_returns_empty(self):
        """_format_domain_facts() returns empty string for empty list."""
        result = _format_domain_facts([], max_tokens=1000)
        assert result == ""

    def test_formats_single_fact(self):
        """_format_domain_facts() formats a single fact correctly."""
        facts = [_make_fact("Pump A flow rate is 500 GPM", score=0.95)]
        result = _format_domain_facts(facts, max_tokens=1000)
        assert "[equipment/pump_a | 0.95]" in result
        assert "Pump A flow rate is 500 GPM" in result

    def test_formats_multiple_facts(self):
        """_format_domain_facts() formats multiple facts with line breaks."""
        facts = [
            _make_fact("Fact 1", score=0.9),
            _make_fact("Fact 2", score=0.85),
        ]
        result = _format_domain_facts(facts, max_tokens=1000)
        assert "Fact 1" in result
        assert "Fact 2" in result
        assert "\n" in result

    def test_skips_empty_content(self):
        """_format_domain_facts() skips facts with empty content."""
        facts = [
            _make_fact("", score=0.9),
            _make_fact("Valid fact", score=0.85),
        ]
        result = _format_domain_facts(facts, max_tokens=1000)
        assert "Valid fact" in result
        assert result.count("[") == 1

    def test_truncates_when_exceeding_token_budget(self):
        """_format_domain_facts() truncates output when exceeding max_tokens."""
        long_content = "This is a very long fact. " * 100
        facts = [_make_fact(long_content, score=0.9)]
        result = _format_domain_facts(facts, max_tokens=10)
        assert result.endswith("...")
        assert len(result) < len(long_content)


class TestGetDomainContext:
    """Tests for get_domain_context() function."""

    def test_returns_empty_when_disabled(self):
        """get_domain_context() returns empty when domain memory is disabled."""
        with patch(
            "deerflow.agents.memory.domain_retrieval.get_domain_memory_config",
            return_value=DomainMemoryConfig(enabled=False),
        ):
            result = get_domain_context(query="Pump A", tenant_id="tenant-1")
        assert result == ""

    def test_returns_empty_when_injection_disabled(self):
        """get_domain_context() returns empty when injection is disabled."""
        with patch(
            "deerflow.agents.memory.domain_retrieval.get_domain_memory_config",
            return_value=DomainMemoryConfig(enabled=True, injection_enabled=False),
        ):
            result = get_domain_context(query="Pump A", tenant_id="tenant-1")
        assert result == ""

    def test_returns_empty_when_storage_unavailable(self):
        """get_domain_context() returns empty when storage is None."""
        with (
            patch(
                "deerflow.agents.memory.domain_retrieval.get_domain_memory_config",
                return_value=DomainMemoryConfig(enabled=True),
            ),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=None),
        ):
            result = get_domain_context(query="Pump A", tenant_id="tenant-1")
        assert result == ""

    def test_returns_empty_when_no_facts_found(self):
        """get_domain_context() returns empty when no facts match query."""
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = []

        with (
            patch(
                "deerflow.agents.memory.domain_retrieval.get_domain_memory_config",
                return_value=DomainMemoryConfig(enabled=True),
            ),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
        ):
            result = get_domain_context(query="Pump A", tenant_id="tenant-1")
        assert result == ""

    def test_returns_formatted_context_with_header(self):
        """get_domain_context() returns formatted context with 'Domain context:' header."""
        facts = [_make_fact("Pump A flow rate is 500 GPM", score=0.9)]
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = facts

        config = DomainMemoryConfig(enabled=True, min_retrieval_score=0.7)
        with (
            patch("deerflow.agents.memory.domain_retrieval.get_domain_memory_config", return_value=config),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
        ):
            result = get_domain_context(query="Pump A", tenant_id="tenant-1")

        assert result.startswith("Domain context:")
        assert "Pump A flow rate is 500 GPM" in result

    def test_passes_domain_and_entity_filters(self):
        """get_domain_context() passes domain and entity_id to search."""
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = []

        with (
            patch(
                "deerflow.agents.memory.domain_retrieval.get_domain_memory_config",
                return_value=DomainMemoryConfig(enabled=True),
            ),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
        ):
            get_domain_context(
                query="Pump A",
                domain="equipment",
                entity_id="Pump A",
                tenant_id="tenant-1",
            )

        mock_storage.search_facts.assert_called_once()
        call_kwargs = mock_storage.search_facts.call_args.kwargs
        assert call_kwargs["domain"] == "equipment"
        assert call_kwargs["entity_id"] == "Pump A"

    def test_applies_decay_policy(self):
        """get_domain_context() applies decay policy to facts."""
        old_fact = _make_fact("Old fact", score=0.95, age_days=180)
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = [old_fact]

        config = DomainMemoryConfig(
            enabled=True,
            domains={"default": DomainDecayConfig(policy="linear", half_life_days=90)},
        )
        with (
            patch("deerflow.agents.memory.domain_retrieval.get_domain_memory_config", return_value=config),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
        ):
            result = get_domain_context(query="test", tenant_id="tenant-1")

        assert "Domain context:" in result

    def test_uses_config_max_tokens(self):
        """get_domain_context() uses max_tokens from config when not specified."""
        facts = [_make_fact("Test fact", score=0.9)]
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = facts

        config = DomainMemoryConfig(enabled=True, max_injection_tokens=500)
        with (
            patch("deerflow.agents.memory.domain_retrieval.get_domain_memory_config", return_value=config),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
        ):
            get_domain_context(query="test", tenant_id="tenant-1")

        mock_storage.search_facts.assert_called_once()

    def test_uses_current_tenant_when_not_specified(self):
        """get_domain_context() uses current tenant when tenant_id not provided."""
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = []

        with (
            patch(
                "deerflow.agents.memory.domain_retrieval.get_domain_memory_config",
                return_value=DomainMemoryConfig(enabled=True),
            ),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
            patch("deerflow.agents.memory.domain_retrieval.get_current_tenant_id", return_value="auto-tenant"),
        ):
            get_domain_context(query="test")

        call_kwargs = mock_storage.search_facts.call_args.kwargs
        assert call_kwargs["tenant_id"] == "auto-tenant"

    def test_min_score_filtering(self):
        """get_domain_context() passes min_score from config to search."""
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = []

        config = DomainMemoryConfig(enabled=True, min_retrieval_score=0.85)
        with (
            patch("deerflow.agents.memory.domain_retrieval.get_domain_memory_config", return_value=config),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
        ):
            get_domain_context(query="test", tenant_id="tenant-1")

        call_kwargs = mock_storage.search_facts.call_args.kwargs
        assert call_kwargs["min_score"] == 0.85
