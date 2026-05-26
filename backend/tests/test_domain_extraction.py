"""Unit tests for domain fact extraction."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from deerflow.agents.memory.updater import extract_domain_facts, update_domain_from_conversation


class TestExtractDomainFacts:
    """Tests for extract_domain_facts() function."""

    def test_empty_messages_returns_empty(self):
        """extract_domain_facts() returns empty list for empty messages."""
        result = extract_domain_facts([], tenant_id="tenant-1")
        assert result == []

    def test_extracts_facts_from_llm_response(self):
        """extract_domain_facts() parses LLM response and stores facts."""
        messages = [
            Mock(type="human", content="Pump A has a flow rate of 500 GPM"),
            Mock(type="ai", content="I'll note that about Pump A"),
        ]

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=json.dumps({
            "facts": [
                {
                    "content": "Pump A flow rate is 500 GPM",
                    "domain": "equipment",
                    "entity_id": "Pump A",
                    "confidence": 0.95,
                },
            ],
        })))

        mock_storage = Mock()
        mock_storage.store_fact = Mock(return_value="fact-123")

        with patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage):
            result = extract_domain_facts(
                messages=messages,
                tenant_id="tenant-1",
                model=mock_model,
            )

        assert len(result) == 1
        assert result[0]["id"] == "fact-123"
        assert result[0]["domain"] == "equipment"
        assert result[0]["entity_id"] == "Pump A"
        mock_storage.store_fact.assert_called_once()

    def test_filters_low_confidence_facts(self):
        """extract_domain_facts() skips facts below confidence threshold."""
        messages = [Mock(type="human", content="Maybe pump A is broken")]

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=json.dumps({
            "facts": [
                {
                    "content": "Pump A might be broken",
                    "domain": "equipment",
                    "entity_id": "Pump A",
                    "confidence": 0.5,  # Below default threshold
                },
            ],
        })))

        mock_storage = Mock()

        with patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage):
            result = extract_domain_facts(
                messages=messages,
                tenant_id="tenant-1",
                model=mock_model,
                confidence_threshold=0.8,
            )

        assert result == []
        mock_storage.store_fact.assert_not_called()

    def test_skips_facts_without_required_fields(self):
        """extract_domain_facts() skips facts missing domain, entity_id, or content."""
        messages = [Mock(type="human", content="Some fact")]

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=json.dumps({
            "facts": [
                {"content": "No domain", "entity_id": "X", "confidence": 0.9},
                {"content": "No entity", "domain": "equipment", "confidence": 0.9},
                {"domain": "equipment", "entity_id": "X", "confidence": 0.9},
            ],
        })))

        mock_storage = Mock()

        with patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage):
            result = extract_domain_facts(
                messages=messages,
                tenant_id="tenant-1",
                model=mock_model,
            )

        assert result == []

    def test_handles_markdown_code_blocks(self):
        """extract_domain_facts() strips markdown code blocks from response."""
        messages = [Mock(type="human", content="Pump A info")]

        response_content = "```json\n" + json.dumps({
            "facts": [
                {"content": "Fact", "domain": "equipment", "entity_id": "Pump A", "confidence": 0.9},
            ],
        }) + "\n```"

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=response_content))

        mock_storage = Mock()
        mock_storage.store_fact = Mock(return_value="fact-123")

        with patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=mock_storage):
            result = extract_domain_facts(
                messages=messages,
                tenant_id="tenant-1",
                model=mock_model,
            )

        assert len(result) == 1

    def test_handles_json_decode_error(self):
        """extract_domain_facts() returns empty list on invalid JSON."""
        messages = [Mock(type="human", content="Test")]

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content="Invalid JSON response"))

        with patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=Mock()):
            result = extract_domain_facts(
                messages=messages,
                tenant_id="tenant-1",
                model=mock_model,
            )

        assert result == []

    def test_returns_empty_when_storage_unavailable(self):
        """extract_domain_facts() returns empty list when storage is None."""
        messages = [Mock(type="human", content="Pump A info")]

        mock_model = Mock()
        mock_model.invoke = Mock(return_value=Mock(content=json.dumps({"facts": []})))

        with patch("deerflow.agents.memory.domain_storage.get_domain_storage", return_value=None):
            result = extract_domain_facts(
                messages=messages,
                tenant_id="tenant-1",
                model=mock_model,
            )

        assert result == []


class TestUpdateDomainFromConversation:
    """Tests for update_domain_from_conversation() convenience function."""

    def test_returns_true_when_facts_stored(self):
        """update_domain_from_conversation() returns True when facts are extracted."""
        messages = [Mock(type="human", content="Pump A info")]

        with patch("deerflow.agents.memory.updater.extract_domain_facts", return_value=[{"id": "fact-1"}]):
            result = update_domain_from_conversation(
                messages=messages,
                tenant_id="tenant-1",
            )

        assert result is True

    def test_returns_false_when_no_facts(self):
        """update_domain_from_conversation() returns False when no facts extracted."""
        messages = [Mock(type="human", content="No domain facts")]

        with patch("deerflow.agents.memory.updater.extract_domain_facts", return_value=[]):
            result = update_domain_from_conversation(
                messages=messages,
                tenant_id="tenant-1",
            )

        assert result is False
