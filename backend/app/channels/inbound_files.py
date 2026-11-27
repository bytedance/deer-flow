"""Shared helpers for inbound channel files and attachment downloads.

Used by Telegram/Discord (and any future channel) so filename sanitization and
size coercion cannot drift between adapters that feed the same upload pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from deerflow.uploads.manager import is_upload_staging_file, normalize_filename
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)


async def open_inbound_http_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    """Build an attachment HTTP client off the event loop, safely under cancellation.

    ``httpx.AsyncClient`` loads the CA bundle synchronously on construction, so
    building it inline would stall the shared Gateway loop. The worker thread
    cannot be cancelled: if the caller is cancelled while awaiting it, the
    client it eventually builds would be discarded without ever being closed.
    Shield the construction and, on cancellation, drain it and close the late
    client before re-raising.
    """
    construction = asyncio.create_task(asyncio.to_thread(httpx.AsyncClient, timeout=timeout))
    try:
        return await asyncio.shield(construction)
    except asyncio.CancelledError:

        async def close_after_construction() -> None:
            try:
                client = await construction
                await client.aclose()
            except Exception as exc:
                logger.error(
                    "Inbound attachment HTTP client cleanup after cancellation failed (%s)",
                    type(exc).__name__,
                )

        await await_drained(close_after_construction())
        raise


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
