"""Tests for readability extraction fallback behavior."""

import subprocess

import pytest

from deerflow.utils.readability import Article, ReadabilityExtractor


@pytest.fixture(autouse=True)
def _reset_readability_js_state(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readabilipy_have_node", lambda: True)
    monkeypatch.setattr(readability, "_readability_js_launch_failed", False)
    monkeypatch.setattr(readability, "_readability_js_available_cached", None)


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


def test_unavailable_readability_uses_cached_link_preserving_fallback(monkeypatch):
    from deerflow.utils import readability

    probe_calls = 0
    extraction_modes: list[bool] = []
    original = readability.simple_json_from_html_string

    def unavailable():
        nonlocal probe_calls
        probe_calls += 1
        return False

    def extract(html: str, use_readability: bool = False):
        extraction_modes.append(use_readability)
        return original(html, use_readability=use_readability)

    monkeypatch.setattr(readability, "_readabilipy_have_node", unavailable)
    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)
    html = '<html><head><title>Guide</title></head><body><article><p>Body</p><a href="/next">Next</a></article></body></html>'

    first = ReadabilityExtractor().extract_article(html, url="https://example.com/current")
    second = ReadabilityExtractor().extract_article(html, url="https://example.com/current")

    assert "[Next](https://example.com/next)" in first.to_markdown()
    assert second.to_markdown() == first.to_markdown()
    assert probe_calls == 1
    assert extraction_modes == [False, False]


def test_readability_probe_failure_is_cached(monkeypatch):
    from deerflow.utils import readability

    probe_calls = 0
    extraction_modes: list[bool] = []

    def fail_probe():
        nonlocal probe_calls
        probe_calls += 1
        raise FileNotFoundError("npm")

    def extract(_html: str, use_readability: bool = False):
        extraction_modes.append(use_readability)
        return {"title": "Guide", "content": "<p>Body</p>"}

    monkeypatch.setattr(readability, "_readabilipy_have_node", fail_probe)
    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)

    ReadabilityExtractor().extract_article("<html><body>Body</body></html>")
    ReadabilityExtractor().extract_article("<html><body>Body</body></html>")

    assert probe_calls == 1
    assert extraction_modes == [False, False]


def test_document_runtime_failure_retries_node_for_later_documents(monkeypatch):
    from deerflow.utils import readability

    probe_calls = 0
    node_attempts = 0
    extraction_modes: list[bool] = []

    def available():
        nonlocal probe_calls
        probe_calls += 1
        return True

    def extract(_html: str, use_readability: bool = False):
        nonlocal node_attempts
        extraction_modes.append(use_readability)
        if use_readability:
            node_attempts += 1
            if node_attempts == 1:
                raise subprocess.CalledProcessError(1, "node", stderr="document OOM")
            return {"title": "Recovered", "content": "<p>Node Body</p>"}
        return {"title": "Fallback", "content": "<p>Python Body</p>"}

    monkeypatch.setattr(readability, "_readabilipy_have_node", available)
    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)

    first = ReadabilityExtractor().extract_article("<html><body>Body</body></html>")
    second = ReadabilityExtractor().extract_article("<html><body>Body</body></html>")

    assert first.title == "Fallback"
    assert second.title == "Recovered"
    assert probe_calls == 1
    assert extraction_modes == [True, False, True]


def test_missing_node_during_extraction_disables_repeated_node_attempts(monkeypatch):
    from deerflow.utils import readability

    extraction_modes: list[bool] = []

    def extract(_html: str, use_readability: bool = False):
        extraction_modes.append(use_readability)
        if use_readability:
            raise FileNotFoundError("node")
        return {"title": "Guide", "content": "<p>Body</p>"}

    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)

    ReadabilityExtractor().extract_article("<html><body>One</body></html>")
    ReadabilityExtractor().extract_article("<html><body>Two</body></html>")

    assert extraction_modes == [True, False, False]


def test_missing_probe_api_still_attempts_node_extraction(monkeypatch):
    from deerflow.utils import readability

    extraction_modes: list[bool] = []

    def extract(_html: str, use_readability: bool = False):
        extraction_modes.append(use_readability)
        return {"title": "Guide", "content": "<p>Body</p>"}

    monkeypatch.setattr(readability, "_readabilipy_have_node", None)
    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)

    ReadabilityExtractor().extract_article("<html><body>One</body></html>")
    ReadabilityExtractor().extract_article("<html><body>Two</body></html>")

    assert extraction_modes == [True, True]


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
