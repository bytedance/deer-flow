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
        # Truncate to 16 hex chars (64 bits). The quarantine nests three hashed
        # components (scope, sandbox id, container id); three full 64-char
        # SHA-256 hexdigests exceed Windows' 260-char MAX_PATH when the root
        # lives under a long path, failing record creation with ENOENT. 64 bits
        # is far beyond what non-adversarial sandbox/container ids need, and
        # matches the sandbox-naming convention elsewhere in this module.
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

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

    def retire_replaced_generations(self, current: SandboxInfo) -> None:
        """Drop fences a live replacement proves absent; never the live one.

        An observed runtime under the same logical ID with a *different*
        generation proves the fenced generations are gone (K8s Pod names and
        Docker container names are unique per logical ID). Their records are
        unreferenced garbage that would otherwise keep every future create on
        the inspect-and-defer path. The live generation's own record — and an
        unversioned ``unknown`` crash fence — are kept: deleting those could
        silently drop a fence a peer has just written.
        """
        directory = self._directory(current)
        if not self._exists(directory):
            return
        keep = self._key(current.container_id) if current.container_id else None
        for record in self._records(directory):
            if record.name == "unknown" or (keep is not None and record.name == keep):
                continue
            self._drop(record)
        try:
            directory.rmdir()
        except OSError:
            # A live or freshly fenced generation still has its record.
            pass

    def retire(self, info: SandboxInfo) -> None:
        """Remove fences only after the caller proves the logical ID is absent.

        The provider must hold its local reservation and the cross-worker
        teardown lease throughout that proof and this removal. A successful
        delete request or failed health check alone does not prove absence.

        A peer may fence the same logical ID between the listing below and the
        ``rmdir``. The teardown lease is keyed by that ID, and a replacement
        shares it, so while the ``del:`` marker is held a peer's claim — and an
        acquire-side ``take()`` for the replacement — are excluded. What is not
        guaranteed is that the exclusion is still held when ``rmdir`` runs: it
        is a TTL lease, not a lock, so the heartbeat can lose it mid-teardown
        (the documented "Lost the teardown exclusion" path stops refreshing
        while the stop continues) and the config schema permits TTLs below a
        normal stop. A record written in that lapse proves the directory holds a
        live generation, so the ``rmdir`` failure is swallowed and the directory
        is kept — exactly as :meth:`retire_replaced_generations` keeps a live
        generation's record: teardown must not abort on a fence a peer just
        wrote.

        This is best-effort, not full fence preservation: it closes the listing
        → ``rmdir`` window only. A peer record landing before the listing is
        still unlinked along with the rest. Both the listing and each unlink
        tolerate a peer that removed the directory or the record first, matching
        the ``FileNotFoundError`` handling in :meth:`contains`, so a teardown
        that finds its work already done returns instead of raising out of
        ``_retire_absent_quarantine``. What stays unclosed on purpose: on Windows
        a peer's ``mark()`` still holding the fresh record open for its
        ``fsync`` raises ``PermissionError``, which is a real storage failure
        rather than an absent fence.
        """
        directory = self._directory(info)
        if not self._exists(directory):
            return
        for record in self._records(directory):
            self._drop(record)
        try:
            directory.rmdir()
        except OSError:
            # A live or freshly fenced generation still has its record.
            pass
