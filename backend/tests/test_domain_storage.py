"""Unit tests for domain memory storage."""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.domain_storage import (
    DecayPolicy,
    DomainFact,
    DomainStorage,
    apply_decay,
    normalize_entity_id,
)


class TestNormalizeEntityId:
    """Tests for entity name normalization."""

    def test_lowercase(self):
        assert normalize_entity_id("Pump A") == "pump_a"

    def test_special_chars(self):
        assert normalize_entity_id("Reactor #1") == "reactor_1"

    def test_multiple_spaces(self):
        assert normalize_entity_id("Main  Feed   Pump") == "main_feed_pump"

    def test_strip_whitespace(self):
        assert normalize_entity_id("  pump_a  ") == "pump_a"

    def test_preserve_numbers(self):
        assert normalize_entity_id("Pump 123") == "pump_123"

    def test_hyphen_to_underscore(self):
        assert normalize_entity_id("pump-a") == "pump_a"


class TestDomainStorage:
    """Tests for DomainStorage class."""

    def test_store_fact_success(self):
        """store_fact() stores fact with embedding and returns ID."""
        mock_store = MagicMock()
        mock_store.add.return_value = ["fact-123"]
        mock_provider = MagicMock()
        mock_provider.embed.return_value = [[0.1] * 768]

        storage = DomainStorage(vector_store=mock_store, embedding_provider=mock_provider)
        fact_id = storage.store_fact(
            tenant_id="tenant-1",
            domain="equipment",
            entity_id="Pump A",
            content="Pump A has flow rate of 500 GPM",
            confidence=0.9,
        )

        assert fact_id is not None
        mock_store.add.assert_called_once()
        call_args = mock_store.add.call_args
        assert call_args[0][0] == "domain_tenant-1"  # collection name
        assert len(call_args[0][1]) == 1  # one chunk
        chunk = call_args[0][1][0]
        assert chunk["content"] == "Pump A has flow rate of 500 GPM"
        assert chunk["metadata"]["domain"] == "equipment"
        assert chunk["metadata"]["entity_id"] == "pump_a"  # normalized

    def test_store_fact_failure_returns_none(self):
        """store_fact() returns None on error."""
        mock_store = MagicMock()
        mock_store.add.side_effect = RuntimeError("DB error")
        mock_provider = MagicMock()
        mock_provider.embed.return_value = [[0.1] * 768]

        storage = DomainStorage(vector_store=mock_store, embedding_provider=mock_provider)
        fact_id = storage.store_fact(
            tenant_id="tenant-1",
            domain="equipment",
            entity_id="Pump A",
            content="Test",
        )

        assert fact_id is None

    def test_search_facts_success(self):
        """search_facts() returns facts sorted by similarity."""
        mock_store = MagicMock()
        mock_store.search.return_value = [
            MagicMock(
                chunk_id="fact-1",
                content="Pump A flow rate: 500 GPM",
                metadata={"domain": "equipment", "entity_id": "pump_a", "confidence": 0.9},
                score=0.85,
            ),
            MagicMock(
                chunk_id="fact-2",
                content="Pump A location: Building 3",
                metadata={"domain": "equipment", "entity_id": "pump_a", "confidence": 0.8},
                score=0.75,
            ),
        ]
        mock_provider = MagicMock()
        mock_provider.embed_query.return_value = [0.1] * 768

        storage = DomainStorage(vector_store=mock_store, embedding_provider=mock_provider)
        facts = storage.search_facts(
            tenant_id="tenant-1",
            query="What is the flow rate of Pump A?",
            domain="equipment",
            entity_id="Pump A",
        )

        assert len(facts) == 2
        assert facts[0].id == "fact-1"
        assert facts[0].similarity_score == 0.85
        assert facts[1].similarity_score == 0.75

    def test_search_facts_with_domain_filter(self):
        """search_facts() filters by domain."""
        mock_store = MagicMock()
        mock_store.search.return_value = [
            MagicMock(
                chunk_id="fact-1",
                content="Equipment fact",
                metadata={"domain": "equipment", "entity_id": "pump_a"},
                score=0.9,
            ),
            MagicMock(
                chunk_id="fact-2",
                content="Process fact",
                metadata={"domain": "process", "entity_id": "pump_a"},
                score=0.85,
            ),
        ]
        mock_provider = MagicMock()
        mock_provider.embed_query.return_value = [0.1] * 768

        storage = DomainStorage(vector_store=mock_store, embedding_provider=mock_provider)
        facts = storage.search_facts(
            tenant_id="tenant-1",
            query="test",
            domain="equipment",
        )

        # Should filter out non-equipment facts
        assert len(facts) == 1
        assert facts[0].domain == "equipment"

    def test_search_facts_empty_result(self):
        """search_facts() returns empty list on no results."""
        mock_store = MagicMock()
        mock_store.search.return_value = []
        mock_provider = MagicMock()
        mock_provider.embed_query.return_value = [0.1] * 768

        storage = DomainStorage(vector_store=mock_store, embedding_provider=mock_provider)
        facts = storage.search_facts(
            tenant_id="tenant-1",
            query="test",
        )

        assert facts == []

    def test_search_facts_error_returns_empty(self):
        """search_facts() returns empty list on error."""
        mock_store = MagicMock()
        mock_store.search.side_effect = RuntimeError("DB error")
        mock_provider = MagicMock()
        mock_provider.embed_query.return_value = [0.1] * 768

        storage = DomainStorage(vector_store=mock_store, embedding_provider=mock_provider)
        facts = storage.search_facts(
            tenant_id="tenant-1",
            query="test",
        )

        assert facts == []

    def test_collection_name_tenant_isolation(self):
        """Each tenant gets a separate collection."""
        storage = DomainStorage()
        assert storage._collection_name("tenant-1") == "domain_tenant-1"
        assert storage._collection_name("tenant-2") == "domain_tenant-2"
        assert storage._collection_name("tenant-1") != storage._collection_name("tenant-2")


