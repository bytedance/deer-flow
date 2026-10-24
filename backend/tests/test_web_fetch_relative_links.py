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
        monkeypatch.setattr(module, "_get_browserless_client", lambda name, cfg: client)
        monkeypatch.setattr(module, "_resolve_host_addresses", lambda host: [ip_address("93.184.216.34")])
        monkeypatch.setattr(module, "_validate_backend_base_url", lambda cfg: None)
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

    calls = []

    def extract(html, *, use_readability):
        calls.append(use_readability)
        raise subprocess.CalledProcessError(1, "node")

    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)
    monkeypatch.setattr(readability, "_readability_js_available", lambda: True)
    article = ReadabilityExtractor().extract_article(_article('<a href="../next">Next</a>'), url=PAGE_URL)
    # The Python fallback keeps link destinations instead of stripping markup.
    assert calls == [True]
    assert "[Next](https://example.com/next)" in article.to_markdown()
    assert "This article explains the documentation" in article.to_markdown()


def test_unavailable_readability_preserves_resolved_link_and_image_destinations(monkeypatch, caplog):
    from deerflow.utils import readability

    calls = []

    def extract(html, *, use_readability):
        calls.append(use_readability)
        return {
            "title": "Guide",
            "content": '<article><p>Article body</p><a>Next</a><img alt="Chart"></article>',
        }

    readability._reset_readability_probe()
    monkeypatch.setattr(readability, "have_node", lambda: False)
    monkeypatch.setattr(readability, "simple_json_from_html_string", extract)

    try:
        article = ReadabilityExtractor().extract_article(
            _article('<a href="../next">Next</a> <img src="images/chart.png" alt="Chart">'),
            url=PAGE_URL,
        )
    finally:
        readability._reset_readability_probe()

    # When Readability.js cannot run at all, extraction must not silently go
    # through readabilipy's pure-Python mode; the explicit fallback keeps the
    # resolved destinations.
    assert calls == []
    assert "# Guide" in article.to_markdown()
    assert "[Next](https://example.com/next)" in article.to_markdown()
    assert "![Chart](https://example.com/docs/images/chart.png)" in article.to_markdown()
    assert "This article explains the documentation" in article.to_markdown()
    assert "Readability.js is unavailable" in caplog.text


def test_python_fallback_keeps_content_outside_empty_main_and_uses_article_title(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)
    html = """<html><head><title>Example Site</title></head><body>
    <nav><a href="/home">Home</a></nav><main></main>
    <article><h1>Real Story</h1><p>Article details.</p><a href="/next">Next</a></article>
    <footer>Site footer</footer></body></html>"""

    article = ReadabilityExtractor().extract_article(html, url=PAGE_URL)
    markdown = article.to_markdown()

    assert markdown.startswith("# Real Story")
    assert "Article details." in markdown
    assert "[Next](https://example.com/next)" in markdown
    assert "Home" not in markdown
    assert "Site footer" not in markdown


def test_python_fallback_strips_shell_inside_main(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)
    html = """<html><head><title>Site</title></head><body>
    <main><nav><a href="/home">Home</a><a href="/a">A</a></nav>
    <h1>Real</h1><p>Article body</p></main></body></html>"""

    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    # The nav sweep must not be keyed to the body branch only: a <main> that
    # wins the container selection must not leak its navigation into the
    # result either.
    assert "Article body" in markdown
    assert "Home" not in markdown
    assert "(/home)" not in markdown


def test_python_fallback_finds_article_outside_container(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)
    html = """<html><head><title>T</title></head><body>
    <main><p>shell text</p></main>
    <article><h1>Real</h1><p>Article body</p></article></body></html>"""

    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    # An <article> beside the selected container must degrade into the
    # content instead of being discarded in favour of the shell text.
    assert markdown.startswith("# Real")
    assert "Article body" in markdown
    assert "shell text" not in markdown


def test_python_fallback_skips_textless_article(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)
    html = "<html><head><title>T</title></head><body><article></article><p>Real prose lives here.</p></body></html>"

    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    # A textless <article> placeholder must fall back to the container, the
    # same way an empty <main> does, instead of serializing as empty content.
    assert "Real prose lives here." in markdown
    assert "No content could be extracted" not in markdown


def test_python_fallback_keeps_in_article_aside_callout(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)
    html = """<html><head><title>Guide</title></head><body>
    <article><h1>Guide</h1><p>Main prose.</p>
    <aside class="note"><p>Important caveat readers need.</p></aside></article>
    </body></html>"""

    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    # Docs sites (MDN, Docusaurus, many blogs) use <aside> for in-article
    # callouts; the shell sweep must not drop real article text with them.
    assert "Main prose." in markdown
    assert "Important caveat readers need." in markdown


def test_python_fallback_still_strips_aside_outside_article(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)
    html = """<html><head><title>Site</title></head><body>
    <main><article><p>Main prose.</p></article>
    <aside><p>Shell sidebar</p></aside></main>
    <footer>Site footer</footer></body></html>"""

    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    # The in-article protection is scoped to the article itself: shell
    # regions beside it still leak nothing into the serialized content.
    assert "Main prose." in markdown
    assert "Shell sidebar" not in markdown
    assert "Site footer" not in markdown


def test_python_fallback_skips_empty_article_before_real_one(monkeypatch):
    from deerflow.utils import readability

    monkeypatch.setattr(readability, "_readability_js_available", lambda: False)
    html = """<html><head><title>T</title></head><body>
    <main><article></article><p>shell</p></main>
    <article><h1>Real story</h1><p>Substantive prose.</p></article></body></html>"""

    markdown = ReadabilityExtractor().extract_article(html, url=PAGE_URL).to_markdown()

    # The first <article> in document order can be a textless placeholder;
    # discarding it must not shadow a real <article> later in the document.
    assert markdown.startswith("# Real story")
    assert "Substantive prose." in markdown
    assert "shell" not in markdown


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
