"""Release-time mirroring of sandbox artifacts back to host thread directories.

DeerFlow resolves ``/api/threads/{tid}/artifacts/...`` and the run worker's
delivery scan against the host-side per-thread ``user-data/`` tree (see
:meth:`deerflow.config.paths.Paths.sandbox_outputs_dir`). Providers that bind-
mount that tree (``uses_thread_data_mounts=True``) get this for free. Providers
without a shared host filesystem (E2B, BoxLite, ...) must copy artifacts back
explicitly before a turn completes, which happens inside
:meth:`SandboxProvider.release` because :class:`SandboxMiddleware` releases the
sandbox in ``after_agent`` — before the worker inspects the host outputs tree.

This module holds the provider-agnostic core of that copy: parsing a remote
listing, deciding which files changed since the last pass, enforcing aggregate
resource ceilings, writing files atomically on the host, and persisting a
per-thread manifest so unchanged files are not re-downloaded. Providers supply
only the listing and a ``download`` callable.

Listing record format (NUL-separated, one file per record)::

    <size-bytes>\\t<mtime-seconds[.fraction]>\\t<absolute-remote-path>\\0

which the GNU ``find -printf`` producer or the BusyBox
``find -exec sh``/``stat``/``printf`` fallback emit.
"""

from __future__ import annotations

import base64
import errno
import json
import logging
import os
import secrets
import shlex
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from deerflow.config.paths import VIRTUAL_PATH_PREFIX

logger = logging.getLogger(__name__)

#: Sub-trees of ``/mnt/user-data`` that flow from the sandbox back to the host.
#: ``uploads`` is deliberately absent: it flows host -> sandbox only.
SYNC_BACK_SUBDIRS: tuple[str, ...] = ("outputs", "workspace")

_MANIFEST_VERSION = 1
_MANIFEST_FIELDS = ("remote_size", "remote_mtime_ns", "host_size", "host_mtime_ns")
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
LISTING_COMPLETE_SENTINEL = "__DEERFLOW_OUTPUT_SYNC_LISTING_COMPLETE_6A92D7D1__"
_BOUNDED_READ_OK = "__DEERFLOW_BOUNDED_READ_OK_8F3B1D42__"
_BOUNDED_READ_EFBIG = "__DEERFLOW_BOUNDED_READ_EFBIG_8F3B1D42__"
_BOUNDED_READ_ERROR = "__DEERFLOW_BOUNDED_READ_ERROR_8F3B1D42__"
_BOUNDED_READ_COMPLETE = "__DEERFLOW_BOUNDED_READ_COMPLETE_8F3B1D42__"
_SECURE_BOUNDED_READ_SCRIPT = f"""\
import base64
import errno
import os
import stat
import sys

root, relative_path, raw_limit = sys.argv[1:]
fd = -1
try:
    limit = int(raw_limit)
    parts = relative_path.split("/")
    if limit < 0 or not relative_path or any(part in ("", ".", "..") for part in parts):
        raise OSError(errno.EPERM, "unsafe relative path")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(root, flags | os.O_DIRECTORY)
    for index, part in enumerate(parts):
        next_flags = flags if index == len(parts) - 1 else flags | os.O_DIRECTORY
        next_fd = os.open(part, next_flags, dir_fd=fd)
        os.close(fd)
        fd = next_fd
    file_stat = os.fstat(fd)
    if not stat.S_ISREG(file_stat.st_mode):
        raise OSError(errno.EPERM, "artifact is not a regular file")
    if file_stat.st_size > limit:
        raise OSError(errno.EFBIG, "artifact exceeds byte allowance")
    remaining = file_stat.st_size
    chunks = []
    while remaining:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = base64.b64encode(b"".join(chunks)).decode("ascii")
    sys.stdout.write({_BOUNDED_READ_OK!r} + "\\n" + payload + "\\n" + {_BOUNDED_READ_COMPLETE!r})
except OSError as exc:
    marker = {_BOUNDED_READ_EFBIG!r} if exc.errno == errno.EFBIG else {_BOUNDED_READ_ERROR!r}
    sys.stdout.write(marker + "\\n" + str(exc))
finally:
    if fd >= 0:
        os.close(fd)
"""


