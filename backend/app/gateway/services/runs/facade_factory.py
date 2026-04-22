"""Facade factory - assembles RunsFacade with dependencies."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

from app.gateway.dependencies import get_checkpointer, get_stream_bridge
from deerflow.runtime.runs.facade import RunsFacade
from deerflow.runtime.runs.facade import RunsRuntime
from deerflow.runtime.runs.internal.execution.supervisor import RunSupervisor
from deerflow.runtime.runs.internal.planner import ExecutionPlanner
from deerflow.runtime.runs.internal.registry import RunRegistry
from deerflow.runtime.runs.internal.streams import RunStreamService
from deerflow.runtime.runs.internal.wait import RunWaitService

from app.infra.storage import StorageRunObserver, ThreadMetaStorage
from app.infra.storage.runs import RunDeleteRepository, RunReadRepository, RunWriteRepository
from .store import AppRunCreateStore, AppRunDeleteStore, AppRunQueryStore

if TYPE_CHECKING:
    from deerflow.runtime.stream_bridge import StreamBridge


type AgentFactory = Callable[..., object]


# Module-level singleton registry (shared across requests)
_registry: RunRegistry | None = None
_supervisor: RunSupervisor | None = None


def _get_state(request: Request, attr: str, label: str):
    value = getattr(request.app.state, attr, None)
    if value is None:
        raise HTTPException(status_code=503, detail=f"{label} not available")
    return value


def get_registry() -> RunRegistry:
    """Get or create singleton registry."""
    global _registry
    if _registry is None:
        _registry = RunRegistry()
    return _registry


def get_supervisor() -> RunSupervisor:
    """Get or create singleton run supervisor."""
    global _supervisor
    if _supervisor is None:
        _supervisor = RunSupervisor()
    return _supervisor


def resolve_agent_factory(assistant_id: str | None) -> AgentFactory:
    """Resolve the agent factory callable from config."""
    from deerflow.agents.lead_agent.agent import make_lead_agent

    return make_lead_agent


def build_runs_facade(
    *,
    stream_bridge: "StreamBridge",
    checkpointer: object,
    store: object | None = None,
    run_read_repo: RunReadRepository | None = None,
    run_write_repo: RunWriteRepository | None = None,
    run_delete_repo: RunDeleteRepository | None = None,
    thread_meta_storage: ThreadMetaStorage | None = None,
    run_event_store: object | None = None,
) -> RunsFacade:
    """
    Build RunsFacade with all dependencies.

    Args:
        stream_bridge: StreamBridge instance
        checkpointer: LangGraph checkpointer
        store: Optional LangGraph runtime store
        run_read_repo: Optional run repository for durable reads
        run_write_repo: Optional run repository for durable writes
        run_delete_repo: Optional run repository for durable deletes
        thread_meta_storage: Optional thread metadata storage adapter

    Returns:
        Configured RunsFacade instance
    """
    registry = get_registry()
    planner = ExecutionPlanner()
    supervisor = get_supervisor()

    stream_service = RunStreamService(stream_bridge)
    wait_service = RunWaitService(stream_service)
    query_store = AppRunQueryStore(run_read_repo) if run_read_repo else None
    create_store = (
        AppRunCreateStore(run_write_repo, thread_meta_storage=thread_meta_storage)
        if run_write_repo
        else None
    )
    delete_store = AppRunDeleteStore(run_delete_repo) if run_delete_repo else None

    # Build storage observer if repositories provided
    storage_observer = None
    if run_write_repo or thread_meta_storage:
        storage_observer = StorageRunObserver(
            run_write_repo=run_write_repo,
            thread_meta_storage=thread_meta_storage,
        )

    return RunsFacade(
        registry=registry,
        planner=planner,
        supervisor=supervisor,
        stream_service=stream_service,
        wait_service=wait_service,
        runtime=RunsRuntime(
            bridge=stream_bridge,
            checkpointer=checkpointer,
            store=store,
            event_store=run_event_store,
            agent_factory_resolver=resolve_agent_factory,
        ),
        observer=storage_observer,
        query_store=query_store,
        create_store=create_store,
        delete_store=delete_store,
    )


def build_runs_facade_from_request(request: "Request") -> RunsFacade:
    """
    Build RunsFacade from FastAPI request context.

    Extracts dependencies from request.app.state.
    """
    app_state = request.app.state

    return build_runs_facade(
        stream_bridge=get_stream_bridge(request),
        checkpointer=get_checkpointer(request),
        store=getattr(request.app.state, "store", None),
        run_read_repo=getattr(app_state, "run_read_repo", None),
        run_write_repo=getattr(app_state, "run_write_repo", None),
        run_delete_repo=getattr(app_state, "run_delete_repo", None),
        thread_meta_storage=getattr(app_state, "thread_meta_storage", None),
        run_event_store=getattr(app_state, "run_event_store", None),
    )
