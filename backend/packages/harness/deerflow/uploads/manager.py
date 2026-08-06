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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import BinaryIO

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.errors import AtomicUploadPublishError, PathTraversalError, UnsafeUploadPathError
from deerflow.uploads.layout import (
    UPLOAD_CONVERSIONS_DIRNAME,
    _truncate_utf8,
    artifact_url_for_virtual_path,
    conversion_path_for_upload,
    ensure_conversion_dir,
    existing_conversion_path_for_upload,
    upload_virtual_path,
)
from deerflow.uploads.lease import UploadIdentity, UploadNameLease, UploadStageLease, portable_name_coordination_key
from deerflow.utils.thread_id import validate_thread_id

logger = logging.getLogger(__name__)

UPLOAD_STAGING_PREFIX = ".upload-"
UPLOAD_STAGING_SUFFIX = ".part"
UPLOAD_DELETION_TRANSACTION_PREFIX = ".upload-delete-"
_UPLOAD_DELETION_RESTORE_INTENT = "restore"
_UPLOAD_DELETION_DISCARD_INTENT = "discard"
_UPLOAD_DELETION_PRIMARY_DIRNAME = "primary"
_UPLOAD_DELETION_CONVERSION_TOMBSTONE = ".conversion"
_UPLOAD_DELETION_COMMIT_MARKER = ".commit"
_UPLOAD_DELETION_RESTORE_MARKER = ".restore"
_UPLOAD_DELETION_REMOTE_JOURNAL = ".remote-delete.json"
_WINDOWS_FORBIDDEN_FILENAME_CHARS = frozenset('<>:"|?*')


class RemoteDeletionCommitRequiredError(RuntimeError):
    """Remote deletion could not be compensated, so host deletion must commit."""


class RemoteDeletionCompensatedError(RuntimeError):
    """Remote deletion failed but its side effects were fully compensated."""


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
    if "\0" in filename:
        raise ValueError(f"Filename contains NUL byte: {filename!r}")
    safe = Path(filename).name
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")
    # Reject backslashes — on Linux Path.name keeps them as literal chars,
    # but they indicate a Windows-style path that should be stripped or rejected.
    if "\\" in safe:
        raise ValueError(f"Filename contains backslash: {filename!r}")
    if "<" in safe or ">" in safe or "--- BEGIN USER INPUT ---" in safe or "--- END USER INPUT ---" in safe:
        raise ValueError(f"Filename contains reserved model-context token: {filename!r}")
    if safe.endswith((" ", ".")) or PureWindowsPath(safe).is_reserved() or any(character in _WINDOWS_FORBIDDEN_FILENAME_CHARS or ord(character) < 32 for character in safe):
        raise ValueError(f"Filename is reserved or invalid on Windows: {filename!r}")
    if len(safe.encode("utf-8")) > 255:
        raise ValueError(f"Filename too long: {len(safe)} chars")
    if is_upload_staging_file(safe):
        raise ValueError(f"Filename uses reserved upload staging pattern: {filename!r}")
    return safe


def _normalize_existing_filename(filename: str) -> str:
    """Validate an exact existing basename without applying new-upload policy.

    POSIX deployments may contain names accepted by older DeerFlow versions
    that are not portable to Windows. They remain deletable after upgrade.
    """
    if not filename:
        raise ValueError("Filename is empty")
    if "\0" in filename:
        raise ValueError(f"Filename contains NUL byte: {filename!r}")
    safe = Path(filename).name
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Filename is unsafe: {filename!r}")
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
        marker_bytes = len(marker.encode("utf-8"))
        suffix_bytes = len(suffix.encode("utf-8"))
        max_stem_bytes = 255 - marker_bytes - suffix_bytes
        if max_stem_bytes < 1:
            # Path.suffix can consume almost the entire component (for example
            # ``a.`` plus 253 extension bytes). In that pathological case,
            # treat the complete basename as the collision stem and truncate
            # its tail so the marker always fits.
            candidate_source = name
            candidate_suffix = ""
            max_stem_bytes = 255 - marker_bytes
        else:
            candidate_source = stem
            candidate_suffix = suffix
        if max_stem_bytes < 1:
            raise AtomicUploadPublishError("Filename leaves no room for collision marker")
        candidate_stem = _truncate_utf8(candidate_source, max_stem_bytes)
        if not candidate_stem and candidate_suffix:
            candidate_source = name
            candidate_suffix = ""
            max_stem_bytes = 255 - marker_bytes
            candidate_stem = _truncate_utf8(candidate_source, max_stem_bytes)
        if not candidate_stem:
            raise AtomicUploadPublishError("Filename stem leaves no room for collision marker")
        yield f"{candidate_stem}{marker}{candidate_suffix}"
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


