# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.citations.collector import CitationCollector
from src.citations.extractor import (
    _extract_domain,
    citations_to_markdown_references,
    extract_citations_from_messages,
    merge_citations,
)
from src.citations.formatter import CitationFormatter
from src.citations.models import Citation, CitationMetadata


class TestCitationMetadata:
    def test_initialization(self):
        meta = CitationMetadata(
            url="https://example.com/page",
            title="Example Page",
            description="An example description",
        )
        assert meta.url == "https://example.com/page"
        assert meta.title == "Example Page"
        assert meta.description == "An example description"
        assert meta.domain == "example.com"  # Auto-extracted in post_init

    def test_id_generation(self):
        meta = CitationMetadata(url="https://example.com", title="Test")
        # Just check it's a non-empty string, length 12
        assert len(meta.id) == 12
        assert isinstance(meta.id, str)

    def test_to_dict(self):
        meta = CitationMetadata(
            url="https://example.com", title="Test", relevance_score=0.8
        )
        data = meta.to_dict()
        assert data["url"] == "https://example.com"
        assert data["title"] == "Test"
        assert data["relevance_score"] == 0.8
        assert "id" in data


class TestCitation:
    def test_citation_wrapper(self):
        meta = CitationMetadata(url="https://example.com", title="Test")
        citation = Citation(number=1, metadata=meta)

        assert citation.number == 1
        assert citation.url == "https://example.com"
        assert citation.title == "Test"
        assert citation.to_markdown_reference() == "[Test](https://example.com)"
        assert citation.to_numbered_reference() == "[1] Test - https://example.com"


class TestExtractor:
    def test_extract_from_tool_message_web_search(self):
        search_result = {
            "results": [
                {
                    "url": "https://example.com/1",
                    "title": "Result 1",
                    "content": "Content 1",
                    "score": 0.9,
                }
            ]
        }

        msg = ToolMessage(
            content=str(search_result).replace("'", '"'),  # Simple JSON dump simulation
            tool_call_id="call_1",
            name="web_search",
        )
        # Mocking json structure if ToolMessage content expects stringified JSON
        import json

        msg.content = json.dumps(search_result)

        citations = extract_citations_from_messages([msg])
        assert len(citations) == 1
        assert citations[0]["url"] == "https://example.com/1"
        assert citations[0]["title"] == "Result 1"

    def test_extract_domain(self):
        assert _extract_domain("https://www.example.com/path") == "www.example.com"
        assert _extract_domain("http://example.org") == "example.org"

    def test_merge_citations(self):
        existing = [{"url": "https://a.com", "title": "A", "relevance_score": 0.5}]
        new = [
            {"url": "https://b.com", "title": "B", "relevance_score": 0.6},
            {
                "url": "https://a.com",
                "title": "A New",
                "relevance_score": 0.7,
            },  # Better score for A
        ]

        merged = merge_citations(existing, new)
        assert len(merged) == 2

        # Check A was updated
        a_citation = next(c for c in merged if c["url"] == "https://a.com")
        assert a_citation["relevance_score"] == 0.7

        # Check B is present
        b_citation = next(c for c in merged if c["url"] == "https://b.com")
        assert b_citation["title"] == "B"

    def test_citations_to_markdown(self):
        citations = [{"url": "https://a.com", "title": "A", "description": "Desc A"}]
        md = citations_to_markdown_references(citations)
        assert "## Key Citations" in md
        assert "- [A](https://a.com)" in md


class TestCollector:
    def test_add_citations(self):
        collector = CitationCollector()
        results = [
            {"url": "https://example.com", "title": "Example", "content": "Test"}
        ]
        added = collector.add_from_search_results(results, query="test")

        assert len(added) == 1
        assert added[0].url == "https://example.com"
        assert len(collector._citations) == 1


class TestFormatter:
    def test_format_inline(self):
        formatter = CitationFormatter(style="superscript")
        assert formatter.format_inline_marker(1) == "¹"
        assert formatter.format_inline_marker(12) == "¹²"
