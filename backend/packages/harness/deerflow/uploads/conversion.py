"""Safe publication of Markdown generated from primary uploads."""

import asyncio
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from deerflow.uploads.async_helpers import run_upload_lease_io, wait_for_task_completion
from deerflow.uploads.errors import UnsafeUploadPathError
from deerflow.uploads.layout import (
    UnsafeConversionPathError,
    conversion_path_for_upload,
    ensure_conversion_dir,
)
from deerflow.uploads.lease import UploadIdentity, UploadNameLease
from deerflow.uploads.manager import (
    PublishedUpload,
    StagedUpload,
    abort_staged_upload,
    create_upload_staging_file,
    replace_system_owned_staged_file,
)
from deerflow.utils.file_conversion import convert_file_to_markdown

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PreparedConversion:
    publication: PublishedUpload
    staged: StagedUpload
    target: Path
    release_publication: bool


def _abort_stage_without_masking(staged: StagedUpload) -> None:
    try:
        abort_staged_upload(staged)
    except BaseException:
        logger.warning("Failed to clean up upload conversion staging file: %s", staged.path, exc_info=True)


def _release_publication_without_masking(publication: PublishedUpload) -> None:
    try:
        publication.release()
    except BaseException:
        logger.warning("Failed to release upload conversion lease: %s", publication.lease.lock_path, exc_info=True)


def _validate_publication(upload_path: Path, publication: PublishedUpload) -> None:
    if publication.path != upload_path:
        raise UnsafeUploadPathError("Upload publication does not match the conversion source")
    if publication.lease.filename != upload_path.name or publication.lease.uploads_dir != upload_path.parent:
        raise UnsafeUploadPathError("Upload publication lease does not match the conversion source")
    if not publication.is_active:
        raise UnsafeUploadPathError("Upload publication lease was already released")
    if not publication.identity.matches(upload_path):
        raise UnsafeUploadPathError("Upload generation changed before conversion")
    upload_stat = os.lstat(upload_path)
    if not stat.S_ISREG(upload_stat.st_mode) or upload_stat.st_nlink != 1:
        raise UnsafeUploadPathError("Upload conversion source is not an exclusive regular file")


def _discard_prepared_conversion(prepared: _PreparedConversion) -> None:
    _abort_stage_without_masking(prepared.staged)
    if prepared.release_publication:
        _release_publication_without_masking(prepared.publication)


def _prepare_conversion(upload_path: Path, publication: PublishedUpload | None) -> _PreparedConversion:
    release_publication = publication is None
    if publication is None:
        lease = UploadNameLease.acquire(upload_path.parent, upload_path.name)
        try:
            publication = PublishedUpload(
                path=upload_path,
                identity=UploadIdentity.from_path(upload_path),
                lease=lease,
            )
        except BaseException:
            try:
                lease.release()
            except BaseException:
                logger.warning("Failed to release upload conversion lease: %s", lease.lock_path, exc_info=True)
            raise

    staged: StagedUpload | None = None
    try:
        _validate_publication(upload_path, publication)
        conversion_dir = ensure_conversion_dir(upload_path.parent)
        target = conversion_path_for_upload(upload_path)
        staged = create_upload_staging_file(conversion_dir)
        staged.handle.close()
        return _PreparedConversion(
            publication=publication,
            staged=staged,
            target=target,
            release_publication=release_publication,
        )
    except BaseException:
        if staged is not None:
            _abort_stage_without_masking(staged)
        if release_publication:
            _release_publication_without_masking(publication)
        raise


def _publish_prepared_conversion(prepared: _PreparedConversion, result: Path) -> Path:
    _validate_publication(prepared.publication.path, prepared.publication)
    if result != prepared.staged.path:
        raise UnsafeConversionPathError("Converter returned an unexpected output path")
    return replace_system_owned_staged_file(prepared.staged, prepared.target.name)


async def _prepare_conversion_cancellation_safe(
    upload_path: Path,
    publication: PublishedUpload | None,
) -> _PreparedConversion:
    prepare_task = asyncio.create_task(
        run_upload_lease_io(_prepare_conversion, upload_path, publication),
        name=f"prepare-upload-conversion:{upload_path.name}",
    )
    cancelled = await wait_for_task_completion(prepare_task)
    if cancelled:
        if not prepare_task.cancelled() and prepare_task.exception() is None:
            cleanup_task = asyncio.create_task(
                asyncio.to_thread(_discard_prepared_conversion, prepare_task.result()),
                name=f"discard-upload-conversion:{upload_path.name}",
            )
            await wait_for_task_completion(cleanup_task)
            cleanup_task.result()
        raise asyncio.CancelledError
    return prepare_task.result()


async def _run_cleanup_off_thread(function, *args) -> None:
    cleanup_task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = await wait_for_task_completion(cleanup_task)
    cleanup_task.result()
    if cancelled:
        raise asyncio.CancelledError


async def convert_uploaded_file_to_markdown(
    upload_path: Path,
    *,
    publication: PublishedUpload | None = None,
) -> Path | None:
    """Convert one primary generation and atomically publish its owned Markdown."""
    prepared = await _prepare_conversion_cancellation_safe(upload_path, publication)
    stage_consumed = False
    try:
        conversion_task = asyncio.create_task(
            convert_file_to_markdown(upload_path, output_path=prepared.staged.path),
            name=f"convert-upload:{upload_path.name}",
        )
        conversion_cancelled = await wait_for_task_completion(conversion_task)
        if conversion_cancelled:
            raise asyncio.CancelledError
        result = conversion_task.result()
        if result is None:
            await _run_cleanup_off_thread(_abort_stage_without_masking, prepared.staged)
            stage_consumed = True
            return None
        publish_task = asyncio.create_task(
            asyncio.to_thread(_publish_prepared_conversion, prepared, Path(result)),
            name=f"publish-upload-conversion:{upload_path.name}",
        )
        publish_cancelled = await wait_for_task_completion(publish_task)
        if publish_cancelled:
            if not publish_task.cancelled() and publish_task.exception() is None:
                stage_consumed = True
            raise asyncio.CancelledError
        converted = publish_task.result()
        stage_consumed = True
        return converted
    finally:
        if not stage_consumed:
            if prepared.release_publication:
                await _run_cleanup_off_thread(_discard_prepared_conversion, prepared)
            else:
                await _run_cleanup_off_thread(_abort_stage_without_masking, prepared.staged)
        elif prepared.release_publication:
            await _run_cleanup_off_thread(_release_publication_without_masking, prepared.publication)
