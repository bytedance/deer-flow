"""Shared upload management logic.

Pure business logic — no FastAPI/HTTP dependencies.
Both Gateway and Client delegate to these functions.
"""

import errno
import logging
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.layout import artifact_url_for_virtual_path, upload_virtual_path
from deerflow.utils.thread_id import validate_thread_id


class PathTraversalError(ValueError):
    """Raised when a path escapes its allowed base directory."""


class UnsafeUploadPathError(ValueError):
    """Raised when an upload destination is not a safe regular file path."""


class AtomicUploadPublishError(UnsafeUploadPathError):
    """Raised when storage cannot honor atomic no-replace publication."""


logger = logging.getLogger(__name__)

UPLOAD_STAGING_PREFIX = ".upload-"
UPLOAD_STAGING_SUFFIX = ".part"


@dataclass(slots=True)
class StagedUpload:
    """A complete-or-in-progress upload stored under a hidden temporary name."""

    base_dir: Path
    path: Path
    handle: BinaryIO


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
    if len(safe.encode("utf-8")) > 255:
        raise ValueError(f"Filename too long: {len(safe)} chars")
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
    fd, temp_path_str = tempfile.mkstemp(
        prefix=UPLOAD_STAGING_PREFIX,
        suffix=UPLOAD_STAGING_SUFFIX,
        dir=base_dir,
    )
    temp_path = Path(temp_path_str)
    try:
        handle = os.fdopen(fd, "wb")
    except Exception:
        os.close(fd)
        temp_path.unlink(missing_ok=True)
        raise
    return StagedUpload(base_dir=base_dir, path=temp_path, handle=handle)


def abort_staged_upload(staged: StagedUpload) -> None:
    """Close and remove a staging file, tolerating repeated cleanup."""
    if not staged.handle.closed:
        staged.handle.close()
    staged.path.unlink(missing_ok=True)


def _validate_staged_upload(staged: StagedUpload) -> None:
    """Reject a staging path that was replaced or moved outside its directory."""
    _validate_upload_directory(staged.base_dir)
    if staged.path.parent.resolve() != staged.base_dir.resolve():
        raise UnsafeUploadPathError("Upload staging path escaped its directory")
    try:
        staged_stat = os.lstat(staged.path)
    except FileNotFoundError as exc:
        raise UnsafeUploadPathError("Upload staging file disappeared") from exc
    if not stat.S_ISREG(staged_stat.st_mode) or staged_stat.st_nlink != 1:
        raise UnsafeUploadPathError("Upload staging path is not an exclusive regular file")


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


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


def publish_staged_upload(staged: StagedUpload, preferred_filename: str) -> Path:
    """Atomically publish a complete staging file without replacing an entry."""
    safe_name = normalize_filename(preferred_filename)
    if not staged.handle.closed:
        staged.handle.close()
    try:
        _validate_staged_upload(staged)
        for candidate_name in _filename_candidates(safe_name):
            candidate = staged.base_dir / candidate_name
            try:
                os.link(staged.path, candidate, follow_symlinks=False)
            except FileExistsError:
                continue
            except (NotImplementedError, TypeError) as exc:
                raise AtomicUploadPublishError("Storage does not support atomic no-replace publication") from exc
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    continue
                raise AtomicUploadPublishError(f"Storage does not support atomic no-replace publication: {exc}") from exc

            try:
                staged.path.unlink()
            except OSError:
                logger.warning("Failed to remove published upload staging link: %s", staged.path, exc_info=True)
            return candidate
    except Exception:
        staged.path.unlink(missing_ok=True)
        raise


def publish_upload_bytes(base_dir: Path, preferred_filename: str, data: bytes) -> Path:
    """Stage and atomically publish an in-memory upload payload."""
    staged = create_upload_staging_file(base_dir)
    try:
        staged.handle.write(data)
        return publish_staged_upload(staged, preferred_filename)
    except Exception:
        abort_staged_upload(staged)
        raise


def publish_upload_copy(base_dir: Path, preferred_filename: str, source_path: Path) -> Path:
    """Copy a local source into staging and atomically publish it."""
    staged = create_upload_staging_file(base_dir)
    try:
        with Path(source_path).open("rb") as source:
            shutil.copyfileobj(source, staged.handle)
        return publish_staged_upload(staged, preferred_filename)
    except Exception:
        abort_staged_upload(staged)
        raise


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


def _iter_upload_dirs(base_dir: Path):
    yield from base_dir.glob("threads/*/user-data/uploads")
    yield from base_dir.glob("users/*/threads/*/user-data/uploads")


def cleanup_stale_upload_staging_files(base_dir: Path | str | None = None) -> int:
    """Remove orphaned Gateway upload staging files left by a hard crash."""
    root = Path(base_dir) if base_dir is not None else get_paths().base_dir
    removed = 0
    for uploads_dir in _iter_upload_dirs(root):
        if not uploads_dir.is_dir():
            continue
        try:
            with os.scandir(uploads_dir) as entries:
                for entry in entries:
                    if not is_upload_staging_file(entry.name) or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        os.unlink(entry.path)
                        removed += 1
                    except FileNotFoundError:
                        pass
                    except OSError:
                        logger.warning("Failed to remove stale upload staging file: %s", entry.path, exc_info=True)
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


def delete_file_safe(base_dir: Path, filename: str, *, convertible_extensions: set[str] | None = None) -> dict:
    """Delete a file inside *base_dir* after path-traversal validation.

    If *convertible_extensions* is provided and the file's extension matches,
    the companion ``.md`` file is also removed (if it exists).

    Args:
        base_dir: Directory containing the file.
        filename: Name of file to delete.
        convertible_extensions: Lowercase extensions (e.g. ``{".pdf", ".docx"}``)
            whose companion markdown should be cleaned up.

    Returns:
        Dict with success and message.

    Raises:
        FileNotFoundError: If the file does not exist.
        PathTraversalError: If path traversal is detected.
    """
    file_path = (base_dir / filename).resolve()
    validate_path_traversal(file_path, base_dir)

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")

    file_path.unlink()

    # Clean up companion markdown generated during upload conversion.
    if convertible_extensions and file_path.suffix.lower() in convertible_extensions:
        file_path.with_suffix(".md").unlink(missing_ok=True)

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
