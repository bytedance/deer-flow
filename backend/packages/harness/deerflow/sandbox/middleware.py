import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.agents.thread_state import SandboxState, ThreadDataState
from deerflow.sandbox import get_sandbox_provider

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

logger = logging.getLogger(__name__)

# Executor for running async workspace sync in sync middleware callbacks
_WORKSPACE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="ws-sync")


def _run_async_sync(coro) -> None:
    """Run an async coroutine synchronously, safe from within a sync context."""
    try:
        asyncio.run(coro)
    except RuntimeError:
        # Already inside an event loop — delegate to a thread where asyncio.run() works
        future = _WORKSPACE_EXECUTOR.submit(asyncio.run, coro)
        future.result(timeout=60)


class SandboxMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]


class SandboxMiddleware(AgentMiddleware[SandboxMiddlewareState]):
    """Create a sandbox environment and assign it to an agent.

    Lifecycle Management:
    - With lazy_init=True (default): Sandbox is acquired on first tool call
    - With lazy_init=False: Sandbox is acquired on first agent invocation (before_agent)
    - Sandbox is reused across multiple turns within the same thread
    - Sandbox is NOT released after each agent call to avoid wasteful recreation
    - Cleanup happens at application shutdown via SandboxProvider.shutdown()
    """

    state_schema = SandboxMiddlewareState

    def __init__(self, lazy_init: bool = True, identity: "AgentIdentity | None" = None):
        """Initialize sandbox middleware.

        Args:
            lazy_init: If True, defer sandbox acquisition until first tool call.
                      If False, acquire sandbox eagerly in before_agent().
                      Default is True for optimal performance.
            identity: Three-tier agent identity for workspace isolation.
                      When set, persistent workspace is synced down before the
                      agent runs and synced up after the agent completes.
        """
        super().__init__()
        self._lazy_init = lazy_init
        self._identity = identity

    def _acquire_sandbox(self, thread_id: str) -> str:
        provider = get_sandbox_provider()
        sandbox_id = provider.acquire(thread_id)
        logger.info(f"Acquiring sandbox {sandbox_id}")
        return sandbox_id

    def _get_workspace_backend(self):
        """Return a WorkspaceBackend instance based on config, or None if not applicable."""
        if self._identity is None or not self._identity.has_agent:
            return None
        from deerflow.config.workspace_config import get_workspace_config

        cfg = get_workspace_config()
        if cfg.backend == "minio" and cfg.minio is not None:
            from deerflow.sandbox.workspace.minio_backend import MinIOWorkspaceBackend

            return MinIOWorkspaceBackend(
                endpoint=cfg.minio.endpoint,
                bucket=cfg.minio.bucket,
                access_key=cfg.minio.access_key,
                secret_key=cfg.minio.secret_key,
                secure=cfg.minio.secure,
                prefix=cfg.minio.prefix,
            )
        # Default: local backend
        from deerflow.sandbox.workspace.local_backend import LocalWorkspaceBackend

        return LocalWorkspaceBackend()

    def _workspace_sync_down(self, state: "SandboxMiddlewareState") -> None:
        """Sync persistent workspace → thread-local workspace (before agent runs)."""
        backend = self._get_workspace_backend()
        if backend is None:
            return
        thread_data = state.get("thread_data") or {}
        workspace_path = thread_data.get("workspace_path") if isinstance(thread_data, dict) else getattr(thread_data, "workspace_path", None)
        if not workspace_path:
            return
        try:
            _run_async_sync(backend.sync_down(self._identity, Path(workspace_path)))
        except Exception as exc:
            logger.warning("Workspace sync_down failed (non-fatal): %s", exc)

    def _workspace_sync_up(self, state: "SandboxMiddlewareState") -> None:
        """Sync thread-local workspace → persistent workspace (after agent completes)."""
        backend = self._get_workspace_backend()
        if backend is None:
            return
        thread_data = state.get("thread_data") or {}
        workspace_path = thread_data.get("workspace_path") if isinstance(thread_data, dict) else getattr(thread_data, "workspace_path", None)
        if not workspace_path:
            return
        try:
            _run_async_sync(backend.sync_up(self._identity, Path(workspace_path)))
        except Exception as exc:
            logger.warning("Workspace sync_up failed (non-fatal): %s", exc)

    @override
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        # Skip acquisition if lazy_init is enabled
        if self._lazy_init:
            self._workspace_sync_down(state)
            return super().before_agent(state, runtime)

        # Eager initialization (original behavior)
        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = (runtime.context or {}).get("thread_id")
            if thread_id is None:
                return super().before_agent(state, runtime)
            sandbox_id = self._acquire_sandbox(thread_id)
            logger.info(f"Assigned sandbox {sandbox_id} to thread {thread_id}")
            self._workspace_sync_down(state)
            return {"sandbox": {"sandbox_id": sandbox_id}}
        self._workspace_sync_down(state)
        return super().before_agent(state, runtime)

    @override
    def after_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        self._workspace_sync_up(state)

        sandbox = state.get("sandbox")
        if sandbox is not None:
            sandbox_id = sandbox["sandbox_id"]
            logger.info(f"Releasing sandbox {sandbox_id}")
            get_sandbox_provider().release(sandbox_id)
            return None

        if (runtime.context or {}).get("sandbox_id") is not None:
            sandbox_id = runtime.context.get("sandbox_id")
            logger.info(f"Releasing sandbox {sandbox_id} from context")
            get_sandbox_provider().release(sandbox_id)
            return None

        # No sandbox to release
        return super().after_agent(state, runtime)
