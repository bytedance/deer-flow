"""File conversion utilities.

Converts document files (PDF, PPT, Excel, Word) to Markdown.

PDF conversion strategy (auto mode):
  1. Try pymupdf4llm if installed — better heading detection, faster on most files.
  2. If output is suspiciously short (< _MIN_CHARS_PER_PAGE chars/page, or < 200 chars
     total when page count is unavailable), treat as image-based and fall back to MarkItDown.
  3. If pymupdf4llm is not installed, use MarkItDown directly (existing behaviour).

Large files (> ASYNC_THRESHOLD_BYTES) are converted in a thread pool via
asyncio.to_thread() to avoid blocking the event loop (fixes #1569).

Conversion failures (Sprint C.1.1)
----------------------------------
``convert_file_to_markdown`` returns a :class:`ConversionResult` carrying
either a ``md_path`` (success) or a structured ``ConversionErrorCode`` plus
``error_detail`` (failure). Callers map the code to a 4xx HTTP body so the
frontend can show an actionable toast (e.g. "encrypted PDF, please remove
the password") instead of a generic "upload failed".

No FastAPI or HTTP dependencies — pure utility functions.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from deerflow.config.app_config import get_app_config

logger = logging.getLogger(__name__)


class ConversionErrorCode(StrEnum):
    """Stable error codes for document conversion failures.

    The string values are the contract with the API/frontend — they show up
    verbatim in upload-error responses, so the frontend can build a toast
    message lookup table without parsing English prose. Adding a new code is
    fine; renaming an existing one is a breaking change.
    """

    # Output looked successful but produced too little usable text — typically
    # an image-based / scanned PDF that neither converter could OCR.
    EMPTY_RESULT = "EMPTY_RESULT"
    # PDF rejected by both converters with a password-protected / encrypted
    # error signature.
    ENCRYPTED_PDF = "ENCRYPTED_PDF"
    # File is not in CONVERTIBLE_EXTENSIONS — a programming bug if the upload
    # route is wired right, but worth surfacing distinctly.
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    # MarkItDown is not installed; with no fallback available we cannot
    # convert non-PDFs at all. Surfaces as a server config issue.
    MARKITDOWN_UNAVAILABLE = "MARKITDOWN_UNAVAILABLE"
    # Anything else that escaped the converter — corrupt file, bad encoding,
    # OS-level read error. The detail string carries the original message.
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class ConversionResult:
    """Outcome of a single :func:`convert_file_to_markdown` call.

    Exactly one of ``md_path`` / ``error`` is set:
    * Success → ``md_path`` is the produced ``.md`` file, ``error`` is None.
    * Failure → ``md_path`` is None, ``error`` is the stable code, and
      ``error_detail`` carries the human-readable reason (English; the
      frontend localises by code, not by detail).

    Use :meth:`ok` / :meth:`failed` for branchless call-site checks.
    """

    md_path: Path | None = None
    error: ConversionErrorCode | None = None
    error_detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.md_path is not None and self.error is None

    @property
    def failed(self) -> bool:
        return self.error is not None

    @classmethod
    def success(cls, md_path: Path) -> ConversionResult:
        return cls(md_path=md_path)

    @classmethod
    def failure(cls, code: ConversionErrorCode, detail: str | None = None) -> ConversionResult:
        return cls(error=code, error_detail=detail)


# Heuristic: substring match against the lowercased exception text. PyMuPDF
# raises ``mupdf.FzErrorFormat`` for password files; MarkItDown bubbles up
# something with ``encrypted`` or ``password`` in the message.
_ENCRYPTED_PDF_HINTS = ("password", "encrypted", "decrypt")


def _classify_error(exc: BaseException) -> ConversionErrorCode:
    msg = str(exc).lower()
    if any(h in msg for h in _ENCRYPTED_PDF_HINTS):
        return ConversionErrorCode.ENCRYPTED_PDF
    if "markitdown" in msg and "no module" in msg:
        return ConversionErrorCode.MARKITDOWN_UNAVAILABLE
    return ConversionErrorCode.INTERNAL_ERROR

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

# Below this many non-whitespace chars, the converted markdown is treated
# as effectively empty and EMPTY_RESULT is reported. Matches the absolute
# threshold used in _pymupdf_output_too_sparse so the user-facing message
# is consistent regardless of which converter ran.
_EMPTY_RESULT_CHAR_THRESHOLD = 200


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


async def convert_file_to_markdown(file_path: Path) -> ConversionResult:
    """Convert a supported document file to Markdown.

    PDF files are handled with a two-converter strategy (see module docstring).
    Large files (> 1 MB) are offloaded to a thread pool to avoid blocking the
    event loop.

    Args:
        file_path: Path to the file to convert.

    Returns:
        ``ConversionResult`` — ``ok`` carries the produced ``.md`` path;
        ``failed`` carries a stable :class:`ConversionErrorCode` plus an
        English ``error_detail``. Callers should never raise on a failure
        result; map the code to a 4xx body instead so the frontend can
        toast a localised, actionable message.
    """
    if file_path.suffix.lower() not in CONVERTIBLE_EXTENSIONS:
        return ConversionResult.failure(
            ConversionErrorCode.UNSUPPORTED_FORMAT,
            f"Extension {file_path.suffix!r} is not in the convertible set.",
        )

    try:
        pdf_converter = _get_pdf_converter()
        file_size = file_path.stat().st_size

        if file_size > _ASYNC_THRESHOLD_BYTES:
            text = await asyncio.to_thread(_do_convert, file_path, pdf_converter)
        else:
            text = _do_convert(file_path, pdf_converter)
    except Exception as exc:
        code = _classify_error(exc)
        logger.error(
            "Failed to convert %s to markdown (%s): %s",
            file_path.name,
            code.value,
            exc,
        )
        return ConversionResult.failure(code, str(exc))

    if len((text or "").strip()) < _EMPTY_RESULT_CHAR_THRESHOLD:
        logger.warning(
            "Converted %s produced only %d chars (likely image-based / scanned); "
            "reporting EMPTY_RESULT",
            file_path.name,
            len((text or "").strip()),
        )
        return ConversionResult.failure(
            ConversionErrorCode.EMPTY_RESULT,
            "Converter produced no usable text. The document is likely image-based or scanned.",
        )

    md_path = file_path.with_suffix(".md")
    md_path.write_text(text, encoding="utf-8")

    logger.info("Converted %s to markdown: %s (%d chars)", file_path.name, md_path.name, len(text))
    return ConversionResult.success(md_path)


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

_ALLOWED_PDF_CONVERTERS = {"auto", "pymupdf4llm", "markitdown"}


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

                if len(outline) >= MAX_OUTLINE_ENTRIES:
                    outline.append({"truncated": True})
                    break
    except Exception:
        return []

    return outline


def _get_uploads_config_value(key: str, default: object) -> object:
    """Read a value from the uploads config, supporting dict and attribute access."""
    cfg = get_app_config()
    uploads_cfg = getattr(cfg, "uploads", None)
    if isinstance(uploads_cfg, dict):
        return uploads_cfg.get(key, default)
    return getattr(uploads_cfg, key, default)


def _get_pdf_converter() -> str:
    """Read pdf_converter setting from app config, defaulting to 'auto'.

    Normalizes the value to lowercase and validates it against the allowed set
    so that values like 'AUTO' or 'MarkItDown' from config.yaml don't silently
    fall through to unexpected behaviour.
    """
    try:
        raw = str(_get_uploads_config_value("pdf_converter", "auto")).strip().lower()
        if raw not in _ALLOWED_PDF_CONVERTERS:
            logger.warning("Invalid pdf_converter value %r; falling back to 'auto'", raw)
            return "auto"
        return raw
    except Exception:
        pass
    return "auto"


def _is_pymupdf4llm_available() -> bool:
    try:
        import pymupdf4llm  # noqa: F401

        return True
    except ImportError:
        return False


def _is_markitdown_available() -> bool:
    try:
        import markitdown  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass(frozen=True)
class ResolvedPdfConverter:
    """Snapshot of the active PDF-converter configuration (Sprint C.3.1).

    Returned by :func:`resolve_pdf_converter` so admins can answer
    "why are my PDF uploads failing?" without grepping logs:

    * ``configured`` — what config.yaml asked for ("auto" / "pymupdf4llm" /
      "markitdown"). Survives lowercasing + allowlist validation.
    * ``effective`` — the converter the runtime will actually attempt
      first. Differs from ``configured`` when the requested backend is
      missing on the host (auto with no pymupdf4llm → "markitdown").
    * ``pymupdf4llm_available`` / ``markitdown_available`` — pip install
      probes. Both False is the "no PDFs work" misconfig.
    * ``warning`` — short English string the admin endpoint surfaces
      when the configuration is broken (e.g. configured=pymupdf4llm but
      the package is missing). Empty when everything is fine.
    """

    configured: str
    effective: str
    pymupdf4llm_available: bool
    markitdown_available: bool
    warning: str = ""


def resolve_pdf_converter() -> ResolvedPdfConverter:
    """Resolve the configured PDF converter against installed packages.

    The "effective" converter is what ``_do_convert`` will actually call
    first for a PDF input:

    * configured=pymupdf4llm + package installed → effective=pymupdf4llm
    * configured=pymupdf4llm + package missing   → effective=markitdown,
      with a ``warning`` so the admin endpoint can flag the misconfig
    * configured=markitdown                     → effective=markitdown
    * configured=auto + pymupdf4llm installed   → effective=pymupdf4llm
    * configured=auto + pymupdf4llm missing     → effective=markitdown
    * neither package installed                 → effective="none",
      ``warning`` says PDF uploads will fail
    """
    configured = _get_pdf_converter()
    has_pymupdf = _is_pymupdf4llm_available()
    has_markitdown = _is_markitdown_available()

    warning = ""
    if configured == "pymupdf4llm":
        if has_pymupdf:
            effective = "pymupdf4llm"
        elif has_markitdown:
            effective = "markitdown"
            warning = (
                "pdf_converter=pymupdf4llm but pymupdf4llm is not installed; "
                "falling back to markitdown. Install with: uv add pymupdf4llm"
            )
        else:
            effective = "none"
            warning = (
                "pdf_converter=pymupdf4llm but neither pymupdf4llm nor "
                "markitdown is installed; PDF uploads will fail."
            )
    elif configured == "markitdown":
        if has_markitdown:
            effective = "markitdown"
        else:
            effective = "none"
            warning = (
                "pdf_converter=markitdown but markitdown is not installed; "
                "PDF uploads will fail. Install with: uv add markitdown"
            )
    else:  # auto
        if has_pymupdf:
            effective = "pymupdf4llm"
        elif has_markitdown:
            effective = "markitdown"
        else:
            effective = "none"
            warning = (
                "pdf_converter=auto but neither pymupdf4llm nor markitdown is "
                "installed; PDF uploads will fail."
            )

    return ResolvedPdfConverter(
        configured=configured,
        effective=effective,
        pymupdf4llm_available=has_pymupdf,
        markitdown_available=has_markitdown,
        warning=warning,
    )


def log_pdf_converter_status() -> ResolvedPdfConverter:
    """Resolve + emit one INFO line at startup.

    Call this once from gateway startup so admins see the active
    converter in the boot log. Returns the snapshot so callers can do
    extra checks without re-resolving.
    """
    snapshot = resolve_pdf_converter()
    if snapshot.warning:
        logger.warning(
            "pdf_converter status: configured=%s effective=%s pymupdf4llm=%s "
            "markitdown=%s — %s",
            snapshot.configured,
            snapshot.effective,
            snapshot.pymupdf4llm_available,
            snapshot.markitdown_available,
            snapshot.warning,
        )
    else:
        logger.info(
            "pdf_converter status: configured=%s effective=%s pymupdf4llm=%s "
            "markitdown=%s",
            snapshot.configured,
            snapshot.effective,
            snapshot.pymupdf4llm_available,
            snapshot.markitdown_available,
        )
    return snapshot
