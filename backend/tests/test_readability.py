"""Tests for readability extraction and message conversion."""

import subprocess

import pytest

from deerflow.utils.readability import Article, ReadabilityExtractor


def test_extract_article_falls_back_when_readability_js_fails(monkeypatch):
    """When Node-based readability fails, extraction should fall back to Python mode."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        if use_readability:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["node", "ExtractArticle.js"],
                stderr="boom",
            )
        return {"title": "Fallback Title", "content": "<p>Fallback Content</p>"}

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    article = ReadabilityExtractor().extract_article("<html><body>test</body></html>")

    assert calls == [True, False]
    assert article.title == "Fallback Title"
    assert article.html_content == "<p>Fallback Content</p>"


def test_extract_article_re_raises_unexpected_exception(monkeypatch):
    """Unexpected errors should be surfaced instead of silently falling back."""

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        if use_readability:
            raise RuntimeError("unexpected parser failure")
        return {"title": "Should Not Reach Fallback", "content": "<p>Fallback</p>"}

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        ReadabilityExtractor().extract_article("<html><body>test</body></html>")
    assert calls == [True]


def test_article_to_message_keeps_absolute_image_url():
    article = Article("Image", '<img src="https://example.com/photo.png" alt="Photo">')

    assert {"type": "image_url", "image_url": {"url": "https://example.com/photo.png"}} in article.to_message()


def test_article_to_message_resolves_relative_image_url():
    article = Article("Image", '<img src="../photo.png" alt="Photo">', url="https://example.com/posts/one")

    assert {"type": "image_url", "image_url": {"url": "https://example.com/photo.png"}} in article.to_message()


def test_extracted_article_to_message_resolves_relative_image_url():
    html = """
    <html><head><title>Image article</title></head>
    <body><article><h1>Image article</h1>
    <p>This article has a photograph and enough text to be extracted by readability.</p>
    <img src="../photo.png" alt="Photo">
    </article></body></html>
    """

    article = ReadabilityExtractor().extract_article(html, url="https://example.com/posts/one")

    assert article.url == "https://example.com/posts/one"
    assert {"type": "image_url", "image_url": {"url": "https://example.com/photo.png"}} in article.to_message()
