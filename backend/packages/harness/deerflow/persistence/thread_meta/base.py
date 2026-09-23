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
from typing import Any, ClassVar, Final

from deerflow.runtime.user_context import AUTO, _AutoSentinel

# Cross-component metadata key. Keep in sync with
# ``frontend/src/core/threads/utils.ts`` and
# ``frontend/tests/e2e/utils/mock-api.ts``.
THREAD_PINNED_METADATA_KEY = "deerflow_pinned"
THREAD_ARCHIVED_METADATA_KEY = "deerflow_archived"

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
    ) -> dict:
        """Create a thread row; when ``project_id`` is set, validate the
        project inside the insert transaction and raise
        ``ProjectNotAssignableError`` on failure (no partial row)."""

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
        status: str | None = None,
        archived: bool | None = None,
        project_id: str | None | _ProjectFilterUnset = PROJECT_FILTER_UNSET,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Search threads.

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
        pass

    @abc.abstractmethod
    async def update_status(self, thread_id: str, status: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
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
