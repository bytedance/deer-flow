"""Byte budgets shared by sandbox binary downloads."""

import errno
from collections.abc import Iterable
from contextlib import suppress

DEFAULT_DOWNLOAD_LIMIT = 100 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def download_limit(max_bytes: int | None, provider_limit: int) -> int:
    """A caller may tighten, but never raise, the provider's download ceiling."""
    if max_bytes is None:
        return provider_limit
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer or None")
    return min(max_bytes, provider_limit)


def read_download_stream(stream: Iterable[bytes], limit: int, path: str) -> bytes:
    """Stop at the first over-budget chunk and close even on interruption.

    The transport owns chunk sizing; do not retain the first overflowing chunk
    or consume any later chunks. Cleanup must not replace the original failure.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in stream:
            total += len(chunk)
            if total > limit:
                raise OSError(errno.EFBIG, f"File exceeds maximum download size of {limit} bytes", path)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            with suppress(Exception):
                close()
