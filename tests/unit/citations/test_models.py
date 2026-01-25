# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for citation models.

Tests the Pydantic BaseModel implementation of CitationMetadata and Citation classes.
"""

import json

import pytest
from pydantic import ValidationError

from src.citations.models import Citation, CitationMetadata


class TestCitationMetadata:
    """Test CitationMetadata Pydantic model."""

    def test_create_basic_metadata(self):
        """Test creating basic citation metadata."""
        metadata = CitationMetadata(
            url="https://example.com/article",
            title="Example Article",
        )
        assert metadata.url == "https://example.com/article"
        assert metadata.title == "Example Article"
        assert metadata.domain == "example.com"  # Auto-extracted from URL
        assert metadata.description is None
        assert metadata.images == []
        assert metadata.extra == {}

    def test_metadata_with_all_fields(self):
        """Test creating metadata with all fields populated."""
        metadata = CitationMetadata(
            url="https://github.com/example/repo",
            title="Example Repository",
            description="A great repository",
            content_snippet="This is a snippet",
            raw_content="Full content here",
            author="John Doe",
            published_date="2025-01-24",
            language="en",
            relevance_score=0.95,
            credibility_score=0.88,
        )
        assert metadata.url == "https://github.com/example/repo"
        assert metadata.domain == "github.com"
        assert metadata.author == "John Doe"
        assert metadata.relevance_score == 0.95
        assert metadata.credibility_score == 0.88

    def test_metadata_domain_auto_extraction(self):
        """Test automatic domain extraction from URL."""
        test_cases = [
            ("https://www.example.com/path", "www.example.com"),
            ("http://github.com/user/repo", "github.com"),
            ("https://api.github.com:443/repos", "api.github.com:443"),
        ]

        for url, expected_domain in test_cases:
            metadata = CitationMetadata(url=url, title="Test")
            assert metadata.domain == expected_domain

    def test_metadata_id_generation(self):
        """Test unique ID generation from URL."""
        metadata1 = CitationMetadata(
            url="https://example.com/article",
            title="Article",
        )
        metadata2 = CitationMetadata(
            url="https://example.com/article",
            title="Article",
        )
        # Same URL should produce same ID
        assert metadata1.id == metadata2.id

        metadata3 = CitationMetadata(
            url="https://different.com/article",
            title="Article",
        )
        # Different URL should produce different ID
        assert metadata1.id != metadata3.id

    def test_metadata_id_length(self):
        """Test that ID is truncated to 12 characters."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Test",
        )
        assert len(metadata.id) == 12
        assert metadata.id.isalnum() or all(c in "0123456789abcdef" for c in metadata.id)

    def test_metadata_from_dict(self):
        """Test creating metadata from dictionary."""
        data = {
            "url": "https://example.com",
            "title": "Example",
            "description": "A description",
            "author": "John Doe",
        }
        metadata = CitationMetadata.from_dict(data)
        assert metadata.url == "https://example.com"
        assert metadata.title == "Example"
        assert metadata.description == "A description"
        assert metadata.author == "John Doe"

    def test_metadata_from_dict_removes_id(self):
        """Test that from_dict removes computed 'id' field."""
        data = {
            "url": "https://example.com",
            "title": "Example",
            "id": "some_old_id",  # Should be ignored
        }
        metadata = CitationMetadata.from_dict(data)
        # Should use newly computed ID, not the old one
        assert metadata.id != "some_old_id"

    def test_metadata_to_dict(self):
        """Test converting metadata to dictionary."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
            author="John Doe",
        )
        result = metadata.to_dict()

        assert result["url"] == "https://example.com"
        assert result["title"] == "Example"
        assert result["author"] == "John Doe"
        assert result["id"] == metadata.id
        assert result["domain"] == "example.com"

    def test_metadata_from_search_result(self):
        """Test creating metadata from search result."""
        search_result = {
            "url": "https://example.com/article",
            "title": "Article Title",
            "content": "Article content here",
            "score": 0.92,
            "type": "page",
        }
        metadata = CitationMetadata.from_search_result(
            search_result,
            query="test query",
        )

        assert metadata.url == "https://example.com/article"
        assert metadata.title == "Article Title"
        assert metadata.description == "Article content here"
        assert metadata.relevance_score == 0.92
        assert metadata.extra["query"] == "test query"
        assert metadata.extra["result_type"] == "page"

    def test_metadata_pydantic_validation(self):
        """Test that Pydantic validates required fields."""
        # URL and title are required
        with pytest.raises(ValidationError):
            CitationMetadata()  # Missing required fields

        with pytest.raises(ValidationError):
            CitationMetadata(url="https://example.com")  # Missing title

    def test_metadata_model_dump(self):
        """Test Pydantic model_dump method."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
            author="John Doe",
        )
        result = metadata.model_dump()

        assert isinstance(result, dict)
        assert result["url"] == "https://example.com"
        assert result["title"] == "Example"

    def test_metadata_model_dump_json(self):
        """Test Pydantic model_dump_json method."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        result = metadata.model_dump_json()

        assert isinstance(result, str)
        data = json.loads(result)
        assert data["url"] == "https://example.com"
        assert data["title"] == "Example"

    def test_metadata_with_images_and_extra(self):
        """Test metadata with list and dict fields."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
            images=["https://example.com/image1.jpg", "https://example.com/image2.jpg"],
            favicon="https://example.com/favicon.ico",
            extra={"custom_field": "value", "tags": ["tag1", "tag2"]},
        )

        assert len(metadata.images) == 2
        assert metadata.favicon == "https://example.com/favicon.ico"
        assert metadata.extra["custom_field"] == "value"


