"""Content-sampled text/binary detection shared by routers and harness tools."""

from __future__ import annotations

from pathlib import Path


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """Check if file is text by examining content for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            # Text files shouldn't contain null bytes
            return b"\x00" not in chunk
    except Exception:
        return False


# Exact matches only; ``_is_active_content_mime_type`` also treats every
# ``+xml`` subtype as active content.
ACTIVE_CONTENT_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/xml",
    "application/xml",
    "text/xsl",
}


def _is_active_content_mime_type(mime_type: str | None) -> bool:
    """Return whether a browser can run script when rendering *mime_type* inline.

    Beyond HTML, this covers every WHATWG XML MIME type (``text/xml``,
    ``application/xml``, or a ``+xml`` subtype) plus ``text/xsl``, which Blink
    also renders as XML: any XML document can carry an XHTML-namespaced
    ``<script>``, so ``report.xml`` or ``feed.rss`` is as dangerous as
    ``page.html`` when opened in the application origin.
    """
    if mime_type is None:
        return False
    mime_type = mime_type.lower()
    return mime_type in ACTIVE_CONTENT_MIME_TYPES or mime_type.endswith("+xml")
