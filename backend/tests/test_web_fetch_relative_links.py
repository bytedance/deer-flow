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
        monkeypatch.setattr(module, "_get_infoquest_client", lambda: SimpleNamespace(fetch=AsyncMock(return_value=html)))
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


def test_python_extraction_fallback_preserves_article_links(monkeypatch):
    import subprocess

    from deerflow.utils import readability

    original = readability.simple_json_from_html_string

    def extract(html, *, use_readability):
        if use_readability:
            raise subprocess.CalledProcessError(1, "node")
        return original(html, use_readability=False)

    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)
    article = ReadabilityExtractor().extract_article(_article('<a href="../next">Next</a>'), url=PAGE_URL)
    # When Readability.js is unavailable, the fallback must still keep the
    # destinations that _resolve_html_urls resolved into the markup.
    assert "[Next](https://example.com/next)" in article.to_markdown()
    assert "This article explains the documentation" in article.to_markdown()


def test_unavailable_readabilityjs_fallback_preserves_resolved_destinations(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_available", lambda: False)
    article = ReadabilityExtractor().extract_article(
        _article('<a href="../next">Next</a> <img src="images/chart.png" alt="Chart">'),
        url=PAGE_URL,
    )
    markdown = article.to_markdown()
    assert "[Next](https://example.com/next)" in markdown
    assert "![Chart](https://example.com/docs/images/chart.png)" in markdown
    assert "# Guide" in markdown


def test_unavailable_readabilityjs_fallback_keeps_multi_article_pages(monkeypatch):
    """A teaser article must not truncate the sections that follow it."""
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_available", lambda: False)
    html = (
        f'<html><head><title>News</title></head><body><article><h2>Teaser</h2><p>Short summary of another story.</p></article><section><h1>Real Story</h1>{"<p>Real story prose. </p>" * 30}<a href="../next">Next</a></section></body></html>'
    )
    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()
    assert "Teaser" in markdown
    assert "Real Story" in markdown
    assert "[Next](https://example.com/next)" in markdown
    # The entry <h1> headline wins over the generic site-name <title>.
    assert "# Real Story" in markdown


def test_unavailable_readabilityjs_fallback_keeps_article_owned_aside(monkeypatch):
    """An <aside> the article owns keeps its warning text and resolved link."""
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_available", lambda: False)
    html = _article('<p>Run the deployment command.</p><aside><p>Do not use this command in production.</p><a href="../safe">Safe procedure</a></aside>')
    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    assert "Run the deployment command." in markdown
    assert "Do not use this command in production." in markdown
    assert "[Safe procedure](https://example.com/safe)" in markdown


def test_unavailable_readabilityjs_fallback_drops_site_chrome_aside_link(monkeypatch):
    """A sidebar <aside> no content container owns is still pruned."""
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_available", lambda: False)
    html = f'<html><head><title>Guide</title></head><body><aside><a href="../promo">Promo</a><p>Sidebar teaser.</p></aside><p>{"Body prose. " * 30}</p></body></html>'
    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    assert "Sidebar teaser." not in markdown
    assert "[Promo]" not in markdown
    assert "Body prose." in markdown


def test_unavailable_readabilityjs_fallback_title_sources(monkeypatch):
    """og:title and entry <h1> headlines outrank a generic or missing <title>."""
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_available", lambda: False)
    og_page = '<html><head><title>Example Site</title><meta property="og:title" content="The Real Headline"></head><body><p>Body prose.</p></body></html>'
    assert ReadabilityExtractor().extract_article(og_page, url=PAGE_URL).title == "The Real Headline"

    generic_title_page = "<html><head><title>Example Site</title></head><body><h1>Entry Headline</h1><p>Body prose.</p></body></html>"
    assert ReadabilityExtractor().extract_article(generic_title_page, url=PAGE_URL).title == "Entry Headline"

    missing_title_page = "<html><body><h1>Entry Headline</h1><p>Body prose.</p></body></html>"
    assert ReadabilityExtractor().extract_article(missing_title_page, url=PAGE_URL).title == "Entry Headline"


def test_unavailable_readabilityjs_fallback_selects_dominant_single_article(monkeypatch):
    """A single article carrying nearly all text narrows to drop residual noise."""
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_available", lambda: False)
    prose = "<p>This article explains the documentation in detail.</p>" * 20
    html = f"<html><head><title>Doc</title></head><body><article><h1>Main Article</h1>{prose}</article><p>Cookie notice.</p></body></html>"
    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()
    assert "Main Article" in markdown
    assert "Cookie notice" not in markdown


def test_unavailable_readabilityjs_fallback_skips_site_header_h1(monkeypatch):
    """A site/logo <h1> in <header> must not become the article headline."""
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_available", lambda: False)
    html = f"<html><head><title>Real Story</title></head><body><header><h1>Site Name</h1></header><article><h2>Chapter One</h2>{'<p>Story prose. </p>' * 20}</article></body></html>"
    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()
    assert "# Real Story" in markdown
    assert "# Site Name" not in markdown
    assert "Story prose." in markdown


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


def test_pages_without_base_skip_html5_tree_construction(monkeypatch):
    from deerflow.utils import readability

    def unexpected_parse(*args, **kwargs):
        pytest.fail("A page without a base prefix must not build an HTML5 tree")

    monkeypatch.setattr(readability, "BeautifulSoup", unexpected_parse)
    html = '<p>Guide</p><a href="../next">Next</a>'
    assert readability._resolve_html_urls(html, PAGE_URL) == '<p>Guide</p><a href="https://example.com/next">Next</a>'


@pytest.mark.parametrize(
    "head",
    [
        '<BaSe href="https://cdn.example.com/">',
        '<!-- <base href="/ignored/"> --><BASE href="https://cdn.example.com/">',
    ],
)
def test_base_precheck_retains_case_insensitive_tree_selection(head):
    from deerflow.utils.readability import _resolve_html_urls

    html = _article('<a href="next">Next</a>', head=head)
    assert '<a href="https://cdn.example.com/next">Next</a>' in _resolve_html_urls(html, PAGE_URL)


@pytest.mark.parametrize(
    "head",
    [
        '<!-- <base href="/ignored/"> -->',
        """<script>const sample = '<base href="/ignored/">';</script>""",
        '<title>Example &lt;base href="/ignored/"&gt;</title>',
    ],
)
def test_base_precheck_false_positives_do_not_override_page_url(head):
    from deerflow.utils.readability import _resolve_html_urls

    html = _article('<a href="../next">Next</a>', head=head)
    assert '<a href="https://example.com/next">Next</a>' in _resolve_html_urls(html, PAGE_URL)