class TestCitation:
    """Test Citation Pydantic model."""

    def test_create_basic_citation(self):
        """Test creating a basic citation."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        citation = Citation(number=1, metadata=metadata)

        assert citation.number == 1
        assert citation.metadata == metadata
        assert citation.context is None
        assert citation.cited_text is None

    def test_citation_properties(self):
        """Test citation property shortcuts."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example Title",
        )
        citation = Citation(number=1, metadata=metadata)

        assert citation.id == metadata.id
        assert citation.url == "https://example.com"
        assert citation.title == "Example Title"

    def test_citation_to_markdown_reference(self):
        """Test markdown reference generation."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        citation = Citation(number=1, metadata=metadata)

        result = citation.to_markdown_reference()
        assert result == "[Example](https://example.com)"

    def test_citation_to_numbered_reference(self):
        """Test numbered reference generation."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example Article",
        )
        citation = Citation(number=5, metadata=metadata)

        result = citation.to_numbered_reference()
        assert result == "[5] Example Article - https://example.com"

    def test_citation_to_inline_marker(self):
        """Test inline marker generation."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        citation = Citation(number=3, metadata=metadata)

        result = citation.to_inline_marker()
        assert result == "[^3]"

    def test_citation_to_footnote(self):
        """Test footnote generation."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example Article",
        )
        citation = Citation(number=2, metadata=metadata)

        result = citation.to_footnote()
        assert result == "[^2]: Example Article - https://example.com"

    def test_citation_with_context_and_text(self):
        """Test citation with context and cited text."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        citation = Citation(
            number=1,
            metadata=metadata,
            context="This is important context",
            cited_text="Important quote from the source",
        )

        assert citation.context == "This is important context"
        assert citation.cited_text == "Important quote from the source"

    def test_citation_from_dict(self):
        """Test creating citation from dictionary."""
        data = {
            "number": 1,
            "metadata": {
                "url": "https://example.com",
                "title": "Example",
                "author": "John Doe",
            },
            "context": "Test context",
        }
        citation = Citation.from_dict(data)

        assert citation.number == 1
        assert citation.metadata.url == "https://example.com"
        assert citation.metadata.title == "Example"
        assert citation.metadata.author == "John Doe"
        assert citation.context == "Test context"

    def test_citation_to_dict(self):
        """Test converting citation to dictionary."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
            author="John Doe",
        )
        citation = Citation(
            number=1,
            metadata=metadata,
            context="Test context",
        )
        result = citation.to_dict()

        assert result["number"] == 1
        assert result["metadata"]["url"] == "https://example.com"
        assert result["metadata"]["author"] == "John Doe"
        assert result["context"] == "Test context"

    def test_citation_round_trip(self):
        """Test converting to dict and back."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
            author="John Doe",
            relevance_score=0.95,
        )
        original = Citation(number=1, metadata=metadata, context="Test")

        # Convert to dict and back
        dict_repr = original.to_dict()
        restored = Citation.from_dict(dict_repr)

        assert restored.number == original.number
        assert restored.metadata.url == original.metadata.url
        assert restored.metadata.title == original.metadata.title
        assert restored.metadata.author == original.metadata.author
        assert restored.metadata.relevance_score == original.metadata.relevance_score

    def test_citation_model_dump(self):
        """Test Pydantic model_dump method."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        citation = Citation(number=1, metadata=metadata)
        result = citation.model_dump()

        assert isinstance(result, dict)
        assert result["number"] == 1
        assert result["metadata"]["url"] == "https://example.com"

    def test_citation_model_dump_json(self):
        """Test Pydantic model_dump_json method."""
        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        citation = Citation(number=1, metadata=metadata)
        result = citation.model_dump_json()

        assert isinstance(result, str)
        data = json.loads(result)
        assert data["number"] == 1
        assert data["metadata"]["url"] == "https://example.com"

    def test_citation_pydantic_validation(self):
        """Test that Pydantic validates required fields."""
        # Number and metadata are required
        with pytest.raises(ValidationError):
            Citation()  # Missing required fields

        metadata = CitationMetadata(
            url="https://example.com",
            title="Example",
        )
        with pytest.raises(ValidationError):
            Citation(metadata=metadata)  # Missing number


