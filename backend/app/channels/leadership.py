"""Per-provider leader lease bookkeeping for one Gateway instance (``channels.leader_lease``).

The shared ``channel_leases`` table (``deerflow.persistence.channel_leases``)
decides, against the database clock, which instance may hold a provider's
platform connection. This module keeps the holder's side of that contract:

- **Local deadline.** A lease granted or renewed by a statement sent at local
  monotonic time ``t`` cannot be taken by a peer before ``t + lease_seconds +
  grace_seconds`` (the database stamps the expiry no earlier than ``t`` and a
  peer must wait ``grace_seconds`` past it). The holder therefore treats its
  lease as safe only while ``now + renew_interval < t + lease_seconds``, where
  ``t`` is the send time of the last *confirmed* renewal. Offsets between host
  clocks do not matter; only the monotonic clock's rate does.
- **Fail closed.** :meth:`ChannelLeadership.holds` turns false one renewal
  interval before that deadline whether or not the database answered, and the
  caller (``ChannelService``) stops the transport when it does. A renewal
  that the database rejects (another owner or a newer epoch) is a loss and the
  transport stops at once; a renewal that errors or times out is merely
  unconfirmed and the deadline keeps running.
- **Bounded calls.** Every repository call is bounded by
  ``operation_timeout``, half the renewal interval, so a stalled database
  cannot hold a renewal past the deadline it protects. A call that times out
  after the statement committed only ever errs toward "not held".

Peers' leases are cached from one bounded read of the whole table per
supervision round (:meth:`ChannelLeadership.observe_all`) and from failed
acquisitions, so ``get_status`` (sync) and the notification claim filter know
who leads *every* provider, including one this instance has no config for
(a provider connected from the web UI on a peer never enters this instance's
channel config).
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from deerflow.persistence.channel_leases import ChannelLeaseGrant, ChannelLeaseState

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class ChannelLeaseRepository(Protocol):
    """What :class:`ChannelLeadership` needs from ``SqlChannelLeaseRepository``."""

    async def acquire(self, provider: str, owner_id: str, *, ttl_seconds: float, grace_seconds: float) -> ChannelLeaseGrant | None: ...

    async def renew(self, provider: str, owner_id: str, epoch: int, *, ttl_seconds: float, transport_running: bool) -> bool: ...

    async def release(self, provider: str, owner_id: str, epoch: int) -> bool: ...

    async def get(self, provider: str) -> ChannelLeaseState | None: ...

    async def list_all(self) -> list[ChannelLeaseState]: ...


class RenewOutcome(enum.Enum):
    RENEWED = "renewed"
    #: The database rejected the renewal: another owner or a newer epoch holds the row.
    LOST = "lost"
    #: The renewal errored or timed out; the lease may or may not still be ours.
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class _Held:
    epoch: int
    #: Local monotonic time by which a peer may be able to take the lease.
    deadline: float


class ChannelLeadership:
    """The lease state of one Gateway instance across every arbitrated provider."""

    def __init__(
        self,
        repo: ChannelLeaseRepository,
        *,
        owner_id: str,
        lease_seconds: int,
        grace_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repo = repo
        self.owner_id = owner_id
        self.lease_seconds = float(lease_seconds)
        self.grace_seconds = float(grace_seconds)
        # ``channels.leader_lease.lease_seconds`` documents renewal every
        # ``lease_seconds // 3`` seconds; the config floor of 3 keeps it >= 1.
        self.renew_interval = float(max(1, int(lease_seconds) // 3))
        self.operation_timeout = max(0.5, self.renew_interval / 2)
        self._clock = clock
        self._held: dict[str, _Held] = {}
        self._observed: dict[str, ChannelLeaseState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # -- local view -----------------------------------------------------

    def now(self) -> float:
        return self._clock()

    def holds(self, provider: str) -> bool:
        """True while a transport for ``provider`` may keep running until the next renewal."""
        held = self._held.get(provider)
        return held is not None and self._clock() + self.renew_interval < held.deadline

    def has_record(self, provider: str) -> bool:
        """True while this instance believes it holds the lease row, even near its deadline."""
        return provider in self._held

    def held_providers(self) -> list[str]:
        return sorted(self._held)

    def leader_of(self, provider: str) -> str | None:
        """The owner of a live lease as last seen by this instance, or ``None``."""
        if provider in self._held:
            return self.owner_id
        observed = self._observed.get(provider)
        return observed.owner_id if observed is not None and observed.live else None

    def peer_leads(self, provider: str) -> bool:
        """Whether a live lease held by another instance was last seen for ``provider``."""
        if provider in self._held:
            return False
        observed = self._observed.get(provider)
        return bool(observed is not None and observed.live and observed.owner_id != self.owner_id)

    def peer_transport_running(self, provider: str) -> bool:
        """Whether a live peer leader reported its transport running at its last renewal."""
        if provider in self._held:
            return False
        observed = self._observed.get(provider)
        return bool(observed is not None and observed.live and observed.transport_running)

    def forget(self, provider: str) -> None:
        """Drop the local hold without touching the row (the lease is lost or past its deadline)."""
        self._held.pop(provider, None)

    # -- database operations ---------------------------------------------

    async def acquire(self, provider: str) -> bool:
        """Hold ``provider``'s lease, taking it if free; ``False`` while a peer holds it or on error."""
        async with self._lock(provider):
            if self.holds(provider):
                return True
            sent = self._clock()
            try:
                grant = await self._bounded(self._repo.acquire(provider, self.owner_id, ttl_seconds=self.lease_seconds, grace_seconds=self.grace_seconds))
            except Exception:
                logger.warning("Could not acquire the %s channel leader lease; retrying on the next renewal tick", provider, exc_info=True)
                return False
            if grant is None:
                # A peer holds the row, so any local record is stale.
                self._held.pop(provider, None)
                await self._observe(provider)
                return False
            if provider not in self._held:
                logger.info("Acquired the %s channel leader lease (epoch %d)", provider, grant.epoch)
            self._held[provider] = _Held(epoch=grant.epoch, deadline=sent + self.lease_seconds)
            self._observed.pop(provider, None)
            return True

    async def renew(self, provider: str, *, transport_running: bool) -> RenewOutcome:
        async with self._lock(provider):
            held = self._held.get(provider)
            if held is None:
                return RenewOutcome.LOST
            sent = self._clock()
            try:
                renewed = await self._bounded(self._repo.renew(provider, self.owner_id, held.epoch, ttl_seconds=self.lease_seconds, transport_running=transport_running))
            except Exception:
                logger.warning("Could not confirm the %s channel leader lease renewal (epoch %d)", provider, held.epoch, exc_info=True)
                return RenewOutcome.UNCONFIRMED
            if not renewed:
                logger.warning("Lost the %s channel leader lease (epoch %d): it expired or another instance took it", provider, held.epoch)
                self._held.pop(provider, None)
                return RenewOutcome.LOST
            self._held[provider] = _Held(epoch=held.epoch, deadline=sent + self.lease_seconds)
            return RenewOutcome.RENEWED

    async def release(self, provider: str) -> None:
        """Hand the lease back so a peer can take it at once (best effort; it expires anyway)."""
        async with self._lock(provider):
            held = self._held.pop(provider, None)
            if held is None:
                return
            try:
                await self._bounded(self._repo.release(provider, self.owner_id, held.epoch))
            except Exception:
                logger.warning("Could not release the %s channel leader lease (epoch %d); it expires on its own", provider, held.epoch, exc_info=True)
                return
            logger.info("Released the %s channel leader lease (epoch %d)", provider, held.epoch)

    async def observe_all(self) -> None:
        """Refresh the cached view of every provider's lease (best effort, one bounded read)."""
        try:
            states = await self._bounded(self._repo.list_all())
        except Exception:
            logger.debug("Could not read the channel leader lease table", exc_info=True)
            return
        self._observed = {state.provider: state for state in states if state.provider not in self._held}

    async def _observe(self, provider: str) -> None:
        try:
            state = await self._bounded(self._repo.get(provider))
        except Exception:
            logger.debug("Could not read the %s channel leader lease", provider, exc_info=True)
            return
        if state is None:
            self._observed.pop(provider, None)
        else:
            self._observed[provider] = state

    async def _bounded(self, call: Awaitable[_T]) -> _T:
        return await asyncio.wait_for(call, timeout=self.operation_timeout)

    def _lock(self, provider: str) -> asyncio.Lock:
        return self._locks.setdefault(provider, asyncio.Lock())
