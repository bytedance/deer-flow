import logging
import re
import subprocess
import threading
import time
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, uses_relative

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from readabilipy import simple_json_from_html_string
from readabilipy.extractors import extract_title
from readabilipy.simple_json import have_node

logger = logging.getLogger(__name__)

# A failed probe is cached only briefly so that a long-lived process can pick
# up Readability.js once the environment recovers (e.g. node_modules appears
# after a delayed npm install); a success is cached for the process lifetime.
_NEGATIVE_PROBE_TTL = 60.0

_probe_lock = threading.Lock()
_probe_available: bool | None = None
_probe_at = 0.0


def _readability_js_available() -> bool:
    """Probe whether readabilipy can really run its Readability.js lane.

    The readabilipy wheel ships its JavaScript without ``node_modules`` and
    tries to ``npm install`` them on first use. On Windows ``npm`` is only a
    ``.cmd`` shim that ``subprocess`` cannot spawn without a shell, so the
    install never runs and ``simple_json_from_html_string`` silently degrades
    to its pure-Python mode: it prints a stderr warning instead of raising,
    and the caller cannot tell that Readability.js never executed. Probing
    ``have_node`` ourselves keeps that decision explicit.
    """
    global _probe_available, _probe_at
    with _probe_lock:
        if _probe_available is True:
            return True
        if _probe_available is False and time.monotonic() - _probe_at < _NEGATIVE_PROBE_TTL:
            return False
        try:
            available = have_node()
        except (subprocess.CalledProcessError, OSError, ValueError):
            available = False
            logger.warning("Readability.js availability probe failed; using the link-preserving Python fallback", exc_info=True)
        if not available:
            logger.warning("Readability.js is unavailable; using the link-preserving Python fallback")
        _probe_available = available
        _probe_at = time.monotonic()
        return available


def _reset_readability_probe() -> None:
    """Clear the cached probe result (test helper)."""
    global _probe_available, _probe_at
    with _probe_lock:
        _probe_available = None
        _probe_at = 0.0


def _python_fallback_article(html: str) -> dict[str, str | None]:
    """Link-preserving Python extraction for when the Readability.js lane is unavailable or failed.

    readabilipy's built-in pure-Python mode unwraps ``<a>`` elements and
    strips ``href``/``src`` attributes, so the model loses every destination.
    This fallback keeps them: ``_resolve_html_urls`` has already rewritten
    relative destinations to absolute URLs before extraction runs.
    """
    soup = BeautifulSoup(html, "html5lib")
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
    og_title_text = og_title.get("content") if og_title else None
    for tag in soup(["script", "style", "template", "svg", "head"]):
        tag.decompose()
    body = soup.body or soup
    # Shell regions are dropped wherever they appear, so neither the <main>
    # branch nor the <article> branch can leak navigation noise into the
    # serialized content. Regions *inside* an <article> are kept: docs sites
    # (MDN, Docusaurus, many blogs) mark in-article callouts as <aside>, so
    # sweeping them would silently drop real article text.
    for tag in body.find_all(["nav", "footer", "aside"]):
        if tag.find_parent("article") is None:
            tag.decompose()
    main = body.find("main")
    container = main if main is not None and main.get_text(strip=True) else body
    # Prefer a detected <article>: surrounding shell text can otherwise
    # exhaust the fetch tools' 4096-character result budget before the
    # article itself is reached. The first <article> in document order can
    # be a textless placeholder (SPA shells, teaser cards), so pick the
    # first text-bearing candidate instead of stopping at the first match:
    # inside the container first, then anywhere else in the body.
    article_container = next((a for a in container.find_all("article") if a.get_text(strip=True)), None)
    if article_container is None and container is not body:
        article_container = next((a for a in body.find_all("article") if a.get_text(strip=True)), None)
    content = article_container if article_container is not None else container
    # Common layouts keep the visible heading outside the article; continue
    # the lookup in the wider container after an article-level miss.
    heading = (article_container.find("h1") if article_container is not None else None) or container.find("h1")
    title = og_title_text or (heading.get_text(" ", strip=True) if heading else None) or extract_title(html)
    return {"title": title, "content": str(content)}


class Article:
    url: str

    def __init__(self, title: str, html_content: str, url: str | None = None):
        self.title = title
        self.html_content = html_content
        self.url = url or ""

    def to_markdown(self, including_title: bool = True) -> str:
        markdown = ""
        if including_title:
            markdown += f"# {self.title}\n\n"

        if self.html_content is None or not str(self.html_content).strip():
            markdown += "*No content available*\n"
        else:
            markdown += md(self.html_content)

        return markdown

    def to_message(self) -> list[dict]:
        image_pattern = r"!\[.*?\]\((.*?)\)"

        content: list[dict[str, str]] = []
        markdown = self.to_markdown()

        if not markdown or not markdown.strip():
            return [{"type": "text", "text": "No content available"}]

        parts = re.split(image_pattern, markdown)

        for i, part in enumerate(parts):
            if i % 2 == 1:
                image_url = urljoin(self.url, part.strip())
                content.append({"type": "image_url", "image_url": {"url": image_url}})
            else:
                text_part = part.strip()
                if text_part:
                    content.append({"type": "text", "text": text_part})

        # If after processing all parts, content is still empty, provide a fallback message.
        if not content:
            content = [{"type": "text", "text": "No content available"}]

        return content