class TestDomainFact:
    """Tests for DomainFact dataclass."""

    def test_creation(self):
        fact = DomainFact(
            id="fact-1",
            content="Test content",
            domain="equipment",
            entity_id="pump_a",
            tenant_id="tenant-1",
            confidence=0.9,
        )
        assert fact.id == "fact-1"
        assert fact.domain == "equipment"
        assert fact.similarity_score == 0.0  # default
        assert fact.adjusted_score == 0.0  # default

    def test_with_scores(self):
        fact = DomainFact(
            id="fact-1",
            content="Test",
            domain="equipment",
            entity_id="pump_a",
            tenant_id="tenant-1",
            similarity_score=0.85,
            adjusted_score=0.75,
        )
        assert fact.similarity_score == 0.85
        assert fact.adjusted_score == 0.75


class TestDecayPolicy:
    """Tests for decay policy functions."""

    def test_never_decay(self):
        """NEVER policy keeps scores unchanged."""
        facts = [
            DomainFact(
                id="f1", content="Old fact", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=0.9,
                created_at=datetime.now(UTC) - timedelta(days=365),
            ),
            DomainFact(
                id="f2", content="New fact", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=0.8,
                created_at=datetime.now(UTC) - timedelta(days=1),
            ),
        ]
        result = apply_decay(facts, DecayPolicy.NEVER, half_life_days=90)
        assert result[0].adjusted_score == 0.9
        assert result[1].adjusted_score == 0.8

    def test_linear_decay(self):
        """LINEAR decay reduces score based on age."""
        now = datetime.now(UTC)
        facts = [
            DomainFact(
                id="f1", content="Old", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=1.0,
                created_at=now - timedelta(days=180),  # 2x half-life
            ),
            DomainFact(
                id="f2", content="New", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=1.0,
                created_at=now - timedelta(days=0),
            ),
        ]
        result = apply_decay(facts, DecayPolicy.LINEAR, half_life_days=90)
        # New fact: decay_factor = 1.0 - 0/(2*90) = 1.0
        assert result[0].id == "f2"  # New fact should rank higher
        assert result[0].adjusted_score == pytest.approx(1.0, abs=0.01)
        # Old fact: decay_factor = 1.0 - 180/(2*90) = 0.0
        assert result[1].adjusted_score == pytest.approx(0.0, abs=0.01)

    def test_exponential_decay(self):
        """EXPONENTIAL decay reduces score exponentially."""
        now = datetime.now(UTC)
        facts = [
            DomainFact(
                id="f1", content="1 half-life old", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=1.0,
                created_at=now - timedelta(days=90),
            ),
        ]
        result = apply_decay(facts, DecayPolicy.EXPONENTIAL, half_life_days=90)
        # After 1 half-life: decay_factor = exp(-0.693 * 90 / 90) ≈ 0.5
        assert result[0].adjusted_score == pytest.approx(0.5, abs=0.01)

    def test_decay_with_no_created_at(self):
        """Facts without created_at keep original score."""
        facts = [
            DomainFact(
                id="f1", content="No date", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=0.9,
                created_at=None,
            ),
        ]
        result = apply_decay(facts, DecayPolicy.LINEAR, half_life_days=90)
        assert result[0].adjusted_score == 0.9

    def test_decay_sorts_by_adjusted_score(self):
        """apply_decay returns facts sorted by adjusted_score descending."""
        now = datetime.now(UTC)
        facts = [
            DomainFact(
                id="old", content="Old", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=0.95,
                created_at=now - timedelta(days=180),
            ),
            DomainFact(
                id="new", content="New", domain="equipment",
                entity_id="pump_a", tenant_id="t1",
                similarity_score=0.8,
                created_at=now - timedelta(days=1),
            ),
        ]
        result = apply_decay(facts, DecayPolicy.LINEAR, half_life_days=90)
        assert result[0].id == "new"  # Higher adjusted score
        assert result[1].id == "old"
