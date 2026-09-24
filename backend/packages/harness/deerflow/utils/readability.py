import logging
import re
import shutil
import subprocess
import threading
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, uses_relative

import readabilipy
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from readabilipy import simple_json_from_html_string

logger = logging.getLogger(__name__)


class Article:
    url: str

    def __init__(self, title: str, html_content: str):
        self.title = title
        self.html_content = html_content

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


_READABILITY_JS_DIR = Path(readabilipy.__file__).resolve().parent / "javascript"
_readability_js_state: bool | None = None  # None = not verified yet
_readability_js_bootstrap_lock = threading.Lock()


def _readability_js_packages_present() -> bool:
    """True when node_modules holds the packages ExtractArticle.js imports.

    readabilipy's own gate is bare ``node_modules`` existence, but an npm run
    killed mid-install can leave a partial tree behind; requiring its two
    runtime dependencies keeps a partial install from being trusted.
    """
    node_modules = _READABILITY_JS_DIR / "node_modules"
    return (node_modules / "jsdom").is_dir() and (node_modules / "@mozilla" / "readability").is_dir()


def _node_dependencies_loadable() -> bool:
    """Node can require the packages ExtractArticle.js imports.

    npm creates package directories before extracting their contents, so
    directory presence alone cannot distinguish a complete install from one
    interrupted mid-extraction; loading them is the real test.
    """
    node = shutil.which("node")
    if node is None:
        return False
    try:
        probe = subprocess.run(
            [node, "-e", "require('jsdom'); require('@mozilla/readability');"],
            cwd=_READABILITY_JS_DIR,
            check=False,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _readability_js_ready() -> bool:
    """Report whether readabilipy's Readability.js dependencies are usable.

    readabilipy probes npm with a bare ``npm`` name, which Windows
    CreateProcess never resolves to ``npm.cmd``, and its wheel ships only
    ``package.json`` with open-ended ranges — so without a setup step every
    Windows host silently degrades to pure-Python extraction (link hrefs
    dropped from fetched pages).

    This probe deliberately checks only readiness: packages present and
    loadable by Node. Installing them happens in the explicit
    ``scripts/setup_readability_js.py`` step (wired into ``make install``
    in ``backend/Makefile``) with a reviewed lockfile and
    ``--ignore-scripts`` — an ordinary web fetch must never run npm against
    unpinned ranges with lifecycle scripts under Gateway privileges.

    The outcome is cached for the process lifetime, and the verification
    lock is never waited on: while another caller verifies, late callers
    degrade for that call instead of parking a shared-executor worker.
    """
    global _readability_js_state
    if _readability_js_state is not None:
        return _readability_js_state
    if not _readability_js_bootstrap_lock.acquire(blocking=False):
        # A verification is already in flight; degrade this call instead of
        # parking the worker thread behind it.
        return False
    try:
        if _readability_js_state is not None:
            return _readability_js_state
        if _readability_js_packages_present() and _node_dependencies_loadable():
            _readability_js_state = True
        else:
            _readability_js_state = False
            logger.warning("Readability.js dependencies are not installed; web fetch uses pure-Python extraction. Run scripts/setup_readability_js.py to install them, then restart the Gateway.")
        return _readability_js_state
    finally:
        _readability_js_bootstrap_lock.release()


class ReadabilityExtractor:
    def extract_article(self, html: str, *, url: str | None = None) -> Article:
        if url:
            html = _resolve_html_urls(html, url)
        try:
            article = simple_json_from_html_string(html, use_readability=_readability_js_ready())
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
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
            article = simple_json_from_html_string(html, use_readability=False)

        html_content = article.get("content")
        if not html_content or not str(html_content).strip():
            html_content = "No content could be extracted from this page"

        title = article.get("title")
        if not title or not str(title).strip():
            title = "Untitled"

        return Article(title=title, html_content=html_content)
