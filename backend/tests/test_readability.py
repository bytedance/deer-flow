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


@pytest.mark.parametrize("src", ["https://example.com/chart(1).png", "/images/chart(a(b)).png", "https://example.com/image.png"])
def test_article_image_urls_are_preserved(src):
    article = Article("Images", f'<p>Before</p><img src="{src}" alt="chart" title="Caption"><p>After</p>', url="https://example.com/page")
    messages = article.to_message()
    expected_url = src if src.startswith("https:") else f"https://example.com{src}"
    assert messages == [
        {"type": "text", "text": "# Images\n\nBefore"},
        {"type": "image_url", "image_url": {"url": expected_url}},
        {"type": "text", "text": "After"},
    ]


def test_article_image_syntax_in_code_remains_text():
    article = Article("Example", "<pre>![example](https://example.com/image.png)</pre>")
    messages = article.to_message()
    assert all(message["type"] == "text" for message in messages)
    assert "![example](https://example.com/image.png)" in messages[0]["text"]
