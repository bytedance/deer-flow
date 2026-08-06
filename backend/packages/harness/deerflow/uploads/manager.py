"""Shared upload management logic.

Pure business logic — no FastAPI/HTTP dependencies.
Both Gateway and Client delegate to these functions.
"""

import errno
import logging
import os
import secrets
import shutil
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.errors import AtomicUploadPublishError, PathTraversalError, UnsafeUploadPathError
from deerflow.uploads.layout import (
    UPLOAD_CONVERSIONS_DIRNAME,
    _truncate_utf8,
    artifact_url_for_virtual_path,
    existing_conversion_path_for_upload,
    upload_virtual_path,
)
from deerflow.uploads.lease import UploadIdentity, UploadNameLease, UploadStageLease
from deerflow.utils.thread_id import validate_thread_id

logger = logging.getLogger(__name__)

UPLOAD_STAGING_PREFIX = ".upload-"
UPLOAD_STAGING_SUFFIX = ".part"


@dataclass(slots=True)
class StagedUpload:
    """A complete-or-in-progress upload stored under a hidden temporary name."""

    base_dir: Path
    path: Path
    handle: BinaryIO
    lease: UploadStageLease


@dataclass(slots=True)
class PublishedUpload:
    """A published upload whose actual filename remains exclusively leased."""

    path: Path
    identity: UploadIdentity
    lease: UploadNameLease

    @property
    def is_active(self) -> bool:
        return self.lease.is_active

    def release(self) -> None:
        """Release the publication's name lease."""
        self.lease.release()


def get_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    """Return the uploads directory path for a thread (no side effects)."""
    validate_thread_id(thread_id)
    return get_paths().sandbox_uploads_dir(thread_id, user_id=user_id or get_effective_user_id())


