"""File conversion utilities.

Converts document files (PDF, PPT, Excel, Word) to Markdown.

PDF conversion strategy (auto mode):
  1. Try pymupdf4llm if installed — better heading detection, faster on most files.
  2. If output is suspiciously short (< _MIN_CHARS_PER_PAGE chars/page, or < 200 chars
     total when page count is unavailable), treat as image-based and fall back to MarkItDown.
  3. If pymupdf4llm is not installed, use MarkItDown directly (existing behaviour).

Large files (> ASYNC_THRESHOLD_BYTES) are converted in a thread pool via
asyncio.to_thread() to avoid blocking the event loop (fixes #1569).

No FastAPI or HTTP dependencies — pure utility functions.
"""

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# File extensions that should be converted to markdown
CONVERTIBLE_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}

# Files larger than this threshold are converted in a background thread.
# Small files complete in < 1s synchronously; spawning a thread adds unnecessary
# scheduling overhead for them.
_ASYNC_THRESHOLD_BYTES = 1 * 1024 * 1024  # 1 MB

# If pymupdf4llm produces fewer characters *per page* than this threshold,
# the PDF is likely image-based or encrypted — fall back to MarkItDown.
# Rationale: normal text PDFs yield 200-2000 chars/page; image-based PDFs
# yield close to 0. 50 chars/page gives a wide safety margin.
# Falls back to absolute 200-char check when page count is unavailable.
_MIN_CHARS_PER_PAGE = 50


def _pymupdf_output_too_sparse(text: str, file_path: Path) -> bool:
    """Return True if pymupdf4llm output is suspiciously short (image-based PDF).

    Uses chars-per-page rather than an absolute threshold so that both short
    documents (few pages, few chars) and long documents (many pages, many chars)
    are handled correctly.
    """
    chars = len(text.strip())
    doc = None
    pages: int | None = None
    try:
        import pymupdf

        doc = pymupdf.open(str(file_path))
        pages = len(doc)
    except Exception:
        pass
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
    if pages is not None and pages > 0:
        return (chars / pages) < _MIN_CHARS_PER_PAGE
    # Fallback: absolute threshold when page count is unavailable
    return chars < 200


def _convert_pdf_with_pymupdf4llm(file_path: Path) -> str | None:
    """Attempt PDF conversion with pymupdf4llm.

    Returns the markdown text, or None if pymupdf4llm is not installed or
    if conversion fails (e.g. encrypted/corrupt PDF).
    """
    try:
        import pymupdf4llm
    except ImportError:
        return None

    try:
        return pymupdf4llm.to_markdown(str(file_path))
    except Exception:
        logger.exception("pymupdf4llm failed to convert %s; falling back to MarkItDown", file_path.name)
        return None


def _convert_with_markitdown(file_path: Path) -> str:
    """Convert any supported file to markdown text using MarkItDown."""
    from markitdown import MarkItDown

    md = MarkItDown()
    return md.convert(str(file_path)).text_content


def _do_convert(file_path: Path, pdf_converter: str) -> str:
    """Synchronous conversion — called directly or via asyncio.to_thread.

    Args:
        file_path: Path to the file.
        pdf_converter: "auto" | "pymupdf4llm" | "markitdown"
    """
    is_pdf = file_path.suffix.lower() == ".pdf"

    if is_pdf and pdf_converter != "markitdown":
        # Try pymupdf4llm first (auto or explicit)
        pymupdf_text = _convert_pdf_with_pymupdf4llm(file_path)

        if pymupdf_text is not None:
            # pymupdf4llm is installed
            if pdf_converter == "pymupdf4llm":
                # Explicit — use as-is regardless of output length
                return pymupdf_text
            # auto mode: fall back if output looks like a failed parse.
            # Use chars-per-page to distinguish image-based PDFs (near 0) from
            # legitimately short documents.
            if not _pymupdf_output_too_sparse(pymupdf_text, file_path):
                return pymupdf_text
            logger.warning(
                "pymupdf4llm produced only %d chars for %s (likely image-based PDF); falling back to MarkItDown",
                len(pymupdf_text.strip()),
                file_path.name,
            )
        # pymupdf4llm not installed or fallback triggered → use MarkItDown

    return _convert_with_markitdown(file_path)


