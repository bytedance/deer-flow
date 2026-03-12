import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.thread_state import SandboxState, ThreadDataState
from src.sandbox import get_sandbox_provider
from src.utils.runtime import get_thread_id

logger = logging.getLogger(__name__)

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
    - In task mode: after each agent turn, outputs are synced to persistent storage
      so they survive sandbox teardown when the grace period expires
    - Sandbox is NOT released after each agent call to avoid wasteful recreation
    - Cleanup happens at application shutdown via SandboxProvider.shutdown()
    """

    state_schema = SandboxMiddlewareState

    def __init__(self, lazy_init: bool = True):
        """Initialize sandbox middleware.

        Args:
            lazy_init: If True, defer sandbox acquisition until first tool call.
                      If False, acquire sandbox eagerly in before_agent().
                      Default is True for optimal performance.
        """
        super().__init__()
        self._lazy_init = lazy_init

    def _acquire_sandbox(self, thread_id: str) -> str:
        provider = get_sandbox_provider()
        sandbox_id = provider.acquire(thread_id)
        logger.info(f"Acquiring sandbox {sandbox_id}")
        return sandbox_id

    @override
    def before_agent(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        # Skip acquisition if lazy_init is enabled
        if self._lazy_init:
            return super().before_agent(state, runtime)

        # Eager initialization (original behavior)
        if "sandbox" not in state or state["sandbox"] is None:
            thread_id = get_thread_id(runtime)
            thread_id = get_thread_id(runtime)
            print(f"Thread ID: {thread_id}")
            sandbox_id = self._acquire_sandbox(thread_id)
            logger.info(f"Assigned sandbox {sandbox_id} to thread {thread_id}")
            return {"sandbox": {"sandbox_id": sandbox_id}}
        return super().before_agent(state, runtime)

    @override
    def after_model(self, state: SandboxMiddlewareState, runtime: Runtime) -> dict | None:
        """After each agent turn, sync outputs to storage if in task mode.

        This ensures that files written during tool execution are persisted
        to R2/local storage before the sandbox's grace period expires.
        """
        provider = get_sandbox_provider()
        if not provider.is_task_mode():
            return super().after_model(state, runtime)

        sandbox_state = state.get("sandbox")
        if sandbox_state is None:
            return super().after_model(state, runtime)

        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is None:
            return super().after_model(state, runtime)

        thread_id = get_thread_id(runtime)
        if thread_id is None:
            return super().after_model(state, runtime)

        # Sync outputs in background — don't block the agent response
        import threading

        sync_thread = threading.Thread(
            target=provider.sync_outputs_to_storage,
            args=(sandbox_id, thread_id),
            name=f"sandbox-output-sync-{sandbox_id[:8]}",
            daemon=True,
        )
        sync_thread.start()

        return super().after_model(state, runtime)
