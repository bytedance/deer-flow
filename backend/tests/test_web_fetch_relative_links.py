"""Fetched HTML must preserve usable destinations in model-visible Markdown."""

import importlib
from ipaddress import ip_address
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.community.browserless.browserless_client import BrowserlessFetchResult
from deerflow.utils.readability import ReadabilityExtractor

PAGE_URL = "https://example.com/docs/current"


def _article(links: str, *, head: str = "") -> str:
    paragraph = "<p>This article explains the documentation in detail, with enough ordinary prose for the real readability extractor to retain the content and its related references.</p>"
    return f"<html><head><title>Guide</title>{head}</head><body><article>{paragraph * 5}<p>{links}</p></article></body></html>"


@pytest.mark.parametrize("provider", ["jina_ai", "browserless", "infoquest"])
@pytest.mark.anyio
async def test_web_fetch_resolves_relative_links_through_real_extraction(monkeypatch, provider):
    module = importlib.import_module(f"deerflow.community.{provider}.tools")
    html = _article('<a href="../next">Next</a> <a href="/reference">Reference</a>')
    monkeypatch.setattr(module, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: None))
    if provider == "jina_ai":
        monkeypatch.setattr(module.JinaClient, "crawl", AsyncMock(return_value=html))
    elif provider == "infoquest":
        monkeypatch.setattr(module, "_get_infoquest_client", lambda: SimpleNamespace(fetch=lambda url: html))
    else:
        client = SimpleNamespace(fetch_html_with_status=AsyncMock(return_value=BrowserlessFetchResult(html, "200", "OK")))
        monkeypatch.setattr(module, "_get_browserless_client", lambda name: client)
        monkeypatch.setattr(module, "_resolve_host_addresses", lambda host: [ip_address("93.184.216.34")])
    result = await module.web_fetch_tool.ainvoke({"url": PAGE_URL})
    assert "[Next](https://example.com/next)" in result
    assert "[Reference](https://example.com/reference)" in result


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        ("../next", "https://example.com/next"),
        ("/reference", "https://example.com/reference"),
        ("?page=2", "https://example.com/docs/current?page=2"),
        ("#section", "https://example.com/docs/current#section"),
        ("//cdn.example.com/file", "https://cdn.example.com/file"),
        ("https://other.example.com/file", "https://other.example.com/file"),
        ("mailto:help@example.com", "mailto:help@example.com"),
    ],
)
def test_extract_article_resolves_link_destinations(destination, expected):
    article = ReadabilityExtractor().extract_article(_article(f'<a href="{destination}">Reference</a>'), url=PAGE_URL)
    assert f"[Reference]({expected})" in article.to_markdown()


def test_extract_article_resolves_images_and_relative_document_base():
    article = ReadabilityExtractor().extract_article(
        _article('<a href="next">Next</a> <img src="images/chart.png" alt="Chart">', head='<base href="../assets/">'),
        url=PAGE_URL,
    )
    markdown = article.to_markdown()
    assert "[Next](https://example.com/assets/next)" in markdown
    assert "![Chart](https://example.com/assets/images/chart.png)" in markdown


def test_extract_article_without_url_preserves_legacy_relative_links():
    article = ReadabilityExtractor().extract_article(_article('<a href="../next">Next</a>'))
    assert "[Next](../next)" in article.to_markdown()


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://cdn.example.com/assets/", "https://cdn.example.com/assets/next"),
        ("//cdn.example.com/assets/", "https://cdn.example.com/assets/next"),
        ("ftp://files.example.com/assets/", "ftp://files.example.com/assets/next"),
    ],
)
def test_extract_article_uses_first_document_base(base, expected):
    article = ReadabilityExtractor().extract_article(
        _article('<a href="next">Next</a>', head=f'<base href="{base}"><base href="https://other.example.com/">'),
        url=PAGE_URL,
    )
    assert f"[Next]({expected})" in article.to_markdown()