class TestCitationIntegration:
    """Integration tests for citation models."""

    def test_search_result_to_citation_workflow(self):
        """Test complete workflow from search result to citation."""
        search_result = {
            "url": "https://example.com/article",
            "title": "Great Article",
            "content": "This is a great article about testing",
            "score": 0.92,
        }

        # Create metadata from search result
        metadata = CitationMetadata.from_search_result(search_result, query="testing")

        # Create citation
        citation = Citation(number=1, metadata=metadata, context="Important source")

        # Verify the workflow
        assert citation.number == 1
        assert citation.url == "https://example.com/article"
        assert citation.title == "Great Article"
        assert citation.metadata.relevance_score == 0.92
        assert citation.to_markdown_reference() == "[Great Article](https://example.com/article)"

    def test_multiple_citations_with_different_formats(self):
        """Test handling multiple citations in different formats."""
        citations = []

        # Create first citation
        metadata1 = CitationMetadata(
            url="https://example.com/1",
            title="First Article",
        )
        citations.append(Citation(number=1, metadata=metadata1))

        # Create second citation
        metadata2 = CitationMetadata(
            url="https://example.com/2",
            title="Second Article",
        )
        citations.append(Citation(number=2, metadata=metadata2))

        # Verify all reference formats
        assert citations[0].to_markdown_reference() == "[First Article](https://example.com/1)"
        assert citations[1].to_numbered_reference() == "[2] Second Article - https://example.com/2"

    def test_citation_json_serialization_roundtrip(self):
        """Test JSON serialization and deserialization roundtrip."""
        original_data = {
            "number": 1,
            "metadata": {
                "url": "https://example.com",
                "title": "Example",
                "author": "John Doe",
                "relevance_score": 0.95,
            },
            "context": "Test context",
            "cited_text": "Important quote",
        }

        # Create from dict
        citation = Citation.from_dict(original_data)

        # Serialize to JSON
        json_str = citation.model_dump_json()

        # Deserialize from JSON
        restored = Citation.model_validate_json(json_str)

        # Verify data integrity
        assert restored.number == original_data["number"]
        assert restored.metadata.url == original_data["metadata"]["url"]
        assert restored.metadata.relevance_score == original_data["metadata"]["relevance_score"]
        assert restored.context == original_data["context"]
