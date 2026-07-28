"""Secondary adapter (anti-corruption layer) -- narrowing ThreadMetaStore to ThreadLookup.

Implements ``ThreadLookup`` from ``deerflow.domain.schedule.ports``. This
context does not own the ``threads_meta`` table and writes no SQL against it: it
asks its one question through the store the thread context already provides.

``require_existing=True`` is the load-bearing argument. The store's default
treats an absent row as accessible -- reasonable for a thread that has not been
written yet, wrong for binding a task to it, since the task would then reference
a thread that never existed.

TODO(hexagonal): this depends on ``ThreadMetaStore``, an infrastructure
component, rather than on a contract published by the thread context -- that
context has not been through a hexagonal slice yet. When it publishes one (a
DTO, not its aggregate and not its repository), replace the body of this class.
The ``ThreadLookup`` port does not move.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.domain.schedule.ports import ThreadLookup

if TYPE_CHECKING:
    from deerflow.persistence.thread_meta.base import ThreadMetaStore


class ThreadStoreThreadLookup(ThreadLookup):
    """Adapts the wide ``ThreadMetaStore`` to the one question this context asks.

    Both halves of that question -- does the thread exist, and may this user use
    it -- collapse into a single bool on purpose: reporting them separately
    would let a caller probe for the existence of threads they cannot see.

    Explicit inheritance is a readability aid only: a misspelled method would
    still instantiate fine and silently inherit the Protocol's ``...`` body,
    so the contract tests must call every port method and assert on what it
    returns.
    """

    def __init__(self, thread_store: ThreadMetaStore) -> None:
        self._thread_store = thread_store

    async def exists_for_user(self, thread_id: str, user_id: str) -> bool:
        return bool(await self._thread_store.check_access(thread_id, user_id, require_existing=True))