async def convert_file_to_markdown(file_path: Path) -> Path | None:
    """Convert a supported document file to Markdown.

    PDF files are handled with a two-converter strategy (see module docstring).
    Large files (> 1 MB) are offloaded to a thread pool to avoid blocking the
    event loop.

    Args:
        file_path: Path to the file to convert.

    Returns:
        Path to the generated .md file, or None if conversion failed.
    """
    try:
        pdf_converter = _get_pdf_converter()
        file_size = file_path.stat().st_size

        if file_size > _ASYNC_THRESHOLD_BYTES:
            text = await asyncio.to_thread(_do_convert, file_path, pdf_converter)
        else:
            text = _do_convert(file_path, pdf_converter)

        md_path = file_path.with_suffix(".md")
        md_path.write_text(text, encoding="utf-8")

        logger.info("Converted %s to markdown: %s (%d chars)", file_path.name, md_path.name, len(text))
        return md_path
    except Exception as e:
        logger.error("Failed to convert %s to markdown: %s", file_path.name, e)
        return None


# Regex for bold-only lines that look like section headings.
# Targets SEC filing structural headings that pymupdf4llm renders as **bold**
# rather than # Markdown headings (because they use same font size as body text,
# distinguished only by bold+caps formatting).
#
# Pattern requires ALL of:
#   1. Entire line is a single **...** block (no surrounding prose)
#   2. Starts with a recognised structural keyword:
#      - ITEM / PART / SECTION (with optional number/letter after)
#      - SCHEDULE, EXHIBIT, APPENDIX, ANNEX, CHAPTER
#      All-caps addresses, boilerplate ("CURRENT REPORT", "SIGNATURES",
#      "WASHINGTON, DC 20549") do NOT start with these keywords and are excluded.
#
# Chinese headings (第三节...) are already captured as standard # headings
# by pymupdf4llm, so they don't need this pattern.
_BOLD_HEADING_RE = re.compile(r"^\*\*((ITEM|PART|SECTION|SCHEDULE|EXHIBIT|APPENDIX|ANNEX|CHAPTER)\b[A-Z0-9 .,\-]*)\*\*\s*$")

# Maximum number of outline entries injected into the agent context.
# Keeps prompt size bounded even for very long documents.
MAX_OUTLINE_ENTRIES = 50

_ALLOWED_PDF_CONVERTERS = {"auto", "pymupdf4llm", "markitdown"}


def extract_outline(md_path: Path) -> list[dict]:
    """Extract document outline (headings) from a Markdown file.

    Recognises two heading styles produced by pymupdf4llm:
    1. Standard Markdown headings: lines starting with one or more '#'
    2. Bold-only structural headings: **ITEM 1. BUSINESS**, **PART II**, etc.
       (SEC filings use bold+caps for section headings with the same font size
       as body text, so pymupdf4llm cannot promote them to # headings)

    Args:
        md_path: Path to the .md file.

    Returns:
        List of dicts with keys: title (str), line (int, 1-based).
        When the outline is truncated at MAX_OUTLINE_ENTRIES, a sentinel entry
        ``{"truncated": True}`` is appended as the last element so callers can
        render a "showing first N headings" hint without re-scanning the file.
        Returns an empty list if the file cannot be read or has no headings.
    """
    outline: list[dict] = []
    try:
        with md_path.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                # Style 1: standard Markdown heading
                if stripped.startswith("#"):
                    title = stripped.lstrip("#").strip()
                    # Strip any inline **...** wrapping (e.g. "## **Overview**" → "Overview")
                    if title:
                        if m2 := re.fullmatch(r"\*\*(.+?)\*\*", title):
                            title = m2.group(1).strip()
                        outline.append({"title": title, "line": lineno})

                # Style 2: bold-only line (entire line is **...**)
                elif m := _BOLD_HEADING_RE.match(stripped):
                    title = m.group(1).strip()
                    if title:
                        outline.append({"title": title, "line": lineno})

                if len(outline) >= MAX_OUTLINE_ENTRIES:
                    outline.append({"truncated": True})
                    break
    except Exception:
        return []

    return outline


def _get_pdf_converter() -> str:
    """Read pdf_converter setting from app config, defaulting to 'auto'.

    Normalizes the value to lowercase and validates it against the allowed set
    so that values like 'AUTO' or 'MarkItDown' from config.yaml don't silently
    fall through to unexpected behaviour.
    """
    try:
        from deerflow.config.app_config import get_app_config

        cfg = get_app_config()
        uploads_cfg = getattr(cfg, "uploads", None)
        if uploads_cfg is not None:
            raw = str(getattr(uploads_cfg, "pdf_converter", "auto")).strip().lower()
            if raw not in _ALLOWED_PDF_CONVERTERS:
                logger.warning("Invalid pdf_converter value %r; falling back to 'auto'", raw)
                return "auto"
            return raw
    except Exception:
        pass
    return "auto"
