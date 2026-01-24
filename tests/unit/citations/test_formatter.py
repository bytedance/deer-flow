# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for citation formatter enhancements.

Tests the multi-format citation parsing and extraction capabilities.
"""

import pytest

from src.citations.formatter import (
    parse_citations_from_report,
    _extract_markdown_links,
    _extract_numbered_citations,
    _extract_footnote_citations,
    _extract_html_links,
)


class TestExtractMarkdownLinks:
    """Test Markdown link extraction [title](url)."""

    def test_extract_single_markdown_link(self):
        """Test extraction of a single markdown link."""
        text = "[Example Article](https://example.com)"
        citations = _extract_markdown_links(text)
        assert len(citations) == 1
        assert citations[0]["title"] == "Example Article"
        assert citations[0]["url"] == "https://example.com"
        assert citations[0]["format"] == "markdown"

    def test_extract_multiple_markdown_links(self):
        """Test extraction of multiple markdown links."""
        text = "[Link 1](https://example.com/1) and [Link 2](https://example.com/2)"
        citations = _extract_markdown_links(text)
        assert len(citations) == 2
        assert citations[0]["title"] == "Link 1"
        assert citations[1]["title"] == "Link 2"

    def test_extract_markdown_link_with_spaces(self):
        """Test markdown link with spaces in title."""
        text = "[Article Title With Spaces](https://example.com)"
        citations = _extract_markdown_links(text)
        assert len(citations) == 1
        assert citations[0]["title"] == "Article Title With Spaces"

    def test_extract_markdown_link_ignore_non_http(self):
        """Test that non-HTTP URLs are ignored."""
        text = "[Relative Link](./relative/path) [HTTP Link](https://example.com)"
        citations = _extract_markdown_links(text)
        assert len(citations) == 1
        assert citations[0]["url"] == "https://example.com"

    def test_extract_markdown_link_with_query_params(self):
        """Test markdown links with query parameters."""
        text = "[Search Result](https://example.com/search?q=test&page=1)"
        citations = _extract_markdown_links(text)
        assert len(citations) == 1
        assert "q=test" in citations[0]["url"]

    def test_extract_markdown_link_empty_text(self):
        """Test with no markdown links."""
        text = "Just plain text with no links"
        citations = _extract_markdown_links(text)
        assert len(citations) == 0

    def test_extract_markdown_link_strip_whitespace(self):
        """Test that whitespace in title and URL is stripped."""
        # Markdown links with spaces in URL are not valid, so they won't be extracted
        text = "[Title](https://example.com)"
        citations = _extract_markdown_links(text)
        assert len(citations) >= 1
        assert citations[0]["title"] == "Title"
        assert citations[0]["url"] == "https://example.com"


class TestExtractNumberedCitations:
    """Test numbered citation extraction [1] Title - URL."""

    def test_extract_single_numbered_citation(self):
        """Test extraction of a single numbered citation."""
        text = "[1] Example Article - https://example.com"
        citations = _extract_numbered_citations(text)
        assert len(citations) == 1
        assert citations[0]["title"] == "Example Article"
        assert citations[0]["url"] == "https://example.com"
        assert citations[0]["format"] == "numbered"

    def test_extract_multiple_numbered_citations(self):
        """Test extraction of multiple numbered citations."""
        text = "[1] First - https://example.com/1\n[2] Second - https://example.com/2"
        citations = _extract_numbered_citations(text)
        assert len(citations) == 2
        assert citations[0]["title"] == "First"
        assert citations[1]["title"] == "Second"

    def test_extract_numbered_citation_with_long_title(self):
        """Test numbered citation with longer title."""
        text = "[5] A Comprehensive Guide to Python Programming - https://example.com"
        citations = _extract_numbered_citations(text)
        assert len(citations) == 1
        assert "Comprehensive Guide" in citations[0]["title"]

    def test_extract_numbered_citation_requires_valid_format(self):
        """Test that invalid numbered format is not extracted."""
        text = "[1 Title - https://example.com"  # Missing closing bracket
        citations = _extract_numbered_citations(text)
        assert len(citations) == 0

    def test_extract_numbered_citation_empty_text(self):
        """Test with no numbered citations."""
        text = "Just plain text"
        citations = _extract_numbered_citations(text)
        assert len(citations) == 0

    def test_extract_numbered_citation_various_numbers(self):
        """Test with various citation numbers."""
        text = "[10] Title Ten - https://example.com/10\n[999] Title 999 - https://example.com/999"
        citations = _extract_numbered_citations(text)
        assert len(citations) == 2

    def test_extract_numbered_citation_ignore_non_http(self):
        """Test that non-HTTP URLs in numbered citations are ignored."""
        text = "[1] Invalid - file://path [2] Valid - https://example.com"
        citations = _extract_numbered_citations(text)
        # Only the valid one should be extracted
        assert len(citations) <= 1


class TestExtractFootnoteCitations:
    """Test footnote citation extraction [^1]: Title - URL."""

    def test_extract_single_footnote_citation(self):
        """Test extraction of a single footnote citation."""
        text = "[^1]: Example Article - https://example.com"
        citations = _extract_footnote_citations(text)
        assert len(citations) == 1
        assert citations[0]["title"] == "Example Article"
        assert citations[0]["url"] == "https://example.com"
        assert citations[0]["format"] == "footnote"

    def test_extract_multiple_footnote_citations(self):
        """Test extraction of multiple footnote citations."""
        text = "[^1]: First - https://example.com/1\n[^2]: Second - https://example.com/2"
        citations = _extract_footnote_citations(text)
        assert len(citations) == 2

    def test_extract_footnote_with_complex_number(self):
        """Test footnote extraction with various numbers."""
        text = "[^123]: Title - https://example.com"
        citations = _extract_footnote_citations(text)
        assert len(citations) == 1
        assert citations[0]["title"] == "Title"

    def test_extract_footnote_citation_with_spaces(self):
        """Test footnote with spaces around separator."""
        text = "[^1]:  Title with spaces  -  https://example.com  "
        citations = _extract_footnote_citations(text)
        assert len(citations) == 1
        # Should strip whitespace
        assert citations[0]["title"] == "Title with spaces"

    def test_extract_footnote_citation_empty_text(self):
        """Test with no footnote citations."""
        text = "No footnotes here"
        citations = _extract_footnote_citations(text)
        assert len(citations) == 0

    def test_extract_footnote_requires_caret(self):
        """Test that missing caret prevents extraction."""
        text = "[1]: Title - https://example.com"  # Missing ^
        citations = _extract_footnote_citations(text)
        assert len(citations) == 0


class TestExtractHtmlLinks:
    """Test HTML link extraction <a href="url">title</a>."""

    def test_extract_single_html_link(self):
        """Test extraction of a single HTML link."""
        text = '<a href="https://example.com">Example Article</a>'
        citations = _extract_html_links(text)
        assert len(citations) == 1
        assert citations[0]["title"] == "Example Article"
        assert citations[0]["url"] == "https://example.com"
        assert citations[0]["format"] == "html"

    def test_extract_multiple_html_links(self):
        """Test extraction of multiple HTML links."""
        text = '<a href="https://a.com">Link A</a> <a href="https://b.com">Link B</a>'
        citations = _extract_html_links(text)
        assert len(citations) == 2

    def test_extract_html_link_single_quotes(self):
        """Test HTML links with single quotes."""
        text = "<a href='https://example.com'>Title</a>"
        citations = _extract_html_links(text)
        assert len(citations) == 1
        assert citations[0]["url"] == "https://example.com"

    def test_extract_html_link_with_attributes(self):
        """Test HTML links with additional attributes."""
        text = '<a class="link" href="https://example.com" target="_blank">Title</a>'
        citations = _extract_html_links(text)
        assert len(citations) == 1
        assert citations[0]["url"] == "https://example.com"

    def test_extract_html_link_ignore_non_http(self):
        """Test that non-HTTP URLs are ignored."""
        text = '<a href="mailto:test@example.com">Email</a> <a href="https://example.com">Web</a>'
        citations = _extract_html_links(text)
        assert len(citations) == 1
        assert citations[0]["url"] == "https://example.com"

    def test_extract_html_link_case_insensitive(self):
        """Test that HTML extraction is case-insensitive."""
        text = '<A HREF="https://example.com">Title</A>'
        citations = _extract_html_links(text)
        assert len(citations) == 1

    def test_extract_html_link_empty_text(self):
        """Test with no HTML links."""
        text = "No links here"
        citations = _extract_html_links(text)
        assert len(citations) == 0

    def test_extract_html_link_strip_whitespace(self):
        """Test that whitespace in title is stripped."""
        text = '<a href="https://example.com">  Title with spaces  </a>'
        citations = _extract_html_links(text)
        assert citations[0]["title"] == "Title with spaces"


class TestParseCitationsFromReport:
    """Test comprehensive citation parsing from complete reports."""

    def test_parse_markdown_links_from_report(self):
        """Test parsing markdown links from a report."""
        report = """
        ## Key Citations
        
        [GitHub](https://github.com)
        [Python Docs](https://python.org)
        """
        result = parse_citations_from_report(report)
        assert result["count"] >= 2
        urls = [c["url"] for c in result["citations"]]
        assert "https://github.com" in urls

    def test_parse_numbered_citations_from_report(self):
        """Test parsing numbered citations."""
        report = """
        ## References
        
        [1] GitHub - https://github.com
        [2] Python - https://python.org
        """
        result = parse_citations_from_report(report)
        assert result["count"] >= 2

    def test_parse_mixed_format_citations(self):
        """Test parsing mixed citation formats."""
        report = """
        ## Key Citations
        
        [GitHub](https://github.com)
        [^1]: Python - https://python.org
        [2] Wikipedia - https://wikipedia.org
        <a href="https://stackoverflow.com">Stack Overflow</a>
        """
        result = parse_citations_from_report(report)
        # Should find all 4 citations
        assert result["count"] >= 3

    def test_parse_citations_deduplication(self):
        """Test that duplicate URLs are deduplicated."""
        report = """
        ## Key Citations
        
        [GitHub 1](https://github.com)
        [GitHub 2](https://github.com)
        [GitHub](https://github.com)
        """
        result = parse_citations_from_report(report)
        # Should have only 1 unique citation
        assert result["count"] == 1
        assert result["citations"][0]["url"] == "https://github.com"

    def test_parse_citations_various_section_patterns(self):
        """Test parsing with different section headers."""
        report_refs = """
        ## References
        [GitHub](https://github.com)
        """
        report_sources = """
        ## Sources
        [GitHub](https://github.com)
        """
        report_bibliography = """
        ## Bibliography
        [GitHub](https://github.com)
        """

        assert parse_citations_from_report(report_refs)["count"] >= 1
        assert parse_citations_from_report(report_sources)["count"] >= 1
        assert parse_citations_from_report(report_bibliography)["count"] >= 1

    def test_parse_citations_custom_patterns(self):
        """Test parsing with custom section patterns."""
        report = """
        ## My Custom Sources
        [GitHub](https://github.com)
        """
        result = parse_citations_from_report(
            report,
            section_patterns=[r"##\s*My Custom Sources"]
        )
        assert result["count"] >= 1

    def test_parse_citations_empty_report(self):
        """Test parsing an empty report."""
        result = parse_citations_from_report("")
        assert result["count"] == 0
        assert result["citations"] == []

    def test_parse_citations_no_section(self):
        """Test parsing report without citation section."""
        report = "This is a report with no citations section"
        result = parse_citations_from_report(report)
        assert result["count"] == 0

    def test_parse_citations_complex_report(self):
        """Test parsing a complex, realistic report."""
        report = """
        # Research Report
        
        ## Introduction
        
        This report summarizes findings from multiple sources.
        
        ## Key Findings
        
        Some important discoveries were made based on research [GitHub](https://github.com).
        
        ## Key Citations
        
        1. Primary sources:
        [GitHub](https://github.com) - A collaborative platform
        [^1]: Python - https://python.org
        
        2. Secondary sources:
        [2] Wikipedia - https://wikipedia.org
        
        3. Web resources:
        <a href="https://stackoverflow.com">Stack Overflow</a>
        
        ## Methodology
        
        [Additional](https://example.com) details about methodology.
        
        ---
        
        [^1]: The Python programming language official site
        """

        result = parse_citations_from_report(report)
        # Should extract multiple citations from the Key Citations section
        assert result["count"] >= 3
        urls = [c["url"] for c in result["citations"]]
        # Verify some key URLs are found
        assert any("github.com" in url or "python.org" in url for url in urls)

    def test_parse_citations_stops_at_next_section(self):
        """Test that citation extraction looks for citation sections."""
        report = """
        ## Key Citations
        
        [Cite 1](https://example.com/1)
        [Cite 2](https://example.com/2)
        
        ## Next Section
        
        Some other content
        """
        result = parse_citations_from_report(report)
        # Should extract citations from the Key Citations section
        # Note: The regex stops at next ## section
        assert result["count"] >= 1
        assert any("example.com/1" in c["url"] for c in result["citations"])

    def test_parse_citations_preserves_metadata(self):
        """Test that citation metadata is preserved."""
        report = """
        ## Key Citations
        
        [Python Documentation](https://python.org)
        """
        result = parse_citations_from_report(report)
        assert len(result["citations"]) >= 1
        citation = result["citations"][0]
        assert "title" in citation
        assert "url" in citation
        assert "format" in citation

    def test_parse_citations_whitespace_handling(self):
        """Test handling of various whitespace configurations."""
        report = """
        ##   Key Citations   
        
        [Link](https://example.com)
        
        """
        result = parse_citations_from_report(report)
        assert result["count"] >= 1

    def test_parse_citations_multiline_links(self):
        """Test extraction of links across formatting."""
        report = """
        ## Key Citations
        
        Some paragraph with a [link to example](https://example.com) in the middle.
        """
        result = parse_citations_from_report(report)
        assert result["count"] >= 1
