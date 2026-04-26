"""Runtime utilities for thread_id resolution and context access.

Thread ID Resolution Strategy
=============================

DeerFlow resolves the current ``thread_id`` from a three-level cascade:

1. **runtime.context["thread_id"]** -- Set by ``worker.py`` (gateway mode)
   or by LangGraph Server (standard mode) when constructing the Runtime.
2. **runtime.config["configurable"]["thread_id"]** -- Available on
   ``ToolRuntime`` instances passed to tools via the ``@tool`` decorator.
   Not available on ``Runtime`` instances received by middlewares.
3. **get_config()["configurable"]["thread_id"]** -- LangGraph's thread-local
   config, available when executing inside a graph's runnable context.

About ``__pregel_runtime``
===========================

In gateway mode (``run_agent()`` in ``worker.py``), the agent graph does not
run inside the LangGraph Server.  The server normally injects a ``Runtime``
object automatically.  Since we run the graph ourselves, we must inject the
Runtime manually via ``config["configurable"]["__pregel_runtime"]``.  This is
the standard mechanism provided by LangGraph's Pregel engine for injecting
runtime context into graph nodes.  It is not a private/internal hack -- it is
the documented way to pass Runtime when running a graph outside the server.

Duck Typing
===========

Both ``langgraph.runtime.Runtime`` (middlewares) and
``langchain.tools.ToolRuntime`` (tools) expose a ``.context`` attribute (a
dict or None).  ``ToolRuntime`` additionally exposes ``.config``.  The
function below uses ``getattr`` with safe defaults so it works with either
type, with ``SimpleNamespace`` in tests, or with ``None``.
"""

from __future__ import annotations

from typing import Any


def get_thread_id(runtime: Any | None) -> str | None:
    """Resolve the current thread_id from a runtime object.

    Follows a three-level fallback chain:

    1. ``runtime.context.get("thread_id")`` -- if context is a non-empty dict.
    2. ``runtime.config.get("configurable", {}).get("thread_id")`` -- if
       the runtime has a config dict (ToolRuntime).
    3. ``get_config().get("configurable", {}).get("thread_id")`` -- LangGraph's
       thread-local config.  Wrapped in ``try/except RuntimeError`` because it
       raises outside a runnable context (e.g., unit tests).

    Args:
        runtime: A Runtime, ToolRuntime, SimpleNamespace, or None.

    Returns:
        The thread_id string, or None if it cannot be resolved.
    """
    if runtime is None:
        return None

    # Level 1: runtime.context["thread_id"]
    context = getattr(runtime, "context", None)
    if context and isinstance(context, dict):
        thread_id = context.get("thread_id")
        if thread_id:
            return thread_id

    # Level 2: runtime.config["configurable"]["thread_id"]
    config = getattr(runtime, "config", None)
    if config and isinstance(config, dict):
        thread_id = config.get("configurable", {}).get("thread_id")
        if thread_id:
            return thread_id

    # Level 3: langgraph.config.get_config() -- only works inside runnable context
    try:
        from langgraph.config import get_config

        config_data = get_config()
        thread_id = config_data.get("configurable", {}).get("thread_id")
        if thread_id:
            return thread_id
    except RuntimeError:
        # Expected when not running inside a LangGraph runnable context (e.g., unit tests).
        # In that case, thread_id cannot be resolved from thread-local config, so fall through.
        pass

    return None
