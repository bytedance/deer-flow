"""``ChannelLeadership``: the holder's side of the per-provider IM leader lease.

The repository decides ownership against the database clock; this class keeps
the local, monotonic deadline that tells the holder when it must stop its
transport. The fake repository below shares the test clock, so the safety
margin (a peer can take over only ``lease + grace`` after the last confirmed
renewal was *sent*) is checked exactly.
"""

from __future__ import annotations

import asyncio

import pytest

from app.channels.leadership import ChannelLeadership, RenewOutcome
from deerflow.persistence.channel_leases import ChannelLeaseGrant, ChannelLeaseState

pytestmark = pytest.mark.asyncio


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeRepo:
    """One lease table, judged against the shared test clock like the SQL repository."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.rows: dict[str, dict] = {}
        self.fail: set[str] = set()
        self.call_latency = 0.0  # simulated statement time on the test clock
        self.calls: list[tuple] = []

    def _maybe_fail(self, op: str) -> None:
        self.calls.append((op,))
        if op in self.fail:
            raise ConnectionError(f"{op} failed")

    async def acquire(self, provider, owner_id, *, ttl_seconds, grace_seconds):
        self._maybe_fail("acquire")
        self.clock.now += self.call_latency
        row = self.rows.get(provider)
        now = self.clock.now
        if row is None or row["expires"] + grace_seconds < now or row["owner"] == owner_id:
            epoch = (row["epoch"] + 1) if row else 1
            self.rows[provider] = {"owner": owner_id, "epoch": epoch, "expires": now + ttl_seconds, "running": False}
            return ChannelLeaseGrant(provider=provider, epoch=epoch, lease_expires_at=now + ttl_seconds)
        return None

    async def renew(self, provider, owner_id, epoch, *, ttl_seconds, transport_running):
        self._maybe_fail("renew")
        self.clock.now += self.call_latency
        row = self.rows.get(provider)
        now = self.clock.now
        if row is None or row["owner"] != owner_id or row["epoch"] != epoch or row["expires"] <= now:
            return False
        row.update(expires=now + ttl_seconds, running=transport_running)
        return True

    async def release(self, provider, owner_id, epoch):
        self._maybe_fail("release")
        row = self.rows.get(provider)
        if row is None or row["owner"] != owner_id or row["epoch"] != epoch:
            return False
        row.update(expires=0.0, running=False)
        return True

    async def get(self, provider):
        self._maybe_fail("get")
        row = self.rows.get(provider)
        if row is None:
            return None
        return ChannelLeaseState(provider=provider, owner_id=row["owner"], epoch=row["epoch"], lease_expires_at=row["expires"], transport_running=row["running"], live=row["expires"] > self.clock.now)

    async def list_all(self):
        self._maybe_fail("list_all")
        return [await self.get(provider) for provider in sorted(self.rows)]


def _leadership(repo: FakeRepo, clock: Clock, owner: str = "A", *, lease_seconds: int = 30, grace_seconds: int = 10) -> ChannelLeadership:
    return ChannelLeadership(repo, owner_id=owner, lease_seconds=lease_seconds, grace_seconds=grace_seconds, clock=clock)


async def test_intervals_follow_the_documented_lease_fraction():
    clock = Clock()
    lead = _leadership(FakeRepo(clock), clock, lease_seconds=30)
    assert (lead.renew_interval, lead.operation_timeout) == (10.0, 5.0)
    small = _leadership(FakeRepo(clock), clock, lease_seconds=3)
    assert (small.renew_interval, small.operation_timeout) == (1.0, 0.5)


async def test_holds_stops_one_renewal_interval_before_the_local_deadline():
    clock = Clock()
    lead = _leadership(FakeRepo(clock), clock)
    assert await lead.acquire("telegram") is True

    clock.now += 19.9  # deadline 1030, interval 10
    assert lead.holds("telegram") is True
    clock.now += 0.1
    assert lead.holds("telegram") is False
    assert lead.has_record("telegram") is True  # the row may still be ours; the transport may not keep running


async def test_deadline_counts_from_when_the_renewal_was_sent():
    """A slow statement must not stretch the deadline: the database stamped the expiry no earlier than the send."""
    clock = Clock()
    repo = FakeRepo(clock)
    lead = _leadership(repo, clock)
    await lead.acquire("telegram")

    clock.now += 10
    sent_at = clock.now
    repo.call_latency = 4.0
    assert await lead.renew("telegram", transport_running=True) is RenewOutcome.RENEWED

    peer_can_take_at = repo.rows["telegram"]["expires"] + lead.grace_seconds
    assert peer_can_take_at >= sent_at + lead.lease_seconds + lead.grace_seconds
    clock.now = sent_at + lead.lease_seconds - lead.renew_interval
    assert lead.holds("telegram") is False  # judged from the send time, not the (later) reply


async def test_a_rejected_renewal_is_a_loss():
    clock = Clock()
    repo = FakeRepo(clock)
    lead = _leadership(repo, clock)
    await lead.acquire("telegram")
    repo.rows["telegram"]["epoch"] += 1  # a peer took the row over

    assert await lead.renew("telegram", transport_running=True) is RenewOutcome.LOST
    assert lead.has_record("telegram") is False
    assert lead.holds("telegram") is False


async def test_an_unconfirmed_renewal_keeps_the_deadline_running():
    clock = Clock()
    repo = FakeRepo(clock)
    lead = _leadership(repo, clock)
    await lead.acquire("telegram")
    repo.fail.add("renew")

    clock.now += 10
    assert await lead.renew("telegram", transport_running=True) is RenewOutcome.UNCONFIRMED
    assert lead.holds("telegram") is True  # 1010 + 10 < 1030
    clock.now += 10
    assert await lead.renew("telegram", transport_running=True) is RenewOutcome.UNCONFIRMED
    assert lead.holds("telegram") is False  # 1020 + 10 is not before 1030: stop now, grace_seconds before a peer may connect
    assert lead.has_record("telegram") is True


async def test_a_stalled_database_call_is_bounded_by_the_operation_timeout():
    class StalledRepo(FakeRepo):
        async def renew(self, *args, **kwargs):
            await asyncio.sleep(30)

    clock = Clock()
    repo = StalledRepo(clock)
    lead = ChannelLeadership(repo, owner_id="A", lease_seconds=3, grace_seconds=1, clock=clock)
    await lead.acquire("telegram")

    outcome = await asyncio.wait_for(lead.renew("telegram", transport_running=True), timeout=5)
    assert outcome is RenewOutcome.UNCONFIRMED


async def test_a_refused_acquire_records_the_peer_for_status():
    clock = Clock()
    repo = FakeRepo(clock)
    peer = _leadership(repo, clock, owner="B")
    await peer.acquire("telegram")
    await peer.renew("telegram", transport_running=True)

    lead = _leadership(repo, clock, owner="A")
    assert await lead.acquire("telegram") is False
    assert lead.leader_of("telegram") == "B"
    assert lead.peer_transport_running("telegram") is True
    assert lead.leader_of("discord") is None

    clock.now += 100  # the peer's lease lapsed
    assert await lead.acquire("telegram") is True
    assert lead.leader_of("telegram") == "A"
    assert lead.peer_transport_running("telegram") is False


async def test_acquire_while_holding_is_a_no_op_and_a_lost_record_is_dropped():
    clock = Clock()
    repo = FakeRepo(clock)
    lead = _leadership(repo, clock)
    await lead.acquire("telegram")
    calls = len(repo.calls)
    assert await lead.acquire("telegram") is True
    assert len(repo.calls) == calls  # no statement while the hold is safe

    clock.now += 25  # near the deadline: the next acquire re-takes our own row
    repo.rows["telegram"].update(owner="B", expires=clock.now + 30)
    assert await lead.acquire("telegram") is False
    assert lead.has_record("telegram") is False


async def test_release_is_fenced_by_epoch_and_best_effort():
    clock = Clock()
    repo = FakeRepo(clock)
    lead = _leadership(repo, clock)
    await lead.acquire("telegram")
    await lead.release("telegram")
    assert repo.rows["telegram"]["expires"] == 0.0
    assert lead.has_record("telegram") is False

    await lead.acquire("discord")
    repo.fail.add("release")
    await lead.release("discord")  # the error is logged, not raised; the row expires on its own
    assert lead.has_record("discord") is False
    await lead.release("slack")  # nothing held: no call
    assert ("release",) in repo.calls


async def test_observe_all_sees_peer_leases_this_instance_never_tried():
    """A provider connected on a peer is in no local config, so no failed acquire ever observes it."""
    clock = Clock()
    repo = FakeRepo(clock)
    peer = _leadership(repo, clock, owner="B")
    await peer.acquire("telegram")
    await peer.renew("telegram", transport_running=True)
    lead = _leadership(repo, clock, owner="A")
    await lead.acquire("discord")

    assert lead.leader_of("telegram") is None
    await lead.observe_all()
    assert (lead.leader_of("telegram"), lead.peer_leads("telegram"), lead.peer_transport_running("telegram")) == ("B", True, True)
    assert (lead.leader_of("discord"), lead.peer_leads("discord")) == ("A", False)  # our own row never reads as a peer's

    clock.now += 100  # the peer's lease lapses
    await lead.observe_all()
    assert (lead.leader_of("telegram"), lead.peer_leads("telegram")) == (None, False)

    repo.fail.add("list_all")
    await lead.observe_all()  # logged, not raised; the last view stays
    assert lead.leader_of("telegram") is None
