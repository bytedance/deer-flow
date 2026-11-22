"""Keep queued attachments outside the sandbox until their run is admitted."""

import hashlib
import logging
import os
import re
import shutil
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile

from app.gateway.persistent_writes import run_drained_write
from app.gateway.routers import uploads
from app.gateway.upload_ingestion import prepare_published_uploads
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.uploads.companions import register_companion
from deerflow.uploads.manager import _MAX_FILENAME_BYTES, _fit_utf8_bytes, _split_stem_suffix, normalize_filename
from deerflow.utils.file_io import await_drained, run_file_io
from deerflow.utils.host_paths import extended_length_path

logger = logging.getLogger(__name__)


class StagedInputFile(TypedDict):
    filename: str
    size: int
    sha256: str


def _validate_staging_id(staging_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", staging_id):
        raise ValueError("Invalid queued upload identifier")


def _staging_dir(thread_id: str, user_id: str, staging_id: str) -> Path:
    _validate_staging_id(staging_id)
    # Sandbox mounts and the artifacts API are scoped to user-data; ordinary
    # thread deletion also removes this sibling directory.
    return extended_length_path(get_paths().thread_dir(thread_id, user_id=user_id) / ".queued-uploads" / staging_id)


def _staged_file(directory: Path, index: int, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    return directory / (f"{index}{suffix}" if suffix in uploads.CONVERTIBLE_EXTENSIONS else str(index))


def _stage_files(directory: Path, files: list[UploadFile], limits: uploads.UploadLimits) -> list[StagedInputFile]:
    if len(files) > limits.max_files:
        raise HTTPException(status_code=413, detail=f"Too many files: maximum is {limits.max_files}")
    try:
        names = [normalize_filename(file.filename or "") for file in files]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid queued attachment filename") from exc

    directory.mkdir(mode=0o700, parents=True)
    staged = []
    total = 0
    for index, (file, filename) in enumerate(zip(files, names, strict=True)):
        size = 0
        digest = hashlib.sha256()
        with _staged_file(directory, index, filename).open("xb") as destination:
            while chunk := file.file.read(uploads.UPLOAD_CHUNK_SIZE):
                size += len(chunk)
                total += len(chunk)
                if size > limits.max_file_size:
                    raise HTTPException(status_code=413, detail=f"File too large: {filename}")
                if total > limits.max_total_size:
                    raise HTTPException(status_code=413, detail="Total upload size too large")
                digest.update(chunk)
                destination.write(chunk)
        staged.append(StagedInputFile(filename=filename, size=size, sha256=digest.hexdigest()))
    return staged


def _discard_staging(directory: Path) -> None:
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not discard queued attachment staging (%s)", type(exc).__name__)


async def stage_input_files(thread_id: str, user_id: str, files: list[UploadFile], config: AppConfig) -> tuple[str, list[StagedInputFile]]:
    staging_id = uuid4().hex
    directory = await run_file_io(_staging_dir, thread_id, user_id, staging_id)
    try:
        staged = await run_drained_write("Stage queued attachments", _stage_files, (HTTPException,), directory, files, uploads._get_upload_limits(config))
    except BaseException:
        await await_drained(run_file_io(_discard_staging, directory))
        raise
    return staging_id, staged


async def discard_input_files(thread_id: str, user_id: str, staging_id: str) -> None:
    directory = await run_file_io(_staging_dir, thread_id, user_id, staging_id)
    await run_drained_write("Discard queued attachments", _discard_staging, (), directory)


def input_file_metadata(staging_id: str, files: list[StagedInputFile]) -> list[dict]:
    """Use stable names so admission and publication agree across retries."""
    _validate_staging_id(staging_id)
    metadata = []
    for index, file in enumerate(files):
        name = normalize_filename(file["filename"])
        stem, suffix = _split_stem_suffix(name)
        tag = f"_{staging_id}_{index}"
        budget = _MAX_FILENAME_BYTES - len(tag)
        suffix = _fit_utf8_bytes(suffix, budget - 1).rstrip(" .")
        filename = f"{_fit_utf8_bytes(stem, budget - len(suffix.encode('utf-8')))}{tag}{suffix}"
        metadata.append({"filename": filename, "original_filename": name, "size": file["size"], "path": uploads.upload_virtual_path(filename), "status": "uploaded"})
    return metadata


def _publish_files(thread_id: str, user_id: str, targets: list[tuple[Path, str]]) -> tuple[list[Path], list[Path]]:
    uploads_dir = uploads.ensure_uploads_dir(thread_id, user_id=user_id)
    paths = []
    published = []
    try:
        for source, filename in targets:
            try:
                path = uploads._link_staged_no_overwrite(source, uploads_dir, filename, unlink_staged=False)
                published.append(path)
            except FileExistsError:
                path = uploads_dir / filename
                # A retry can find its own published inode. Never reuse bytes
                # from a different upload claiming the same name.
                if not os.path.samestat(source.lstat(), path.lstat()):
                    raise
            paths.append(path)
    except BaseException:
        uploads._cleanup_uploaded_paths(published)
        raise
    return paths, published


async def publish_input_files(thread_id: str, user_id: str, staging_id: str, files: list[StagedInputFile], *, request: Request, config: AppConfig) -> list[dict]:
    """Publish only while the destination run owns the thread's run slot."""
    directory = await run_file_io(_staging_dir, thread_id, user_id, staging_id)
    metadata = input_file_metadata(staging_id, files)
    targets: list[tuple[Path, str]] = []
    companion_indices: list[tuple[int, int]] = []
    convert = uploads._auto_convert_documents_enabled(config)
    for index, file in enumerate(metadata):
        source = _staged_file(directory, index, file["original_filename"])
        targets.append((source, file["filename"]))
        if convert and source.suffix in uploads.CONVERTIBLE_EXTENSIONS:
            # Convert while the source is still private. The final staged
            # pathname is reserved for a fully written conversion.
            companion = directory / f"{index}.md"
            if not await run_file_io(companion.is_file):
                converted = await uploads.convert_file_to_markdown(source, output_path=directory / f"{index}.md.part")
                if converted is None:
                    continue
                await run_file_io(os.replace, converted, companion)
            companion_indices.append((len(targets) - 1, len(targets)))
            targets.append((companion, Path(file["filename"]).with_suffix(".md").name))

    async def publish_and_sync() -> None:
        paths, published = await run_drained_write("Publish queued attachments", _publish_files, (), thread_id, user_id, targets)
        try:
            provider = await run_file_io(uploads.get_sandbox_provider)
            if uploads._uses_thread_data_mounts(provider):
                await prepare_published_uploads(paths)
            else:
                # Keep the ordinary upload endpoint's sandbox authorization.
                lease = await uploads.try_acquire_sandbox_for_request(request, provider, thread_id, user_id=user_id, app_config=config, owner_prefix="gateway:queued-upload")
                try:
                    if not lease.denied and lease.sandbox is None:
                        raise RuntimeError("Failed to acquire sandbox for queued attachments")
                    await prepare_published_uploads(paths, sandbox=None if lease.denied else lease.sandbox)
                finally:
                    await lease.release()
        except BaseException:
            await run_file_io(uploads._cleanup_uploaded_paths, published)
            raise
        await discard_input_files(thread_id, user_id, staging_id)
        # Unlinking the staged alias changes the inode's ctime. Record the
        # association afterward, once the upload has its final identity.
        for original, companion in companion_indices:
            await run_file_io(register_companion, paths[original], paths[companion])

    await await_drained(publish_and_sync())
    return metadata
