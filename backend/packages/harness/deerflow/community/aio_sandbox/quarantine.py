"""Non-expiring quarantine records outside sandbox-visible mounts.

Like the acquire flock, these records live in the shared Gateway home. A lease
can expire or disappear; uncertainty about a running command cannot. Records
are bound to the runtime instance id, so a replacement can reuse the logical
sandbox id without inheriting the old instance's fence.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from deerflow.utils.file_lock import retry_until_locked

from .sandbox_info import SandboxInfo


@dataclass(frozen=True)
class QuarantineSnapshot:
    directory_identity: tuple[int, int] | None
    mutation_token: bytes
    records: Mapping[str, bytes]


class SandboxQuarantine:
    def __init__(self, root: Path, scope: str):
        self._root = root / self._key(scope)

    @staticmethod
    def _key(value: str) -> str:
        # Truncate to 16 hex chars (64 bits). The quarantine nests three hashed
        # components (scope, sandbox id, container id); three full 64-char
        # SHA-256 hexdigests exceed Windows' 260-char MAX_PATH when the root
        # lives under a long path, failing record creation with ENOENT. 64 bits
        # is far beyond what non-adversarial sandbox/container ids need, and
        # matches the sandbox-naming convention elsewhere in this module.
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def _directory(self, info: SandboxInfo) -> Path:
        return self._root / self._key(info.sandbox_id)

    @contextmanager
    def _mutation_lock(self, info: SandboxInfo, check: Callable[[], None] | None = None) -> Iterator[BinaryIO]:
        """Serialize receipt replacement with compare-and-delete, never runtime IO.

        Keep this sidecar outside the removable generation directory and never
        unlink it: otherwise a waiter and a new writer could lock different inodes.
        """
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self._root / f".{self._key(info.sandbox_id)}.lock").open("a+b") as lock_file:
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            if os.name == "nt":
                import msvcrt

                def acquire() -> None:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                def acquire() -> None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            retry_until_locked(acquire, check=check)
            try:
                if check is not None:
                    check()
                yield lock_file
            finally:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _exists(path: Path) -> bool:
        # Do not collapse storage/permission failures into "no quarantine".
        try:
            path.stat()
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def _records(directory: Path) -> list[Path]:
        """List the fences a teardown pass is about to drop.

        The teardown exclusion is a TTL lease, not a lock, so a peer's retire()
        can finish between the caller's existence check and this listing. Its
        records are then gone, which is the state both callers were asked to
        produce; ``contains()`` reports the same interleaving as "no fence".
        """
        try:
            return list(directory.iterdir())
        except FileNotFoundError:
            return []

    @staticmethod
    def _drop(record: Path) -> None:
        """Unlink one fence, tolerating a peer that unlinked it first."""
        try:
            record.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _receipt(record: Path) -> bytes | None:
        try:
            return record.read_bytes()
        except FileNotFoundError:
            return None

    @staticmethod
    def _directory_identity(directory: Path) -> tuple[int, int] | None:
        try:
            stat = directory.stat()
        except FileNotFoundError:
            return None
        return stat.st_dev, stat.st_ino

    @staticmethod
    def _mutation_token(lock_file: BinaryIO) -> bytes:
        lock_file.seek(1)
        return lock_file.read(16)

    def snapshot(self, info: SandboxInfo, *, check: Callable[[], None] | None = None) -> QuarantineSnapshot:
        """Capture cleanup targets before proving absence, including legacy empty records."""
        with self._mutation_lock(info, check) as lock_file:
            directory = self._directory(info)
            identity = self._directory_identity(directory)
            if check is not None:
                check()
            token = self._mutation_token(lock_file)
            records = {}
            for record in self._records(directory):
                if check is not None:
                    check()
                receipt = self._receipt(record)
                if receipt is not None:
                    records[record.name] = receipt
            if check is not None:
                check()
            return QuarantineSnapshot(identity, token, records)

    def mark(self, info: SandboxInfo) -> None:
        with self._mutation_lock(info) as lock_file:
            token = uuid.uuid4().bytes
            # Publish the directory-fence version before creating crash residue.
            # The append-mode lock handle keeps bootstrap safe; a second handle
            # overwrites only bytes beyond Windows' locked first byte. Never
            # replace/unlink this inode, and keep its token bounded to 16 bytes.
            with open(lock_file.name, "r+b") as state:
                state.seek(1)
                state.write(token)
                state.truncate(17)
                state.flush()
                os.fsync(state.fileno())
            directory = self._directory(info)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            generation = self._key(info.container_id) if info.container_id else "unknown"
            # A fresh opaque receipt distinguishes a re-mark of the same name,
            # especially "unknown", from the version an old cleanup observed.
            # Stage outside the generation directory so a crash leaves either
            # its existing fence or fail-closed empty-directory residue.
            descriptor, temporary = tempfile.mkstemp(dir=self._root, prefix=".mark-")
            try:
                with os.fdopen(descriptor, "wb") as record:
                    record.write(token)
                    record.flush()
                    os.fsync(record.fileno())
                os.replace(temporary, directory / generation)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def contains(self, info: SandboxInfo) -> bool:
        directory = self._directory(info)
        if not self._exists(directory):
            return False
        if not info.container_id:
            # Version skew must not allow discovery to forget the generation.
            return True
        if self._exists(directory / "unknown") or self._exists(directory / self._key(info.container_id)):
            return True
        # Crash residue: mark() died between mkdir and record creation, so the
        # queried generation may be the unrecorded one. Fail closed. A directory
        # already holding other generations proves this is a different one.
        try:
            return not any(directory.iterdir())
        except FileNotFoundError:
            # A concurrent retire() removed the directory between the existence
            # check and the listing: the fence is gone, exactly as _exists reports.
            return False

    def retire_replaced_generations(self, current: SandboxInfo, *, snapshot: QuarantineSnapshot, check: Callable[[], None] | None = None) -> None:
        """Drop fences a live replacement proves absent; never the live one.

        An observed runtime under the same logical ID with a *different*
        generation proves the fenced generations are gone (K8s Pod names and
        Docker container names are unique per logical ID). Their records are
        unreferenced garbage that would otherwise keep every future create on
        the inspect-and-defer path. The live generation's own record — and an
        unversioned ``unknown`` crash fence — are kept: deleting those could
        silently drop a fence a peer has just written.
        """
        keep = {"unknown"}
        if current.container_id:
            keep.add(self._key(current.container_id))
        self._retire(current, snapshot, keep=keep, check=check)

    def retire(self, info: SandboxInfo, *, snapshot: QuarantineSnapshot, check: Callable[[], None] | None = None) -> None:
        """Retire only the receipt versions captured before the absence proof.

        The provider must hold its local reservation and the cross-worker
        teardown lease; ``check`` propagates an observed lease loss even while
        waiting for the mutation lock. A new generation or a re-marked unknown
        generation survives even if the heartbeat has not noticed that loss yet.
        """
        self._retire(info, snapshot, keep=set(), check=check)

    def _retire(self, info: SandboxInfo, snapshot: QuarantineSnapshot, *, keep: set[str], check: Callable[[], None] | None) -> None:
        directory = self._directory(info)
        with self._mutation_lock(info, check) as lock_file:
            identity = self._directory_identity(directory)
            if identity is None or snapshot.directory_identity is None or identity != snapshot.directory_identity:
                return
            if check is not None:
                check()
            unchanged_directory = self._mutation_token(lock_file) == snapshot.mutation_token
            for name, receipt in snapshot.records.items():
                if check is not None:
                    check()
                record = directory / name
                if not receipt and not unchanged_directory:
                    # Legacy empty records cannot attest a re-marked version.
                    continue
                if name not in keep and self._receipt(record) == receipt:
                    if check is not None:
                        check()
                    self._drop(record)
            if check is not None:
                check()
            if not unchanged_directory:
                # A new empty directory is itself a crash-residue fence.
                return
            try:
                directory.rmdir()
            except OSError:
                # A live/fresh record or a peer's completed cleanup is normal.
                pass
