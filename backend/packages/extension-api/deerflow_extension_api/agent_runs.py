"""Optional host-bound control of full Agent runs, independent of Gateway imports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

AGENT_RUNS_RESOLVER_KEY = "deerflow_agent_runs_resolver"
AGENT_RUNS_CONTEXT_KEY = "__deerflow_extension_agent_runs"


class AgentRunError(Exception):
    """Host rejection with an HTTP-equivalent status (403, 404, 409, 422, 503)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AgentRun:
    thread_id: str
    run_id: str
    status: str
    assistant_id: str | None = None
    stop_reason: str | None = None


class AgentRuns(Protocol):
    """A process-local delegated capability bound by the host to one user.

    The host rechecks permissions and ownership on every operation. Retaining
    this handle after a handler returns permits a service to orchestrate runs;
    it is not a credential to serialize or reuse after host shutdown/restart.
    """

    def for_plugin(self, namespace: str) -> AgentRuns:
        """Partition idempotency keys without widening this user's permissions.

        Action/tool dispatch scopes handles to the registered plugin namespace.
        Contributed routes scope request-resolved handles explicitly. A scoped
        handle cannot be rebound to a different plugin.
        """
        ...

    async def create_thread(self, *, assistant_id: str = "lead_agent", thread_id: str | None = None, metadata: Mapping[str, Any] | None = None) -> str:
        """Create an owned thread, or return the caller's existing thread ID."""
        ...

    async def start(self, *, thread_id: str, input: Mapping[str, Any], context: Mapping[str, Any] | None = None, idempotency_key: str | None = None) -> AgentRun:
        """Start or continue the thread's Agent with ordinary run admission.

        Scoped handles namespace local idempotency keys automatically. An active
        run conflicts; start never implicitly cancels it.
        """
        ...

    async def resume(self, *, thread_id: str, resume: Any, idempotency_key: str | None = None) -> AgentRun:
        """Submit an explicit interrupt response; never approve automatically."""
        ...

    async def get(self, *, thread_id: str, run_id: str) -> AgentRun:
        """Read current status, including on a different Gateway worker."""
        ...

    async def get_state(self, *, thread_id: str) -> dict[str, Any]:
        """Read the thread's latest API state (values, next, interrupts, etc.).

        This is thread state, not an immutable run result. Serialize follow-up
        admissions if a plugin needs to associate output with one specific run.
        """
        ...

    async def wait(self, *, thread_id: str, run_id: str, timeout: float = 60) -> AgentRun:
        """Wait for a terminal/interrupt status, or raise TimeoutError.

        Timeout or cancellation of the caller does not cancel the Agent run.
        """
        ...

    async def cancel(self, *, thread_id: str, run_id: str) -> None:
        """Request interrupt, retaining checkpoints. Completion may be async."""
        ...


def resolve_agent_runs(request: object) -> AgentRuns | None:
    """Resolve from host-authenticated request state, never a supplied user ID.

    Unsupported hosts, credentials or unstamped requests return None. Inconsistent
    authenticated identities raise PermissionError. No ambient user fallback exists.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    resolver = getattr(state, AGENT_RUNS_RESOLVER_KEY, None)
    return resolver(request) if callable(resolver) else None


def require_agent_runs(request: object) -> AgentRuns:
    runs = resolve_agent_runs(request)
    if runs is None:
        raise NotImplementedError("host-bound Agent run control is unavailable")
    return runs
