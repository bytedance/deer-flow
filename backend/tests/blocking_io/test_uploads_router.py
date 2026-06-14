"""Regression anchor: writing an uploaded file must not block the event loop.

``_write_upload_file_with_limits`` is the core of ``POST /api/.../uploads``: it
opens the destination file, streams the ``UploadFile`` in chunks, and writes each
chunk to disk while enforcing size limits. The chunk *read* is genuinely async
(Starlette runs it in a threadpool); the open / per-chunk ``write`` / ``close`` /
cleanup ``unlink`` are blocking filesystem IO that the function offloads via
``asyncio.to_thread``. If any of that regresses back onto the event loop, the
strict Blockbuster gate raises ``BlockingError`` and this test fails.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

from app.gateway.routers.uploads import _write_upload_file_with_limits

pytestmark = pytest.mark.asyncio


async def test_write_upload_file_does_not_block_event_loop(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    await asyncio.to_thread(uploads_dir.mkdir, parents=True, exist_ok=True)

    # Multi-chunk payload so the chunked read/write loop actually iterates.
    payload = b"deerflow-upload-anchor-" * 4096  # ~90 KB, spans several chunks
    upload = UploadFile(filename="anchor.bin", file=io.BytesIO(payload))

    file_path, file_size, total_size = await _write_upload_file_with_limits(
        upload,
        uploads_dir=uploads_dir,
        display_filename="anchor.bin",
        max_single_file_size=10 * 1024 * 1024,
        max_total_size=10 * 1024 * 1024,
        total_size=0,
    )

    assert file_size == len(payload)
    assert total_size == len(payload)
    written = await asyncio.to_thread(Path(file_path).read_bytes)
    assert written == payload


async def test_write_upload_file_over_limit_cleans_up_without_blocking(tmp_path: Path) -> None:
    """The 413 path closes the handle and unlinks the partial file — also off-loop."""
    uploads_dir = tmp_path / "uploads"
    await asyncio.to_thread(uploads_dir.mkdir, parents=True, exist_ok=True)

    payload = b"x" * (256 * 1024)
    upload = UploadFile(filename="too-big.bin", file=io.BytesIO(payload))

    with pytest.raises(Exception):  # HTTPException 413  # noqa: B017
        await _write_upload_file_with_limits(
            upload,
            uploads_dir=uploads_dir,
            display_filename="too-big.bin",
            max_single_file_size=1024,  # force "File too large" mid-stream
            max_total_size=10 * 1024 * 1024,
            total_size=0,
        )

    # Partial file was unlinked on the error path.
    leftovers = await asyncio.to_thread(lambda: list(uploads_dir.iterdir()))
    assert leftovers == []
