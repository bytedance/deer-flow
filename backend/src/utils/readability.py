import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import readabilipy
from markdownify import markdownify as md
from readabilipy import simple_json_from_html_string
from readabilipy.utils import run_npm_install

_READABILITY_DEPS_READY: bool | None = None

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


class ReadabilityExtractor:
    @staticmethod
    def _ensure_readability_js_dependencies() -> None:
        global _READABILITY_DEPS_READY
        if _READABILITY_DEPS_READY is True:
            return

        pkg_path = Path(readabilipy.__file__).resolve().parent
        js_dir = pkg_path / "javascript"
        package_json = js_dir / "package.json"
        lru_cache_file = js_dir / "node_modules" / "lru-cache" / "dist" / "commonjs" / "index.min.js"

        if lru_cache_file.exists():
            _READABILITY_DEPS_READY = True
            return

        if not package_json.exists():
            raise RuntimeError("ReadabiliPy JS assets are missing. Install Node.js 14+ and reinstall readabilipy so the JavaScript dependencies are bundled.") from None

        run_npm_install()

        if not lru_cache_file.exists():
            raise RuntimeError("ReadabiliPy JS dependencies are incomplete. Run `npm install` in the readabilipy javascript directory or reinstall readabilipy with Node.js available.") from None

        _READABILITY_DEPS_READY = True

    @staticmethod
    def _extract_title(html: str) -> str | None:
        if not html:
            return None
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        return title or None

    def extract_article(self, html: str) -> Article:
        self._ensure_readability_js_dependencies()

        try:
            article = simple_json_from_html_string(html, use_readability=True)
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
