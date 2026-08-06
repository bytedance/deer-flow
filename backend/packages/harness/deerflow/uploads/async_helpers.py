"""Cancellation-safe async adapters for blocking upload publication APIs."""

import asyncio
import atexit
import contextvars
import functools
import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from deerflow.uploads.manager import (
    PublishedUpload,
    publish_upload_bytes_leased,
    rollback_published_upload,
)

logger = logging.getLogger(__name__)

_UPLOAD_LEASE_EXECUTOR = ThreadPoolExecutor(
    max_workers=min(32, (os.cpu_count() or 1) + 4),
    thread_name_prefix="upload-lease-wait",
)
atexit.register(_UPLOAD_LEASE_EXECUTOR.shutdown, wait=False, cancel_futures=True)


async def run_upload_lease_io[**P, T](func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Run work that may wait for an upload lease outside general I/O pools."""
    loop = asyncio.get_running_loop()
    context = contextvars.copy_context()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_UPLOAD_LEASE_EXECUTOR, context.run, call)


async def wait_for_task_completion(task: asyncio.Task) -> bool:
    """Drain *task* despite cancellation and report whether cancellation arrived."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    return cancelled


async def run_upload_io_cancellation_safe[**P, T](
    func: Callable[P, T],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run blocking upload I/O to completion before propagating cancellation."""
    io_task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    cancelled = await wait_for_task_completion(io_task)
    result = io_task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


def _rollback_and_release(publication: PublishedUpload) -> None:
    try:
        rollback_published_upload(publication)
    finally:
        publication.release()


async def publish_upload_bytes_leased_async(
    base_dir: Path,
    preferred_filename: str,
    data: bytes,
) -> PublishedUpload:
    """Publish bytes off-thread without leaking a lease when cancelled."""
    publish_task = asyncio.create_task(
        run_upload_lease_io(publish_upload_bytes_leased, base_dir, preferred_filename, data),
        name=f"publish-upload:{preferred_filename}",
    )
    try:
        return await asyncio.shield(publish_task)
    except asyncio.CancelledError:
        await wait_for_task_completion(publish_task)
        if not publish_task.cancelled() and publish_task.exception() is None:
            cleanup_task = asyncio.create_task(
                asyncio.to_thread(_rollback_and_release, publish_task.result()),
                name=f"rollback-cancelled-upload:{preferred_filename}",
            )
            await wait_for_task_completion(cleanup_task)
            try:
                cleanup_task.result()
            except Exception:
                logger.warning("Failed to roll back cancelled upload publication", exc_info=True)
        raise


async def release_published_upload_async(publication: PublishedUpload) -> None:
    """Commit by releasing a publication, delaying and swallowing new cancellation.

    Callers use this only after response metadata has been constructed or after
    rollback has completed. Once release starts, the transaction's outcome is
    fixed, so a newly arriving cancellation must not turn committed files into
    an indeterminate cancelled result.
    """
    release_task = asyncio.create_task(
        asyncio.to_thread(publication.release),
        name=f"release-upload:{publication.path.name}",
    )
    await wait_for_task_completion(release_task)
    release_task.result()


async def rollback_published_upload_async(publication: PublishedUpload) -> None:
    """Roll back a publication off-thread, draining repeated cancellation."""
    rollback_task = asyncio.create_task(
        asyncio.to_thread(rollback_published_upload, publication),
        name=f"rollback-upload:{publication.path.name}",
    )
    await wait_for_task_completion(rollback_task)
    rollback_task.result()
