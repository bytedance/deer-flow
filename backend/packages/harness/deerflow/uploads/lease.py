"""Cross-process leases and inode identities for published uploads."""

import errno
import hashlib
import logging
import os
import stat
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from deerflow.uploads.errors import UnsafeUploadPathError
from deerflow.uploads.layout import UPLOAD_CONVERSIONS_DIRNAME, ensure_upload_lock_dir, ensure_upload_stage_lock_dir

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows only
    fcntl = None  # type: ignore[assignment]
    import msvcrt

logger = logging.getLogger(__name__)


_THREAD_LOCKS_GUARD = threading.Lock()


@dataclass(slots=True)
class _ThreadLockEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    references: int = 0


_THREAD_LOCKS: dict[tuple[int, int, str], _ThreadLockEntry] = {}


def portable_name_coordination_key(filename: str) -> str:
    """Collapse portable filesystem case and Unicode aliases for lease locking."""
    return unicodedata.normalize("NFC", filename).casefold().rstrip(" .")


def _acquire_thread_lock(uploads_dir: Path, filename: str) -> tuple[tuple[int, int, str], _ThreadLockEntry]:
    directory_stat = os.lstat(uploads_dir)
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise UnsafeUploadPathError("Unsafe upload lease directory")
    key = (directory_stat.st_dev, directory_stat.st_ino, filename)
    with _THREAD_LOCKS_GUARD:
        entry = _THREAD_LOCKS.get(key)
        if entry is None:
            entry = _ThreadLockEntry()
            _THREAD_LOCKS[key] = entry
        entry.references += 1
    try:
        entry.lock.acquire()
    except BaseException:
        with _THREAD_LOCKS_GUARD:
            entry.references -= 1
            if entry.references == 0 and _THREAD_LOCKS.get(key) is entry:
                del _THREAD_LOCKS[key]
        raise
    return key, entry


def _try_acquire_thread_lock(
    uploads_dir: Path,
    filename: str,
) -> tuple[tuple[int, int, str], _ThreadLockEntry] | None:
    directory_stat = os.lstat(uploads_dir)
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        raise UnsafeUploadPathError("Unsafe upload lease directory")
    key = (directory_stat.st_dev, directory_stat.st_ino, filename)
    with _THREAD_LOCKS_GUARD:
        entry = _THREAD_LOCKS.get(key)
        if entry is None:
            entry = _ThreadLockEntry()
            _THREAD_LOCKS[key] = entry
        entry.references += 1
    if entry.lock.acquire(blocking=False):
        return key, entry
    with _THREAD_LOCKS_GUARD:
        entry.references -= 1
        if entry.references == 0 and _THREAD_LOCKS.get(key) is entry:
            del _THREAD_LOCKS[key]
    return None


def _release_thread_lock(key: tuple[int, int, str], entry: _ThreadLockEntry) -> None:
    entry.lock.release()
    with _THREAD_LOCKS_GUARD:
        entry.references -= 1
        if entry.references == 0 and _THREAD_LOCKS.get(key) is entry:
            del _THREAD_LOCKS[key]


@dataclass(frozen=True, slots=True)
class UploadIdentity:
    """Filesystem identity of one published upload generation."""

    device: int
    inode: int

    @classmethod
    def from_path(cls, path: Path) -> "UploadIdentity":
        upload_stat = os.lstat(path)
        if not stat.S_ISREG(upload_stat.st_mode):
            raise UnsafeUploadPathError("Published upload is not a regular file")
        return cls(device=upload_stat.st_dev, inode=upload_stat.st_ino)

    def matches(self, path: Path) -> bool:
        """Return whether *path* still names this generation."""
        try:
            upload_stat = os.lstat(path)
        except FileNotFoundError:
            return False
        return stat.S_ISREG(upload_stat.st_mode) and (upload_stat.st_dev, upload_stat.st_ino) == (
            self.device,
            self.inode,
        )


