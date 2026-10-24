"""Tests for readability extraction fallback behavior."""

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
    monkeypatch.setattr("deerflow.utils.readability._readability_js_available", lambda: True)

    article = ReadabilityExtractor().extract_article("<html><head><title>Fallback Title</title></head><body><p>Fallback Content</p></body></html>")

    # The link-preserving Python fallback replaces the readabilipy pure-Python
    # mode; Readability.js is attempted exactly once.
    assert calls == [True]
    assert article.title == "Fallback Title"
    assert "Fallback Content" in article.html_content


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
    monkeypatch.setattr("deerflow.utils.readability._readability_js_available", lambda: True)

    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        ReadabilityExtractor().extract_article("<html><body>test</body></html>")
    assert calls == [True]


def test_availability_probe_failure_uses_fallback_and_is_cached(monkeypatch, caplog):
    """A failing availability probe must degrade explicitly, once, with links kept."""
    from deerflow.utils import readability

    calls = 0

    def fail_probe():
        nonlocal calls
        calls += 1
        raise subprocess.CalledProcessError(1, "npm install")

    readability._reset_readability_probe()
    monkeypatch.setattr(readability, "have_node", fail_probe)
    html = '<html><head><title>Guide</title></head><body><a href="/next">Next</a></body></html>'

    try:
        article = ReadabilityExtractor().extract_article(html, url="https://example.com/current")
        ReadabilityExtractor().extract_article(html, url="https://example.com/current")
    finally:
        readability._reset_readability_probe()

    assert calls == 1
    assert "[Next](https://example.com/next)" in article.to_markdown()
    assert "availability probe failed" in caplog.text


def test_negative_probe_result_is_retried_after_ttl(monkeypatch):
    """A negative probe must not downgrade a process forever: once the
    short-lived cache expires the probe runs again."""
    from deerflow.utils import readability

    calls = 0

    def probe():
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(readability, "have_node", probe)
    monkeypatch.setattr(readability, "_NEGATIVE_PROBE_TTL", 0.0)

    try:
        ReadabilityExtractor().extract_article("<html><body><p>a</p></body></html>")
        ReadabilityExtractor().extract_article("<html><body><p>a</p></body></html>")
    finally:
        readability._reset_readability_probe()

    assert calls == 2


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
