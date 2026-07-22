"""Shared document outline extraction.

Extracted from ``file_conversion.py`` and ``uploads_middleware.py`` so both
the middleware and the ``list_uploaded_files`` tool can use the same code.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Regex for bold structural headings produced by pymupdf4llm when it can't
# promote bold text to a Markdown # heading (common in SEC filings).
#
# Chinese headings (第三节...) are already captured as standard # headings
# by pymupdf4llm, so they don't need this pattern.
_BOLD_HEADING_RE = re.compile(r"^\*\*((ITEM|PART|SECTION|SCHEDULE|EXHIBIT|APPENDIX|ANNEX|CHAPTER)\b[A-Z0-9 .,\-]*)\*\*\s*$")

# Regex for split-bold headings produced by pymupdf4llm when a heading spans
# multiple text spans in the PDF (e.g. section number and title are separate spans).
# Matches lines like:  **1** **Introduction**  or  **3.2** **Multi-Head Attention**
# Requirements:
#   1. Entire line consists only of **...** blocks separated by whitespace (no prose)
#   2. First block is a section number (digits and dots, e.g. "1", "3.2", "A.1")
#   3. Second block must not be purely numeric/punctuation — excludes financial table
#      headers like **2023** **2022** **2021** while allowing non-ASCII titles such as
#      **1** **概述** or accented words (negative lookahead instead of [A-Za-z])
#   4. At most two additional blocks (four total) with [^*]+ (no * inside) to keep
#      the regex linear and avoid ReDoS on attacker-controlled content
_SPLIT_BOLD_HEADING_RE = re.compile(r"^\*\*[\dA-Z][\d\.]*\*\*\s+\*\*(?!\d[\d\s.,\-–—/:()%]*\*\*)[^*]+\*\*(?:\s+\*\*[^*]+\*\*){0,2}\s*$")

# Maximum number of outline entries injected into the agent context.
# Keeps prompt size bounded even for very long documents.
MAX_OUTLINE_ENTRIES = 50

_OUTLINE_PREVIEW_LINES = 5


def _clean_bold_title(raw: str) -> str:
    """Normalise a title string that may contain pymupdf4llm bold artefacts.

    pymupdf4llm sometimes emits adjacent bold spans as ``**A** **B**`` instead
    of a single ``**A B**`` block.  This helper merges those fragments and then
    strips the outermost ``**...**`` wrapper so the caller gets plain text.

    Examples::

        "**Overview**"                       → "Overview"
        "**UNITED STATES** **SECURITIES**"   → "UNITED STATES SECURITIES"
        "plain text"                         → "plain text"  (unchanged)
    """
    # Merge adjacent bold spans: "** **" → " "
    merged = re.sub(r"\*\*\s*\*\*", " ", raw).strip()
    # Strip outermost **...** if the whole string is wrapped
    if m := re.fullmatch(r"\*\*(.+?)\*\*", merged, re.DOTALL):
        return m.group(1).strip()
    return merged


def extract_outline(md_path: Path) -> list[dict]:
    """Extract document outline (headings) from a Markdown file.

    Recognises three heading styles produced by pymupdf4llm:

    1. Standard Markdown headings: lines starting with one or more '#'.
       Inline ``**...**`` wrappers and adjacent bold spans (``** **``) are
       cleaned so the title is plain text.

    2. Bold-only structural headings: ``**ITEM 1. BUSINESS**``, ``**PART II**``,
       etc.  SEC filings use bold+caps for section headings with the same font
       size as body text, so pymupdf4llm cannot promote them to # headings.

    3. Split-bold headings: ``**1** **Introduction**``, ``**3.2** **Attention**``.
       pymupdf4llm emits these when the section number and title text are
       separate spans in the underlying PDF (common in academic papers).

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
                    title = _clean_bold_title(stripped.lstrip("#").strip())
                    if title:
                        outline.append({"title": title, "line": lineno})

                # Style 2: single bold block with SEC structural keyword
                elif m := _BOLD_HEADING_RE.match(stripped):
                    title = m.group(1).strip()
                    if title:
                        outline.append({"title": title, "line": lineno})

                # Style 3: split-bold heading — **<num>** **<title>**
                # Regex already enforces max 4 blocks and non-numeric second block.
                elif _SPLIT_BOLD_HEADING_RE.match(stripped):
                    title = " ".join(re.findall(r"\*\*([^*]+)\*\*", stripped))
                    if title:
                        outline.append({"title": title, "line": lineno})

                if len(outline) > MAX_OUTLINE_ENTRIES:
                    outline.pop()
                    outline.append({"truncated": True})
                    break
    except Exception:
        return []

    return outline


def extract_outline_for_file(file_path: Path) -> tuple[list[dict], list[str]]:
    """Return the document outline and fallback preview for *file_path*.

    Looks for a sibling ``<stem>.md`` file produced by the upload conversion
    pipeline.

    Returns:
        (outline, preview) where:
        - outline: list of ``{title, line}`` dicts (plus optional sentinel).
          Empty when no headings are found or no .md exists.
        - preview: first few non-empty lines of the .md, used as a content
          anchor when outline is empty so the agent has some context.
          Empty when outline is non-empty (no fallback needed).
    """
    md_path = file_path.with_suffix(".md")
    if not md_path.is_file():
        return [], []

    outline = extract_outline(md_path)
    if outline:
        logger.debug("Extracted %d outline entries from %s", len(outline), file_path.name)
        return outline, []

    # outline is empty — read the first few non-empty lines as a content preview
    preview: list[str] = []
    try:
        with md_path.open(encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    preview.append(stripped)
                if len(preview) >= _OUTLINE_PREVIEW_LINES:
                    break
    except Exception:
        logger.debug("Failed to read preview lines from %s", md_path, exc_info=True)
    return [], preview
