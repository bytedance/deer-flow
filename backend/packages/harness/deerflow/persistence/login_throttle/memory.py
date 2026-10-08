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

from deerflow.persistence.login_throttle.base import LoginThrottleRecord

#: Upper bound on tracked IPs before the capacity sweep runs (historical constant).
MAX_TRACKED_IPS = 10000


class MemoryLoginThrottleStore:
    """Process-local counter with a bounded tracked-IP set."""

    def __init__(self, *, max_tracked_ips: int = MAX_TRACKED_IPS) -> None:
        self._records: dict[str, LoginThrottleRecord] = {}
        self._max_tracked_ips = max_tracked_ips

    async def get(self, ip: str) -> LoginThrottleRecord | None:
        return self._records.get(ip)

    async def check(self, ip: str, *, max_attempts: int, lockout_seconds: float, now: float | None = None) -> float:
        record = self._records.get(ip)
        if record is None:
            return 0.0
        if record.fail_count < max_attempts:
            return 0.0
        if not record.locked:
            # Over the *current* threshold but the lock never started under the
            # threshold these failures accumulated under (the operator tightened
            # max_login_attempts mid-count). Keep the record: the next failure
            # starts the lock and a successful login clears it — deleting here
            # would hand the IP a fresh budget under a stricter policy.
            return 0.0
        now = time.time() if now is None else now
        if now >= record.expires_at:
            # The lock served the full sentence of the duration in force when it
            # started — a later duration increase must not resurrect it.
            self._discard(ip, record)
            return 0.0
        if now < record.locked_at + lockout_seconds:
            # Still locked. The sentence now follows the current duration, and
            # that evaluation is committed — including decreases — so the stored
            # sentence always matches the policy the lock was last evaluated
            # under; a later raise can never resurrect time the lock already
            # served under a shorter policy.
            if lockout_seconds != record.lock_duration and self._records.get(ip) == record:
                self._records[ip] = replace(record, lock_duration=lockout_seconds)
            return record.locked_at + lockout_seconds - now
        # Original sentence still running, but the current (lowered) duration has
        # already elapsed — release early.
        self._discard(ip, record)
        return 0.0

    async def record_failure(self, ip: str, *, max_attempts: int, lockout_seconds: float, now: float | None = None) -> LoginThrottleRecord:
        now = time.time() if now is None else now
        self._sweep_if_full(now)
        record = self._records.get(ip)
        if record is None:
            new_record = LoginThrottleRecord(fail_count=1)
        else:
            new_count = record.fail_count + 1
            if new_count >= max_attempts:
                new_record = LoginThrottleRecord(fail_count=new_count, locked_at=now, lock_duration=lockout_seconds)
            else:
                new_record = LoginThrottleRecord(fail_count=new_count)
        self._records[ip] = new_record
        return new_record

    async def reset(self, ip: str) -> None:
        self._records.pop(ip, None)

    def _discard(self, ip: str, snapshot: LoginThrottleRecord) -> None:
        # Compare-and-delete: only remove the record the decision was made on.
        if self._records.get(ip) == snapshot:
            del self._records[ip]

    def _sweep_if_full(self, now: float) -> None:
        """Evict expired lockouts when the dict grows too large.

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
        for key in [k for k, record in self._records.items() if record.locked and now >= record.expires_at]:
            del self._records[key]
        # If still too large, evict the cheapest-to-lose half ordered by each
        # record's own expiry: never-locked counters (expires_at == 0.0) first,
        # then locked records whose committed sentence expires earliest.
        if len(self._records) >= self._max_tracked_ips:
            by_expiry = sorted(self._records.items(), key=lambda kv: kv[1].expires_at)
            for key, _ in by_expiry[: len(by_expiry) // 2]:
                del self._records[key]
