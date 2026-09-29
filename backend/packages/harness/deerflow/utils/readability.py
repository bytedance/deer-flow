import logging
import re
import subprocess
from functools import lru_cache
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, uses_relative

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from readabilipy import simple_json_from_html_string
from readabilipy.simple_json import have_node

logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
def _readability_available() -> bool:
    """Probe Readability.js availability once per process.

    ``readabilipy``'s own check re-runs (and may re-attempt an ``npm
    install`` into site-packages) on every extraction, which is wasteful
    for environments where Node.js can never be found, such as Windows
    hosts where ``npm`` is only resolvable as ``npm.cmd``.
    """
    try:
        return bool(have_node())
    except (OSError, subprocess.SubprocessError, ValueError):
        # The probe must never break fetching, and unavailability must be
        # cached: readabilipy's have_node() runs a network-bound `npm
        # install` with check=True, so a failing install raises
        # CalledProcessError (a SubprocessError, not an OSError) and a
        # non-numeric `node -v` output raises ValueError — either escaping
        # here would re-attempt the install on every fetch or fail it.
        return False


_FALLBACK_DROP_TAGS = ("script", "style", "noscript", "template", "iframe", "svg", "nav", "footer", "aside", "form", "button")


def _fallback_article_title(soup: BeautifulSoup, root=None) -> str:
    """Ranked headline extraction for the link-preserving fallback.

    ``og:title`` is the site-published headline and comes first. ``<h1>``
    candidates are restricted to the selected content container; a ``<h1>``
    inside a ``<header>`` is skipped only when that header is site-level
    chrome (no ``<article>``/``<main>`` ancestor) — a header owned by the
    article itself, such as ``<article><header class="entry-header"><h1>``,
    carries the real headline and must be kept. Headline text is joined
    with spaces so inline children do not glue words together. A bare
    ``<title>`` is the last resort.
    """
    og_title = soup.find("meta", attrs={"property": "og:title", "content": True})
    if og_title is not None:
        candidate = og_title["content"].strip()
        if candidate:
            return candidate
    container = root if root is not None else soup
    for h1 in container.find_all("h1"):
        header = h1.find_parent("header")
        if header is not None and header.find_parent(["article", "main"]) is None:
            continue  # A site-level chrome heading, not an article headline.
        candidate = " ".join(h1.get_text(" ", strip=True).split())
        if candidate:
            return candidate
    if soup.title is not None:
        return " ".join(soup.title.get_text(" ", strip=True).split())
    return ""


def _fallback_content_root(soup: BeautifulSoup):
    """Pick a content container without truncating sibling content.

    ``<main>`` is the canonical container and is kept whole. Without one,
    the body is kept unless a single ``article`` dominates the page (the
    text outside it is a rounding error) — the only case where narrowing
    to that article cannot drop a teaser article or sibling sections the
    way the previous first-``article`` selection did.
    """
    body = soup.body if soup.body is not None else soup
    main = body.find("main")
    if main is not None:
        return main
    articles = body.find_all("article")
    if len(articles) == 1:
        article = articles[0]
        container_chars = len(body.get_text(strip=True))
        outside_chars = container_chars - len(article.get_text(strip=True))
        if outside_chars < min(200, container_chars // 10):
            return article
    return body


def _python_fallback_article_json(html: str) -> dict[str, str | None]:
    """Link-preserving extraction used when Readability.js is unavailable.

    ``readabilipy``'s pure-Python tree strips element attributes, erasing
    the ``href``/``src`` destinations that ``_resolve_html_urls`` has just
    resolved. This fallback keeps the resolved destinations so the
    model-visible Markdown stays navigable on hosts where Readability.js
    can never run (Windows, npm-less containers).
    """
    soup = BeautifulSoup(html, "html5lib")
    for element in soup.find_all(_FALLBACK_DROP_TAGS):
        element.decompose()
    root = _fallback_content_root(soup)
    return {
        "title": _fallback_article_title(soup, root),
        "date": None,
        "content": str(root),
    }


class ReadabilityExtractor:
    def extract_article(self, html: str, *, url: str | None = None) -> Article:
        if url:
            html = _resolve_html_urls(html, url)
        try:
            if _readability_available():
                article = simple_json_from_html_string(html, use_readability=True)
            else:
                article = _python_fallback_article_json(html)
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
            article = _python_fallback_article_json(html)

        html_content = article.get("content")
        if not html_content or not str(html_content).strip():
            html_content = "No content could be extracted from this page"

        title = article.get("title")
        if not title or not str(title).strip():
            title = "Untitled"

        return Article(title=title, html_content=html_content, url=url)
