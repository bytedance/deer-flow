import logging
import os
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
_READABILITY_NPM_INSTALL_TIMEOUT_SECONDS = 300
_readability_js_state: bool | None = None  # None = not settled yet; False caches only deterministic failures
_readability_js_bootstrap_lock = threading.Lock()


def _readability_js_packages_present() -> bool:
    """True when node_modules holds the packages ExtractArticle.js imports.

    readabilipy's own gate is bare ``node_modules`` existence, but an npm run
    killed mid-install (timeout, crash) can leave a partial tree behind;
    requiring its two runtime dependencies keeps a partial install from
    being cached as ready.
    """
    node_modules = _READABILITY_JS_DIR / "node_modules"
    return (node_modules / "jsdom").is_dir() and (node_modules / "@mozilla" / "readability").is_dir()


def _readability_js_ready() -> bool:
    """Ensure readabilipy's Readability.js dependencies are usable.

    readabilipy probes npm with a bare ``npm`` name, which Windows
    CreateProcess never resolves to ``npm.cmd``, so its one-time bootstrap
    always fails there and every Windows host silently degrades to
    pure-Python extraction (link hrefs dropped from fetched pages). Resolve
    npm the way the rest of the codebase does (``shutil.which``, as in the
    lark-cli installer) and install the packages readabilipy expects into
    its javascript directory.

    Coordination rules:
    - Settled outcomes (success, npm missing, non-zero exit) are cached for
      the process lifetime.
    - Transient bootstrap errors (``OSError``, timeout) are not cached, so a
      first-fetch network blip retries on a later call instead of degrading
      every fetch until restart.
    - Waiters never block on the lock: while a bootstrap is in flight,
      other callers get ``False`` (pure-Python for that call). Async
      callers run ``extract_article`` through ``asyncio.to_thread`` on the
      shared default executor, and parking one worker per waiting request
      for the length of an npm install would starve the whole pool.
    """
    global _readability_js_state
    if _readability_js_state is not None:
        return _readability_js_state
    if not _readability_js_bootstrap_lock.acquire(blocking=False):
        # A bootstrap is already in flight; degrade this call instead of
        # parking the worker thread behind it.
        return False
    try:
        if _readability_js_state is not None:
            return _readability_js_state
        if _readability_js_packages_present():
            _readability_js_state = True
            return True
        npm = shutil.which("npm")
        if npm is None:
            logger.warning("npm is unavailable; Readability.js extraction uses pure-Python mode")
            _readability_js_state = False
            return False
        # readabilipy's wheel ships only package.json — open-ended ranges, no
        # lockfile — so every fresh bootstrap resolves current versions via
        # npm install.
        install_cmd = [npm, "install", "--no-audit", "--no-fund"]
        try:
            # Capture bytes and decode with replacement: npm emits UTF-8
            # (box-drawing progress, typographic quotes), and text=True would
            # decode with the strict locale codec — on Windows ANSI code pages
            # that raises UnicodeDecodeError, killing npm mid-install instead
            # of falling back.
            result = subprocess.run(
                install_cmd,
                cwd=_READABILITY_JS_DIR,
                check=False,
                capture_output=True,
                timeout=_READABILITY_NPM_INSTALL_TIMEOUT_SECONDS,
                env={**os.environ, "npm_config_update_notifier": "false"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            # Transient (offline, timeout under load): leave the state unset
            # so a later call retries instead of degrading until restart.
            logger.warning("Bootstrapping Readability.js npm dependencies failed transiently; this call uses pure-Python extraction: %s", exc)
            return False
        if result.returncode != 0:
            logger.warning("npm install for Readability.js dependencies failed: %s", result.stderr.decode("utf-8", errors="replace").strip()[:500])
            _readability_js_state = False
            return False
        _readability_js_state = _readability_js_packages_present()
        if not _readability_js_state:
            logger.warning("Readability.js npm dependencies are still missing after install; using pure-Python extraction")
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
