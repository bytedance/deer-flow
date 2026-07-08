"""Classify index job errors into standardised categories for observability."""

from __future__ import annotations


def classify_index_error(error_message: str | None) -> str:
    """Map an index job error string to a stable error category.

    Categories are aligned with ``ConversionErrorCode`` values plus
    ``DIMENSION_MISMATCH`` (from ``EmbeddingDimensionMismatchError``).
    Everything else falls into ``OTHER``.

    Returns the category string, never None.
    """
    if not error_message:
        return "OTHER"

    msg_lower = error_message.lower()
    keyword_map = [
        ("empty_result", "EMPTY_RESULT"),
        ("no text", "EMPTY_RESULT"),
        ("no content", "EMPTY_RESULT"),
        ("encrypted_pdf", "ENCRYPTED_PDF"),
        ("encrypted", "ENCRYPTED_PDF"),
        ("unsupported_format", "UNSUPPORTED_FORMAT"),
        ("unsupported file", "UNSUPPORTED_FORMAT"),
        ("markitdown_unavailable", "MARKITDOWN_UNAVAILABLE"),
        ("ocr_unavailable", "OCR_UNAVAILABLE"),
        ("dimension mismatch", "DIMENSION_MISMATCH"),
        ("embedding dimension", "DIMENSION_MISMATCH"),
        ("internal_error", "INTERNAL_ERROR"),
    ]
    for needle, category in keyword_map:
        if needle in msg_lower:
            return category
    return "OTHER"


def classify_failures(failed_jobs: list[dict]) -> dict[str, int]:
    """Aggregate failure counts by category from a list of failed job dicts.

    Each dict is expected to have an ``"error"`` key.
    """
    counts: dict[str, int] = {}
    for job in failed_jobs:
        category = classify_index_error(job.get("error"))
        counts[category] = counts.get(category, 0) + 1
    return counts
