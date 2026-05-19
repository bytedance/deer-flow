"""Centralized accessors for singleton objects stored on ``app.state``.

**Getters** (used by routers): raise 503 when a required dependency is
missing, except ``get_store`` which returns ``None``.

Initialization is handled directly in ``app.py`` via :class:`AsyncExitStack`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any, TypeVar, cast

from fastapi import FastAPI, HTTPException, Request

from deerflow.config.app_config import AppConfig

from deerflow.runtime import RunContext

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.feedback import FeedbackRepository
    from deerflow.persistence.thread_meta.base import ThreadMetaStore
    from deerflow.runtime import RunManager, StreamBridge
    from deerflow.runtime.events.store.base import RunEventStore
    from deerflow.runtime.runs.store.base import RunStore
    from langgraph.types import Checkpointer
else:
    FeedbackRepository = Any
    RunManager = Any
    RunEventStore = Any
    RunStore = Any
    StreamBridge = Any
    Checkpointer = Any


T = TypeVar("T")


def get_config(request: Request) -> AppConfig:
    """Return the app-scoped ``AppConfig`` stored on ``app.state``."""
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise HTTPException(status_code=503, detail="Configuration not available")
    return config


@asynccontextmanager
async def langgraph_runtime(app: FastAPI) -> AsyncGenerator[None, None]:
    """Bootstrap and tear down all LangGraph runtime singletons.

    Usage in ``app.py``::

        async with langgraph_runtime(app):
            yield
    """
    from deerflow.agents.memory.storage import set_gateway_store, set_memory_storage
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.runtime import make_store, make_stream_bridge
    from deerflow.runtime.checkpointer.async_provider import make_checkpointer
    from deerflow.runtime.events.store import make_run_event_store

    async with AsyncExitStack() as stack:
        config = getattr(app.state, "config", None)
        if config is None:
            raise RuntimeError("langgraph_runtime() requires app.state.config to be initialized")

        # Initialize persistence engine BEFORE creating any singletons that
        # depend on it (checkpointer, store, repositories, auth providers).
        await init_engine_from_config(config.database)

        app.state.stream_bridge = await stack.enter_async_context(make_stream_bridge(config))
        app.state.checkpointer = await stack.enter_async_context(make_checkpointer(config))
        app.state.store = await stack.enter_async_context(make_store(config))

        # Wire the Store into memory storage so memory data shares the same
        # persistence backend and tenant isolation as threads.
        set_gateway_store(app.state.store)

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

        # Tenant repository (DB-backed, replaces JSON TenantStorage)
        if sf is not None:
            from deerflow.persistence.tenant import TenantRepository

            app.state.tenant_store = TenantRepository(sf)
        else:
            app.state.tenant_store = None

        # Agent repository (tenant-level agents)
        if sf is not None:
            from deerflow.persistence.agent import AgentPermissionRepository, AgentRepository, AgentUsageRepository

            app.state.agent_repo = AgentRepository(sf)
            app.state.agent_permission_repo = AgentPermissionRepository(sf)
            app.state.agent_usage_repo = AgentUsageRepository(sf)
        else:
            app.state.agent_repo = None
            app.state.agent_permission_repo = None
            app.state.agent_usage_repo = None

        # Tenant MCP Server repository
        if sf is not None:
            from deerflow.persistence.mcp_server import TenantMcpServerRepository

            app.state.tenant_mcp_repo = TenantMcpServerRepository(sf)
        else:
            app.state.tenant_mcp_repo = None

        # Tenant HTTP Connector repository
        if sf is not None:
            from deerflow.persistence.http_connector import TenantHttpConnectorRepository

            app.state.http_connector_repo = TenantHttpConnectorRepository(sf)
        else:
            app.state.http_connector_repo = None

        # Knowledge base service
        if sf is not None:
            from deerflow.config.rag_config import get_rag_config
            from deerflow.knowledge_base.dispatcher import IndexingDispatcher
            from deerflow.knowledge_base.service import KnowledgeBaseService
            from deerflow.persistence.knowledge_base.document_repository import DocumentRepository
            from deerflow.persistence.knowledge_base.index_job_repository import IndexJobRepository
            from deerflow.persistence.knowledge_base.permission_repository import KbPermissionRepository
            from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

            kb_repo = KnowledgeBaseRepository(sf)
            doc_repo = DocumentRepository(sf)
            job_repo = IndexJobRepository(sf)
            kb_service = KnowledgeBaseService(
                kb_repo=kb_repo,
                doc_repo=doc_repo,
                job_repo=job_repo,
                permission_repo=KbPermissionRepository(sf),
            )

            rag_cfg = get_rag_config()
            index_dispatcher = IndexingDispatcher(
                indexing_service=kb_service._indexing,
                kb_repo=kb_repo,
                doc_repo=doc_repo,
                workers=rag_cfg.indexing_workers,
                queue_max=rag_cfg.indexing_queue_max,
            )
            await index_dispatcher.start()
            kb_service.attach_dispatcher(index_dispatcher)
            stack.push_async_callback(index_dispatcher.aclose)
            try:
                recovered = await index_dispatcher.recover()
                if recovered:
                    logger.info("IndexingDispatcher recovered %d orphan job(s)", recovered)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("IndexingDispatcher recover() failed at startup: %s", exc)

            app.state.kb_service = kb_service
            app.state.index_dispatcher = index_dispatcher
            try:
                report = await kb_service.startup_consistency_check()
                logger.info(
                    "kb_service.startup_consistency_check: checked=%d marked_stale=%d errors=%d",
                    report.get("checked", 0),
                    report.get("marked_stale", 0),
                    report.get("errors", 0),
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "kb_service.startup_consistency_check failed: %s — startup continues", exc
                )
        else:
            app.state.kb_service = None
            app.state.index_dispatcher = None

        # Run event store (has its own factory with config-driven backend selection)
        run_events_config = getattr(config, "run_events", None)
        if run_events_config is not None and isinstance(run_events_config, dict):
            from deerflow.config.run_events_config import RunEventsConfig
            run_events_config = RunEventsConfig(**run_events_config)
        app.state.run_event_store = make_run_event_store(run_events_config)

        # Closure (closed-loop) service: ClosureRepository + publisher wired to
        # the same RunEventStore so closure.* events flow through the existing
        # SSE/poll plumbing. Skipped when no DB session factory is configured.
        if sf is not None:
            from deerflow.closed_loop.events import ClosureEventPublisher
            from deerflow.closed_loop.repository import ClosureRepository
            from deerflow.closed_loop.service import ClosureService
            from deerflow.closed_loop.service_factory import set_default_service

            app.state.closure_service = ClosureService(
                repository=ClosureRepository(sf),
                event_publisher=ClosureEventPublisher(app.state.run_event_store),
            )
            # Mirror the wired service onto the harness-side singleton so
            # builtin tools (which run in-process without a FastAPI request)
            # share the same repository + event publisher.
            set_default_service(app.state.closure_service)
        else:
            app.state.closure_service = None

        # RunManager with store backing for persistence
        from deerflow.runtime import RunManager as _RunManager

        app.state.run_manager = _RunManager(store=app.state.run_store)

        try:
            yield
        finally:
            set_gateway_store(None)
            set_memory_storage(None)
            try:
                from deerflow.closed_loop.service_factory import set_default_service

                set_default_service(None)
            except Exception:  # noqa: BLE001
                logger.debug("clearing closure service singleton failed", exc_info=True)
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


def get_agent_repo(request: Request):
    """Return the agent repository (may be None if DB not available)."""
    return getattr(request.app.state, "agent_repo", None)


def get_agent_permission_repo(request: Request):
    """Return the agent permission repository (may be None if DB not available)."""
    return getattr(request.app.state, "agent_permission_repo", None)


def get_tenant_mcp_repo(request: Request):
    """Return the tenant MCP server repository (may be None if DB not available)."""
    return getattr(request.app.state, "tenant_mcp_repo", None)


def get_closure_service(request: Request):
    """Return the closed-loop (closure) service, or 503 when DB is not available."""
    val = getattr(request.app.state, "closure_service", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Closure service not available")
    return val


def get_agent_usage_repo(request: Request):
    """Return the agent usage repository (may be None if DB not available)."""
    return getattr(request.app.state, "agent_usage_repo", None)


def get_store(request: Request):
    """Return the global store (may be ``None`` if not configured)."""
    return getattr(request.app.state, "store", None)


def get_thread_store(request: Request) -> ThreadMetaStore:
    """Return the thread metadata store (SQL or memory-backed)."""
    val = getattr(request.app.state, "thread_store", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Thread metadata store not available")
    return val


def get_tenant_store(request: Request):
    """Return the DB-backed tenant repository."""
    from deerflow.persistence.tenant import TenantRepository

    val: TenantRepository | None = getattr(request.app.state, "tenant_store", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Tenant store not available")
    return val


def get_run_context(request: Request) -> RunContext:
    """Build a :class:`RunContext` from ``app.state`` singletons.

    Returns a *base* context with infrastructure dependencies.
    """
    config = get_config(request)
    return RunContext(
        checkpointer=get_checkpointer(request),
        store=get_store(request),
        event_store=get_run_event_store(request),
        run_events_config=getattr(config, "run_events", None),
        thread_store=get_thread_store(request),
        app_config=config,
    )


# ---------------------------------------------------------------------------
# Auth helpers (used by authz.py and auth middleware)
# ---------------------------------------------------------------------------

# Cached singletons to avoid repeated instantiation per request
_cached_local_provider: LocalAuthProvider | None = None
_cached_repo: SQLiteUserRepository | None = None
_cached_ins_base_provider: object | None = None


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
            raise HTTPException(status_code=503, detail="Database not available — persistence engine not initialized")
        _cached_repo = SQLiteUserRepository(sf)
    if _cached_local_provider is None:
        from app.gateway.auth.local_provider import LocalAuthProvider

        _cached_local_provider = LocalAuthProvider(repository=_cached_repo)
    return _cached_local_provider


def get_ins_base_provider():
    """Get or create the cached InsBaseAuthProvider singleton.

    Returns None if RPC is not configured or the provider is not enabled.
    """
    global _cached_ins_base_provider

    from deerflow.config.auth_config import get_auth_config
    from app.gateway.auth.ins_base_provider import InsBaseAuthProvider
    from deerflow.rpc.rpc_client import get_rpc_client

    auth_config = get_auth_config()
    if auth_config.provider != "ins_base":
        return None

    if _cached_ins_base_provider is not None:
        return _cached_ins_base_provider

    rpc_client = get_rpc_client()
    if rpc_client is None:
        logger.warning("RPC client is not configured — InsBaseAuthProvider not available")
        return None

    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.tenant import TenantRepository

    sf = get_session_factory()
    tenant_repo = TenantRepository(sf) if sf else None

    _cached_ins_base_provider = InsBaseAuthProvider(
        rpc_client=rpc_client, tenant_repo=tenant_repo, session_factory=get_session_factory
    )
    return _cached_ins_base_provider


async def get_current_user_from_request(request: Request):
    """Get the current authenticated user from the request cookie.

    Raises HTTPException 401 if not authenticated.

    For the ``ins_base`` provider, validates the token via
    ``InsBaseAuthProvider.get_user()`` instead of decoding as a local JWT.
    """
    import logging

    from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
    from deerflow.config.auth_config import get_auth_config

    logger = logging.getLogger(__name__)
    request_path = getattr(getattr(request, "url", None), "path", "<unknown>")

    access_token = request.cookies.get("access_token")
    if not access_token:
        logger.warning("get_current_user_from_request: no access_token cookie for path=%s", request_path)
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.NOT_AUTHENTICATED, message="Not authenticated").model_dump(),
        )

    config = get_auth_config()
    if config.provider == "ins_base":
        from app.gateway.deps import get_ins_base_provider

        ins_provider = get_ins_base_provider()
        if ins_provider is None:
            raise HTTPException(
                status_code=503,
                detail=AuthErrorResponse(code=AuthErrorCode.PROVIDER_NOT_FOUND, message="ins-base auth provider not available").model_dump(),
            )

        user = await ins_provider.get_user(access_token)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail=AuthErrorResponse(code=AuthErrorCode.TOKEN_INVALID, message="Invalid or expired token").model_dump(),
            )

        from deerflow.config.tenant import set_current_tenant_id

        set_current_tenant_id(user.tenant_id)
        return user

    from app.gateway.auth import decode_token
    from app.gateway.auth.errors import TokenError, token_error_to_code

    payload = decode_token(access_token)
    if isinstance(payload, TokenError):
        logger.warning("get_current_user_from_request: TokenError=%s for path=%s", payload.value, request_path)
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=token_error_to_code(payload), message=f"Token error: {payload.value}").model_dump(),
        )

    # Set tenant context from the JWT payload so downstream code that relies
    # on get_current_tenant_id() sees the authenticated user's actual tenant.
    from deerflow.config.tenant import set_current_tenant_id

    set_current_tenant_id(payload.tenant_id)

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
