"""Bridge between LangGraph's runtime context and the task-scoped store.

Middlewares run inside the agent graph and can only reach host state through
``request.runtime``. The host installs the task store under a host-owned key;
extensions read it through this helper and keep their own objects *inside* the
store, so two extensions cannot collide on a runtime-context key.
"""

from __future__ import annotations

from collections.abc import Mapping

from deerflow_extension_api.state import ExtensionData

#: Host-owned key. Extensions must not write to the runtime context directly.
EXTENSION_TASK_STORE_KEY = "__deerflow_extension_task_store"


def task_store_from_runtime(runtime: object) -> ExtensionData | None:
    """Return the task-scoped store, or None when there is no live task."""
    context = getattr(runtime, "context", None)
    if not isinstance(context, Mapping):
        return None
    store = context.get(EXTENSION_TASK_STORE_KEY)
    return store if isinstance(store, ExtensionData) else None
