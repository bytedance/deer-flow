"""Tests for readability extraction fallback behavior."""

import subprocess

import pytest

from deerflow.utils.readability import Article, ReadabilityExtractor


def test_article_to_message_handles_images_without_source_url():
    article = Article("Image", "<img src='https://example.com/photo.png'>")

    assert article.to_message() == [
        {"type": "text", "text": "# Image"},
        {"type": "image_url", "image_url": {"url": "https://example.com/photo.png"}},
    ]


def test_extract_article_preserves_source_url_for_relative_images(monkeypatch):
    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        lambda html, use_readability: {
            "title": "Image",
            "content": "<p>Body</p><img src='photo.png'>",
        },
    )

    article = ReadabilityExtractor().extract_article(
        "<html><body>test</body></html>", url="https://example.com/articles/one"
    )

    assert article.to_message()[-1] == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/articles/photo.png"},
    }


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