@dataclass(frozen=True)
class OutputSyncLimits:
    """Resource ceilings for one sync pass.

    ``max_file_bytes`` bounds a single artifact. ``max_total_bytes`` and
    ``max_files`` bound downloads. ``max_listing_bytes`` and
    ``max_listing_files`` independently bound the untrusted remote inventory
    before any download starts. ``deadline_seconds`` covers both listing and
    downloads when providers pass the same absolute deadline into the core.

    When a pass-level ceiling is hit the pass stops early, logs what it dropped,
    and leaves the manifest un-pruned so files it never reached are not mistaken
    for guest deletions.
    """

    max_file_bytes: int
    max_total_bytes: int
    max_files: int
    deadline_seconds: float
    max_listing_bytes: int = 8 * 1024 * 1024
    max_listing_files: int = 20_000


@dataclass
class OutputSyncResult:
    synced: int = 0
    skipped: int = 0
    downloaded_files: int = 0
    downloaded_bytes: int = 0
    truncated_reason: str | None = None


def _require_secure_dir_fd_support() -> None:
    required = (os.open, os.mkdir, os.stat, os.unlink)
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or any(fn not in os.supports_dir_fd for fn in required):
        raise OSError(errno.ENOTSUP, "race-safe output sync requires POSIX directory-fd and O_NOFOLLOW support")


