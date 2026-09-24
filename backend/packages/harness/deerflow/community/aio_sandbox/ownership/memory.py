"""In-process ownership store for single-instance deployments.

Correct only when one gateway process owns the container backend: nothing here is
visible to another process, so a peer would see every container as unowned and
adopt it. :attr:`supports_cross_process` is ``False`` to say so, and the provider
warns at startup. Multi-worker / multi-instance gateways must use the redis
store — the same rule `stream_bridge`'s memory backend carries.

TTL and the two lease states are implemented for real rather than stubbed out, so
one store-contract suite exercises both backends and a lapsed lease behaves
identically whichever store is configured.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .base import RenewOutcome, SandboxOwnershipStore


@dataclass(frozen=True, slots=True)
class _Lease:
    owner_id: str
    expires_at: float
    destroying: bool


class MemoryOwnershipStore(SandboxOwnershipStore):
    """Ownership leases held in this process only."""

    supports_cross_process = False

    def __init__(self, *, owner_id: str, ttl_seconds: float, time_source=time.monotonic) -> None:
        self._owner_id = owner_id
        self._ttl = float(ttl_seconds)
        self._now = time_source
        # sandbox_id -> _Lease. Guarded by _lock: the acquire path, the idle
        # checker thread, and the renewal thread all touch it.
        self._leases: dict[str, _Lease] = {}
        self._lock = threading.Lock()

    @property
    def owner_id(self) -> str:
        return self._owner_id

    def _live_lease_locked(self, sandbox_id: str) -> _Lease | None:
        lease = self._leases.get(sandbox_id)
        if lease is None:
            return None
        if self._now() >= lease.expires_at:
            del self._leases[sandbox_id]
            return None
        return lease

    def _write_locked(self, sandbox_id: str, *, destroying: bool) -> None:
        self._leases[sandbox_id] = _Lease(owner_id=self._owner_id, expires_at=self._now() + self._ttl, destroying=destroying)

    def take(self, sandbox_id: str) -> bool:
        with self._lock:
            lease = self._live_lease_locked(sandbox_id)
            # Refuse only a teardown in progress; a live peer's normal lease is
            # taken over, which is the point of take().
            if lease is not None and lease.destroying:
                return False
            self._write_locked(sandbox_id, destroying=False)
            return True

    def claim(self, sandbox_id: str, *, for_destroy: bool = False) -> bool:
        with self._lock:
            lease = self._live_lease_locked(sandbox_id)
            if lease is not None and lease.owner_id != self._owner_id:
                return False
            if not for_destroy and lease is not None and lease.destroying:
                # Never unwind our own teardown: the stop is already in flight
                # and cannot be recalled, so downgrading to `own:` would let a
                # `take()` hand out a container that is about to die.
                return False
            self._write_locked(sandbox_id, destroying=for_destroy)
            return True

    def renew(self, sandbox_id: str) -> RenewOutcome:
        with self._lock:
            lease = self._live_lease_locked(sandbox_id)
            if lease is None:
                return RenewOutcome.LAPSED
            if lease.owner_id != self._owner_id or lease.destroying:
                return RenewOutcome.LOST
            self._write_locked(sandbox_id, destroying=False)
            return RenewOutcome.RENEWED

    def release(self, sandbox_id: str) -> None:
        with self._lock:
            lease = self._live_lease_locked(sandbox_id)
            if lease is not None and lease.owner_id == self._owner_id:
                del self._leases[sandbox_id]

    def owner(self, sandbox_id: str) -> str | None:
        with self._lock:
            lease = self._live_lease_locked(sandbox_id)
            return None if lease is None else lease.owner_id

    def close(self) -> None:
        with self._lock:
            self._leases.clear()
