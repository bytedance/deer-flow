"""Abstract interface for thread metadata storage.

Implementations:
- ThreadMetaRepository: SQL-backed (sqlite / postgres via SQLAlchemy)
- MemoryThreadMetaStore: wraps LangGraph BaseStore (memory mode)

All mutating and querying methods accept a ``user_id`` parameter with
three-state semantics (see :mod:`deerflow.runtime.user_context`):

- ``AUTO`` (default): resolve from the request-scoped contextvar.
- Explicit ``str``: use the provided value verbatim.
- Explicit ``None``: bypass owner filtering (migration/CLI only).
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Final

from deerflow.runtime.user_context import AUTO, _AutoSentinel

# Cross-component metadata key. Keep in sync with
# ``frontend/src/core/threads/utils.ts`` and
# ``frontend/tests/e2e/utils/mock-api.ts``.
THREAD_PINNED_METADATA_KEY = "deerflow_pinned"
THREAD_ARCHIVED_METADATA_KEY = "deerflow_archived"

# Server-only metadata key: set when the owner explicitly ends an incognito
# thread, so the activity renewal that run completion performs cannot extend a
# thread the user has already closed. Clients cannot write it (the Gateway
# strips server-reserved keys from every request body).
THREAD_INCOGNITO_ENDED_METADATA_KEY = "deerflow_incognito_ended"

# ``status`` value of an incognito row whose data has been (or is being)
# purged. The row itself stays as a tombstone: deleting it would let the same
# thread id be created again as an ordinary thread, and read routes would
# answer a 200 with empty content instead of reporting the thread as gone.
THREAD_INCOGNITO_EXPIRED_STATUS = "expired"


def _as_utc(value: object) -> datetime | None:
    """Parse a stored timestamp (datetime or ISO string) as UTC."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def is_incognito_expired(record: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Return whether *record* is an incognito thread past its lifetime.

    Two states count as expired: the tombstone the sweep writes before it
    purges data (``status == "expired"``), and a live row whose ``expires_at``
    deadline already passed but which the sweep has not reached yet. From the
    owner's point of view an incognito thread disappears the moment its
    deadline passes, not at the next sweep.
    """
    if record.get("incognito") is not True:
        return False
    if record.get("status") == THREAD_INCOGNITO_EXPIRED_STATUS:
        return True
    deadline = _as_utc(record.get("expires_at"))
    return deadline is not None and deadline <= (now or datetime.now(UTC))


def incognito_deadline(
    *,
    now: datetime,
    created_at: datetime,
    window: timedelta,
    max_lifetime: timedelta,
) -> datetime:
    """Return the earlier of a renewal window and the absolute lifetime.

    ``window`` is the idle window on an activity renewal and the end grace
    period when the owner ends the chat. Every write that moves
    ``expires_at`` goes through this function, so ``max_lifetime`` is a true
    ceiling rather than a rule only renewals respect.
    """
    return min(now + window, created_at + max_lifetime)


# Cross-component metadata key. Keep in sync with
# ``frontend/src/core/threads/utils.ts`` and
# ``frontend/tests/e2e/utils/mock-api.ts``.
THREAD_PROJECT_METADATA_KEY = "deerflow_project_id"


class _ProjectFilterUnset:
    """Sentinel for ``search(project_id=...)``: absent filter vs explicit unassigned."""

    _instance: ClassVar[_ProjectFilterUnset | None] = None

    def __new__(cls) -> _ProjectFilterUnset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<PROJECT_FILTER_UNSET>"


PROJECT_FILTER_UNSET: Final = _ProjectFilterUnset()


class InvalidMetadataFilterError(ValueError):
    """Raised when all client-supplied metadata filter keys are rejected."""


class ThreadOwnershipConflictError(Exception):
    """Raised when create would overwrite a thread owned by another user."""


class ThreadCreateConflictError(Exception):
    """Raised when create would overwrite a row the caller must not replace.

    The memory store historically overwrote a duplicate id, while the SQL
    store's primary key rejects the insert. An incognito row is the one record
    that must survive external writes: overwriting a tombstone would let the
    id be reused, and overwriting a live incognito row would silently convert
    or extend it. A store raises this instead, and the Gateway resolves the
    existing row through its idempotent-create path (410 expired, 409 mode
    mismatch, or the existing row itself)."""


class ThreadMetaStore(abc.ABC):
    @abc.abstractmethod
    async def create(
        self,
        thread_id: str,
        *,
        assistant_id: str | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
        display_name: str | None = None,
        metadata: dict | None = None,
        project_id: str | None = None,
        incognito: bool = False,
        expires_at: datetime | None = None,
    ) -> dict:
        """Create a thread row; when ``project_id`` is set, validate the
        project inside the insert transaction and raise
        ``ProjectNotAssignableError`` on failure (no partial row).

        ``incognito`` marks a thread that must never appear in a thread list,
        search result, project, archive view or share; ``expires_at`` is the
        absolute deadline its lifetime sweep uses. Ordinary mutators never
        touch either field: only the lifecycle methods below move the deadline
        and the tombstone."""

    @abc.abstractmethod
    async def claim_unowned(self, thread_id: str, owner: str) -> bool:
        """Atomically claim a legacy row whose owner is ``None``.

        Returns ``True`` only when this call changed ``user_id`` from ``None``
        to ``owner``. Missing and already-owned rows return ``False``.
        """

    @abc.abstractmethod
    async def set_project(self, thread_id: str, project_id: str | None, *, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Atomically move a thread into/out of a project (RFC v2 §5.2).

        Returns False when the thread is missing/foreign, or the target
        project is missing/foreign/archived. Must not touch ``updated_at``.
        """

    @abc.abstractmethod
    async def get(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        pass

    @abc.abstractmethod
    async def search(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        query: str | None = None,
        status: str | None = None,
        archived: bool | None = None,
        project_id: str | None | _ProjectFilterUnset = PROJECT_FILTER_UNSET,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Search threads.

        Incognito threads are never returned, regardless of filters: the only
        way to reach one is by its exact thread id through :meth:`get`.

        ``archived=None`` includes all threads; False includes legacy rows
        without a true archive flag. Filtering precedes pagination.

        Results are ordered with pinned threads first
        (``metadata.deerflow_pinned is True``), then by ``updated_at`` and
        ``thread_id`` descending within each group.
        """
        pass

    @abc.abstractmethod
    async def update_display_name(
        self,
        thread_id: str,
        display_name: str,
        *,
        remove_metadata_keys: tuple[str, ...] = (),
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> None:
        """Update the display name and remove caller-selected stale metadata.

        Must be a no-op for an incognito tombstone (``status="expired"``): run
        finalization on another worker can reach it after the sweep purged the
        thread, and writing the title back would leave content on a row that
        reads no longer resolve.
        """
        pass

    @abc.abstractmethod
    async def update_status(self, thread_id: str, status: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """Update the run status.

        Like :meth:`update_display_name`, this must never overwrite an
        incognito tombstone. A resurrected row would resolve for its owner
        again while ``expires_at`` is already cleared, so the sweep would never
        select it for deletion.
        """
        pass

    @abc.abstractmethod
    async def update_metadata(self, thread_id: str, metadata: dict, *, touch: bool = True, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """Merge ``metadata`` into the thread's metadata field.

        Existing keys are overwritten by the new values; keys absent from
        ``metadata`` are preserved. No-op if the thread does not exist
        or the owner check fails.

        When ``touch`` is ``True`` (default) the row's ``updated_at`` is
        refreshed so the change bumps recency ordering. Pass ``touch=False``
        for metadata that is not conversation activity (e.g. pin/unpin) so the
        thread keeps its place in ``updated_at``-sorted lists.
        """
        pass

    @abc.abstractmethod
    async def update_owner(self, thread_id: str, owner_user_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        """Move a thread metadata row to a new owner.

        Intended for trusted internal repair/migration paths. No-op if the
        row does not exist or the caller fails the owner check.
        """
        pass

    @abc.abstractmethod
    async def check_access(self, thread_id: str, user_id: str, *, require_existing: bool = False) -> bool:
        """Check if ``user_id`` has access to ``thread_id``."""
        pass

    @abc.abstractmethod
    async def delete(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
        pass

    # ------------------------------------------------------------------
    # Incognito lifetime
    #
    # These have no-op defaults rather than ``@abc.abstractmethod`` so a
    # third-party store written before incognito existed keeps instantiating.
    # Such a store simply never expires a thread; both stores shipped with
    # DeerFlow implement the full lifecycle.
    # ------------------------------------------------------------------

    async def incognito_ids(self, thread_ids: Sequence[str], *, user_id: str | None | _AutoSentinel = AUTO) -> set[str]:
        """Return the subset of ``thread_ids`` that name incognito threads.

        The run-activity feed must never list an incognito thread, and it
        holds a page of ids rather than records; this lets it filter them in
        one call. Missing and foreign rows are not returned. The base
        implementation performs one owner-scoped :meth:`get` per id; the SQL
        store overrides it with a single query.
        """
        found: set[str] = set()
        for thread_id in thread_ids:
            record = await self.get(thread_id, user_id=user_id)
            if record is not None and record.get("incognito") is True:
                found.add(thread_id)
        return found

    async def list_due_incognito(self, *, now: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return incognito rows whose deadline passed, oldest deadline first.

        The lifetime sweep calls this with no owner scope: expiry is a
        server-side lifecycle, not a user action.
        """
        return []

    async def renew_incognito(
        self,
        thread_id: str,
        *,
        idle_ttl: timedelta,
        max_lifetime: timedelta,
        now: datetime | None = None,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> bool:
        """Push the deadline to ``min(now + idle_ttl, created_at + max_lifetime)``.

        Called on run admission and run completion, i.e. exactly when the
        thread is active. Moving to an earlier deadline is allowed (the
        absolute ceiling wins) but never extends a thread beyond it. Returns
        ``False`` for missing/non-incognito/tombstoned rows, for a row whose
        deadline already passed (expiry is not undone by activity, even before
        the sweep reaches it), and for a thread the owner already ended, whose
        grace deadline must not grow back into a full idle window.
        """
        return False

    async def end_incognito(self, thread_id: str, *, grace: timedelta, max_lifetime: timedelta, now: datetime | None = None, user_id: str | None | _AutoSentinel = AUTO) -> bool:
        """Schedule an owner-requested end: deadline ``min(now + grace, created_at + max_lifetime)``.

        Records the end in metadata so activity renewal stops. Returns
        ``False`` for missing/non-incognito/tombstoned rows or a foreign owner.
        """
        return False

    async def begin_incognito_expiry(self, thread_id: str, *, now: datetime | None = None) -> bool:
        """Write the tombstone before any data is purged.

        Clears the thread's content from the row (display name, metadata,
        project membership) and marks it ``expired`` so reads stop resolving
        it even if the purge below fails halfway. Returns ``False`` when the
        row is missing, not incognito, or its deadline is still in the future;
        the sweep's due list is a snapshot, so a concurrent renewal must win
        over a stale batch entry. An already-tombstoned row whose deadline is
        past returns ``True`` again so a failed purge retries.
        """
        return False

    async def finish_incognito_expiry(self, thread_id: str) -> None:
        """Mark a tombstoned row as purged by clearing ``expires_at``.

        The sweep selects rows by a non-NULL past ``expires_at``, so this is
        what stops a completed purge from being retried. It runs only after
        every other store has been cleaned.
        """
        return None
