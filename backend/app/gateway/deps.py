"""Centralized accessors for singleton objects stored on ``app.state``.

**Getters** (used by routers): raise 503 when a required dependency is
missing, except ``get_store`` and ``get_thread_meta_repo`` which return
``None``.

Initialization is handled directly in ``app.py`` via :class:`AsyncExitStack`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from deerflow.runtime import RunContext, RunManager


@asynccontextmanager
async def langgraph_runtime(app: FastAPI) -> AsyncGenerator[None, None]:
    """Bootstrap and tear down all LangGraph runtime singletons.

    Usage in ``app.py``::

        async with langgraph_runtime(app):
            yield
    """
    from deerflow.agents.checkpointer.async_provider import make_checkpointer
    from deerflow.config import get_app_config
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.runtime import make_store, make_stream_bridge
    from deerflow.runtime.events.store import make_run_event_store

    async with AsyncExitStack() as stack:
        app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge())

        # Initialize persistence engine BEFORE checkpointer so that
        # auto-create-database logic runs first (postgres backend).
        config = get_app_config()
        await init_engine_from_config(config.database)

        app.state.checkpointer = await stack.enter_async_context(make_checkpointer())
        app.state.store = await stack.enter_async_context(make_store())

        # Initialize repositories — one get_session_factory() call for all.
        sf = get_session_factory()
        if sf is not None:
            from deerflow.persistence.feedback import FeedbackRepository
            from deerflow.persistence.run import RunRepository
            from deerflow.persistence.thread_meta import ThreadMetaRepository

            app.state.run_store = RunRepository(sf)
            app.state.feedback_repo = FeedbackRepository(sf)
            app.state.thread_meta_repo = ThreadMetaRepository(sf)
        else:
            from deerflow.persistence.thread_meta import MemoryThreadMetaStore
            from deerflow.runtime.runs.store.memory import MemoryRunStore

            app.state.run_store = MemoryRunStore()
            app.state.feedback_repo = None
            app.state.thread_meta_repo = MemoryThreadMetaStore(app.state.store)

        # Run event store (has its own factory with config-driven backend selection)
        run_events_config = getattr(config, "run_events", None)
        app.state.run_event_store = make_run_event_store(run_events_config)

        # RunManager with store backing for persistence
        app.state.run_manager = RunManager(store=app.state.run_store)

        try:
            yield
        finally:
            await close_engine()


# ---------------------------------------------------------------------------
# Getters -- called by routers per-request
# ---------------------------------------------------------------------------


def _require(attr: str, label: str):
    """Create a FastAPI dependency that returns ``app.state.<attr>`` or 503."""

    def dep(request: Request):
        val = getattr(request.app.state, attr, None)
        if val is None:
            raise HTTPException(status_code=503, detail=f"{label} not available")
        return val

    dep.__name__ = dep.__qualname__ = f"get_{attr}"
    return dep


get_stream_bridge = _require("stream_bridge", "Stream bridge")
get_run_manager = _require("run_manager", "Run manager")
get_checkpointer = _require("checkpointer", "Checkpointer")
get_run_event_store = _require("run_event_store", "Run event store")
get_feedback_repo = _require("feedback_repo", "Feedback")
get_run_store = _require("run_store", "Run store")


def get_store(request: Request):
    """Return the global store (may be ``None`` if not configured)."""
    return getattr(request.app.state, "store", None)


get_thread_meta_repo = _require("thread_meta_repo", "Thread metadata store")


def get_run_context(request: Request) -> RunContext:
    """Build a :class:`RunContext` from ``app.state`` singletons.

    Returns a *base* context with infrastructure dependencies.  Callers that
    need per-run fields (e.g. ``follow_up_to_run_id``) should use
    ``dataclasses.replace(ctx, follow_up_to_run_id=...)`` before passing it
    to :func:`run_agent`.
    """
    from deerflow.config import get_app_config

    return RunContext(
        checkpointer=get_checkpointer(request),
        store=get_store(request),
        event_store=get_run_event_store(request),
        run_events_config=getattr(get_app_config(), "run_events", None),
        thread_meta_repo=get_thread_meta_repo(request),
    )


async def get_current_user(request: Request) -> str | None:
    """Extract user identity from request.

    Phase 2: always returns None (no authentication).
    Phase 3: extract user_id from JWT / session / API key header.
    """
    return None