def publish_staged_upload_leased(
    staged: StagedUpload,
    preferred_filename: str,
    *,
    reserved_coordination_keys: set[str] | None = None,
) -> PublishedUpload:
    """Atomically publish a staging file and retain its actual-name lease."""
    safe_name = normalize_filename(preferred_filename)
    if not staged.handle.closed:
        staged.handle.close()
    _validate_staged_upload(staged)
    staged_identity = UploadIdentity.from_path(staged.path)
    for candidate_name in _filename_candidates(safe_name):
        coordination_key = portable_name_coordination_key(candidate_name)
        if reserved_coordination_keys is not None and coordination_key in reserved_coordination_keys:
            continue
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
        lease = UploadNameLease.try_acquire(staged.base_dir, candidate_name)
        if lease is None:
            continue
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
            publication = PublishedUpload(path=candidate, identity=staged_identity, lease=lease)
            if reserved_coordination_keys is not None:
                reserved_coordination_keys.add(coordination_key)
            return publication
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


def publish_upload_copy_leased(
    base_dir: Path,
    preferred_filename: str,
    source_path: Path,
    *,
    reserved_coordination_keys: set[str] | None = None,
) -> PublishedUpload:
    """Copy a source into staging, publish it, and retain the actual-name lease."""
    safe_name = normalize_filename(preferred_filename)
    staged = create_upload_staging_file(base_dir)
    try:
        with Path(source_path).open("rb") as source:
            shutil.copyfileobj(source, staged.handle)
        return publish_staged_upload_leased(
            staged,
            safe_name,
            reserved_coordination_keys=reserved_coordination_keys,
        )
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
    try:
        staged_path, stage_lease = _stage_primary_deletion(
            publication.path.parent,
            publication.path,
            publication.identity,
            recover_on_crash=False,
            conversion_path=owned_conversion,
        )
    except (FileNotFoundError, UnsafeUploadPathError):
        # The pathname was replaced after the optimistic identity check. The
        # staging helper restores that replacement without deleting it.
        return
    try:
        _discard_staged_deletion(staged_path)
    except BaseException:
        _restore_staged_deletion(
            staged_path,
            publication.path,
            publication.identity,
        )
        raise
    finally:
        stage_lease.release()


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
    """Clean upload stages and recover interrupted primary deletions."""
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
                    if entry.name.startswith(UPLOAD_DELETION_TRANSACTION_PREFIX) and entry.name.endswith(UPLOAD_STAGING_SUFFIX) and entry.is_dir(follow_symlinks=False):
                        stage_lease = UploadStageLease.try_acquire(uploads_dir, entry.name)
                        if stage_lease is None:
                            continue
                        try:
                            if _recover_stale_deletion_transaction(Path(entry.path)):
                                removed += 1
                        finally:
                            stage_lease.release()
                        continue
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


def _deletion_transaction_metadata(transaction_name: str) -> tuple[int, bool] | None:
    """Decode the selected inode and crash intent from a transaction name."""
    if not (transaction_name.startswith(UPLOAD_DELETION_TRANSACTION_PREFIX) and transaction_name.endswith(UPLOAD_STAGING_SUFFIX)):
        return None
    body = transaction_name[len(UPLOAD_DELETION_TRANSACTION_PREFIX) : -len(UPLOAD_STAGING_SUFFIX)]
    intent, separator, remaining = body.partition("-")
    if separator and intent in {
        _UPLOAD_DELETION_RESTORE_INTENT,
        _UPLOAD_DELETION_DISCARD_INTENT,
    }:
        recover_on_crash = intent == _UPLOAD_DELETION_RESTORE_INTENT
        body = remaining
    else:
        # Transactions created before the intent field was introduced always
        # represented user-requested deletion and therefore recover on crash.
        recover_on_crash = True
    inode_hex, separator, token = body.partition("-")
    if not separator or not inode_hex or len(token) != 32 or any(character not in "0123456789abcdef" for character in inode_hex + token):
        return None
    return int(inode_hex, 16), recover_on_crash


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


def _scan_upload_path_by_identity(base_dir: Path, identity: UploadIdentity) -> Path:
    """Return the directory entry that actually names *identity*."""
    matching_path: Path | None = None
    with os.scandir(base_dir) as entries:
        for entry in entries:
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(entry_stat.st_mode) and (entry_stat.st_dev, entry_stat.st_ino) == (
                identity.device,
                identity.inode,
            ):
                if entry_stat.st_nlink != 1 or matching_path is not None:
                    raise UnsafeUploadPathError("Upload is no longer an exclusive directory entry")
                matching_path = Path(entry.path)
    if matching_path is None:
        raise UnsafeUploadPathError("Upload directory entry changed during deletion")
    matching_stat = os.lstat(matching_path)
    if not stat.S_ISREG(matching_stat.st_mode) or matching_stat.st_nlink != 1 or (matching_stat.st_dev, matching_stat.st_ino) != (identity.device, identity.inode):
        raise UnsafeUploadPathError("Upload is no longer an exclusive directory entry")
    return matching_path


