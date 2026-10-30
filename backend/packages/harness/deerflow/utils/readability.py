import logging
import re
import subprocess
from html import escape, unescape
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import urljoin, urlparse, uses_relative

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from readabilipy import simple_json_from_html_string

logger = logging.getLogger(__name__)

try:
    from readabilipy.simple_json import have_node as _readabilipy_have_node
except ImportError:  # pragma: no cover - compatibility with future readabilipy layouts
    logger.warning(
        "Cannot import readabilipy's Node availability probe; attempting Readability.js extraction directly",
        exc_info=True,
    )
    _readabilipy_have_node = None

_readability_js_launch_failed = False
_readability_js_available_cached: bool | None = None
_readability_js_probe_lock = Lock()


def _readability_js_available() -> bool:
    """Cache whether the optional Node extractor can be used."""
    global _readability_js_available_cached

    if _readability_js_launch_failed:
        return False
    if _readabilipy_have_node is None:
        return True
    if _readability_js_available_cached is not None:
        return _readability_js_available_cached
    with _readability_js_probe_lock:
        if _readability_js_launch_failed:
            return False
        if _readability_js_available_cached is not None:
            return _readability_js_available_cached
        try:
            _readability_js_available_cached = bool(_readabilipy_have_node())
        except (subprocess.SubprocessError, OSError, ValueError):
            logger.warning("Readability.js availability probe failed; using the Python fallback", exc_info=True)
            _readability_js_available_cached = False
            return False
        if not _readability_js_available_cached:
            logger.warning("Readability.js is unavailable; using the Python fallback")
        return _readability_js_available_cached


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
# A successful Readability.js extraction always strips <body> and <title>;
# their presence in the content signals the subprocess returned the raw document.
_UNEXTRACTED_DOC_RE = re.compile(r"<body\b[^>]*>|<title\b[^>]*>", re.IGNORECASE)
_BODY_INNER_RE = re.compile(r"<body[^>]*>(.*)</body>", re.DOTALL | re.IGNORECASE)


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
        global _readability_js_launch_failed

        if url:
            html = _resolve_html_urls(html, url)
        article = None
        if _readability_js_available():
            try:
                article = simple_json_from_html_string(html, use_readability=True)
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                # A missing executable is an environment-level failure. A
                # non-zero exit can be document-specific (OOM, stack depth,
                # malformed input), so only disable Node for the former.
                if isinstance(exc, FileNotFoundError):
                    _readability_js_launch_failed = True
                stderr = getattr(exc, "stderr", None)
                if isinstance(stderr, bytes):
                    stderr = stderr.decode(errors="replace")
                stderr_info = f"; stderr={stderr.strip()}" if isinstance(stderr, str) and stderr.strip() else ""
                logger.warning(
                    "Readability.js extraction failed with %s%s; falling back to pure-Python extraction",
                    type(exc).__name__,
                    stderr_info,
                    exc_info=True,
                )
        if article is None:
            article = simple_json_from_html_string(html, use_readability=False)

        html_content = article.get("content")
        if not html_content or not str(html_content).strip():
            html_content = "No content could be extracted from this page"

        # Detect silent Readability.js degradation: a successful extraction always
        # strips <body> and <title> from the content. Their presence means the
        # subprocess returned the raw document (e.g. on Windows where the node
        # bridge may not produce real output). When detected, use the resolved
        # HTML's <body> content so that <a> destinations survive.
        if url and html and _UNEXTRACTED_DOC_RE.search(html_content):
            logger.info("Readability.js returned the unextracted document; using resolved HTML body")
            body_match = _BODY_INNER_RE.search(html)
            html_content = body_match.group(1) if body_match else html

        title = article.get("title")
        if not title or not str(title).strip():
            title = "Untitled"

        return Article(title=title, html_content=html_content, url=url)
