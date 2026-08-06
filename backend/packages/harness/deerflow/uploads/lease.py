"""Cross-process leases and inode identities for published uploads."""

import hashlib
import os
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from deerflow.uploads.errors import UnsafeUploadPathError
from deerflow.uploads.layout import ensure_upload_lock_dir

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows only
    fcntl = None  # type: ignore[assignment]
    import msvcrt


_LOCK_STRIPES = tuple(threading.Lock() for _ in range(64))


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
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)


def _unlock_file(lock_file: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    lock_file.seek(0)
    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


@dataclass(slots=True)
class UploadNameLease:
    """Exclusive thread-and-process lease for one actual upload filename."""

    uploads_dir: Path
    filename: str
    lock_path: Path
    _lock_file: BinaryIO
    _stripe: threading.Lock
    _active: bool = True
    _state_lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def acquire(cls, uploads_dir: Path, filename: str) -> "UploadNameLease":
        """Acquire the stable name lease, blocking until it is available."""
        if not filename or Path(filename).name != filename or "\\" in filename:
            raise UnsafeUploadPathError(f"Unsafe upload lease filename: {filename!r}")
        if len(filename.encode("utf-8")) > 255:
            raise UnsafeUploadPathError("Upload lease filename is too long")

        digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()
        stripe = _LOCK_STRIPES[int(digest[:2], 16) % len(_LOCK_STRIPES)]
        stripe.acquire()
        lock_file: BinaryIO | None = None
        try:
            lock_path = ensure_upload_lock_dir(Path(uploads_dir)) / f"{digest}.lock"
            lock_file = _open_lock_file(lock_path)
            _lock_file(lock_file)
            return cls(
                uploads_dir=Path(uploads_dir),
                filename=filename,
                lock_path=lock_path,
                _lock_file=lock_file,
                _stripe=stripe,
            )
        except BaseException:
            if lock_file is not None:
                lock_file.close()
            stripe.release()
            raise

    @property
    def is_active(self) -> bool:
        """Return whether this object still owns the name lease."""
        with self._state_lock:
            return self._active

    def release(self) -> None:
        """Release the OS lock and process stripe; repeated calls are harmless."""
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
                self._stripe.release()
            if error is not None:
                raise error

    def __enter__(self) -> "UploadNameLease":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
