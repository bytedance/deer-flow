"""Contract for the per-IP failed-login counter behind ``POST /api/v1/auth/login/local``.

A store keeps one record per client IP: how many consecutive logins failed,
and — once that count reached ``max_attempts`` — when the lock started and
the sentence committed for it. The policy values (``max_attempts``,
``lockout_seconds``) are *not* stored as configuration: the caller passes the
live values on every call so a ``config.yaml`` edit applies to the next login
without a restart, and the semantics below decide how an in-flight record
follows a changed policy.

Semantics every implementation must share (pinned by
``tests/test_login_throttle_store.py`` against both stores):

- ``record_failure`` increments the count; when the new count reaches
  ``max_attempts`` the lock starts *now* with ``lockout_seconds`` as its
  committed duration (a record already over the threshold but never locked —
  the operator tightened the policy mid-count — locks on that next failure).
- ``check`` allows a record below the current threshold (raising
  ``max_attempts`` releases a lower count immediately) and one that is over
  it but never locked (the count is kept, not reset). An active lock first
  serves the duration committed for it: once that elapsed the record is
  cleared, so a later raise of ``lockout_seconds`` never resurrects a served
  sentence. While the committed sentence still runs, the lock follows the
  *current* duration — a lowered value releases early, a raised value
  extends — and that evaluation is committed to the record (decreases
  included), so the stored sentence always matches the policy the lock was
  last evaluated under.
- ``reset`` forgets the IP (successful login).
- ``get`` is the cheap existence probe the router uses to skip the policy
  read for clean IPs; it never mutates.

``now`` is an epoch timestamp supplied by the caller (defaulting to
``time.time()``) so replicas compare the same clock the lock was stamped with
and tests can freeze it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LoginThrottleRecord:
    """One IP's throttle state.

    ``locked_at == 0.0`` means "counting, never locked"; a lock stores the
    epoch timestamp it started at and the duration committed for it.
    """

    fail_count: int
    locked_at: float = 0.0
    lock_duration: float = 0.0

    @property
    def locked(self) -> bool:
        return self.locked_at > 0.0

    @property
    def expires_at(self) -> float:
        """When the committed sentence ends (0.0 for a never-locked counter)."""
        return self.locked_at + self.lock_duration if self.locked else 0.0


class LoginThrottleStore(Protocol):
    """Async per-IP failed-login counter shared by every login replica using it."""

    async def get(self, ip: str) -> LoginThrottleRecord | None:
        """Return the record for ``ip`` without mutating anything, or ``None`` for a clean IP."""
        ...

    async def check(self, ip: str, *, max_attempts: int, lockout_seconds: float, now: float | None = None) -> float:
        """Return the seconds the IP stays locked under the given policy, ``0.0`` when it may log in.

        Clears served / released locks as a side effect (see the module docstring).
        """
        ...

    async def record_failure(self, ip: str, *, max_attempts: int, lockout_seconds: float, now: float | None = None) -> LoginThrottleRecord:
        """Count one failed login under the given policy and return the new record."""
        ...

    async def reset(self, ip: str) -> None:
        """Forget the IP after a successful login."""
        ...
