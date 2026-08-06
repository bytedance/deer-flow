"""Cancellation-safe async adapters for blocking upload publication APIs."""

import asyncio
import logging
from pathlib import Path

from deerflow.uploads.manager import (
    PublishedUpload,
    publish_upload_bytes_leased,
    rollback_published_upload,
)

logger = logging.getLogger(__name__)


def _rollback_and_release(publication: PublishedUpload) -> None:
    try:
        rollback_published_upload(publication)
    finally:
        publication.release()


async def _drain_task(task: asyncio.Task) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break


async def publish_upload_bytes_leased_async(
    base_dir: Path,
    preferred_filename: str,
    data: bytes,
) -> PublishedUpload:
    """Publish bytes off-thread without leaking a lease when cancelled."""
    publish_task = asyncio.create_task(
        asyncio.to_thread(publish_upload_bytes_leased, base_dir, preferred_filename, data),
        name=f"publish-upload:{preferred_filename}",
    )
    try:
        return await asyncio.shield(publish_task)
    except asyncio.CancelledError:
        await _drain_task(publish_task)
        if not publish_task.cancelled() and publish_task.exception() is None:
            cleanup_task = asyncio.create_task(
                asyncio.to_thread(_rollback_and_release, publish_task.result()),
                name=f"rollback-cancelled-upload:{preferred_filename}",
            )
            await _drain_task(cleanup_task)
            try:
                cleanup_task.result()
            except Exception:
                logger.warning("Failed to roll back cancelled upload publication", exc_info=True)
        raise


async def release_published_upload_async(publication: PublishedUpload) -> None:
    """Release a publication off-thread before propagating cancellation."""
    release_task = asyncio.create_task(
        asyncio.to_thread(publication.release),
        name=f"release-upload:{publication.path.name}",
    )
    cancelled = False
    while not release_task.done():
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError:
            cancelled = True
    release_task.result()
    if cancelled:
        raise asyncio.CancelledError