def ensure_uploads_dir(thread_id: str, *, user_id: str | None = None) -> Path:
    """Return the uploads directory for a thread, creating it if needed."""
    base = get_uploads_dir(thread_id, user_id=user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_filename(filename: str) -> str:
    """Sanitize a filename by extracting its basename.

    Strips any directory components and rejects traversal patterns.

    Args:
        filename: Raw filename from user input (may contain path components).

    Returns:
        Safe filename (basename only).

    Raises:
        ValueError: If filename is empty or resolves to a traversal pattern.
    """
    if not filename:
        raise ValueError("Filename is empty")
    safe = Path(filename).name
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")
    # Reject backslashes — on Linux Path.name keeps them as literal chars,
    # but they indicate a Windows-style path that should be stripped or rejected.
    if "\\" in safe:
        raise ValueError(f"Filename contains backslash: {filename!r}")
    if "<" in safe or ">" in safe or "--- BEGIN USER INPUT ---" in safe or "--- END USER INPUT ---" in safe:
        raise ValueError(f"Filename contains reserved model-context token: {filename!r}")
    if len(safe.encode("utf-8")) > 255:
        raise ValueError(f"Filename too long: {len(safe)} chars")
    if is_upload_staging_file(safe):
        raise ValueError(f"Filename uses reserved upload staging pattern: {filename!r}")
    return safe


def claim_unique_filename(name: str, seen: set[str]) -> str:
    """Generate a unique filename by appending ``_N`` suffix on collision.

    Automatically adds the returned name to *seen* so callers don't need to.

    Args:
        name: Candidate filename.
        seen: Set of filenames already claimed (mutated in place).

    Returns:
        A filename not present in *seen* (already added to *seen*).
    """
    if name not in seen:
        seen.add(name)
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    candidate = f"{stem}_{counter}{suffix}"
    while candidate in seen:
        counter += 1
        candidate = f"{stem}_{counter}{suffix}"
    seen.add(candidate)
    return candidate


def is_upload_staging_file(filename: str) -> bool:
    """Return whether *filename* is a transient Gateway upload staging file."""
    return filename.startswith(UPLOAD_STAGING_PREFIX) and filename.endswith(UPLOAD_STAGING_SUFFIX)


def _validate_upload_directory(base_dir: Path) -> Path:
    """Return a real upload directory without following a directory symlink."""
    try:
        st = os.lstat(base_dir)
    except FileNotFoundError as exc:
        raise UnsafeUploadPathError(f"Upload directory does not exist: {base_dir}") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise UnsafeUploadPathError(f"Upload directory is unsafe: {base_dir}")
    return base_dir


def create_upload_staging_file(base_dir: Path) -> StagedUpload:
    """Create a hidden same-directory staging file for a complete payload."""
    base_dir = _validate_upload_directory(Path(base_dir))
    while True:
        temp_path = base_dir / f"{UPLOAD_STAGING_PREFIX}{secrets.token_hex(16)}{UPLOAD_STAGING_SUFFIX}"
        lease = UploadStageLease.acquire(base_dir, temp_path.name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            fd = os.open(temp_path, flags, 0o600)
        except FileExistsError:
            lease.release()
            continue
        except BaseException:
            lease.release()
            raise
        try:
            handle = os.fdopen(fd, "wb")
        except Exception:
            os.close(fd)
            temp_path.unlink(missing_ok=True)
            lease.release()
            raise
        return StagedUpload(base_dir=base_dir, path=temp_path, handle=handle, lease=lease)


def abort_staged_upload(staged: StagedUpload) -> None:
    """Close and remove a staging file, tolerating repeated cleanup."""
    close_error: BaseException | None = None
    unlink_error: BaseException | None = None
    lease_error: BaseException | None = None
    try:
        if not staged.handle.closed:
            staged.handle.close()
    except BaseException as exc:
        close_error = exc
    try:
        staged.path.unlink(missing_ok=True)
    except BaseException as exc:
        unlink_error = exc
    try:
        staged.lease.release()
    except BaseException as exc:
        lease_error = exc
    if close_error is not None:
        if unlink_error is not None:
            raise close_error from unlink_error
        if lease_error is not None:
            raise close_error from lease_error
        raise close_error
    if unlink_error is not None:
        if lease_error is not None:
            raise unlink_error from lease_error
        raise unlink_error
    if lease_error is not None:
        raise lease_error


def _validate_staged_upload(staged: StagedUpload) -> None:
    """Reject a staging path that was replaced or moved outside its directory."""
    _validate_upload_directory(staged.base_dir)
    if not staged.lease.is_active or staged.lease.stage_dir != staged.base_dir or staged.lease.stage_filename != staged.path.name:
        raise UnsafeUploadPathError("Upload staging liveness lease is missing")
    if staged.path.parent.resolve() != staged.base_dir.resolve():
        raise UnsafeUploadPathError("Upload staging path escaped its directory")
    try:
        staged_stat = os.lstat(staged.path)
    except FileNotFoundError as exc:
        raise UnsafeUploadPathError("Upload staging file disappeared") from exc
    if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1:
        raise UnsafeUploadPathError("Upload staging path is not an exclusive regular file")


def _filename_candidates(name: str) -> Iterator[str]:
    """Yield collision candidates that stay within the filename byte limit."""
    yield name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while True:
        marker = f"_{counter}"
        max_stem_bytes = 255 - len(marker.encode("utf-8")) - len(suffix.encode("utf-8"))
        if max_stem_bytes < 1:
            raise AtomicUploadPublishError("Filename suffix leaves no room for collision marker")
        candidate_stem = _truncate_utf8(stem, max_stem_bytes)
        if not candidate_stem:
            raise AtomicUploadPublishError("Filename stem leaves no room for collision marker")
        yield f"{candidate_stem}{marker}{suffix}"
        counter += 1


def _unlink_matching_upload(path: Path, identity: UploadIdentity) -> None:
    """Remove *path* only while it still names *identity*."""
    if identity.matches(path):
        path.unlink(missing_ok=True)


def _rollback_link_without_masking(path: Path, identity: UploadIdentity) -> None:
    try:
        _unlink_matching_upload(path, identity)
    except BaseException:
        logger.warning("Failed to roll back partially published upload: %s", path, exc_info=True)


def _release_lease_without_masking(lease: UploadNameLease) -> None:
    try:
        lease.release()
    except BaseException:
        logger.warning("Failed to release upload name lease: %s", lease.lock_path, exc_info=True)


def publish_staged_upload_leased(staged: StagedUpload, preferred_filename: str) -> PublishedUpload:
    """Atomically publish a staging file and retain its actual-name lease."""
    safe_name = normalize_filename(preferred_filename)
    if not staged.handle.closed:
        staged.handle.close()
    _validate_staged_upload(staged)
    staged_identity = UploadIdentity.from_path(staged.path)
    for candidate_name in _filename_candidates(safe_name):
        candidate = staged.base_dir / candidate_name
        try:
            os.lstat(candidate)
        except FileNotFoundError:
            pass
        else:
            # A visible entry cannot be published to, so skip it before taking
            # its lease. This also lets one multi-file request retain the first
            # generation's lease while choosing a suffix for a duplicate name.
            continue
        lease = UploadNameLease.acquire(staged.base_dir, candidate_name)
        linked = False
        try:
            try:
                os.link(staged.path, candidate, follow_symlinks=False)
                linked = True
            except FileExistsError:
                lease.release()
                continue
            except (NotImplementedError, TypeError) as exc:
                raise AtomicUploadPublishError("Storage does not support atomic no-replace publication") from exc
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    lease.release()
                    continue
                raise AtomicUploadPublishError(f"Storage does not support atomic no-replace publication: {exc}") from exc

            if not staged_identity.matches(candidate):
                raise AtomicUploadPublishError("Published upload identity changed during publication")
            try:
                staged.path.unlink()
            except OSError as exc:
                _rollback_link_without_masking(candidate, staged_identity)
                raise AtomicUploadPublishError("Failed to remove upload staging link after publication") from exc
            staged.lease.release()

            try:
                candidate_stat = os.lstat(candidate)
            except FileNotFoundError as exc:
                raise AtomicUploadPublishError("Published upload disappeared") from exc
            if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_nlink != 1 or not staged_identity.matches(candidate):
                _rollback_link_without_masking(candidate, staged_identity)
                raise AtomicUploadPublishError("Published upload did not become an exclusive regular file")
            return PublishedUpload(path=candidate, identity=staged_identity, lease=lease)
        except BaseException:
            if linked:
                _rollback_link_without_masking(candidate, staged_identity)
            _release_lease_without_masking(lease)
            raise


def publish_staged_upload(staged: StagedUpload, preferred_filename: str) -> Path:
    """Atomically publish a complete staging file without replacing an entry."""
    publication = publish_staged_upload_leased(staged, preferred_filename)
    try:
        return publication.path
    finally:
        publication.release()


def _abort_staged_upload_without_masking(staged: StagedUpload) -> None:
    try:
        abort_staged_upload(staged)
    except BaseException:
        logger.warning("Failed to clean up upload staging file: %s", staged.path, exc_info=True)


def publish_upload_bytes_leased(base_dir: Path, preferred_filename: str, data: bytes) -> PublishedUpload:
    """Stage bytes, publish them atomically, and retain the actual-name lease."""
    safe_name = normalize_filename(preferred_filename)
    staged = create_upload_staging_file(base_dir)
    try:
        staged.handle.write(data)
        return publish_staged_upload_leased(staged, safe_name)
    except BaseException:
        _abort_staged_upload_without_masking(staged)
        raise


def publish_upload_bytes(base_dir: Path, preferred_filename: str, data: bytes) -> Path:
    """Stage and atomically publish an in-memory upload payload."""
    publication = publish_upload_bytes_leased(base_dir, preferred_filename, data)
    try:
        return publication.path
    finally:
        publication.release()


def publish_upload_copy_leased(base_dir: Path, preferred_filename: str, source_path: Path) -> PublishedUpload:
    """Copy a source into staging, publish it, and retain the actual-name lease."""
    safe_name = normalize_filename(preferred_filename)
    staged = create_upload_staging_file(base_dir)
    try:
        with Path(source_path).open("rb") as source:
            shutil.copyfileobj(source, staged.handle)
        return publish_staged_upload_leased(staged, safe_name)
    except BaseException:
        _abort_staged_upload_without_masking(staged)
        raise


def publish_upload_copy(base_dir: Path, preferred_filename: str, source_path: Path) -> Path:
    """Copy a local source into staging and atomically publish it."""
    publication = publish_upload_copy_leased(base_dir, preferred_filename, source_path)
    try:
        return publication.path
    finally:
        publication.release()


def make_upload_file_sandbox_readable(file_path: Path) -> None:
    """Add group/other read bits to one verified regular upload artifact."""
    file_path = Path(file_path)
    file_stat = os.lstat(file_path)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise UnsafeUploadPathError(f"Unsafe upload file: {file_path.name}")
    readable_mode = stat.S_IMODE(file_stat.st_mode) | stat.S_IRGRP | stat.S_IROTH
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(file_path, readable_mode, **chmod_kwargs)


def rollback_published_upload(publication: PublishedUpload) -> None:
    """Remove only the still-leased upload generation represented by *publication*."""
    if not publication.is_active:
        raise RuntimeError("Cannot roll back a publication after releasing its lease")
    if publication.lease.filename != publication.path.name:
        raise UnsafeUploadPathError("Publication lease does not match its upload path")
    if not publication.identity.matches(publication.path):
        return
    owned_conversion = existing_conversion_path_for_upload(publication.path)
    if owned_conversion is not None:
        owned_conversion.unlink(missing_ok=True)
    publication.path.unlink()


def replace_system_owned_staged_file(staged: StagedUpload, filename: str) -> Path:
    """Atomically replace one generated file inside the owned namespace."""
    if staged.base_dir.name != UPLOAD_CONVERSIONS_DIRNAME:
        raise UnsafeUploadPathError("System-owned replace requires conversion directory")
    if not staged.handle.closed:
        staged.handle.close()
    _validate_staged_upload(staged)
    target = staged.base_dir / normalize_filename(filename)
    os.replace(staged.path, target)
    staged.lease.release()
    return target


def validate_path_traversal(path: Path, base: Path) -> None:
    """Verify that *path* is inside *base*.

    Raises:
        PathTraversalError: If a path traversal is detected.
    """
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        raise PathTraversalError("Path traversal detected") from None


def validate_upload_destination(base_dir: Path, filename: str) -> Path:
    """Validate an upload destination without mutating an existing file."""
    safe_name = normalize_filename(filename)
    dest = base_dir / safe_name

    try:
        st = os.lstat(dest)
    except FileNotFoundError:
        st = None

    if st is not None and not stat.S_ISREG(st.st_mode):
        raise UnsafeUploadPathError(f"Upload destination is not a regular file: {safe_name}")
    if st is not None and st.st_nlink > 1:
        raise UnsafeUploadPathError(f"Upload destination has multiple links: {safe_name}")

    validate_path_traversal(dest, base_dir)
    return dest


def _iter_upload_storage_dirs(base_dir: Path):
    for user_data_dir in base_dir.glob("threads/*/user-data"):
        yield user_data_dir / "uploads"
        yield user_data_dir / UPLOAD_CONVERSIONS_DIRNAME
    for user_data_dir in base_dir.glob("users/*/threads/*/user-data"):
        yield user_data_dir / "uploads"
        yield user_data_dir / UPLOAD_CONVERSIONS_DIRNAME


def cleanup_stale_upload_staging_files(base_dir: Path | str | None = None) -> int:
    """Remove orphaned Gateway upload staging files left by a hard crash."""
    root = Path(base_dir) if base_dir is not None else get_paths().base_dir
    removed = 0
    for uploads_dir in _iter_upload_storage_dirs(root):
        try:
            directory_stat = os.lstat(uploads_dir)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            continue
        try:
            with os.scandir(uploads_dir) as entries:
                for entry in entries:
                    if not is_upload_staging_file(entry.name) or not entry.is_file(follow_symlinks=False):
                        continue
                    stage_lease = UploadStageLease.try_acquire(uploads_dir, entry.name)
                    if stage_lease is None:
                        continue
                    try:
                        os.unlink(entry.path)
                        removed += 1
                    except FileNotFoundError:
                        pass
                    except OSError:
                        logger.warning("Failed to remove stale upload staging file: %s", entry.path, exc_info=True)
                    finally:
                        stage_lease.release()
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("Failed to scan uploads directory for stale staging files: %s", uploads_dir, exc_info=True)
    return removed


def write_upload_file_no_symlink(base_dir: Path, filename: str, data: bytes) -> Path:
    """Compatibility wrapper for collision-safe upload publication."""
    return publish_upload_bytes(base_dir, filename, data)


def list_files_in_dir(directory: Path) -> dict:
    """List files (not directories) in *directory*.

    Args:
        directory: Directory to scan.

    Returns:
        Dict with "files" list (sorted by name) and "count".
        Each file entry has ``size`` as *int* (bytes).  Call
        :func:`enrich_file_listing` to add virtual / artifact URLs.
    """
    if not directory.is_dir():
        return {"files": [], "count": 0}

    files = []
    with os.scandir(directory) as entries:
        for entry in sorted(entries, key=lambda e: e.name):
            if is_upload_staging_file(entry.name):
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            st = entry.stat(follow_symlinks=False)
            files.append(
                {
                    "filename": entry.name,
                    "size": st.st_size,
                    "path": entry.path,
                    "extension": Path(entry.name).suffix,
                    "modified": st.st_mtime,
                }
            )
    return {"files": files, "count": len(files)}


def delete_file_safe(base_dir: Path, filename: str) -> dict:
    """Delete a primary upload and only its exact owned conversion.

    Args:
        base_dir: Directory containing the file.
        filename: Name of file to delete.
    Returns:
        Dict with success and message.

    Raises:
        FileNotFoundError: If the file does not exist.
        PathTraversalError: If path traversal is detected.
    """
    safe_name = normalize_filename(filename)
    if safe_name != filename:
        raise PathTraversalError("Path traversal detected")
    try:
        base_dir = _validate_upload_directory(Path(base_dir))
    except UnsafeUploadPathError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise FileNotFoundError(f"File not found: {filename}") from exc
        raise
    lease = UploadNameLease.acquire(base_dir, safe_name)
    try:
        file_path = base_dir / safe_name
        try:
            file_stat = os.lstat(file_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {filename}") from None
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise UnsafeUploadPathError(f"Unsafe upload file: {safe_name}")

        owned_conversion = existing_conversion_path_for_upload(file_path)
        if owned_conversion is not None:
            owned_conversion.unlink(missing_ok=True)
        file_path.unlink()
    finally:
        lease.release()

    return {"success": True, "message": f"Deleted {filename}"}


def upload_artifact_url(thread_id: str, filename: str) -> str:
    """Build the artifact URL for a file in a thread's uploads directory.

    *filename* is percent-encoded so that spaces, ``#``, ``?`` etc. are safe.
    """
    return artifact_url_for_virtual_path(thread_id, upload_virtual_path(filename))


def enrich_file_listing(result: dict, thread_id: str) -> dict:
    """Add virtual paths and artifact URLs on a listing result.

    Mutates *result* in place and returns it for convenience.
    """
    for f in result["files"]:
        filename = f["filename"]
        f["virtual_path"] = upload_virtual_path(filename)
        f["artifact_url"] = upload_artifact_url(thread_id, filename)
    return result
