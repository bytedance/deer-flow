"""Tests for readability extraction fallback behavior."""

import subprocess

import pytest

from deerflow.utils.readability import Article, ReadabilityExtractor


def test_extract_article_falls_back_when_readability_js_fails(monkeypatch):
    """When Node-based readability fails, extraction should use the link-preserving Python fallback."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["node", "ExtractArticle.js"],
            stderr="boom",
        )

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )
    monkeypatch.setattr("deerflow.utils.readability._readability_available", lambda: True)
    monkeypatch.setattr(
        "deerflow.utils.readability._python_fallback_article_json",
        lambda html: {"title": "Fallback Title", "content": "<p>Fallback Content</p>"},
    )

    article = ReadabilityExtractor().extract_article("<html><body>test</body></html>")

    assert calls == [True]
    assert article.title == "Fallback Title"
    assert article.html_content == "<p>Fallback Content</p>"


def test_extract_article_re_raises_unexpected_exception(monkeypatch):
    """Unexpected errors should be surfaced instead of silently falling back."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )
    monkeypatch.setattr("deerflow.utils.readability._readability_available", lambda: True)

    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        ReadabilityExtractor().extract_article("<html><body>test</body></html>")
    assert calls == [True]


def test_unavailable_readabilityjs_never_invokes_node_extraction(monkeypatch):
    """On hosts without Readability.js, the node path must not be attempted at all."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        return {"title": "Should Not Run", "content": "<p>node</p>"}

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )
    monkeypatch.setattr("deerflow.utils.readability._readability_available", lambda: False)

    article = ReadabilityExtractor().extract_article("<html><body>test</body></html>")

    assert calls == []
    assert "test" in article.html_content


def test_article_to_message_with_images():
    """Article.to_message should handle articles containing images without AttributeError."""
    # Absolute image URL without source url
    art_abs = Article("Test Image", '<img src="https://example.com/pic.png">')
    msg_abs = art_abs.to_message()
    assert any(block.get("type") == "image_url" and block["image_url"]["url"] == "https://example.com/pic.png" for block in msg_abs)

    # Relative image URL with source url
    art_rel = Article("Test Relative Image", '<img src="/assets/pic.png">', url="https://example.com/base/")
    msg_rel = art_rel.to_message()
    assert any(block.get("type") == "image_url" and block["image_url"]["url"] == "https://example.com/assets/pic.png" for block in msg_rel)