@contextmanager
def _safe_host_directory_fd(base_dir: Path, directory: Path) -> Iterator[int]:
    """Open/create ``directory`` beneath a trusted base without path re-resolution.

    Every component is opened relative to the already-verified parent directory
    descriptor with ``O_NOFOLLOW``. A concurrent symlink swap therefore cannot
    redirect later reads, writes, replacements, or deletions outside the state
    root.
    """
    _require_secure_dir_fd_support()
    base_dir.mkdir(parents=True, exist_ok=True)
    try:
        relative = directory.absolute().relative_to(base_dir.absolute())
    except ValueError as exc:
        raise PermissionError(f"host output path escapes configured base directory: {directory}") from exc

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current_fd = os.open(base_dir, directory_flags)
    try:
        for segment in relative.parts:
            try:
                os.mkdir(segment, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(segment, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        yield current_fd
    finally:
        os.close(current_fd)


def _ensure_safe_host_directory(base_dir: Path, directory: Path) -> None:
    with _safe_host_directory_fd(base_dir, directory):
        pass


def _safe_host_lstat(base_dir: Path, path: Path) -> os.stat_result:
    with _safe_host_directory_fd(base_dir, path.parent) as parent_fd:
        return os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)


def _atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    host_base_dir: Path,
    mtime_ns: int | None = None,
) -> os.stat_result:
    """Atomically replace ``path`` through its verified parent directory fd."""
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.sync.tmp"
    with _safe_host_directory_fd(host_base_dir, path.parent) as parent_fd:
        file_fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            file_fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
            with os.fdopen(file_fd, "wb") as temporary:
                file_fd = None
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            if mtime_ns is not None:
                try:
                    os.utime(
                        temporary_name,
                        ns=(mtime_ns, mtime_ns),
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except (OSError, OverflowError):
                    logger.debug("Skipped mtime restoration for %s (ns=%d)", path, mtime_ns)
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temporary_name = ""
            return os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if temporary_name:
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass


def _safe_unlink_host_file(base_dir: Path, path: Path) -> bool:
    """Unlink a regular file or symlink through a verified parent descriptor."""
    with _safe_host_directory_fd(base_dir, path.parent) as parent_fd:
        try:
            mode = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return False
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            raise OSError(errno.EPERM, "refusing to delete non-file output-sync path", path)
        os.unlink(path.name, dir_fd=parent_fd)
        return True


def load_sync_manifest(
    manifest_path: Path,
    sandbox_id: str,
    *,
    host_base_dir: Path,
    log_prefix: str,
) -> tuple[dict[str, dict[str, int]], bool]:
    """Load verified remote and host versions from a prior output sync.

    Returns ``(files, dirty)``; ``dirty`` is True when the on-disk manifest is
    unusable (corrupt, wrong version, or written by another sandbox) and should
    be rewritten even if nothing changes.
    """
    try:
        with _safe_host_directory_fd(host_base_dir, manifest_path.parent) as parent_fd:
            file_fd = os.open(manifest_path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            with os.fdopen(file_fd, "rb") as manifest_file:
                raw = manifest_file.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise OSError(errno.EFBIG, "output-sync manifest exceeds size cap", manifest_path)
        data = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return {}, False
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning("%s: failed to load manifest %s: %s", log_prefix, manifest_path, e)
        return {}, True

    if not isinstance(data, dict) or data.get("version") != _MANIFEST_VERSION or not isinstance(data.get("files"), dict):
        logger.warning("%s: ignoring invalid manifest %s", log_prefix, manifest_path)
        return {}, True
    if data.get("sandbox_id") != sandbox_id:
        logger.debug("%s: ignoring manifest from another sandbox %s", log_prefix, manifest_path)
        return {}, True

    files: dict[str, dict[str, int]] = {}
    for key, value in data["files"].items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        if all(isinstance(value.get(field), int) for field in _MANIFEST_FIELDS):
            files[key] = {field: value[field] for field in _MANIFEST_FIELDS}
    return files, False


def write_sync_manifest(
    manifest_path: Path,
    sandbox_id: str,
    files: dict[str, dict[str, int]],
    *,
    host_base_dir: Path,
    log_prefix: str,
) -> None:
    """Atomically store output-sync versions after host files are written."""
    try:
        _ensure_safe_host_directory(host_base_dir, manifest_path.parent)
        payload = json.dumps(
            {
                "version": _MANIFEST_VERSION,
                "sandbox_id": sandbox_id,
                "files": files,
            },
            sort_keys=True,
        )
        _atomic_write_bytes(
            manifest_path,
            payload.encode(),
            host_base_dir=host_base_dir,
        )
    except OSError as e:
        logger.warning("%s: failed to write manifest %s: %s", log_prefix, manifest_path, e)


def _safe_relative_path(rel: str) -> str | None:
    """Return ``rel`` when it is a plain relative POSIX path that stays inside its root.

    The remote listing is untrusted input (the agent controls the sandbox
    filesystem), so every segment is checked lexically: no absolute paths, no
    ``.``/``..``/empty segments, and no backslashes (a path separator on
    Windows hosts, where ``Path`` would honour it).
    """
    if not rel or rel.startswith("/") or "\\" in rel:
        return None
    if any(segment in ("", ".", "..") for segment in rel.split("/")):
        return None
    return rel


def build_secure_bounded_read_command(remote_root: str, relative_path: str, max_bytes: int) -> str:
    """Build a race-safe, exact-cap remote file read command.

    The command walks every path component with ``openat`` and ``O_NOFOLLOW``,
    then reads at most the size observed from the already-open regular-file
    descriptor. It therefore cannot escape through a symlink swap or consume
    even one artifact byte beyond ``max_bytes``.
    """
    if not remote_root.startswith("/") or "\x00" in remote_root:
        raise ValueError("remote_root must be an absolute path without NUL bytes")
    safe_relative = _safe_relative_path(relative_path)
    if safe_relative is None:
        raise ValueError(f"unsafe relative artifact path: {relative_path!r}")
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    return " ".join(
        (
            "python3 -c",
            shlex.quote(_SECURE_BOUNDED_READ_SCRIPT),
            shlex.quote(remote_root.rstrip("/") or "/"),
            shlex.quote(safe_relative),
            str(max_bytes),
        )
    )


def parse_secure_bounded_read_output(output: str, *, path: str) -> bytes:
    """Parse :func:`build_secure_bounded_read_command` output."""
    status, separator, payload = output.partition("\n")
    if not separator:
        raise OSError(errno.EIO, f"bounded read for {path!r} returned no status marker")
    if status == _BOUNDED_READ_EFBIG:
        raise OSError(errno.EFBIG, "File exceeds maximum download size", path)
    if status == _BOUNDED_READ_ERROR:
        detail = payload.strip() or "unknown error"
        raise OSError(errno.EIO, f"secure bounded read failed for {path!r}: {detail}")
    if status != _BOUNDED_READ_OK:
        raise OSError(errno.EIO, f"bounded read for {path!r} returned an invalid status marker")
    encoded, completion_separator, completion = payload.rpartition("\n")
    if not completion_separator or completion != _BOUNDED_READ_COMPLETE:
        raise OSError(errno.EIO, f"bounded read for {path!r} returned an incomplete payload")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise OSError(errno.EIO, f"bounded read for {path!r} returned invalid base64") from exc


def build_bounded_listing_command(
    targets: tuple[str, ...],
    limits: OutputSyncLimits,
    *,
    busybox_stat_fallback: bool,
) -> str:
    """Build a shell inventory command bounded before stdout reaches the host.

    GNU ``head -z`` terminates the producer after ``max_listing_files + 1``
    complete NUL records. Minimal images without ``head -z`` still get the hard
    byte cap and the provider-level command timeout; the shared parser enforces
    the record cap without allocating a split list.
    """
    if not targets:
        return ":"
    if limits.max_listing_bytes <= 0 or limits.max_listing_files <= 0:
        raise ValueError("output-sync listing limits must be positive")

    quoted_targets = " ".join(shlex.quote(target) for target in targets)
    if busybox_stat_fallback:
        producer = (
            "status=0; "
            f"for d in {quoted_targets}; do "
            'if [ ! -d "$d" ]; then status=1; continue; fi; '
            "if find \"$d\" -type f -printf '%s\\t%T@\\t%p\\0' 2>/dev/null; then :; "
            'elif ! find "$d" -type f -exec sh -c \''
            "for p do "
            'size=$(stat -c %s -- "$p") || exit 1; '
            'mtime=$(stat -c %Y -- "$p") || exit 1; '
            'printf "%s\\t%s\\t%s\\0" "$size" "$mtime" "$p" || exit 1; '
            "done' sh {} + 2>/dev/null; then status=1; fi; "
            'done; exit "$status"'
        )
    else:
        producer = f'status=0; for d in {quoted_targets}; do if [ ! -d "$d" ]; then status=1; continue; fi; find "$d" -type f -printf \'%s\\t%T@\\t%p\\0\' 2>/dev/null || status=1; done; exit "$status"'

    record_cap = limits.max_listing_files + 1
    completion_frame_bytes = len(LISTING_COMPLETE_SENTINEL.encode("ascii")) + 1
    byte_cap = limits.max_listing_bytes + completion_frame_bytes
    return f"( ( {producer} ) && printf '%s\\0' {shlex.quote(LISTING_COMPLETE_SENTINEL)} ) | {{ if head -z -n 1 </dev/null >/dev/null 2>&1; then head -z -n {record_cap}; else cat; fi; }} | head -c {byte_cap}"


def parse_bounded_listing_output(listing: str) -> tuple[str, bool]:
    """Remove the producer-completion frame and report a complete inventory.

    The marker is emitted only when every target scan succeeds. The shell byte
    cap cannot retain a complete marker after truncation. On platforms without
    ``head -z`` support, the shared parser enforces the record cap separately.
    Either a missing marker or a parser-level truncation makes the inventory
    read-only: files may still be mirrored, but absent manifest entries cannot
    authorize host deletion.
    """
    completion_frame = f"{LISTING_COMPLETE_SENTINEL}\0"
    if not listing.endswith(completion_frame):
        return listing, False
    return listing[: -len(completion_frame)], True


def _iter_nul_records(listing: str) -> Iterator[tuple[str, bool]]:
    """Yield records without allocating ``listing.split('\\0')``.

    The boolean marks whether the record ended in NUL. A final unterminated
    record means the producer hit its byte cap and must never authorize pruning.
    """
    start = 0
    while start < len(listing):
        end = listing.find("\0", start)
        if end < 0:
            yield listing[start:], False
            return
        yield listing[start:end], True
        start = end + 1


def sync_listing_to_host(
    listing: str,
    *,
    remote_root: str,
    thread_id: str,
    user_id: str | None,
    sandbox_id: str,
    manifest_name: str,
    download: Callable[[str, int, float], bytes],
    limits: OutputSyncLimits,
    subdirs: tuple[str, ...] = SYNC_BACK_SUBDIRS,
    log_prefix: str = "sandbox sync",
    deadline: float | None = None,
    listing_complete: bool = False,
) -> OutputSyncResult:
    """Mirror the files in ``listing`` into the host thread directory.

    Args:
        listing: NUL-separated ``size\\tmtime\\tpath`` records (see module doc).
        remote_root: Remote directory that holds the ``subdirs`` (``/home/user``
            on E2B, ``/mnt/user-data`` on BoxLite). Entries outside
            ``{remote_root}/{subdir}/`` are ignored.
        thread_id / user_id: Host bucket to write into; both are validated by
            :meth:`Paths.thread_dir`, which raises ``ValueError`` on unsafe ids.
        sandbox_id: Remote identity recorded in the manifest so a manifest from
            a previous VM is never trusted for a new one.
        manifest_name: Per-provider manifest filename inside the thread dir.
        download: Fetches one file by its ``/mnt/user-data/...`` virtual path,
            accepting the maximum number of payload bytes this pass may still
            receive and the remaining monotonic time budget. It must enforce both
            before returning, and raise ``OSError(errno.EFBIG, ...)`` instead of
            returning too many bytes. Other exceptions are logged and skipped.
        limits: Per-file and per-pass resource ceilings.
        deadline: Absolute ``time.monotonic()`` deadline shared with the provider's
            remote listing request. Omit only when the caller has not done remote
            work before entering this function.
        listing_complete: False when the provider knows its inventory was cut
            short. Incomplete listings never authorize host deletions.

    The remote file is the source of truth: a host-side edit is overwritten on
    the next pass when its size or modification time differs. Files whose
    manifest entry still matches both the remote and host metadata are skipped
    without a download, which keeps repeated releases cheap.

    Host writes go through a sibling temp file and ``os.replace`` so a reader
    never observes a partially written artifact.
    """
    from deerflow.config.paths import get_paths  # lazy import to avoid cycles

    paths = get_paths()
    thread_dir = paths.thread_dir(thread_id, user_id=user_id)
    thread_root = thread_dir / "user-data"
    manifest_path = thread_dir / manifest_name
    result = OutputSyncResult()
    if deadline is None:
        deadline = time.monotonic() + limits.deadline_seconds
    if not listing_complete:
        result.truncated_reason = "incomplete remote listing"

    encoded_listing = listing.encode("utf-8", errors="surrogatepass")
    if len(encoded_listing) > limits.max_listing_bytes:
        listing = encoded_listing[: limits.max_listing_bytes].decode("utf-8", errors="ignore")
        listing_complete = False
        result.truncated_reason = f"listing byte cap {limits.max_listing_bytes}"

    try:
        _ensure_safe_host_directory(paths.base_dir, thread_dir)
    except OSError as e:
        logger.warning("%s: unsafe host thread directory %s: %s", log_prefix, thread_dir, e)
        result.truncated_reason = "unsafe host thread directory"
        return result
    manifest, manifest_dirty = load_sync_manifest(
        manifest_path,
        sandbox_id,
        host_base_dir=paths.base_dir,
        log_prefix=log_prefix,
    )

    remote_root = remote_root.rstrip("/")
    seen_manifest_keys: set[str] = set()
    listing_records = 0

    def mark_listing_incomplete(reason: str) -> None:
        nonlocal listing_complete
        listing_complete = False
        if result.truncated_reason is None:
            result.truncated_reason = reason

    for entry, terminated in _iter_nul_records(listing):
        if time.monotonic() >= deadline:
            result.truncated_reason = f"time budget {limits.deadline_seconds}s"
            listing_complete = False
            break
        if not terminated:
            result.truncated_reason = f"listing byte cap {limits.max_listing_bytes}"
            listing_complete = False
            break
        # NUL already delimits records, so do NOT strip: a filename that
        # legitimately ends in whitespace (e.g. "report ") would have its
        # trailing space trimmed here, pointing host_path at the wrong file and
        # recording a manifest key that never matches again.
        if not entry:
            mark_listing_incomplete("malformed remote listing")
            continue
        listing_records += 1
        if listing_records > limits.max_listing_files:
            result.truncated_reason = f"listing file cap {limits.max_listing_files}"
            listing_complete = False
            break
        try:
            size_str, remote_mtime_str, remote_path = entry.split("\t", 2)
            remote_size = int(size_str)
            remote_mtime_ns = int(Decimal(remote_mtime_str) * 1_000_000_000)
        except (InvalidOperation, ValueError):
            logger.debug("%s: unparseable entry %r", log_prefix, entry)
            mark_listing_incomplete("malformed remote listing")
            continue

        if remote_size < 0:
            logger.debug("%s: negative size in entry %r", log_prefix, entry)
            mark_listing_incomplete("malformed remote listing")
            continue

        # Map the absolute remote path onto one of the mirrored sub-trees.
        sub_match: tuple[str, str] | None = None
        for sub in subdirs:
            prefix = f"{remote_root}/{sub}/"
            if remote_path.startswith(prefix):
                sub_match = (sub, remote_path[len(prefix) :])
                break
        if sub_match is None:
            mark_listing_incomplete("out-of-contract remote listing")
            continue
        sub, rel = sub_match
        safe_rel = _safe_relative_path(rel)
        if safe_rel is None:
            logger.warning("%s: ignoring unsafe remote path %r", log_prefix, remote_path)
            mark_listing_incomplete("unsafe remote listing")
            continue
        host_path = thread_root / sub / safe_rel
        virtual_path = f"{VIRTUAL_PATH_PREFIX}/{sub}/{safe_rel}"
        manifest_key = f"{sub}/{safe_rel}"
        seen_manifest_keys.add(manifest_key)

        try:
            _ensure_safe_host_directory(paths.base_dir, host_path.parent)
        except OSError as e:
            logger.warning("%s: refusing unsafe host path %s: %s", log_prefix, host_path, e)
            result.skipped += 1
            continue

        if remote_size > limits.max_file_bytes:
            logger.warning("%s: skipping oversize artefact %s (%d bytes > %d cap)", log_prefix, remote_path, remote_size, limits.max_file_bytes)
            result.skipped += 1
            continue

        try:
            host_stat = _safe_host_lstat(paths.base_dir, host_path)
            if not stat.S_ISLNK(host_stat.st_mode) and manifest.get(manifest_key) == {
                "remote_size": remote_size,
                "remote_mtime_ns": remote_mtime_ns,
                "host_size": host_stat.st_size,
                "host_mtime_ns": host_stat.st_mtime_ns,
            }:
                result.skipped += 1
                continue
        except OSError:
            pass

        if result.downloaded_files >= limits.max_files:
            result.truncated_reason = f"file count cap {limits.max_files}"
            break
        if result.downloaded_bytes + remote_size > limits.max_total_bytes:
            result.truncated_reason = f"total byte budget {limits.max_total_bytes}"
            break

        remaining_total = limits.max_total_bytes - result.downloaded_bytes
        download_limit = min(limits.max_file_bytes, remaining_total)
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            result.truncated_reason = f"time budget {limits.deadline_seconds}s"
            listing_complete = False
            break
        try:
            data = download(virtual_path, download_limit, remaining_seconds)
        except TimeoutError:
            result.truncated_reason = f"time budget {limits.deadline_seconds}s"
            listing_complete = False
            break
        except OSError as e:
            if e.errno != errno.EFBIG:
                logger.warning("%s: failed to download %s from sandbox %s: %s", log_prefix, virtual_path, sandbox_id, e)
                continue
            if remaining_total <= limits.max_file_bytes:
                result.truncated_reason = f"total byte budget {limits.max_total_bytes}"
                break
            logger.warning(
                "%s: skipping oversize artefact %s: download exceeds per-file byte cap %d (listing reported %d)",
                log_prefix,
                remote_path,
                limits.max_file_bytes,
                remote_size,
            )
            result.skipped += 1
            continue
        except Exception as e:
            logger.warning("%s: failed to download %s from sandbox %s: %s", log_prefix, virtual_path, sandbox_id, e)
            continue
        # The listing is a pre-download snapshot and can race a growing file.
        # Enforce and account from the bytes actually returned so stale metadata
        # can never bypass either the per-file host-write cap or aggregate pass
        # budget. The bounded callback contract prevents the remote round-trip
        # from exceeding the exact remaining allowance before buffering.
        actual_size = len(data)
        result.downloaded_files += 1
        result.downloaded_bytes += actual_size
        if actual_size > download_limit:
            raise RuntimeError(f"{log_prefix}: download callback violated {download_limit}-byte allowance for {virtual_path}")
        if time.monotonic() >= deadline:
            result.truncated_reason = f"time budget {limits.deadline_seconds}s"
            listing_complete = False
            break

        try:
            host_stat = _atomic_write_bytes(
                host_path,
                data,
                host_base_dir=paths.base_dir,
                mtime_ns=remote_mtime_ns,
            )
            manifest[manifest_key] = {
                # Record the observed payload size, not the stale listing size.
                # If the remote file raced the listing, the next pass will not
                # incorrectly trust that snapshot as unchanged.
                "remote_size": actual_size,
                "remote_mtime_ns": remote_mtime_ns,
                "host_size": host_stat.st_size,
                "host_mtime_ns": host_stat.st_mtime_ns,
            }
            manifest_dirty = True
            result.synced += 1
        except OSError as e:
            logger.warning("%s: failed to write %s on host: %s", log_prefix, host_path, e)

    # A truncated pass did not observe every remote file, so
    # ``seen_manifest_keys`` is incomplete; pruning "stale" entries here would
    # forget files we simply never reached. Skip pruning and let the next
    # release reconcile them (freshly downloaded entries are still written).
    stale_keys = set(manifest) - seen_manifest_keys
    if stale_keys and listing_complete and result.truncated_reason is None:
        for key in stale_keys:
            safe_key = _safe_relative_path(key)
            if safe_key is None or safe_key.split("/", 1)[0] not in subdirs:
                logger.warning("%s: dropping unsafe manifest key %r without deleting a host path", log_prefix, key)
                manifest.pop(key)
                manifest_dirty = True
                continue
            host_path = thread_root / safe_key
            try:
                _safe_unlink_host_file(paths.base_dir, host_path)
            except OSError as e:
                logger.warning("%s: failed to remove deleted guest artifact %s: %s", log_prefix, host_path, e)
                continue
            manifest.pop(key)
            manifest_dirty = True

    if manifest_dirty:
        write_sync_manifest(
            manifest_path,
            sandbox_id,
            manifest,
            host_base_dir=paths.base_dir,
            log_prefix=log_prefix,
        )

    if result.truncated_reason is not None:
        logger.warning(
            "%s: sandbox=%s thread=%s truncated (%s); downloaded=%d files/%d bytes this pass, remaining artefacts deferred to next release",
            log_prefix,
            sandbox_id,
            thread_id,
            result.truncated_reason,
            result.downloaded_files,
            result.downloaded_bytes,
        )
    if result.synced or result.skipped:
        logger.info("%s: sandbox=%s thread=%s synced=%d skipped=%d", log_prefix, sandbox_id, thread_id, result.synced, result.skipped)
    return result
