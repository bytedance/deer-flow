# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT
from src.crawler.article import Article


class DummyMarkdownify:
    """A dummy markdownify replacement for patching if needed."""

    @staticmethod
    def markdownify(html):
        return html


def test_to_markdown_includes_title(monkeypatch):
    article = Article("Test Title", "<p>Hello <b>world</b>!</p>")
    result = article.to_markdown(including_title=True)
    assert result.startswith("# Test Title")
    assert "Hello" in result


def test_to_markdown_excludes_title():
    article = Article("Test Title", "<p>Hello <b>world</b>!</p>")
    result = article.to_markdown(including_title=False)
    assert not result.startswith("# Test Title")
    assert "Hello" in result


def test_to_message_with_text_only():
    article = Article("Test Title", "<p>Hello world!</p>")
    article.url = "https://example.com/"
    result = article.to_message()
    assert isinstance(result, list)
    assert any(item["type"] == "text" for item in result)
    assert all("type" in item for item in result)


def test_to_message_with_image(monkeypatch):
    html = '<p>Intro</p><img src="img/pic.png"/>'
    article = Article("Title", html)
    article.url = "https://host.com/path/"
    # The markdownify library will convert <img> to markdown image syntax
    result = article.to_message()
    # Should have both text and image_url types
    types = [item["type"] for item in result]
    assert "image_url" in types
    assert "text" in types
    # Check that the image_url is correctly joined
    image_items = [item for item in result if item["type"] == "image_url"]
    assert image_items
    assert image_items[0]["image_url"]["url"] == "https://host.com/path/img/pic.png"


def test_to_message_multiple_images():
    html = '<p>Start</p><img src="a.png"/><p>Mid</p><img src="b.jpg"/>End'
    article = Article("Title", html)
    article.url = "http://x/"
    result = article.to_message()
    image_urls = [
        item["image_url"]["url"] for item in result if item["type"] == "image_url"
    ]
    assert "http://x/a.png" in image_urls
    assert "http://x/b.jpg" in image_urls
    text_items = [item for item in result if item["type"] == "text"]
    assert any("Start" in item["text"] for item in text_items)
    assert any("Mid" in item["text"] for item in text_items)


def test_to_message_handles_empty_html():
    article = Article("Empty", "")
    article.url = "http://test/"
    result = article.to_message()
    assert isinstance(result, list)
    assert result[0]["type"] == "text"
