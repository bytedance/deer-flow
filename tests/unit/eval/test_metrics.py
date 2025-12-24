# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Unit tests for report evaluation metrics."""

from src.eval.metrics import (
    compute_metrics,
    count_citations,
    count_images,
    count_words,
    detect_sections,
    extract_domains,
    get_word_count_target,
)


class TestCountWords:
    """Tests for word counting function."""

    def test_english_words(self):
        text = "This is a simple test sentence."
        assert count_words(text) == 6

    def test_chinese_characters(self):
        text = "这是一个测试"
        assert count_words(text) == 6

    def test_mixed_content(self):
        text = "Hello 你好 World 世界"
        assert count_words(text) == 4 + 2  # 2 English + 4 Chinese

    def test_empty_string(self):
        assert count_words("") == 0


class TestCountCitations:
    """Tests for citation counting function."""

    def test_markdown_citations(self):
        text = """
        Check out [Google](https://google.com) and [GitHub](https://github.com).
        """
        assert count_citations(text) == 2

    def test_no_citations(self):
        text = "This is plain text without any links."
        assert count_citations(text) == 0

    def test_invalid_urls(self):
        text = "[Link](not-a-url) [Another](ftp://ftp.example.com)"
        assert count_citations(text) == 0

    def test_complex_urls(self):
        text = "[Article](https://example.com/path/to/article?id=123&ref=test)"
        assert count_citations(text) == 1


class TestExtractDomains:
    """Tests for domain extraction function."""

    def test_extract_multiple_domains(self):
        text = """
        https://google.com/search
        https://www.github.com/user/repo
        https://docs.python.org/3/
        """
        domains = extract_domains(text)
        assert len(domains) == 3
        assert "google.com" in domains
        assert "github.com" in domains
        assert "docs.python.org" in domains

    def test_deduplicate_domains(self):
        text = """
        https://example.com/page1
        https://example.com/page2
        https://www.example.com/page3
        """
        domains = extract_domains(text)
        assert len(domains) == 1
        assert "example.com" in domains

    def test_no_urls(self):
        text = "Plain text without URLs"
        assert extract_domains(text) == []


class TestCountImages:
    """Tests for image counting function."""

    def test_markdown_images(self):
        text = """
        ![Alt text](https://example.com/image1.png)
        ![](https://example.com/image2.jpg)
        """
        assert count_images(text) == 2

    def test_no_images(self):
        text = "Text without images [link](url)"
        assert count_images(text) == 0


class TestDetectSections:
    """Tests for section detection function."""

    def test_detect_title(self):
        text = "# My Report Title\n\nSome content here."
        sections = detect_sections(text)
        assert sections.get("title") is True

    def test_detect_key_points(self):
        text = "## Key Points\n- Point 1\n- Point 2"
        sections = detect_sections(text)
        assert sections.get("key_points") is True

    def test_detect_chinese_sections(self):
        text = """# 报告标题
## 要点
- 要点1
## 概述
这是概述内容
        """
        sections = detect_sections(text)
        assert sections.get("title") is True
        assert sections.get("key_points") is True
        assert sections.get("overview") is True

    def test_detect_citations_section(self):
        text = """
        ## Key Citations
        - [Source 1](https://example.com)
        """
        sections = detect_sections(text)
        assert sections.get("key_citations") is True


class TestComputeMetrics:
    """Tests for the main compute_metrics function."""

    def test_complete_report(self):
        report = """
# Research Report Title

## Key Points
- Point 1
- Point 2
- Point 3

## Overview
This is an overview of the research topic.

## Detailed Analysis
Here is the detailed analysis with [source](https://example.com).

![Figure 1](https://example.com/image.png)

## Key Citations
- [Source 1](https://example.com)
- [Source 2](https://another.com)
        """
        metrics = compute_metrics(report)

        assert metrics.has_title is True
        assert metrics.has_key_points is True
        assert metrics.has_overview is True
        assert metrics.has_citations_section is True
        assert metrics.citation_count >= 2
        assert metrics.image_count == 1
        assert metrics.unique_sources >= 1
        assert metrics.section_coverage_score > 0.5

    def test_minimal_report(self):
        report = "Just some text without structure."
        metrics = compute_metrics(report)

        assert metrics.has_title is False
        assert metrics.citation_count == 0
        assert metrics.section_coverage_score < 0.5

    def test_metrics_to_dict(self):
        report = "# Title\n\nSome content"
        metrics = compute_metrics(report)
        result = metrics.to_dict()

        assert isinstance(result, dict)
        assert "word_count" in result
        assert "citation_count" in result
        assert "section_coverage_score" in result


class TestGetWordCountTarget:
    """Tests for word count target function."""

    def test_strategic_investment_target(self):
        target = get_word_count_target("strategic_investment")
        assert target["min"] == 10000
        assert target["max"] == 15000

    def test_news_target(self):
        target = get_word_count_target("news")
        assert target["min"] == 800
        assert target["max"] == 2000

    def test_default_target(self):
        target = get_word_count_target("unknown_style")
        assert target["min"] == 1000
        assert target["max"] == 5000
