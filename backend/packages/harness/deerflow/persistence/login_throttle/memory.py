"""In-process failed-login counter — one per Gateway process, not shared.

This is the historical ``app.gateway.routers.auth._login_attempts`` dict moved
behind :class:`~deerflow.persistence.login_throttle.base.LoginThrottleStore`.
With N Gateway replicas behind one load balancer each replica keeps its own
counter, so an attacker effectively gets N × ``max_login_attempts`` guesses
and a lockout on one replica is invisible to the others; use the SQL store
whenever an application database exists (``auth.local.throttle_storage``).
"""

from __future__ import annotations

import time
from dataclasses import replace

from deerflow.persistence.login_throttle.base import LoginThrottlePolicy, LoginThrottleRecord, evaluate_check

#: Upper bound on tracked IPs before the capacity sweep runs (historical constant).
MAX_TRACKED_IPS = 10000


class MemoryLoginThrottleStore:
    """Process-local counter with a bounded tracked-IP set."""

    def __init__(self, *, max_tracked_ips: int = MAX_TRACKED_IPS) -> None:
        self._records: dict[str, LoginThrottleRecord] = {}
        self._max_tracked_ips = max_tracked_ips

    async def get(self, ip: str) -> LoginThrottleRecord | None:
        return self._records.get(ip)

    async def check(self, ip: str, *, policy: LoginThrottlePolicy, now: float | None = None) -> float:
        """Apply the shared ``check`` contract to this process's record.

        The policy is resolved lazily: a clean IP returns before ``policy`` is
        awaited. That await is a yield point, so the record is read again
        afterwards and the decision is made on that fresh snapshot — a record
        a concurrent request cleared or replaced meanwhile is never judged
        from the stale probe. The compare-and-set that follows cannot miss:
        there is no ``await`` between the fresh read and the write and the
        event loop thread holds the GIL, so no peer can change the record in
        between — unlike the SQL store, whose writes race other replicas and
        therefore check their affected-row count and re-evaluate. The guards
        are kept only as a statement of the same discipline.
        """
        if ip not in self._records:
            return 0.0
        max_attempts, lockout_seconds = await policy()
        record = self._records.get(ip)  # fresh: the policy read yielded the loop
        if record is None:
            return 0.0
        now = time.time() if now is None else now
        decision = evaluate_check(record, max_attempts=max_attempts, lockout_seconds=lockout_seconds, now=now)
        if decision.discard:
            self._discard(ip, record)
        elif decision.commit_duration is not None and self._records.get(ip) == record:
            self._records[ip] = replace(record, lock_duration=decision.commit_duration)
        return decision.remaining

    async def record_failure(self, ip: str, *, max_attempts: int, lockout_seconds: float, now: float | None = None) -> LoginThrottleRecord:
        now = time.time() if now is None else now
        self._sweep_if_full(now, keep=ip)
        record = self._records.get(ip)
        if record is None:
            new_record = LoginThrottleRecord(fail_count=1)
        else:
            new_count = record.fail_count + 1
            if new_count < max_attempts:
                # Below the (possibly raised) threshold: counting, any lock is cleared.
                new_record = LoginThrottleRecord(fail_count=new_count)
            elif record.locked and now < record.expires_at:
                # A failure during an active lock keeps the lock's start and its
                # committed duration: the sentence is "N seconds after the lock
                # started", not "after the last attempt" (#6501 review).
                new_record = LoginThrottleRecord(fail_count=new_count, locked_at=record.locked_at, lock_duration=record.lock_duration)
            else:
                # Never locked, or the lock already served its sentence: start anew.
                new_record = LoginThrottleRecord(fail_count=new_count, locked_at=now, lock_duration=lockout_seconds)
        self._records[ip] = new_record
        return new_record

    async def reset(self, ip: str) -> None:
        self._records.pop(ip, None)

    def _discard(self, ip: str, snapshot: LoginThrottleRecord) -> None:
        # Compare-and-delete: only remove the record the decision was made on.
        if self._records.get(ip) == snapshot:
            del self._records[ip]

    def _sweep_if_full(self, now: float, *, keep: str) -> None:
        """Evict expired lockouts when the dict grows too large.

        ``keep`` is the IP whose failure is being recorded: its record is live
        and ``record_failure`` decides its fate from its own values (a served
        lock starts a fresh sentence), the same contract the SQL store keeps
        by excluding the upserted row from its sweep.

        Expiry is a property of each record's own committed sentence — ``locked
        and now >= expires_at`` — independent of the live threshold: a record
        locked under an old, lower threshold must still be swept once its
        sentence is served, even if the current max has moved past its count.
        Gating on the current threshold would retain expired records while the
        capacity fallback below evicts live counters (they sort first),
        granting active offenders fresh budgets.
        """
        if len(self._records) < self._max_tracked_ips:
            return
        for key in [k for k, record in self._records.items() if k != keep and record.locked and now >= record.expires_at]:
            del self._records[key]
        # If still too large, evict the cheapest-to-lose half ordered by each
        # record's own expiry: never-locked counters (expires_at == 0.0) first,
        # then locked records whose committed sentence expires earliest.
        if len(self._records) >= self._max_tracked_ips:
            by_expiry = sorted(((k, record) for k, record in self._records.items() if k != keep), key=lambda kv: kv[1].expires_at)
            for key, _ in by_expiry[: len(by_expiry) // 2]:
                del self._records[key]