def _find_upload_path_by_identity(base_dir: Path, identity: UploadIdentity) -> Path:
    """Re-scan for the selected identity immediately before deletion staging."""
    return _scan_upload_path_by_identity(base_dir, identity)


def _restore_staged_deletion(
    staged_path: Path,
    original_path: Path,
    identity: UploadIdentity,
) -> None:
    """Restore a staged primary and conversion without replacing a new generation."""
    try:
        staged_stat = os.lstat(staged_path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1 or (staged_stat.st_dev, staged_stat.st_ino) != (identity.device, identity.inode):
        raise UnsafeUploadPathError("Staged upload deletion changed identity")
    _clear_staged_deletion_commit(staged_path)
    _mark_staged_deletion_restore(staged_path)
    try:
        original_stat = os.lstat(original_path)
    except FileNotFoundError:
        original_stat = None
    restored_path: Path
    if original_stat is not None:
        if stat.S_ISREG(original_stat.st_mode) and (
            original_stat.st_dev,
            original_stat.st_ino,
        ) == (identity.device, identity.inode):
            restored_path = original_path
        else:
            restored_path = _link_staged_entry_as_recovery(staged_path, original_path)
            logger.warning(
                "Upload name was recreated during deletion rollback; preserved the prior generation as %s",
                restored_path,
            )
    else:
        try:
            os.link(staged_path, original_path, follow_symlinks=False)
        except FileExistsError:
            restored_path = _link_staged_entry_as_recovery(staged_path, original_path)
            logger.warning(
                "Upload name was recreated during deletion rollback; preserved the prior generation as %s",
                restored_path,
            )
        else:
            restored_path = original_path

    _restore_staged_conversion(staged_path, restored_path)
    staged_path.unlink()
    _clear_staged_deletion_restore(staged_path)
    _finish_deletion_transaction(staged_path)


def _staged_conversion_path(staged_path: Path) -> Path:
    return _deletion_transaction_dir_for_staged_path(staged_path) / _UPLOAD_DELETION_CONVERSION_TOMBSTONE


def _deletion_transaction_dir_for_staged_path(staged_path: Path) -> Path:
    """Return the transaction root for both current and legacy layouts."""
    parent = staged_path.parent
    if parent.name == _UPLOAD_DELETION_PRIMARY_DIRNAME:
        candidate = parent.parent
        if candidate.name.startswith(UPLOAD_DELETION_TRANSACTION_PREFIX) and candidate.name.endswith(UPLOAD_STAGING_SUFFIX):
            return candidate
    return parent


def _staged_deletion_commit_marker(staged_path: Path) -> Path:
    return _deletion_transaction_dir_for_staged_path(staged_path) / _UPLOAD_DELETION_COMMIT_MARKER


def _staged_deletion_restore_marker(staged_path: Path) -> Path:
    return _deletion_transaction_dir_for_staged_path(staged_path) / _UPLOAD_DELETION_RESTORE_MARKER


def _staged_deletion_remote_journal(staged_path: Path) -> Path:
    return _deletion_transaction_dir_for_staged_path(staged_path) / _UPLOAD_DELETION_REMOTE_JOURNAL


def _create_deletion_phase_marker(marker: Path, *, error_message: str) -> None:
    """Create and validate one durable deletion phase marker."""
    try:
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        marker_stat = os.lstat(marker)
        if not stat.S_ISREG(marker_stat.st_mode) or marker_stat.st_nlink != 1:
            raise UnsafeUploadPathError(error_message)
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(marker.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _mark_staged_deletion_committed(staged_path: Path) -> None:
    """Persist that remote side effects may begin and recovery must discard."""
    _create_deletion_phase_marker(
        _staged_deletion_commit_marker(staged_path),
        error_message="Unsafe upload deletion commit marker",
    )


def _mark_staged_deletion_restore(staged_path: Path) -> None:
    """Persist that a live rollback began and recovery must finish restoring."""
    _create_deletion_phase_marker(
        _staged_deletion_restore_marker(staged_path),
        error_message="Unsafe upload deletion restore marker",
    )


def _clear_staged_deletion_commit(staged_path: Path) -> None:
    _unlink_deletion_control_durably(_staged_deletion_commit_marker(staged_path))


def _clear_staged_deletion_restore(staged_path: Path) -> None:
    _unlink_deletion_control_durably(_staged_deletion_restore_marker(staged_path))


def _unlink_deletion_control_durably(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _restore_staged_conversion(staged_path: Path, restored_primary_path: Path) -> None:
    """Restore the exact conversion moved into a deletion transaction."""
    staged_conversion = _staged_conversion_path(staged_path)
    try:
        conversion_stat = os.lstat(staged_conversion)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(conversion_stat.st_mode) or conversion_stat.st_nlink not in {1, 2}:
        raise UnsafeUploadPathError("Staged upload conversion changed identity")

    target = conversion_path_for_upload(restored_primary_path)
    if conversion_stat.st_nlink == 2:
        try:
            target_stat = os.lstat(target)
        except FileNotFoundError as exc:
            raise UnsafeUploadPathError("Staged upload conversion has an unknown hard-link peer") from exc
        if not stat.S_ISREG(target_stat.st_mode) or (target_stat.st_dev, target_stat.st_ino) != (conversion_stat.st_dev, conversion_stat.st_ino):
            raise UnsafeUploadPathError("Staged upload conversion has an unexpected hard-link peer")
        staged_conversion.unlink()
        return
    try:
        os.link(staged_conversion, target, follow_symlinks=False)
    except FileExistsError:
        # A replacement generation may already own this deterministic target.
        # Never overwrite it with the prior generation's conversion.
        logger.warning(
            "Discarding staged conversion because the restored target already exists: %s",
            target,
        )
    staged_conversion.unlink()


def _discard_staged_deletion(staged_path: Path) -> None:
    """Commit deletion of the exact primary and conversion tombstones."""
    _staged_conversion_path(staged_path).unlink(missing_ok=True)
    staged_path.unlink(missing_ok=True)
    _clear_staged_deletion_restore(staged_path)
    if not _staged_deletion_remote_journal(staged_path).exists():
        _clear_staged_deletion_commit(staged_path)
    _finish_deletion_transaction(staged_path)


def _recovery_path_for(original_path: Path) -> Path:
    """Return a collision-resistant visible recovery name within NAME_MAX."""
    marker = f"_recovered_{secrets.token_hex(8)}"
    prefix = _truncate_utf8(
        original_path.name,
        255 - len(marker.encode("utf-8")),
    )
    return original_path.with_name(f"{prefix}{marker}")


def _preserve_staged_entry_as_recovery(staged_path: Path, original_path: Path) -> Path:
    """Publish staged bytes under a visible no-replace recovery name."""
    recovery_path = _link_staged_entry_as_recovery(staged_path, original_path)
    staged_path.unlink()
    return recovery_path


def _link_staged_entry_as_recovery(staged_path: Path, original_path: Path) -> Path:
    """Link staged bytes under a visible no-replace recovery name."""
    while True:
        recovery_path = _recovery_path_for(original_path)
        try:
            os.link(staged_path, recovery_path, follow_symlinks=False)
            break
        except FileExistsError:
            continue
    return recovery_path


def _finish_deletion_transaction(staged_path: Path) -> None:
    """Remove the now-empty transaction directory, when this is the new layout."""
    transaction_dir = _deletion_transaction_dir_for_staged_path(staged_path)
    if not (transaction_dir.name.startswith(UPLOAD_DELETION_TRANSACTION_PREFIX) and transaction_dir.name.endswith(UPLOAD_STAGING_SUFFIX) and transaction_dir.parent.name == UPLOAD_CONVERSIONS_DIRNAME):
        return
    primary_dir = transaction_dir / _UPLOAD_DELETION_PRIMARY_DIRNAME
    if (transaction_dir / _UPLOAD_DELETION_REMOTE_JOURNAL).exists():
        # Keep the empty primary container as the on-disk layout discriminator;
        # older direct-layout transactions may legitimately have a primary
        # named exactly like the new journal control.
        return
    try:
        primary_dir.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning(
            "Failed to remove completed upload deletion primary directory: %s",
            primary_dir,
            exc_info=True,
        )
    try:
        transaction_dir.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning(
            "Failed to remove completed upload deletion transaction: %s",
            transaction_dir,
            exc_info=True,
        )


def _recover_stale_deletion_transaction(transaction_dir: Path) -> bool:
    """Restore a crash-abandoned tombstone whose basename records its target."""
    metadata = _deletion_transaction_metadata(transaction_dir.name)
    if metadata is None:
        logger.warning("Refusing malformed upload deletion transaction name: %s", transaction_dir)
        return False
    expected_inode, recover_on_crash = metadata
    try:
        transaction_stat = os.lstat(transaction_dir)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(transaction_stat.st_mode) or not stat.S_ISDIR(transaction_stat.st_mode):
        return False

    entries = list(os.scandir(transaction_dir))
    if not entries:
        transaction_dir.rmdir()
        return True
    conversion_entries = [entry for entry in entries if entry.name == _UPLOAD_DELETION_CONVERSION_TOMBSTONE]
    commit_entries = [entry for entry in entries if entry.name == _UPLOAD_DELETION_COMMIT_MARKER]
    restore_entries = [entry for entry in entries if entry.name == _UPLOAD_DELETION_RESTORE_MARKER]
    primary_dir_entries = [entry for entry in entries if entry.name == _UPLOAD_DELETION_PRIMARY_DIRNAME and entry.is_dir(follow_symlinks=False)]
    remote_journal_entries = [entry for entry in entries if entry.name == _UPLOAD_DELETION_REMOTE_JOURNAL and primary_dir_entries]
    legacy_primary_entries = [
        entry
        for entry in entries
        if entry.name
        not in {
            _UPLOAD_DELETION_CONVERSION_TOMBSTONE,
            _UPLOAD_DELETION_COMMIT_MARKER,
            _UPLOAD_DELETION_RESTORE_MARKER,
        }
        and not (entry.name == _UPLOAD_DELETION_REMOTE_JOURNAL and remote_journal_entries)
        and not (entry.name == _UPLOAD_DELETION_PRIMARY_DIRNAME and entry.is_dir(follow_symlinks=False))
    ]
    if (
        len(conversion_entries) > 1
        or len(commit_entries) > 1
        or len(restore_entries) > 1
        or len(remote_journal_entries) > 1
        or len(primary_dir_entries) > 1
        or len(legacy_primary_entries) > 1
        or (primary_dir_entries and legacy_primary_entries)
    ):
        logger.warning(
            "Refusing malformed upload deletion transaction with %s entries: %s",
            len(entries),
            transaction_dir,
        )
        return False
    if remote_journal_entries:
        remote_journal_stat = remote_journal_entries[0].stat(follow_symlinks=False)
        if not stat.S_ISREG(remote_journal_stat.st_mode) or remote_journal_stat.st_nlink != 1:
            logger.warning("Refusing malformed remote upload deletion journal: %s", transaction_dir)
            return False
    primary_dir: Path | None = None
    if primary_dir_entries:
        primary_dir_entry = primary_dir_entries[0]
        if not primary_dir_entry.is_dir(follow_symlinks=False):
            logger.warning("Refusing malformed upload deletion primary directory: %s", transaction_dir)
            return False
        primary_dir = Path(primary_dir_entry.path)
        nested_primary_entries = list(os.scandir(primary_dir))
        if len(nested_primary_entries) > 1:
            logger.warning("Refusing upload deletion transaction with multiple primary entries: %s", transaction_dir)
            return False
        primary_entries = nested_primary_entries
    else:
        # Compatibility with transactions written before primaries were
        # isolated from fixed control names in a dedicated directory.
        primary_entries = legacy_primary_entries
    if conversion_entries:
        conversion_stat = conversion_entries[0].stat(follow_symlinks=False)
        if not stat.S_ISREG(conversion_stat.st_mode) or conversion_stat.st_nlink not in {1, 2}:
            logger.warning("Refusing malformed upload conversion tombstone: %s", transaction_dir)
            return False
    if commit_entries:
        commit_stat = commit_entries[0].stat(follow_symlinks=False)
        if not stat.S_ISREG(commit_stat.st_mode) or commit_stat.st_nlink != 1:
            logger.warning("Refusing malformed upload deletion commit marker: %s", transaction_dir)
            return False
        recover_on_crash = False
    elif remote_journal_entries:
        if not recover_on_crash:
            logger.warning("Refusing discard transaction with an uncommitted remote journal: %s", transaction_dir)
            return False
        # The process crashed after preparing the durable remote operation but
        # before persisting permission to start it. No remote side effect could
        # have begun, so discard the prepared journal and restore the host.
        _unlink_deletion_control_durably(Path(remote_journal_entries[0].path))
        remote_journal_entries = []
    if restore_entries:
        restore_stat = restore_entries[0].stat(follow_symlinks=False)
        if not stat.S_ISREG(restore_stat.st_mode) or restore_stat.st_nlink != 1:
            logger.warning("Refusing malformed upload deletion restore marker: %s", transaction_dir)
            return False
        if commit_entries:
            logger.warning("Refusing upload deletion transaction with conflicting phase markers: %s", transaction_dir)
            return False
        recover_on_crash = True
    if not recover_on_crash and conversion_entries and conversion_stat.st_nlink != 1:
        logger.warning(
            "Refusing discard transaction with a linked conversion tombstone: %s",
            transaction_dir,
        )
        return False
    if not primary_entries:
        if remote_journal_entries:
            # sandbox_sync reconciles this durable remote cleanup before the
            # transaction and its commit marker can be removed.
            return False
        if recover_on_crash and not commit_entries and not conversion_entries:
            if restore_entries:
                Path(restore_entries[0].path).unlink()
            if primary_dir is not None:
                primary_dir.rmdir()
            transaction_dir.rmdir()
            return True
        if not commit_entries:
            logger.warning("Refusing upload deletion transaction without a primary: %s", transaction_dir)
            return False
        if conversion_entries:
            Path(conversion_entries[0].path).unlink()
        Path(commit_entries[0].path).unlink()
        if primary_dir is not None:
            primary_dir.rmdir()
        transaction_dir.rmdir()
        return True
    entry = primary_entries[0]
    if not entry.is_file(follow_symlinks=False):
        logger.warning("Refusing malformed upload deletion transaction: %s", transaction_dir)
        return False
    try:
        original_name = _normalize_existing_filename(entry.name)
    except ValueError:
        logger.warning("Refusing upload deletion transaction with unsafe target: %s", transaction_dir)
        return False
    if original_name != entry.name:
        return False

    uploads_dir = transaction_dir.parent.parent / "uploads"
    name_lease = UploadNameLease.try_acquire(
        uploads_dir,
        original_name,
        allow_legacy_posix_filename=True,
    )
    if name_lease is None:
        return False
    try:
        staged_path = Path(entry.path)
        staged_stat = os.lstat(staged_path)
        if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink not in {1, 2} or staged_stat.st_ino != expected_inode:
            logger.warning("Refusing unsafe upload deletion tombstone: %s", staged_path)
            return False
        identity = UploadIdentity(
            device=staged_stat.st_dev,
            inode=staged_stat.st_ino,
        )
        if not recover_on_crash:
            visible_matches: list[Path] = []
            if staged_stat.st_nlink == 2:
                # A discard transaction never restores a visible peer.  If a
                # previous attempt crashed after relinking the tombstone (or a
                # rollback raced with recovery), remove the one verified peer
                # first; a crash after this unlink leaves an idempotent nlink=1
                # tombstone for the next startup pass.
                with os.scandir(uploads_dir) as upload_entries:
                    for upload_entry in upload_entries:
                        try:
                            upload_stat = upload_entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if stat.S_ISREG(upload_stat.st_mode) and (
                            upload_stat.st_dev,
                            upload_stat.st_ino,
                        ) == (identity.device, identity.inode):
                            visible_matches.append(Path(upload_entry.path))
                if len(visible_matches) != 1:
                    logger.warning(
                        "Refusing ambiguous upload discard recovery with %s visible aliases: %s",
                        len(visible_matches),
                        staged_path,
                    )
                    return False
            if not conversion_entries:
                # Backward compatibility for transactions created before the
                # exact conversion was moved beside the primary tombstone.
                original_path = uploads_dir / original_name
                try:
                    current_original_stat = os.lstat(original_path)
                except FileNotFoundError:
                    current_original_stat = None
                delete_conversion = current_original_stat is None or (stat.S_ISREG(current_original_stat.st_mode) and (current_original_stat.st_dev, current_original_stat.st_ino) == (identity.device, identity.inode))
                if delete_conversion:
                    owned_conversion = existing_conversion_path_for_upload(original_path)
                    if owned_conversion is not None:
                        owned_conversion.unlink(missing_ok=True)
            if visible_matches:
                visible_matches[0].unlink()
            _discard_staged_deletion(staged_path)
            return True
        if staged_stat.st_nlink == 2:
            # A previous recovery may have crashed after publishing the visible
            # hard link but before removing the tombstone.  Accept only one
            # exact visible peer; any additional/hidden alias is ambiguous.
            visible_matches: list[Path] = []
            with os.scandir(uploads_dir) as upload_entries:
                for upload_entry in upload_entries:
                    try:
                        upload_stat = upload_entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if stat.S_ISREG(upload_stat.st_mode) and (
                        upload_stat.st_dev,
                        upload_stat.st_ino,
                    ) == (identity.device, identity.inode):
                        visible_matches.append(Path(upload_entry.path))
            if len(visible_matches) != 1:
                logger.warning(
                    "Refusing ambiguous upload deletion recovery with %s visible aliases: %s",
                    len(visible_matches),
                    staged_path,
                )
                return False
            _restore_staged_conversion(staged_path, visible_matches[0])
            staged_path.unlink()
            _clear_staged_deletion_restore(staged_path)
            _finish_deletion_transaction(staged_path)
            return True
        _restore_staged_deletion(
            staged_path,
            uploads_dir / original_name,
            identity,
        )
        return True
    finally:
        name_lease.release()


def _restore_unexpected_staged_entry(staged_path: Path, original_path: Path) -> None:
    """Restore an entry moved during an identity race without unlinking it."""
    staged_stat = os.lstat(staged_path)
    if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1:
        raise UnsafeUploadPathError("Unsafe staged upload entry cannot be restored")
    try:
        os.link(staged_path, original_path, follow_symlinks=False)
    except FileExistsError:
        # A non-cooperating writer recreated the original name while the entry
        # was staged. Preserve the moved payload under a collision-resistant
        # visible recovery name instead of deleting either generation.
        recovery_path = _preserve_staged_entry_as_recovery(staged_path, original_path)
        logger.warning(
            "Upload entry changed during deletion; preserved the raced entry as %s",
            recovery_path,
        )
        _finish_deletion_transaction(staged_path)
        return
    staged_path.unlink()
    _finish_deletion_transaction(staged_path)


def _stage_primary_deletion(
    base_dir: Path,
    primary_path: Path,
    identity: UploadIdentity,
    *,
    recover_on_crash: bool = True,
    conversion_path: Path | None = None,
) -> tuple[Path, UploadStageLease]:
    """Move one primary generation and its exact conversion into a transaction."""
    staging_dir = ensure_conversion_dir(base_dir)
    intent = _UPLOAD_DELETION_RESTORE_INTENT if recover_on_crash else _UPLOAD_DELETION_DISCARD_INTENT
    while True:
        transaction_dir = staging_dir / (f"{UPLOAD_DELETION_TRANSACTION_PREFIX}{intent}-{identity.inode:x}-{secrets.token_hex(16)}{UPLOAD_STAGING_SUFFIX}")
        stage_lease = UploadStageLease.acquire(staging_dir, transaction_dir.name)
        try:
            transaction_dir.mkdir(mode=0o700)
        except FileExistsError:
            stage_lease.release()
            continue
        primary_dir = transaction_dir / _UPLOAD_DELETION_PRIMARY_DIRNAME
        try:
            primary_dir.mkdir(mode=0o700)
        except BaseException:
            transaction_dir.rmdir()
            stage_lease.release()
            raise
        staged_path = primary_dir / primary_path.name

        try:
            os.rename(primary_path, staged_path)
        except BaseException:
            primary_dir.rmdir()
            transaction_dir.rmdir()
            stage_lease.release()
            raise

        try:
            staged_stat = os.lstat(staged_path)
            if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1 or (staged_stat.st_dev, staged_stat.st_ino) != (identity.device, identity.inode):
                _restore_unexpected_staged_entry(staged_path, primary_path)
                raise UnsafeUploadPathError("Upload is no longer an exclusive directory entry")
            if conversion_path is not None:
                conversion_identity = UploadIdentity.from_path(conversion_path)
                staged_conversion = _staged_conversion_path(staged_path)
                os.rename(conversion_path, staged_conversion)
                staged_conversion_stat = os.lstat(staged_conversion)
                if not stat.S_ISREG(staged_conversion_stat.st_mode) or staged_conversion_stat.st_nlink != 1 or (staged_conversion_stat.st_dev, staged_conversion_stat.st_ino) != (conversion_identity.device, conversion_identity.inode):
                    raise UnsafeUploadPathError("Upload conversion changed during deletion staging")
            return staged_path, stage_lease
        except BaseException:
            if staged_path.exists():
                try:
                    staged_stat = os.lstat(staged_path)
                    if (staged_stat.st_dev, staged_stat.st_ino) == (
                        identity.device,
                        identity.inode,
                    ):
                        _restore_staged_deletion(
                            staged_path,
                            primary_path,
                            identity,
                        )
                    else:
                        _restore_unexpected_staged_entry(
                            staged_path,
                            primary_path,
                        )
                except BaseException:
                    logger.warning(
                        "Failed to restore staged upload deletion: %s",
                        primary_path,
                        exc_info=True,
                    )
            stage_lease.release()
            raise


def delete_file_safe(
    base_dir: Path,
    filename: str,
    *,
    delete_remote_copy: Callable[[str, Path, Path | None], None] | None = None,
) -> dict:
    """Delete a primary upload and only its exact owned conversion.

    Args:
        base_dir: Directory containing the file.
        filename: Name of file to delete.
        delete_remote_copy: Optional provider hook invoked while the selected
            primary is staged and its generation lease is still held.
    Returns:
        Dict with success and message.

    Raises:
        FileNotFoundError: If the file does not exist.
        PathTraversalError: If path traversal is detected.
    """
    safe_name = _normalize_existing_filename(filename)
    if safe_name != filename:
        raise PathTraversalError("Path traversal detected")
    try:
        base_dir = _validate_upload_directory(Path(base_dir))
    except UnsafeUploadPathError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise FileNotFoundError(f"File not found: {filename}") from exc
        raise
    lease = UploadNameLease.acquire(
        base_dir,
        safe_name,
        allow_legacy_posix_filename=True,
    )
    try:
        file_path = base_dir / safe_name
        try:
            file_stat = os.lstat(file_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {filename}") from None
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise UnsafeUploadPathError(f"Unsafe upload file: {safe_name}")

        identity = UploadIdentity(device=file_stat.st_dev, inode=file_stat.st_ino)
        # Capture the exact directory-entry spelling before the final race
        # check.  On case-insensitive or normalization-insensitive filesystems
        # ``safe_name`` may be only an alias, while generated companions are
        # keyed by the real published spelling.  A second scan below detects a
        # non-cooperating rename; its new spelling must not redirect companion
        # cleanup away from this initial generation.
        initial_file_path = _scan_upload_path_by_identity(base_dir, identity)
        if portable_name_coordination_key(initial_file_path.name) != portable_name_coordination_key(safe_name):
            raise UnsafeUploadPathError("Upload name changed outside the requested generation lease")
        owned_conversion = existing_conversion_path_for_upload(initial_file_path)
        companion_name = initial_file_path.name

        actual_file_path = _find_upload_path_by_identity(base_dir, identity)
        if portable_name_coordination_key(actual_file_path.name) != portable_name_coordination_key(safe_name):
            raise UnsafeUploadPathError("Upload name changed outside the requested generation lease")
        final_stat = os.lstat(actual_file_path)
        if not stat.S_ISREG(final_stat.st_mode) or final_stat.st_nlink != 1 or (final_stat.st_dev, final_stat.st_ino) != (identity.device, identity.inode):
            raise UnsafeUploadPathError("Upload is no longer an exclusive directory entry")
        staged_path, stage_lease = _stage_primary_deletion(
            base_dir,
            actual_file_path,
            identity,
            recover_on_crash=True,
            conversion_path=owned_conversion,
        )
        remote_delete_committed = False
        try:
            if delete_remote_copy is not None:
                staged_conversion = _staged_conversion_path(staged_path)
                prepare_remote_delete = getattr(delete_remote_copy, "prepare", None)
                if callable(prepare_remote_delete):
                    prepare_remote_delete(
                        companion_name,
                        staged_path,
                        staged_conversion if staged_conversion.exists() else None,
                    )
                # Once a remote mutation may begin, crash recovery must never
                # resurrect a host generation whose sandbox copies may already
                # be gone. A live, fully compensated failure clears this marker
                # in _restore_staged_deletion below.
                try:
                    _mark_staged_deletion_committed(staged_path)
                except BaseException:
                    abort_remote_delete = getattr(delete_remote_copy, "abort_prepared", None)
                    if callable(abort_remote_delete):
                        abort_remote_delete()
                    raise
                delete_remote_copy(
                    companion_name,
                    staged_path,
                    staged_conversion if staged_conversion.exists() else None,
                )
                remote_delete_committed = True
            else:
                _mark_staged_deletion_committed(staged_path)
            _discard_staged_deletion(staged_path)
        except RemoteDeletionCompensatedError:
            # Clear the irreversible phase before removing the durable remote
            # journal. A crash between these steps is recovered as a prepared,
            # never-started transaction and restores the authoritative host
            # generation.
            _clear_staged_deletion_commit(staged_path)
            abort_remote_delete = getattr(delete_remote_copy, "abort_prepared", None)
            if callable(abort_remote_delete):
                abort_remote_delete()
            _restore_staged_deletion(staged_path, actual_file_path, identity)
            raise
        except RemoteDeletionCommitRequiredError:
            # At least one remote mutation could not be rolled back.  Restoring
            # the host generation would publish a permanently split view, so
            # keep the persisted discard intent and finish locally when able.
            try:
                _mark_staged_deletion_committed(staged_path)
                _discard_staged_deletion(staged_path)
            except BaseException:
                logger.warning(
                    "Failed to finish a deletion after remote compensation failed: %s",
                    actual_file_path,
                    exc_info=True,
                )
            raise
        except BaseException:
            if remote_delete_committed:
                # The remote view already committed.  Leave the discard
                # transaction for startup recovery if cleanup still fails,
                # instead of resurrecting a host-only generation.  This also
                # handles a commit-marker write error while the process is
                # still alive.
                try:
                    _discard_staged_deletion(staged_path)
                except BaseException:
                    logger.warning(
                        "Failed to finish a deletion after the remote copy was removed: %s",
                        actual_file_path,
                        exc_info=True,
                    )
                raise
            _restore_staged_deletion(staged_path, actual_file_path, identity)
            raise
        finally:
            stage_lease.release()
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
