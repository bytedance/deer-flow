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
class ExecutionFence:
    """Opaque execution generation, checked atomically with durable run admission.

    The lease must exist in the host database and belong to this capability's
    user and plugin namespace. Unsupported stores fail closed. This fences new
    admission/cancellation, not arbitrary external effects from an admitted Agent.

    SQL host schema contract: extension_execution_leases has the composite key
    (namespace, resource_id), plus user_id, holder_id, epoch (BIGINT), and
    expires_at (database-clock Unix seconds). Trusted operator-installed extensions
    coordinate these rows through the shared host database. Advance epoch on each
    takeover, retain tombstones, and serialize acquisition against row locks.
    The host locks that row and checks user/holder/epoch/expiry inside admission
    and cancellation transactions. A separate database or preflight check cannot
    provide this contract. Fenced calls require heartbeat-enabled run ownership;
    start additionally requires a cross-process stream bridge.
    """

    namespace: str
    resource_id: str
    holder_id: str
    epoch: int

    def __post_init__(self):
        for value, maximum in ((self.namespace, 96), (self.resource_id, 128), (self.holder_id, 128)):
            if not isinstance(value, str) or not value or len(value) > maximum:
                raise ValueError("Invalid execution fence identity")
        if type(self.epoch) is not int or not 1 <= self.epoch < 2**63:
            raise ValueError("Invalid execution fence epoch")


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

    async def configuration_evidence(self, *, thread_id: str, run_id: str) -> dict[str, Any]:
        """Read immutable host evidence captured from this run's actual assembly.

        Fails closed if the factory/host produced no evidence. No config re-read,
        credentials, raw instructions or mutable thread-state fallback.
        """
        ...

    async def read_artifact(self, *, thread_id: str, path: str) -> bytes:
        """Read a bounded regular output file through owner authorization.

        Returns at most 2 MiB, rejecting symlinks and concurrent mutations.
        The caller must retain these bytes to create an immutable version.
        """
        ...

    async def configuration_revision(self, *, assistant_ids: list[str], durable: bool = False) -> str:
        """Opaque revision of declarative Agent/host configuration.

        Revalidates the caller. Includes app/extensions config and Custom Agent
        config/SOUL; excludes mutable memory, file contents referenced by tools,
        provider state and effective per-run assembly. By default compare within
        one host lifetime only. With durable=True, compare across restarts sharing the host
        signing secret; secret rotation invalidates revisions. This retains no
        grant and is an invalidation guard, not an assembly attestation.
        """
        ...

    async def create_thread(self, *, assistant_id: str = "lead_agent", thread_id: str | None = None, metadata: Mapping[str, Any] | None = None) -> str:
        """Create an owned thread, or return the caller's existing thread ID."""
        ...

    async def start(self, *, thread_id: str, input: Mapping[str, Any], context: Mapping[str, Any] | None = None, idempotency_key: str | None = None, execution_fence: ExecutionFence | None = None) -> AgentRun:
        """Start or continue the thread's Agent with ordinary run admission.

        Scoped handles namespace local idempotency keys automatically. An active
        run conflicts; start never implicitly cancels it. execution_fence is
        host-only admission authority, never copied into Agent input/context.
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

    async def cancel(self, *, thread_id: str, run_id: str, execution_fence: ExecutionFence | None = None) -> None:
        """Request interrupt, retaining checkpoints. Completion may be async.

        With execution_fence, persist only under the live extension generation;
        the existing run owner consumes the request. Unsupported hosts fail closed.
        """
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
