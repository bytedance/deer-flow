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
from typing import Any

from deerflow.runtime.user_context import AUTO, _AutoSentinel

# Cross-component metadata key. Keep in sync with
# ``frontend/src/core/threads/utils.ts`` and
# ``frontend/tests/e2e/utils/mock-api.ts``.
THREAD_PINNED_METADATA_KEY = "deerflow_pinned"


class InvalidMetadataFilterError(ValueError):
    """Raised when all client-supplied metadata filter keys are rejected."""


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
    ) -> dict:
        pass

    @abc.abstractmethod
    async def get(self, thread_id: str, *, user_id: str | None | _AutoSentinel = AUTO) -> dict | None:
        pass

    @abc.abstractmethod
    async def search(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        user_id: str | None | _AutoSentinel = AUTO,
    ) -> list[dict[str, Any]]:
        """Search threads.

        Results are ordered with pinned threads first
        (``metadata.deerflow_pinned is True``), then by ``updated_at`` and
        ``thread_id`` descending within each group.
        """
        pass

    @abc.abstractmethod
    async def update_display_name(self, thread_id: str, display_name: str, *, user_id: str | None | _AutoSentinel = AUTO) -> None:
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
