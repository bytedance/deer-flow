"""Unit tests for domain memory telemetry logging."""

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.domain_retrieval import get_domain_context
from deerflow.agents.memory.domain_storage import DomainFact, DomainStorage
from deerflow.config.domain_memory_config import DomainMemoryConfig


class TestDomainStorageTelemetry:
    """Tests for domain storage telemetry logging."""

    def test_store_fact_logs_success_with_latency(self, caplog):
        """store_fact() logs success message with latency."""
        mock_vector_store = MagicMock()
        mock_embedding_provider = MagicMock()
        mock_embedding_provider.embed.return_value = [[0.1, 0.2, 0.3]]

        storage = DomainStorage(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
        )

        with caplog.at_level(logging.INFO):
            storage.store_fact(
                tenant_id="tenant-xyz",
                domain="equipment",
                entity_id="Pump A",
                content="Flow rate is 500 GPM",
            )

        assert any(
            "Domain memory saved" in record.message
            and "tenant=tenant-xyz" in record.message
            and "domain=equipment" in record.message
            and "entity=pump_a" in record.message
            and "latency=" in record.message
            for record in caplog.records
        )

    def test_store_fact_logs_error_on_failure(self, caplog):
        """store_fact() logs error message on failure."""
        mock_vector_store = MagicMock()
        mock_vector_store.add.side_effect = RuntimeError("Storage error")
        mock_embedding_provider = MagicMock()
        mock_embedding_provider.embed.return_value = [[0.1, 0.2, 0.3]]

        storage = DomainStorage(
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
        )

        with caplog.at_level(logging.ERROR):
            result = storage.store_fact(
                tenant_id="tenant-1",
                domain="equipment",
                entity_id="Pump A",
                content="Test",
            )

        assert result is None
        assert any("Failed to store domain fact" in record.message for record in caplog.records)


class TestDomainRetrievalTelemetry:
    """Tests for domain retrieval telemetry logging."""

    def test_get_domain_context_logs_retrieval_with_metrics(self, caplog):
        """get_domain_context() logs retrieval with facts count and top score."""
        facts = [
            DomainFact(
                id="fact-1",
                content="Test fact",
                domain="equipment",
                entity_id="pump_a",
                tenant_id="tenant-1",
                similarity_score=0.92,
                adjusted_score=0.92,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = facts

        config = DomainMemoryConfig(enabled=True)
        with (
            patch("deerflow.agents.memory.domain_retrieval.get_domain_memory_config", return_value=config),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
            caplog.at_level(logging.INFO),
        ):
            get_domain_context(query="Pump A", tenant_id="tenant-1")

        assert any(
            "Domain memory retrieved" in record.message
            and "tenant=tenant-1" in record.message
            and "facts=1" in record.message
            and "top_score=" in record.message
            and "latency=" in record.message
            for record in caplog.records
        )

    def test_get_domain_context_logs_debug_on_empty_results(self, caplog):
        """get_domain_context() logs debug message when no facts found."""
        mock_storage = MagicMock()
        mock_storage.search_facts.return_value = []

        config = DomainMemoryConfig(enabled=True)
        with (
            patch("deerflow.agents.memory.domain_retrieval.get_domain_memory_config", return_value=config),
            patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage),
            caplog.at_level(logging.DEBUG),
        ):
            get_domain_context(query="Unknown", tenant_id="tenant-1")

        assert any(
            "Domain memory retrieved" in record.message
            and "facts=0" in record.message
            for record in caplog.records
        )