def test_python_extraction_fallback_preserves_article_text(monkeypatch):
    import subprocess

    from deerflow.utils import readability

    original = readability.simple_json_from_html_string

    def extract(html, *, use_readability):
        if use_readability:
            raise subprocess.CalledProcessError(1, "node")
        return original(html, use_readability=False)

    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)
    article = ReadabilityExtractor().extract_article(_article('<a href="../next">Next</a>'), url=PAGE_URL)
    # The existing Python fallback strips link markup; preserve its text contract.
    assert "Next" in article.to_markdown()
    assert "This article explains the documentation" in article.to_markdown()


@pytest.mark.parametrize("base", ["http://[broken", "data:text/plain,invalid", "javascript:void(0)", "about:blank", "mailto:help@example.com", "blob:https://example.com/id"])
def test_invalid_document_base_does_not_lose_valid_relative_links(base):
    article = ReadabilityExtractor().extract_article(
        _article('<a href="../next">Next</a>', head=f'<base href="{base}">'),
        url=PAGE_URL,
    )
    assert "[Next](https://example.com/next)" in article.to_markdown()


@pytest.mark.parametrize(
    "fragment",
    [
        "<b>Bold <i>mixed</b> italics</i>",
        "<p>Before<div>Block</div>after</p>",
        "<table>Outside<tr><td>Cell</td></tr></table>",
        '<a href="https://example.com/next">Outer <a href="https://example.com/inner">Inner</a> Tail</a>',
    ],
)
def test_url_resolution_preserves_malformed_markup_extraction(fragment):
    html = _article(fragment + '<a href="../next">Next</a>')
    extractor = ReadabilityExtractor()
    assert extractor.extract_article(html, url=PAGE_URL).to_markdown() == extractor.extract_article(html).to_markdown().replace("(../next)", "(https://example.com/next)")


def test_document_base_skips_target_only_base():
    html = _article('<a href="next">Next</a>', head='<base target="_blank"><base href="https://cdn.example.com/assets/">')
    assert "[Next](https://cdn.example.com/assets/next)" in ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()


@pytest.mark.parametrize("destination", ["href=../next", "HREF='../next'", 'href="../next?x=1&amp;y=2"', 'href = "../next" href="/ignored"'])
def test_rewriter_changes_only_destination_values(destination):
    from deerflow.utils.readability import _resolve_html_urls

    html = """<!-- <a href="/comment"> -->\n<script>const sample = "<a href=/script>";</script>\n""" + f"<p><b>Misnested <i>text</b> tail</i> <a {destination}>Next</a></p>"
    result = _resolve_html_urls(html, PAGE_URL)
    assert result.startswith(html[: html.index("<p>")])
    assert "<p><b>Misnested <i>text</b> tail</i>" in result
    assert '"https://example.com/next' in result
    if 'href="/ignored"' in html:
        assert 'href="/ignored"' in result


@pytest.mark.parametrize("tag", ["textarea", "title", "xmp", "iframe", "noembed", "noframes"])
def test_rewriter_preserves_link_examples_in_text_elements(tag):
    from deerflow.utils.readability import _resolve_html_urls

    example = f'<{tag}><a href="/literal">Example</a></{tag}>'
    html = example + '<a href="../next">Next</a>'
    assert _resolve_html_urls(html, PAGE_URL) == example + '<a href="https://example.com/next">Next</a>'


@pytest.mark.parametrize("attribute", ["href", 'href=""', "href=''", 'href href="/ignored"'])
def test_empty_destination_uses_document_base(attribute):
    from deerflow.utils.readability import _resolve_html_urls

    html = f"<a {attribute}>Current</a>"
    assert f'href="{PAGE_URL}"' in _resolve_html_urls(html, PAGE_URL)


def test_textarea_with_script_example_does_not_hide_following_links():
    from deerflow.utils.readability import _resolve_html_urls

    example = '<textarea><script><a href="/literal"></textarea>'
    html = example + '<a href="../next">Next</a>'
    assert _resolve_html_urls(html, PAGE_URL) == example + '<a href="https://example.com/next">Next</a>'
