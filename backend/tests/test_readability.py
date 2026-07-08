"""Tests for readability extraction fallback behavior."""

import pytest

from deerflow.utils.readability import ReadabilityExtractor


def test_extract_article_uses_pure_python_extractor_first(monkeypatch):
    """The extractor should use the pure-Python path directly."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        return {"title": "Fallback Title", "content": "<p>Fallback Content</p>"}

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    article = ReadabilityExtractor().extract_article("<html><body>test</body></html>")

    assert calls == [False]
    assert article.title == "Fallback Title"
    assert article.html_content == "<p>Fallback Content</p>"


def test_extract_article_falls_back_to_raw_html_on_extractor_error(monkeypatch):
    """Unexpected extractor errors should fall back to raw HTML."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    article = ReadabilityExtractor().extract_article("<html><body>test</body></html>")
    assert calls == [False]
    assert article.title == "Untitled"
    assert article.html_content == "<html><body>test</body></html>"
