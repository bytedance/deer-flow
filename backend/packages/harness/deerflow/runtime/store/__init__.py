"""Store provider for the DeerFlow runtime.

Re-exports the public API of both the async provider (for long-running
servers) and the sync provider (for CLI tools and the embedded client).

Async usage (FastAPI lifespan)::

    from deerflow.runtime.store import make_store

    async with make_store() as store:
        app.state.store = store

Sync usage (CLI / DeerFlowClient)::

    from deerflow.runtime.store import get_store, store_context

    store = get_store()                   # singleton
    with store_context() as store: ...    # one-shot
"""

from .async_provider import make_store
from .provider import get_store, reset_store, store_context

__all__ = [
    # async
    "make_store",
    # sync
    "get_store",
    "reset_store",
    "store_context",
]
