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


def test_python_fallback_title_prefers_og_title_over_generic_title_tag():
    """A generic site-name <title> must not replace the real og:title headline."""
    from deerflow.utils.readability import _python_fallback_article_json

    html = '<html><head><title>Example Site</title><meta property="og:title" content="The Real Headline"></head><body><p>Body prose.</p></body></html>'

    assert _python_fallback_article_json(html)["title"] == "The Real Headline"


def test_python_fallback_title_prefers_h1_when_title_is_generic_or_missing():
    """Pages without a headline <title> keep their entry <h1> headline."""
    from deerflow.utils.readability import _python_fallback_article_json

    generic_title = "<html><head><title>Example Site</title></head><body><h1>Entry Headline</h1><p>Body prose.</p></body></html>"
    missing_title = "<html><body><h1>Entry Headline</h1><p>Body prose.</p></body></html>"

    assert _python_fallback_article_json(generic_title)["title"] == "Entry Headline"
    assert _python_fallback_article_json(missing_title)["title"] == "Entry Headline"


def test_python_fallback_keeps_all_articles_and_sibling_content():
    """A teaser article before the real content must not truncate the page."""
    from deerflow.utils.readability import _python_fallback_article_json

    body_prose = "<p>Real story prose. </p>" * 30
    html = f"<html><head><title>News</title></head><body><article><h2>Teaser</h2><p>Short summary of another story.</p></article><section><h1>Real Story</h1>{body_prose}<a href='../next'>Next</a></section></body></html>"

    article = _python_fallback_article_json(html)

    assert "Teaser" in article["content"]
    assert "Real Story" in article["content"]
    assert '<a href="../next">Next</a>' in article["content"]
    # The entry <h1> headline wins over the generic document title.
    assert article["title"] == "Real Story"


def test_python_fallback_selects_main_container_over_first_article():
    """<main> is the canonical container; content outside it is site chrome."""
    from deerflow.utils.readability import _python_fallback_article_json

    body_prose = "<p>Section prose. </p>" * 20
    html = f"<html><body><article><h2>Teaser</h2><p>Short summary.</p></article><main><h1>Real Story</h1>{body_prose}</main></body></html>"

    article = _python_fallback_article_json(html)

    # Per HTML5 semantics, site-level chrome (e.g. a related-story teaser)
    # lives outside <main> and is intentionally not part of the article body.
    assert "Teaser" not in article["content"]
    assert "Real Story" in article["content"]
    assert article["title"] == "Real Story"


def test_python_fallback_selects_dominant_single_article():
    """A single article carrying nearly all text narrows to drop residual noise."""
    from deerflow.utils.readability import _python_fallback_article_json

    body_prose = "<p>This article explains the documentation in detail.</p>" * 20
    html = f"<html><head><title>Doc</title></head><body><article><h1>Main Article</h1>{body_prose}</article><p>Cookie notice.</p></body></html>"

    article = _python_fallback_article_json(html)

    assert "Main Article" in article["content"]
    assert "Cookie notice" not in article["content"]


def test_python_fallback_title_skips_site_header_h1():
    """A site/logo <h1> inside <header> must not outrank the real <title>."""
    from deerflow.utils.readability import _python_fallback_article_json

    html = f"<html><head><title>Real Story</title></head><body><header><h1>Site Name</h1></header><p>{'Story prose. ' * 30}</p></body></html>"

    assert _python_fallback_article_json(html)["title"] == "Real Story"


def test_python_fallback_title_uses_container_h1_over_site_header():
    """A real headline <h1> inside the content container beats a site-header <h1>."""
    from deerflow.utils.readability import _python_fallback_article_json

    body_prose = "<p>Section prose. </p>" * 20
    html = f"<html><head><title>News</title></head><body><header><h1>Site Name</h1></header><main><h1>Real Story</h1>{body_prose}</main></body></html>"

    assert _python_fallback_article_json(html)["title"] == "Real Story"


def test_python_fallback_title_keeps_article_header_headline():
    """A header owned by the article carries the real headline, not site chrome."""
    from deerflow.utils.readability import _python_fallback_article_json

    body_prose = "<p>Story prose. </p>" * 20
    html = f'<html><head><title>Site Name</title></head><body><main><article><header class="entry-header"><h1 class="entry-title">Real Story</h1></header>{body_prose}</article></main></body></html>'

    assert _python_fallback_article_json(html)["title"] == "Real Story"


def test_python_fallback_title_keeps_words_across_inline_elements():
    """Inline children must not glue headline words together."""
    from deerflow.utils.readability import _python_fallback_article_json

    html = f"<html><head><title>Generic</title></head><body><h1>Real <em>Story</em> Today</h1><p>{'Body prose. ' * 20}</p></body></html>"

    assert _python_fallback_article_json(html)["title"] == "Real Story Today"


def test_probe_caches_unavailability_when_npm_install_fails(monkeypatch):
    """A failing npm install must be cached as unavailability, not retried per fetch."""
    from deerflow.utils.readability import _readability_available

    _readability_available.cache_clear()
    try:
        calls: list[int] = []

        def failing_have_node():
            calls.append(1)
            raise subprocess.CalledProcessError(1, ["npm", "install"], stderr="boom")

        monkeypatch.setattr("deerflow.utils.readability.have_node", failing_have_node)

        assert _readability_available() is False
        assert _readability_available() is False
        assert len(calls) == 1
    finally:
        # Restore the process-wide cache state for the other tests.
        _readability_available.cache_clear()


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
