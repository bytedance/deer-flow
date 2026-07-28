"""Secondary adapter (anti-corruption layer) -- narrowing RunStore to RunLookup.

Implements ``RunLookup`` from ``deerflow.domain.feedback.ports``. Unlike its
sibling ``feedback_repository.py``, this context does not own the ``runs``
table and writes no SQL against it: it asks its one question through the
component the run context already provides.

Being the downstream consumer of an upstream context is the normal shape
here, not debt. Until that context publishes a contract of its own, a thin
translation layer is what keeps its wide interface -- and its untyped dict
rows -- out of the domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deerflow.domain.feedback.ports import RunLookup

if TYPE_CHECKING:
    from deerflow.runtime.runs.store import RunStore


class RunStoreRunLookup(RunLookup):
    """Adapts the framework ``RunStore`` (wide interface) to the narrow
    ``RunLookup`` port -- reuses the existing lookup, no new SQL.

    Used by the service to confirm a run belongs to the thread before
    writing feedback. That is referential integrity, not authorization:
    the router's ``@require_permission(..., owner_check=True)`` proves the
    caller owns the thread, and this check proves the run belongs to it --
    only together do they establish that the caller owns the run. Which is
    why the port takes no ``user_id``.

    TODO(hexagonal): this depends on ``RunStore``, an infrastructure
    component, rather than on a contract published by the run context --
    that context has not been through a hexagonal slice yet. When it
    publishes one (a DTO, not its aggregate and not its repository),
    replace the body of this class. The ``RunLookup`` port does not move.
    """

    def __init__(self, run_store: RunStore) -> None:
        self._run_store = run_store

    async def thread_of(self, run_id: str) -> str | None:
        run = await self._run_store.get(run_id)
        return run.get("thread_id") if run else None
