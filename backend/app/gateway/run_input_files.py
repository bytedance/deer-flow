"""Keep queued attachments outside the sandbox until their run is admitted."""

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
from collections.abc import Awaitable, Callable
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
from deerflow.uploads.manager import UPLOAD_STAGING_PREFIX, UPLOAD_STAGING_SUFFIX, normalize_filename
from deerflow.utils.atomic_write import publish_bytes_atomically
from deerflow.utils.file_io import await_drained, run_file_io
from deerflow.utils.host_paths import extended_length_path

logger = logging.getLogger(__name__)
QUEUED_UPLOADS_DIR = ".queued-uploads"


class StagedInputFile(TypedDict):
    filename: str
    size: int
    sha256: str


def is_staging_id(staging_id: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", staging_id))


def _validate_staging_id(staging_id: str) -> None:
    if not is_staging_id(staging_id):
        raise ValueError("Invalid queued upload identifier")


def _staging_dir(thread_id: str, user_id: str, staging_id: str) -> Path:
    _validate_staging_id(staging_id)
    # Sandbox mounts and the artifacts API are scoped to user-data; ordinary
    # thread deletion also removes this sibling directory.
    return extended_length_path(get_paths().thread_dir(thread_id, user_id=user_id) / QUEUED_UPLOADS_DIR / staging_id)


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


def _is_staged_link(source: Path, target: Path) -> bool:
    try:
        return os.path.samestat(source.lstat(), target.lstat())
    except FileNotFoundError:
        return False


def _rollback_links(links: list[tuple[Path, Path]]) -> None:
    for source, target in reversed(links):
        try:
            if _is_staged_link(source, target):
                target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not roll back queued attachment publication (%s)", type(exc).__name__)


def _publish_files(
    thread_id: str,
    user_id: str,
    directory: Path,
    targets: list[tuple[Path, str]],
    converted: dict[int, Path],
) -> tuple[list[Path], list[tuple[Path, Path]], list[tuple[Path, Path]]]:
    uploads_dir = uploads.ensure_uploads_dir(thread_id, user_id=user_id)
    plan = directory / "destinations.json"
    try:
        destinations: dict[str, str] = json.loads(plan.read_text(encoding="utf-8"))
    except FileNotFoundError:
        destinations = {}
    occupied = {entry.name.casefold(): entry for entry in uploads_dir.iterdir()}
    seen = {entry.name for entry in occupied.values()} | set(destinations.values())
    links: list[tuple[Path, Path]] = []

    def link(source: Path, requested: str) -> Path:
        filename = destinations.get(source.name)
        if filename is None:
            uploads._pure_destination(uploads_dir, requested)
        elif (existing := occupied.get(filename.casefold())) is not None and existing.name != filename:
            # A different spelling still counts as a collision on case-sensitive filesystems.
            filename = None
        while True:
            if filename is None:
                filename = uploads.claim_unique_filename(requested, seen)
                destinations[source.name] = filename
                # Persist the choice before making a sandbox-visible link so a
                # pre-graph failure can retry with the same attachment names.
                publish_bytes_atomically(plan, json.dumps(destinations).encode("utf-8"))
            try:
                path = uploads._link_staged_no_overwrite(source, uploads_dir, filename, unlink_staged=False)
            except FileExistsError:
                path = uploads_dir / filename
                if not _is_staged_link(source, path):
                    filename = None
                    continue
            links.append((source, path))
            return path

    try:
        # Claim user-supplied names first so a generated companion cannot
        # displace an attachment such as report.md accompanying report.pdf.
        paths = [link(source, filename) for source, filename in targets]
        companions = [(paths[index], link(source, paths[index].with_suffix(".md").name)) for index, source in converted.items()]
    except BaseException:
        _rollback_links(links)
        raise
    return paths, companions, links


_REMOTE_UPLOAD_TRANSACTION = """
import json, os, stat, sys
from pathlib import Path

action, directory, prefix, suffix, names = json.loads(sys.argv[1])
directory = Path(directory)
files = [
    [directory / name, *(directory / f"{prefix}-{index}{kind}{suffix}" for kind in ("", "-next", "-old"))]
    for index, name in enumerate(names)
]

def info(path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None

def same_file(first, second):
    return first is not None and second is not None and os.path.samestat(first, second)

def rollback():
    # Only touch destinations that still contain this batch's staged inode.
    for target, staged, _, backup in reversed(files):
        if same_file(info(staged), info(target)):
            if info(backup) is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(backup, target)

if action == 'promote':
    try:
        for target, staged, candidate, backup in files:
            previous = info(target)
            if same_file(info(staged), previous):
                continue  # The transport may have retried an acknowledged move.
            if previous is not None:
                if stat.S_ISDIR(previous.st_mode):
                    raise IsADirectoryError(target)
                if info(backup) is None:
                    os.link(target, backup, follow_symlinks=False)
            if info(candidate) is None:
                os.link(staged, candidate, follow_symlinks=False)
            os.replace(candidate, target)
    except BaseException:
        rollback()
        raise
elif action in ('rollback', 'discard'):
    if action == 'rollback':
        rollback()
    for _, staged, candidate, backup in files:
        for path in (staged, candidate, backup):
            path.unlink(missing_ok=True)
print(prefix)
"""


def _publish_remote_uploads(sandbox, paths: list[Path]) -> None:
    """Transfer private files before publishing their names in a remote sandbox."""
    prefix = f"{UPLOAD_STAGING_PREFIX}{uuid4().hex}"
    root = getattr(sandbox, "artifact_root", None)
    directory = f"{root.rstrip('/')}/uploads" if isinstance(root, str) and root else uploads.upload_virtual_path("").rstrip("/")

    def checked_command(action: str) -> None:
        payload = json.dumps([action, directory, prefix, UPLOAD_STAGING_SUFFIX, [path.name for path in paths]])
        output = sandbox.execute_command(f"python3 -I -c {shlex.quote(_REMOTE_UPLOAD_TRANSACTION)} {shlex.quote(payload)}", timeout=30)
        if output.strip() != prefix or getattr(output, "exit_code", 0) != 0:
            if action == "probe":
                raise OSError("Remote sandbox does not support queued upload publication with Python 3")
            raise OSError("Remote queued upload reconciliation was not acknowledged")

    checked_command("probe")
    action = "discard"
    try:
        for index, path in enumerate(paths):
            staged_name = f"{prefix}-{index}{UPLOAD_STAGING_SUFFIX}"
            uploads._sync_upload_to_sandbox(sandbox, path, uploads.upload_virtual_path(staged_name))
        action = "rollback"
        checked_command("promote")
    except BaseException:
        for retry in (False, True):
            try:
                checked_command(action)
                break
            except Exception:
                if retry:
                    logger.exception("Failed to reconcile remote queued upload before releasing the sandbox")
        raise
    else:
        try:
            checked_command("discard")
        except Exception:
            logger.exception("Failed to remove temporary remote queued upload files")


async def publish_input_files(thread_id: str, user_id: str, staging_id: str, files: list[StagedInputFile], *, request: Request, config: AppConfig, on_published: Callable[[], Awaitable[None]] | None = None) -> list[dict]:
    """Publish only while the destination run owns the thread's run slot."""
    directory = await run_file_io(_staging_dir, thread_id, user_id, staging_id)
    targets: list[tuple[Path, str]] = []
    converted: dict[int, Path] = {}
    convert = uploads._auto_convert_documents_enabled(config)
    for index, file in enumerate(files):
        source = _staged_file(directory, index, file["filename"])
        targets.append((source, file["filename"]))
        if convert and source.suffix in uploads.CONVERTIBLE_EXTENSIONS:
            # Convert while the source is still private. The final staged
            # pathname is reserved for a fully written conversion.
            companion = directory / f"{index}.md"
            if not await run_file_io(companion.is_file):
                output = await uploads.convert_file_to_markdown(source, output_path=directory / f"{index}.md.part")
                if output is None:
                    continue
                await run_file_io(os.replace, output, companion)
            converted[index] = companion

    async def publish_and_sync() -> list[Path]:
        links = []
        lease = None
        try:
            provider = await run_file_io(uploads.get_sandbox_provider)
            if not uploads._uses_thread_data_mounts(provider):
                # Keep the ordinary upload endpoint's sandbox authorization.
                # Fresh remote sandboxes can mirror uploads during acquisition.
                lease = await uploads.try_acquire_sandbox_for_request(request, provider, thread_id, user_id=user_id, app_config=config, owner_prefix="gateway:queued-upload")
                if not lease.denied and lease.sandbox is None:
                    raise RuntimeError("Failed to acquire sandbox for queued attachments")
            originals, companions, links = await run_drained_write("Publish queued attachments", _publish_files, (), thread_id, user_id, directory, targets, converted)
            paths = [target for _, target in links]
            await prepare_published_uploads(paths)
            if lease is not None and not lease.denied:
                await run_file_io(_publish_remote_uploads, lease.sandbox, paths)
        except BaseException:
            await run_file_io(_rollback_links, links)
            raise
        finally:
            if lease is not None:
                try:
                    await lease.release()
                except Exception:
                    logger.exception("Failed to release the queued attachment sandbox lease")
        if on_published is not None:
            await on_published()
        await run_file_io(_discard_staging, directory)
        # Unlinking the staged alias changes the inode's ctime. Record the
        # association afterward, once the upload has its final identity.
        for original, companion in companions:
            try:
                await run_file_io(register_companion, original, companion)
            except Exception as exc:
                logger.warning("Could not register queued attachment companion (%s)", type(exc).__name__)
        return originals

    paths = await await_drained(publish_and_sync())
    return [{"filename": path.name, "original_filename": file["filename"], "size": file["size"], "path": uploads.upload_virtual_path(path.name), "status": "uploaded"} for file, path in zip(files, paths, strict=True)]
