"""Non-expiring quarantine records outside sandbox-visible mounts.

Like the acquire flock, these records live in the shared Gateway home. A lease
can expire or disappear; uncertainty about a running command cannot. Records
are bound to the runtime instance id, so a replacement can reuse the logical
sandbox id without inheriting the old instance's fence.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .sandbox_info import SandboxInfo


class SandboxQuarantine:
    def __init__(self, root: Path, scope: str):
        self._root = root / self._key(scope)

    @staticmethod
    def _key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _directory(self, info: SandboxInfo) -> Path:
        return self._root / self._key(info.sandbox_id)

    @staticmethod
    def _exists(path: Path) -> bool:
        # Do not collapse storage/permission failures into "no quarantine".
        try:
            path.stat()
        except FileNotFoundError:
            return False
        return True

    def mark(self, info: SandboxInfo) -> None:
        directory = self._directory(info)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        generation = self._key(info.container_id) if info.container_id else "unknown"
        # Empty records are atomic and idempotent: a process dying during the
        # write still leaves a fence, never partially parsed metadata.
        with (directory / generation).open("ab") as record:
            os.fsync(record.fileno())

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

    def retire(self, info: SandboxInfo) -> None:
        """Remove fences only after the caller proves the logical ID is absent.

        The provider must hold its local reservation and the cross-worker
        teardown lease throughout that proof and this removal. A successful
        delete request or failed health check alone does not prove absence.
        """
        directory = self._directory(info)
        if not self._exists(directory):
            return
        for record in directory.iterdir():
            record.unlink()
        directory.rmdir()
