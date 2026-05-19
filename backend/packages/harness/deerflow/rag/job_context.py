"""Background-job context manager (Sprint B.4).

Why
---
The Sprint B dispatcher runs each indexing job as an ``asyncio.Task``
spun up by a long-lived worker. ``contextvars`` are *task-local*: when
``asyncio.create_task`` snapshots the worker's context, it copies the
**worker's** state, not the request that originally enqueued the job.
The worker's context is whatever was set when the dispatcher started —
typically empty. That means a job pulled off the queue has **no
tenant_id, no user_id**, even though the request that submitted it
clearly did.

If we let ``execute_index_job`` run with empty context:

* The Chroma backend would fall back to the ``"default"`` tenant
  collection, mixing every tenant's vectors into one bucket.
* Repository calls would resolve ``user_id=AUTO`` to a missing user
  and crash mid-job — better than silent cross-tenant write, but still
  the wrong failure mode.

``with_kb_context`` is the seam where the dispatcher re-establishes the
tenant + user context that was in scope when the job was *submitted*.
The values are carried on the ``IndexJobRequest`` (captured at
``submit`` time, see ``deerflow.knowledge_base.dispatcher``) and
restored inside the worker before each job runs.

Asyncio semantics recap
-----------------------
``ContextVar.set`` returns a :class:`~contextvars.Token`; passing it
back to ``ContextVar.reset`` restores the *exact* prior state — not
just "default". This is the only correct way to scope a contextvar
override to a function body. The setters in
``deerflow.config.tenant`` and ``deerflow.runtime.user_context``
already return tokens; ``with_kb_context`` is just the discipline
that makes sure no caller forgets to reset.
"""

from __future__ import annotations

import contextlib
from typing import AsyncIterator

from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    reset_tenant_id,
    set_current_tenant_id,
)


@contextlib.asynccontextmanager
async def with_kb_context(
    *,
    tenant_id: str | None,
    user_id: str | None = None,
) -> AsyncIterator[None]:
    """Restore tenant + user context for a background indexing job.

    Pass the values captured when the job was *submitted* (not the
    worker's empty context). On exit the prior values are restored via
    the :class:`~contextvars.Token` returned by each setter — neither
    leaks into the next job picked off the queue.

    ``tenant_id`` is required for KB jobs because the Chroma backend
    derives the per-tenant collection prefix from the contextvar; an
    empty / "default" tenant in production indicates a bug, not a
    valid state.

    ``user_id`` is optional: not every code path that calls into KB
    write operations needs the per-user filter (e.g. an admin-triggered
    reindex-all dispatched on behalf of a tenant). Pass it when the
    enqueueing request had it.
    """
    if not tenant_id or tenant_id == _DEFAULT_TENANT_ID:
        raise ValueError(
            "with_kb_context requires a real tenant_id; got "
            f"{tenant_id!r}. Background indexing jobs must carry the "
            "submitter's tenant — falling back to the 'default' bucket "
            "would mix vectors across tenants."
        )

    tenant_token = set_current_tenant_id(tenant_id)

    user_token = None
    if user_id:
        # Lazy import keeps the runtime/user_context import out of the
        # tenant-only call path, which the unit tests exercise without
        # an auth context.
        from deerflow.runtime.user_context import _current_user

        # We carry the id as a structural CurrentUser by wrapping it in
        # a tiny shim object — set_current_user expects something with
        # an `id` attribute.
        class _BgUser:
            __slots__ = ("id",)

            def __init__(self, uid: str) -> None:
                self.id = uid

        user_token = _current_user.set(_BgUser(user_id))

    try:
        yield
    finally:
        if user_token is not None:
            from deerflow.runtime.user_context import _current_user

            _current_user.reset(user_token)
        reset_tenant_id(tenant_token)
