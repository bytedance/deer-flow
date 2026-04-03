"""File conversion utilities.

Converts document files (PDF, PPT, Excel, Word) to Markdown using markitdown.
No FastAPI or HTTP dependencies — pure utility functions.
"""

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


async def convert_file_to_markdown(file_path: Path) -> Path | None:
    """Convert a file to markdown using markitdown.

    Args:
        file_path: Path to the file to convert.

    Returns:
        Path to the markdown file if conversion was successful, None otherwise.
    """
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(file_path))

        # Save as .md file with same name
        md_path = file_path.with_suffix(".md")
        md_path.write_text(result.text_content, encoding="utf-8")

        logger.info(f"Converted {file_path.name} to markdown: {md_path.name}")
        return md_path
    except Exception as e:
        logger.error(f"Failed to convert {file_path.name} to markdown: {e}")
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
    """Read pdf_converter setting from app config, defaulting to 'auto'."""
    try:
        from deerflow.config.app_config import get_app_config

        cfg = get_app_config()
        uploads_cfg = getattr(cfg, "uploads", None)
        if uploads_cfg is not None:
            return str(getattr(uploads_cfg, "pdf_converter", "auto"))
    except Exception:
        pass
    return "auto"
