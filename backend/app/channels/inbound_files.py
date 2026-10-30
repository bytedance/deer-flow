"""Shared helpers for inbound channel file descriptors.

Used by Telegram/Discord (and any future channel) so filename sanitization and
size coercion cannot drift between adapters that feed the same upload pipeline.
"""

from __future__ import annotations

from typing import Any

from deerflow.uploads.manager import is_upload_staging_file, normalize_filename


def safe_inbound_filename(value: Any, fallback: str) -> str:
    """Normalize a user-supplied filename or return *fallback* when unsafe."""
    if not isinstance(value, str):
        return fallback
    try:
        candidate = normalize_filename(value.strip())
    except (UnicodeError, ValueError):
        return fallback
    if is_upload_staging_file(candidate) or any(ord(char) < 32 for char in candidate):
        return fallback
    return candidate


def coerce_file_size(value: Any) -> int | None:
    """Coerce a payload size field to a non-negative int, or ``None``.

    Whitelists bool/int/float/str shapes so accidental truthy values (and
    truncated floats) never become sizes.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