def _open_lock_file(lock_path: Path) -> BinaryIO:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(lock_path)
        if not stat.S_ISREG(descriptor_stat.st_mode) or descriptor_stat.st_nlink != 1 or not stat.S_ISREG(path_stat.st_mode) or (descriptor_stat.st_dev, descriptor_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise UnsafeUploadPathError("Unsafe upload lock file")
        if descriptor_stat.st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        return os.fdopen(fd, "r+b", buffering=0)
    except BaseException:
        os.close(fd)
        raise


def _lock_file(lock_file: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return
    while True:
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            time.sleep(0.05)


def _unlock_file(lock_file: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _try_lock_file(lock_file: BinaryIO) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise
        return True
    lock_file.seek(0)
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return False
        raise
    return True


def _stage_uploads_dir(stage_dir: Path) -> Path:
    if stage_dir.name == UPLOAD_CONVERSIONS_DIRNAME:
        return stage_dir.parent / "uploads"
    return stage_dir


def _stage_lock_path(stage_dir: Path, stage_filename: str) -> Path:
    digest = hashlib.sha256(f"{stage_dir.name}\0{stage_filename}".encode()).hexdigest()
    return ensure_upload_stage_lock_dir(_stage_uploads_dir(stage_dir)) / f"{digest}.lock"


@dataclass(slots=True)
class UploadStageLease:
    """Cross-process liveness lease for one hidden upload staging file."""

    stage_dir: Path
    stage_filename: str
    lock_path: Path
    _lock_file: BinaryIO
    _identity: UploadIdentity
    _active: bool = True
    _state_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def acquire(cls, stage_dir: Path, stage_filename: str) -> "UploadStageLease":
        lock_path = _stage_lock_path(Path(stage_dir), stage_filename)
        lock_file = _open_lock_file(lock_path)
        try:
            _lock_file(lock_file)
            return cls(
                stage_dir=Path(stage_dir),
                stage_filename=stage_filename,
                lock_path=lock_path,
                _lock_file=lock_file,
                _identity=UploadIdentity.from_path(lock_path),
            )
        except BaseException:
            lock_file.close()
            raise

    @classmethod
    def try_acquire(cls, stage_dir: Path, stage_filename: str) -> "UploadStageLease | None":
        lock_path = _stage_lock_path(Path(stage_dir), stage_filename)
        lock_file = _open_lock_file(lock_path)
        try:
            if not _try_lock_file(lock_file):
                lock_file.close()
                return None
            return cls(
                stage_dir=Path(stage_dir),
                stage_filename=stage_filename,
                lock_path=lock_path,
                _lock_file=lock_file,
                _identity=UploadIdentity.from_path(lock_path),
            )
        except BaseException:
            lock_file.close()
            raise

    @property
    def is_active(self) -> bool:
        with self._state_lock:
            return self._active

    def _remove_matching_lock_file(self) -> None:
        try:
            if self._identity.matches(self.lock_path):
                self.lock_path.unlink(missing_ok=True)
        except BaseException:
            logger.warning("Failed to remove upload stage liveness file: %s", self.lock_path, exc_info=True)

    def release(self) -> None:
        with self._state_lock:
            if not self._active:
                return
            if fcntl is not None:
                self._remove_matching_lock_file()
            try:
                _unlock_file(self._lock_file)
            except BaseException:
                logger.warning("Failed to unlock upload stage liveness file: %s", self.lock_path, exc_info=True)
            try:
                self._lock_file.close()
            except BaseException:
                logger.warning("Failed to close upload stage liveness file: %s", self.lock_path, exc_info=True)
            finally:
                self._active = False
            if fcntl is None:
                self._remove_matching_lock_file()


@dataclass(slots=True)
class UploadNameLease:
    """Exclusive thread-and-process lease for one actual upload filename."""

    uploads_dir: Path
    filename: str
    lock_path: Path
    _lock_file: BinaryIO
    _thread_lock_key: tuple[int, int, str]
    _thread_lock_entry: _ThreadLockEntry
    _active: bool = True
    _state_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def acquire(
        cls,
        uploads_dir: Path,
        filename: str,
        *,
        allow_legacy_posix_filename: bool = False,
    ) -> "UploadNameLease":
        """Acquire the stable name lease, blocking until it is available."""
        uploads_dir, coordination_key, digest = cls._validate_request(
            uploads_dir,
            filename,
            allow_legacy_posix_filename=allow_legacy_posix_filename,
        )
        thread_lock_key, thread_lock_entry = _acquire_thread_lock(uploads_dir, coordination_key)
        lock_file: BinaryIO | None = None
        try:
            lock_path = ensure_upload_lock_dir(uploads_dir) / f"{digest}.lock"
            lock_file = _open_lock_file(lock_path)
            _lock_file(lock_file)
            return cls(
                uploads_dir=uploads_dir,
                filename=filename,
                lock_path=lock_path,
                _lock_file=lock_file,
                _thread_lock_key=thread_lock_key,
                _thread_lock_entry=thread_lock_entry,
            )
        except BaseException:
            if lock_file is not None:
                lock_file.close()
            _release_thread_lock(thread_lock_key, thread_lock_entry)
            raise

    @classmethod
    def try_acquire(
        cls,
        uploads_dir: Path,
        filename: str,
        *,
        allow_legacy_posix_filename: bool = False,
    ) -> "UploadNameLease | None":
        """Acquire a name lease without waiting, or return ``None`` when busy."""
        uploads_dir, coordination_key, digest = cls._validate_request(
            uploads_dir,
            filename,
            allow_legacy_posix_filename=allow_legacy_posix_filename,
        )
        thread_lock = _try_acquire_thread_lock(uploads_dir, coordination_key)
        if thread_lock is None:
            return None
        thread_lock_key, thread_lock_entry = thread_lock
        thread_lock_owned = True
        lock_file: BinaryIO | None = None
        try:
            lock_path = ensure_upload_lock_dir(uploads_dir) / f"{digest}.lock"
            lock_file = _open_lock_file(lock_path)
            if not _try_lock_file(lock_file):
                lock_file.close()
                lock_file = None
                _release_thread_lock(thread_lock_key, thread_lock_entry)
                thread_lock_owned = False
                return None
            return cls(
                uploads_dir=uploads_dir,
                filename=filename,
                lock_path=lock_path,
                _lock_file=lock_file,
                _thread_lock_key=thread_lock_key,
                _thread_lock_entry=thread_lock_entry,
            )
        except BaseException:
            if lock_file is not None and not lock_file.closed:
                lock_file.close()
            if thread_lock_owned:
                _release_thread_lock(thread_lock_key, thread_lock_entry)
            raise

    @staticmethod
    def _validate_request(
        uploads_dir: Path,
        filename: str,
        *,
        allow_legacy_posix_filename: bool = False,
    ) -> tuple[Path, str, str]:
        allow_legacy = allow_legacy_posix_filename and os.name != "nt"
        if not filename or Path(filename).name != filename or ("\\" in filename and not allow_legacy):
            raise UnsafeUploadPathError(f"Unsafe upload lease filename: {filename!r}")
        if len(filename.encode("utf-8")) > 255:
            raise UnsafeUploadPathError("Upload lease filename is too long")
        uploads_dir = Path(uploads_dir)
        coordination_key = portable_name_coordination_key(filename)
        if not coordination_key:
            if not allow_legacy:
                raise UnsafeUploadPathError(f"Unsafe upload lease filename: {filename!r}")
            # New uploads reject components made entirely from Win32-ignored
            # dots/spaces. Existing POSIX entries still need a stable, distinct
            # lock key so they can be deleted after upgrade.
            coordination_key = f"legacy-posix:{unicodedata.normalize('NFC', filename).casefold()}"
        digest = hashlib.sha256(coordination_key.encode("utf-8")).hexdigest()
        return uploads_dir, coordination_key, digest

    @property
    def is_active(self) -> bool:
        """Return whether this object still owns the name lease."""
        with self._state_lock:
            return self._active

    def release(self) -> None:
        """Release the OS and exact-name thread locks; repeated calls are harmless."""
        with self._state_lock:
            if not self._active:
                return
            error: BaseException | None = None
            try:
                _unlock_file(self._lock_file)
            except BaseException as exc:  # pragma: no cover - exceptional OS failure
                error = exc
            try:
                self._lock_file.close()
            except BaseException as exc:  # pragma: no cover - exceptional OS failure
                if error is None:
                    error = exc
            finally:
                self._active = False
                _release_thread_lock(self._thread_lock_key, self._thread_lock_entry)
            if error is not None:
                raise error

    def __enter__(self) -> "UploadNameLease":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