_BASE_TAG_RE = re.compile(r"<base", re.IGNORECASE)


def _resolve_html_urls(html: str, url: str) -> str:
    """Resolve destinations before extraction can discard the document's base tag."""
    # A base element requires a literal start-tag prefix. False positives in
    # comments or text elements still go through HTML5 tree construction.
    base = BeautifulSoup(html, "html5lib").find("base", href=True) if _BASE_TAG_RE.search(html) else None
    base_url = url
    if base is not None:
        try:
            candidate = urljoin(url, str(base["href"]).strip())
            # Keep only bases urljoin can resolve relative paths against.
            # Opaque bases fall back to the fetched URL; hierarchical FTP remains valid.
            if urlparse(candidate).scheme in uses_relative:
                base_url = candidate
        except ValueError:
            pass  # An invalid base must not prevent extraction of the page.
    resolver = _DestinationRewriter(html, base_url)
    resolver.feed(html)
    resolver.close()
    return resolver.result()


# Tokenize attributes only inside a start tag identified by HTMLParser. Keeping
# source spans avoids rebuilding malformed markup before jsdom parses it.
_ATTRIBUTE_RE = re.compile(r"""([^\s/>=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]*))?""")


class _DestinationRewriter(HTMLParser):
    # Treat link examples inside text-only elements as data, including nested
    # script-looking text; only the matching closing tag resumes tokenization.
    CDATA_CONTENT_ELEMENTS = ("script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "plaintext")

    def __init__(self, html: str, base_url: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.base_url = base_url
        self.text_element: str | None = None
        self.line_offsets = [0, *(match.end() for match in re.finditer("\n", html))]
        self.replacements: list[tuple[int, int, str]] = []

    def handle_starttag(self, tag, attrs):
        if self.text_element is not None:
            return
        if tag in {"textarea", "title", "xmp", "iframe", "noembed", "noframes", "plaintext"}:
            self.text_element = tag
            return
        attribute = {"a": "href", "img": "src"}.get(tag)
        if attribute is None:
            return
        raw = self.get_starttag_text()
        tag_end = re.match(r"<[^\s/>]+", raw).end()
        for match in _ATTRIBUTE_RE.finditer(raw, tag_end):
            if match.group(1).lower() != attribute:
                continue
            value = match.group(2)
            if value is not None:
                original = unescape(value[1:-1] if value.startswith(('"', "'")) else value)
                try:
                    resolved = urljoin(self.base_url, original.strip())
                except ValueError:
                    return
                if resolved != original:
                    line, column = self.getpos()
                    offset = self.line_offsets[line - 1] + column
                    self.replacements.append((offset + match.start(2), offset + match.end(2), '"' + escape(resolved, quote=True) + '"'))
            else:
                line, column = self.getpos()
                offset = self.line_offsets[line - 1] + column + match.end(1)
                self.replacements.append((offset, offset, '="' + escape(self.base_url, quote=True) + '"'))
            # Browsers use the first duplicate attribute, including a bare one.
            return

    def handle_endtag(self, tag):
        if tag == self.text_element and tag != "plaintext":
            self.text_element = None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def result(self) -> str:
        parts = []
        cursor = 0
        for start, end, value in self.replacements:
            parts.extend((self.html[cursor:start], value))
            cursor = end
        parts.append(self.html[cursor:])
        return "".join(parts)


class ReadabilityExtractor:
    def extract_article(self, html: str, *, url: str | None = None) -> Article:
        if url:
            html = _resolve_html_urls(html, url)
        article = None
        if _readability_js_available():
            try:
                # readabilipy re-checks have_node() internally, so if
                # node_modules disappears between our probe and this call it
                # still degrades silently to its link-stripping pure-Python
                # mode. The window is narrow and accepted: the probe keeps
                # the common case explicit, and the fallback below guarantees
                # destinations are never stripped either way.
                article = simple_json_from_html_string(html, use_readability=True)
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                stderr = getattr(exc, "stderr", None)
                if isinstance(stderr, bytes):
                    stderr = stderr.decode(errors="replace")
                stderr_info = f"; stderr={stderr.strip()}" if isinstance(stderr, str) and stderr.strip() else ""
                logger.warning(
                    "Readability.js extraction failed with %s%s; using the link-preserving Python fallback",
                    type(exc).__name__,
                    stderr_info,
                    exc_info=True,
                )
        if article is None:
            article = _python_fallback_article(html)

        html_content = article.get("content")
        if not html_content or not str(html_content).strip():
            html_content = "No content could be extracted from this page"

        title = article.get("title")
        if not title or not str(title).strip():
            title = "Untitled"

        return Article(title=title, html_content=html_content, url=url)
