"""Centralized accessors for singleton objects stored on ``app.state``.

**Getters** (used by routers): raise 503 when a required dependency is
missing, except ``get_store`` which returns ``None``.

``AppConfig`` is intentionally *not* cached on ``app.state``. Routers and the
run path resolve it through :func:`deerflow.config.app_config.get_app_config`,
which performs mtime-based hot reload, so edits to ``config.yaml`` take
effect on the next request without a process restart. The engines created in
:func:`langgraph_runtime` (stream bridge, persistence, checkpointer, store,
run-event store) accept a ``startup_config`` snapshot — they are
restart-required by design and stay bound to that snapshot to keep the live
process consistent with itself.

Initialization is handled directly in ``app.py`` via :class:`AsyncExitStack`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, TypeVar, cast

from fastapi import FastAPI, HTTPException, Request
from langgraph.types import Checkpointer

from deerflow.community.browser_automation.session import browser_multi_worker_error
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.persistence.feedback import FeedbackRepository
from deerflow.runtime import RunContext, RunManager, StreamBridge
from deerflow.runtime.events.store.base import RunEventStore
from deerflow.runtime.runs.store.base import RunStore

logger = logging.getLogger(__name__)

# Upper bound (seconds) for draining in-flight runs during shutdown, before the
# AsyncExitStack tears down the checkpointer (and its connection pool). Kept
# local to avoid an app -> deps -> app import cycle. This is a *separate* budget
# from ``app.gateway.app._SHUTDOWN_HOOK_TIMEOUT_SECONDS`` (currently also 5.0s,
# which bounds channel-service stop): the two govern independent teardown steps
# and may diverge, but both count toward the lifespan shutdown window — revisit
# them together if their sum must stay within the server's graceful-shutdown
# timeout.
_RUN_DRAIN_TIMEOUT_SECONDS = 5.0


def _browser_tools_enabled_in_config(config: AppConfig) -> bool:
    """Return whether process-local agentic browser sessions are configured."""
    get_tool_config = getattr(config, "get_tool_config", None)
    if callable(get_tool_config):
        return get_tool_config("browser_navigate") is not None
    return any(getattr(tool, "name", None) == "browser_navigate" for tool in (getattr(config, "tools", None) or []))


def _enforce_postgres_for_multi_worker(config: AppConfig) -> None:
    """Refuse unsafe multi-worker configurations before persistence starts.

    Three checks (all must pass for multi-worker):

    1. Process-local browser sessions must be disabled. Browser tools keep
       Chromium and Playwright objects in one worker's memory, while ordinary
       uvicorn dispatch provides no thread-id affinity.
    2. The DB backend must be Postgres — SQLite write-locks cannot support
       concurrent multi-process access.
    3. ``run_ownership.heartbeat_enabled`` must be True — without heartbeat,
       every run has a NULL lease, so reconciliation treats all inflight
       runs as orphans and Worker B would kill Worker A's live runs on
       every rolling update or scale-up.

    This gate runs once at startup before any persistence engine is
    initialised so the error message is clear and the process exits
    immediately.
    """
    try:
        workers = int(os.environ.get("GATEWAY_WORKERS", "1"))
    except (TypeError, ValueError):
        workers = 1

    if workers <= 1:
        return

    if _browser_tools_enabled_in_config(config):
        raise SystemExit(browser_multi_worker_error(workers))

    backend = getattr(config.database, "backend", None)
    if backend != "postgres":
        raise SystemExit(f"GATEWAY_WORKERS={workers} requires database.backend='postgres', but database.backend is '{backend}'. SQLite cannot support concurrent multi-process access. Set GATEWAY_WORKERS=1 or switch to Postgres.")

    run_ownership = getattr(config, "run_ownership", None)
    if run_ownership is None or not run_ownership.heartbeat_enabled:
        raise SystemExit(
            f"GATEWAY_WORKERS={workers} requires run_ownership.heartbeat_enabled=true. "
            "Without heartbeat, every run has a NULL lease, so reconciliation "
            "treats all inflight runs as orphans — Worker B would kill Worker A's "
            "live runs on every rolling update or scale-up. "
            "Set run_ownership.heartbeat_enabled=true in config.yaml."
        )


def _validate_agent_storage(config: AppConfig) -> None:
    """Fail fast on an agent-storage backend the database cannot support.

    ``agent_storage.backend: db`` needs a durable, shared SQL database — a
    ``memory`` database is per-process, so agent definitions would silently
    diverge across nodes (and there is no SQL URL to open). Mirrors deermem's
    create_storage fail-fast and the multi-worker gate above.

    Also warns when a multi-worker Postgres deployment leaves agent storage on
    ``file``: custom agents created on one node's local disk are invisible to
    the others, exactly the divergence the db backend exists to fix.
    """
    agent_storage = getattr(config, "agent_storage", None)
    backend = getattr(agent_storage, "backend", "file")
    db_backend = getattr(getattr(config, "database", None), "backend", None)
    if backend == "db" and db_backend not in ("sqlite", "postgres"):
        raise SystemExit(
            f"agent_storage.backend='db' requires database.backend to be 'sqlite' or 'postgres', "
            f"but database.backend is '{db_backend}'. A 'memory' database is per-process and cannot "
            "share agent definitions across nodes. Set database.backend, or use agent_storage.backend='file'."
        )
    try:
        workers = int(os.environ.get("GATEWAY_WORKERS", "1"))
    except (TypeError, ValueError):
        workers = 1
    if workers > 1 and db_backend == "postgres" and backend == "file":
        logger.warning(
            "GATEWAY_WORKERS=%s with database.backend='postgres' but agent_storage.backend='file': custom agents are stored per-node on local disk and are not visible across workers/nodes. Set agent_storage.backend='db' to share them.",
            workers,
        )


async def _drain_inflight_runs(run_manager: RunManager) -> None:
    """Drain in-flight runs before the checkpointer is torn down (issue #3373).

    Shields the (internally-bounded) drain so that even if the lifespan
    coroutine is itself cancelled mid-shutdown — a second SIGINT or the server's
    graceful-shutdown timeout, i.e. the same signal storm behind #3373 — the
    checkpointer pool is not closed while run tasks are still writing
    checkpoints. On such a cancellation we let the already-running drain finish
    (it is bounded by ``RunManager.shutdown``'s own timeout) and then propagate
    the cancellation.
    """
    drain = asyncio.create_task(run_manager.shutdown(timeout=_RUN_DRAIN_TIMEOUT_SECONDS))
    try:
        await asyncio.shield(drain)
    except asyncio.CancelledError:
        # Re-shield so this second wait does not abandon the in-flight drain;
        # it is bounded, so this cannot hang. Then re-raise to honour shutdown.
        try:
            await asyncio.shield(drain)
        except Exception:
            logger.exception("In-flight run drain failed after shutdown cancellation")
        raise
    except Exception:
        logger.exception("Failed to drain in-flight runs during shutdown")


async def _publish_recovered_run_stream_end(
    bridge: StreamBridge,
    recovered_runs: list[RunRecord],
    *,
    cleanup_delay: float = 60.0,
) -> None:
    """Terminate retained streams for runs recovered as orphaned at startup."""
    for record in recovered_runs:
        stream_exists = getattr(bridge, "stream_exists", None)
        if stream_exists is not None:
            try:
                if not await stream_exists(record.run_id):
                    logger.debug("Skipping recovered stream end for %s: stream already expired", record.run_id)
                    continue
            except Exception:
                logger.debug("Failed to check recovered stream existence for %s", record.run_id, exc_info=True)
        try:
            await bridge.publish_end(record.run_id)
        except Exception:
            logger.warning(
                "Failed to publish recovered run stream end for %s",
                record.run_id,
                exc_info=True,
            )
            continue
        task = asyncio.create_task(bridge.cleanup(record.run_id, delay=cleanup_delay))
        task.add_done_callback(lambda task, run_id=record.run_id: _log_recovered_stream_cleanup_result(task, run_id))


def _log_recovered_stream_cleanup_result(task: asyncio.Task[None], run_id: str) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.warning("Failed to clean up recovered run stream for %s", run_id, exc_info=True)


if TYPE_CHECKING:
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.thread_meta.base import ThreadMetaStore
    from deerflow.runtime import RunRecord


T = TypeVar("T")


async def _mark_latest_recovered_threads_error(
    run_manager: RunManager,
    thread_store: ThreadMetaStore,
    recovered_runs: list[RunRecord],
) -> None:
    """Mark thread status as error only when its newest run was recovered."""
    recovered_by_thread: dict[str, set[str]] = {}
    for record in recovered_runs:
        recovered_by_thread.setdefault(record.thread_id, set()).add(record.run_id)

    for thread_id, recovered_run_ids in recovered_by_thread.items():
        try:
            latest_runs = await run_manager.list_by_thread(thread_id, user_id=None, limit=1)
        except Exception:
            logger.warning("Failed to find latest run for thread %s during run reconciliation", thread_id, exc_info=True)
            continue
        if not latest_runs or latest_runs[0].run_id not in recovered_run_ids:
            continue
        try:
            await thread_store.update_status(thread_id, "error", user_id=None)
        except Exception:
            logger.warning("Failed to mark thread %s as error during run reconciliation", thread_id, exc_info=True)


def get_config() -> AppConfig:
    """Return the freshest ``AppConfig`` for the current request.

    Routes through :func:`deerflow.config.app_config.get_app_config`, which
    honours runtime ``ContextVar`` overrides and reloads ``config.yaml`` from
    disk when its mtime changes. ``AppConfig`` is not cached on ``app.state``
    at all — the only startup-time snapshot lives as a local
    ``startup_config`` variable inside ``lifespan()`` and is passed
    explicitly into :func:`langgraph_runtime` for the engines that are
    restart-required by design. Routing every request through
    :func:`get_app_config` closes the bytedance/deer-flow issue #3107 BUG-001
    split-brain where the worker / lead-agent thread saw a stale startup
    snapshot.

    Hot-reload boundary: fields backed by startup-time singletons
    (engines, sandbox provider, IM channels, logging handler) require a
    process restart to change at runtime. The authoritative list lives in
    :mod:`deerflow.config.reload_boundary` and is mirrored by the
    standardised ``"startup-only:"`` prefix on the matching
    ``Field(description=...)`` in :class:`AppConfig` — IDE hover on those
    fields will surface the boundary inline. See
    ``backend/CLAUDE.md`` "Config Hot-Reload Boundary" for the operator
    summary.

    Any failure to materialise the config (missing file, permission denied,
    YAML parse error, validation error) is reported as 503 — semantically
    "the gateway cannot serve requests without a usable configuration" — and
    logged with the original exception so operators have something to debug.
    """
    try:
        return get_app_config()
    except Exception as exc:  # noqa: BLE001 - request boundary: log and degrade gracefully
        logger.exception("Failed to load AppConfig at request time")
        raise HTTPException(status_code=503, detail="Configuration not available") from exc


@asynccontextmanager
async def langgraph_runtime(app: FastAPI, startup_config: AppConfig) -> AsyncGenerator[None, None]:
    """Bootstrap and tear down all LangGraph runtime singletons.

    ``startup_config`` is the ``AppConfig`` snapshot taken once during
    ``lifespan()`` for one-shot infrastructure bootstrap. The engines and
    stores constructed here (stream bridge, persistence engine, checkpointer,
    store, run-event store) are restart-required by design — they hold live
    connections, file handles, or singleton providers — so they bind to this
    snapshot and survive across `config.yaml` edits. Request-time consumers
    must still go through :func:`get_config` for any field that should be
    hot-reloadable. See ``backend/CLAUDE.md`` "Config Hot-Reload Boundary".

    The matching ``run_events_config`` is frozen onto ``app.state`` so
    :func:`get_run_context` pairs a freshly-loaded ``AppConfig`` with the
    *startup-time* run-events configuration the underlying ``event_store``
    was built from — otherwise the runtime could end up combining a live
    new ``run_events_config`` with an event store still bound to the
    previous backend.

    Usage in ``app.py``::

        async with langgraph_runtime(app, startup_config):
            yield
    """
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.runtime import make_store, make_stream_bridge
    from deerflow.runtime.checkpoint_mode import freeze_checkpoint_channel_mode
    from deerflow.runtime.checkpointer.async_provider import make_checkpointer
    from deerflow.runtime.events.store import make_run_event_store

    # ------------------------------------------------------------------
    # Multi-worker safety gate: reject SQLite when GATEWAY_WORKERS > 1.
    # SQLite write-locks cannot support concurrent multi-process access.
    # ------------------------------------------------------------------
    _enforce_postgres_for_multi_worker(startup_config)
    # Reject agent_storage.backend='db' on a non-durable database, and warn on
    # node-divergent file storage under multi-worker Postgres.
    _validate_agent_storage(startup_config)

    async with AsyncExitStack() as stack:
        config = startup_config
        app.state.checkpoint_channel_mode = freeze_checkpoint_channel_mode(config.database.checkpoint_channel_mode)

        app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge(config))

        # Initialize persistence engine BEFORE checkpointer so that
        # auto-create-database logic runs first (postgres backend).
        await init_engine_from_config(config.database)

        app.state.checkpointer = await stack.enter_async_context(make_checkpointer(config))
        app.state.store = await stack.enter_async_context(make_store(config))

        # Initialize repositories — one get_session_factory() call for all.
        sf = get_session_factory()
        if sf is not None:
            from deerflow.persistence.feedback import FeedbackRepository
            from deerflow.persistence.run import RunRepository

            app.state.run_store = RunRepository(sf)
            app.state.feedback_repo = FeedbackRepository(sf)
        else:
            from deerflow.runtime.runs.store.memory import MemoryRunStore

            app.state.run_store = MemoryRunStore()
            app.state.feedback_repo = None

        from deerflow.persistence.thread_meta import make_thread_store

        app.state.thread_store = make_thread_store(sf, app.state.store)
        if sf is not None:
            from deerflow.persistence.scheduled_task_runs import (
                ScheduledTaskRunRepository,
            )
            from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

            app.state.scheduled_task_repo = ScheduledTaskRepository(sf)
            app.state.scheduled_task_run_repo = ScheduledTaskRunRepository(sf)
        else:
            app.state.scheduled_task_repo = None
            app.state.scheduled_task_run_repo = None

        # Run event store. The store and the matching ``run_events_config`` are
        # both frozen at startup so ``get_run_context`` does not combine a
        # freshly-reloaded ``AppConfig.run_events`` with a store still bound to
        # the previous backend.
        run_events_config = getattr(config, "run_events", None)
        app.state.run_events_config = run_events_config
        app.state.run_event_store = make_run_event_store(run_events_config)

        # RunManager with store backing for persistence
        run_ownership_config = getattr(config, "run_ownership", None)
        app.state.run_manager = RunManager(
            store=app.state.run_store,
            run_ownership_config=run_ownership_config,
        )
        # Startup recovery: mark inflight runs whose lease has expired as error.
        # In single-worker mode (SQLite / backend=memory), no run has a lease, so
        # all inflight rows are reclaimed (unchanged behaviour). In multi-worker
        # mode (Postgres), only runs with an expired lease are reclaimed; runs
        # owned by another live worker are skipped.
        from deerflow.utils.time import now_iso

        recovered_runs = await app.state.run_manager.reconcile_orphaned_inflight_runs(
            error="Gateway restarted before this run reached a durable final state.",
            before=now_iso(),
        )
        sb_config = getattr(config, "stream_bridge", None)
        cleanup_delay = getattr(sb_config, "recovered_stream_cleanup_delay_seconds", 60.0) if sb_config else 60.0
        await _publish_recovered_run_stream_end(app.state.stream_bridge, recovered_runs, cleanup_delay=cleanup_delay)
        await _mark_latest_recovered_threads_error(app.state.run_manager, app.state.thread_store, recovered_runs)

        # Start the lease heartbeat if enabled (multi-worker deployments).
        await app.state.run_manager.start_heartbeat()

        try:
            yield
        finally:
            # Drain in-flight run tasks BEFORE the AsyncExitStack tears down the
            # checkpointer (and its connection pool). A run still mid-graph would
            # otherwise leak into asyncio.run() shutdown, where langgraph's
            # _checkpointer_put_after_previous aput races the closed pool and
            # raises PoolClosed (issue #3373).
            run_manager = getattr(app.state, "run_manager", None)
            if run_manager is not None:
                await _drain_inflight_runs(run_manager)
            await close_engine()


# ---------------------------------------------------------------------------
# Getters – called by routers per-request
# ---------------------------------------------------------------------------


def _require(attr: str, label: str) -> Callable[[Request], T]:
    """Create a FastAPI dependency that returns ``app.state.<attr>`` or 503."""

    def dep(request: Request) -> T:
        val = getattr(request.app.state, attr, None)
        if val is None:
            raise HTTPException(status_code=503, detail=f"{label} not available")
        return cast(T, val)

    dep.__name__ = dep.__qualname__ = f"get_{attr}"
    return dep


get_stream_bridge: Callable[[Request], StreamBridge] = _require("stream_bridge", "Stream bridge")
get_run_manager: Callable[[Request], RunManager] = _require("run_manager", "Run manager")
get_checkpointer: Callable[[Request], Checkpointer] = _require("checkpointer", "Checkpointer")
get_run_event_store: Callable[[Request], RunEventStore] = _require("run_event_store", "Run event store")
get_feedback_repo: Callable[[Request], FeedbackRepository] = _require("feedback_repo", "Feedback")
get_run_store: Callable[[Request], RunStore] = _require("run_store", "Run store")


def get_store(request: Request):
    """Return the global store (may be ``None`` if not configured)."""
    return getattr(request.app.state, "store", None)


def get_thread_store(request: Request) -> ThreadMetaStore:
    """Return the thread metadata store (SQL or memory-backed)."""
    val = getattr(request.app.state, "thread_store", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Thread metadata store not available")
    return val


def get_scheduled_task_repo(request: Request):
    val = getattr(request.app.state, "scheduled_task_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task repo not available")
    return val


def get_scheduled_task_run_repo(request: Request):
    val = getattr(request.app.state, "scheduled_task_run_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task run repo not available")
    return val


def get_scheduled_task_service(request: Request):
    val = getattr(request.app.state, "scheduled_task_service", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task service not available")
    return val


def get_run_context(request: Request) -> RunContext:
    """Build a :class:`RunContext` from ``app.state`` singletons.

    Returns a *base* context with infrastructure dependencies. The
    ``app_config`` field is resolved live so per-run fields (e.g.
    ``models[*].max_tokens``) follow ``config.yaml`` edits; the
    ``event_store`` / ``run_events_config`` pair stays frozen to the snapshot
    captured in :func:`langgraph_runtime` so callers never see a store bound
    to one backend paired with a config pointing at another.
    """
    return RunContext(
        checkpointer=get_checkpointer(request),
        store=get_store(request),
        event_store=get_run_event_store(request),
        run_events_config=getattr(request.app.state, "run_events_config", None),
        checkpoint_channel_mode=getattr(request.app.state, "checkpoint_channel_mode", "full"),
        thread_store=get_thread_store(request),
        app_config=get_config(),
        on_run_completed=getattr(request.app.state, "scheduled_task_service", None).handle_run_completion if getattr(request.app.state, "scheduled_task_service", None) is not None else None,
    )


# ---------------------------------------------------------------------------
# Auth helpers (used by authz.py and auth middleware)
# ---------------------------------------------------------------------------

# Cached singletons to avoid repeated instantiation per request
_cached_local_provider: LocalAuthProvider | None = None
_cached_repo: SQLiteUserRepository | None = None


def get_local_provider() -> LocalAuthProvider:
    """Get or create the cached LocalAuthProvider singleton.

    Must be called after ``init_engine_from_config()`` — the shared
    session factory is required to construct the user repository.
    """
    global _cached_local_provider, _cached_repo
    if _cached_repo is None:
        from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
        from deerflow.persistence.engine import get_session_factory

        sf = get_session_factory()
        if sf is None:
            raise RuntimeError("get_local_provider() called before init_engine_from_config(); cannot access users table")
        _cached_repo = SQLiteUserRepository(sf)
    if _cached_local_provider is None:
        from app.gateway.auth.local_provider import LocalAuthProvider

        _cached_local_provider = LocalAuthProvider(repository=_cached_repo)
    return _cached_local_provider


async def get_current_user_from_request(request: Request):
    """Get the current authenticated user from the request cookie.

    Raises HTTPException 401 if not authenticated.
    """
    state = getattr(request, "state", None)
    state_user = getattr(state, "user", None)
    from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL, AUTH_SOURCE_SESSION

    if state_user is not None and getattr(state, "auth_source", None) in {
        AUTH_SOURCE_SESSION,
        AUTH_SOURCE_AUTH_DISABLED,
        AUTH_SOURCE_INTERNAL,
    }:
        return state_user

    from app.gateway.auth import decode_token
    from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse, TokenError, token_error_to_code

    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.NOT_AUTHENTICATED, message="Not authenticated").model_dump(),
        )

    payload = decode_token(access_token)
    if isinstance(payload, TokenError):
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=token_error_to_code(payload), message=f"Token error: {payload.value}").model_dump(),
        )

    provider = get_local_provider()
    user = await provider.get_user(payload.sub)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.USER_NOT_FOUND, message="User not found").model_dump(),
        )

    # Token version mismatch → password was changed, token is stale
    if user.token_version != payload.ver:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.TOKEN_INVALID, message="Token revoked (password changed)").model_dump(),
        )

    return user


async def require_admin_user(request: Request, *, detail: str) -> None:
    """Require the authenticated caller to be an admin user.

    ``AuthMiddleware`` normally stamps ``request.state.user`` before the request
    reaches a router. Falling back to the strict dependency keeps the route safe
    in tests or alternative ASGI compositions that mount a router without the
    global middleware. ``detail`` is the route-specific 403 message.

    Centralising this here means a future change to the admin definition (e.g.
    allowing an internal system role, adding audit logging, or switching to a
    permission-based check) lands in one place instead of drifting across the
    per-router copies that previously existed in ``mcp``, ``channel_connections``
    and ``channels``.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        user = await get_current_user_from_request(request)

    if getattr(user, "system_role", None) != "admin":
        raise HTTPException(status_code=403, detail=detail)


async def get_optional_user_from_request(request: Request):
    """Get optional authenticated user from request.

    Returns None if not authenticated.
    """
    try:
        return await get_current_user_from_request(request)
    except HTTPException:
        return None


async def get_current_user(request: Request) -> str | None:
    """Extract user_id from request cookie, or None if not authenticated.

    Thin adapter that returns the string id for callers that only need
    identification (e.g., ``feedback.py``). Full-user callers should use
    ``get_current_user_from_request`` or ``get_optional_user_from_request``.
    """
    user = await get_optional_user_from_request(request)
    return str(user.id) if user else None
