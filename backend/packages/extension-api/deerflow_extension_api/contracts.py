"""The extension contracts and their data types.

Compatibility rules enforced throughout this module:
  * every Protocol method carries a default implementation, so adding a method
    later stays additive for already-released extensions;
  * every optional dataclass field carries a default, so adding a field stays
    additive.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar, runtime_checkable

from deerflow_extension_api.plugins import PluginContribution
from deerflow_extension_api.state import ExtensionData

if TYPE_CHECKING:  # pragma: no cover - typing only
    from deerflow_extension_api.assembly import AgentAssemblyObserver
    from deerflow_extension_api.compaction import ContextCompactionObserver
    from deerflow_extension_api.completed_run_evidence import CompletedRunEvidenceReader
    from deerflow_extension_api.model_invocation import ModelInvoker
    from deerflow_extension_api.placement import AgentBuildContext, MiddlewarePlacement
    from deerflow_extension_api.run_evidence import RunEvidenceReader
    from deerflow_extension_api.skill_mutations import SkillMutationService

F = TypeVar("F", bound=Callable[..., Any])


# --- Host projections -------------------------------------------------------


@dataclass(frozen=True)
class HostPolicySnapshot:
    """The limits the host actually enforces, projected for extensions.

    A narrow projection instead of the host's AppConfig: exposing AppConfig
    would pin every extension to the harness release cadence. Every field has
    a default so widening this stays additive.
    """

    token_budget_enabled: bool = False
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    budget_warn_fraction: float | None = None
    budget_hard_fraction: float | None = None
    max_subagents_per_run: int | None = None


# --- Task lifecycle ---------------------------------------------------------


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value if isinstance(value, ReadOnlyDict) else ReadOnlyDict(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


def _read_only(self: ReadOnlyDict, *args: Any, **kwargs: Any) -> Any:
    raise TypeError("ReadOnlyDict does not support item assignment or deletion")


class ReadOnlyDict(dict[str, Any]):
    """A detached, deeply read-only dict the host hands to extensions.

    Nested mappings become ``ReadOnlyDict`` and lists become tuples, so one
    observer cannot change what the next one reads. Being a ``dict`` keeps
    ``dataclasses.asdict()``, ``copy.deepcopy()``, pickling and ``json.dumps()``
    working; ``dict(value)`` or ``value.copy()`` returns a mutable copy.
    """

    __slots__ = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__((key, _freeze(item)) for key, item in dict(*args, **kwargs).items())

    __setitem__ = __delitem__ = __ior__ = _read_only
    clear = pop = popitem = setdefault = update = _read_only

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (dict(self),))

    def __copy__(self) -> ReadOnlyDict:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> ReadOnlyDict:
        return self

    def __repr__(self) -> str:
        return f"ReadOnlyDict({dict.__repr__(self)})"


class TaskOutcome(StrEnum):
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskStopDetail:
    """The final state the host recorded for a task, passed to ``on_task_stop``.

    ``TaskOutcome`` stays the coarse, stable classification; this carries the
    detail behind it. A lead run's status is decided after the graph has ended
    (a model failing after retries ends the graph normally), so callback-based
    observers cannot see it; ``on_task_stop`` runs after it is persisted.
    """

    # Lead run: the RunStatus value (``success``, ``error``, ``timeout``,
    # ``interrupted``, or ``waiting_for_input`` for a resumable pause).
    # Subagent: the SubagentStatus value (``completed``, ``failed``,
    # ``cancelled``, ``timed_out``).
    status: str
    # The short error message the host stored for the task, if any.
    error: str | None = None
    # Lead run with a goal: the goal evaluator's verdict (for example
    # ``satisfied``, ``blocker``, ``stand_down_reason``), a read-only copy.
    goal_verdict: Mapping[str, Any] | None = field(default=None, hash=False)
    # Lead run: False when the host could not confirm the terminal write (the
    # run store rejected it or the worker lost ownership). ``status`` is then
    # the worker's staged status and the stored run may still say otherwise.
    persisted: bool = True


@dataclass(frozen=True)
class TaskInfo:
    """Identity of one lead-agent or subagent execution."""

    task_id: str
    run_id: str
    thread_id: str
    kind: Literal["lead", "subagent"]
    parent_task_id: str | None = None
    agent_name: str | None = None
    resumed: bool = False
    # Lead run: a read-only copy of the run's metadata (for a scheduled run,
    # ``scheduled_task_id``, ``scheduled_task_run_id`` and ``scheduled_trigger``).
    # Empty for subagents.
    # Descriptive, not identity: excluded from equality and hashing, so the
    # ``info`` passed at stop equals the one passed at start.
    metadata: Mapping[str, Any] = field(default_factory=lambda: ReadOnlyDict(), compare=False)
    # Set only on the ``info`` passed to ``on_task_stop``; ``None`` at start.
    stop: TaskStopDetail | None = field(default=None, compare=False)


class TaskLifecycleContributor(Protocol):
    async def on_task_start(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: TaskInfo,
    ) -> None:
        return None

    async def on_task_stop(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: TaskInfo,
        outcome: TaskOutcome,
    ) -> None:
        return None


# --- System model calls not wrapped by middleware model-call hooks ----------


class SystemOperationKind(StrEnum):
    GOAL = "goal"
    MEMORY = "memory"
    TITLE = "title"
    SUMMARIZATION = "summarization"


@dataclass(frozen=True)
class SystemModelRequest:
    """Read-only snapshot taken before a system-owned model call."""

    messages: Sequence[Any] = ()
    model_name: str | None = None
    invoke_config: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Normalize ``messages`` to a tuple so the snapshot is what it claims to be.

        Call sites differ: goal evaluation and memory extraction pass a message list,
        while title generation and summarization pass one prompt string. A bare ``str``
        already satisfies ``Sequence``, so without this an observer iterating
        ``request.messages`` would silently walk characters. Copying a list also makes
        the frozen snapshot immutable in fact, not only by dataclass declaration — the
        caller keeps its own list and observations may run after the call returns.
        """
        messages = self.messages
        if isinstance(messages, tuple):
            return
        normalized = tuple(messages) if isinstance(messages, Sequence) and not isinstance(messages, str | bytes) else (messages,)
        object.__setattr__(self, "messages", normalized)


@dataclass(frozen=True)
class SystemModelResult:
    """Success or failure snapshot taken after a system-owned model call."""

    response: Any | None = None
    error: BaseException | None = None
    duration_ms: float | None = None


class SystemModelCallObserver(Protocol):
    async def on_system_model_call(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        kind: SystemOperationKind,
        request: SystemModelRequest,
        result: SystemModelResult,
    ) -> None:
        return None


# --- Middleware -------------------------------------------------------------


class MiddlewareContributor(Protocol):
    def contribute_middlewares(
        self,
        app_store: ExtensionData,
        ctx: AgentBuildContext,
    ) -> Sequence[MiddlewarePlacement]:
        return ()


# --- Extension services ----------------------------------------------------


@dataclass(frozen=True)
class ExtensionRuntimeDeps:
    """Host capabilities bound after Gateway infrastructure is ready."""

    app_store: ExtensionData | None = None
    policy: HostPolicySnapshot = field(default_factory=HostPolicySnapshot)
    session_factory: Any | None = None
    run_evidence_reader: RunEvidenceReader | None = None
    model_invoker: ModelInvoker | None = None
    completed_run_evidence: CompletedRunEvidenceReader | None = None
    skill_mutations: SkillMutationService | None = None
    # Async callable (user_id, grant, *, validator=None, plugin_namespace=None)
    # -> AgentRuns restoring a captured session ceiling for unattended host-side
    # recovery. The host revalidates the user row per operation and fails closed;
    # expiry/revocation stay the extension's contract via the validator. None on
    # hosts without the delegated-restore capability.
    agent_runs_restore: Any | None = None


class ExtensionService(Protocol):
    async def start(self, deps: ExtensionRuntimeDeps) -> None:
        return None

    async def stop(self) -> None:
        return None


# --- Registration surface ---------------------------------------------------


@runtime_checkable
class ExtensionRegistry(Protocol):
    """The write-only registration surface handed to ``install()``.

    Structural and minimal on purpose. Every method has a default so additive
    contract releases remain compatible with older registry implementations.
    The host's concrete registry additionally carries host-only machinery
    (attribution, positional rollback, build) that is deliberately absent here.
    """

    def plugin(self, contribution: PluginContribution) -> bool:
        """Return True when accepted; False means this host lacks plugin UI support."""
        return False

    def knowledge_provider(self, name: str, provider: Any) -> bool:
        """Register a read-only ``deerflow.knowledge.RetrievalProvider``.

        The host validates its KnowledgeCapabilities and optional catalog,
        documents and contextual search implementations. The value stays Any
        here to keep extension-api independent of the harness and Pydantic.
        False means the host does not support this contribution.
        """
        return False

    def workspace_search(self, provider: Any) -> bool:
        """Register one WorkspaceSearchProvider; False on hosts without search."""
        return False

    def middlewares(self, contributor: MiddlewareContributor) -> None:
        return None

    def task_lifecycle(self, contributor: TaskLifecycleContributor) -> None:
        return None

    def system_model_observer(self, observer: SystemModelCallObserver) -> None:
        return None

    def agent_assembly_observer(self, observer: AgentAssemblyObserver) -> None:
        return None

    def context_compaction_observer(self, observer: ContextCompactionObserver) -> None:
        return None

    def service(self, service: ExtensionService) -> None:
        return None

    def routers(self, routers: Sequence[Any]) -> None:
        """Register HTTP routers constructed eagerly during extension install.

        Router types stay ``Any`` so this contract package has no FastAPI
        dependency. The host validates supported route shapes before mounting;
        runtime resources belong in a separately registered service.
        """
        return None


#: The install() entry point signature every extension exposes.
ExtensionInstall = Callable[[ExtensionRegistry, Mapping[str, Any]], None]


# --- Declaration decorator --------------------------------------------------


def extension(*, api: str, name: str | None = None) -> Callable[[F], F]:
    """Stamp an install function with the API version it was written against.

    Optional. pip's dependency resolution is the primary compatibility
    mechanism; this covers `--no-deps` installs and editable monorepo checkouts
    where versions can skew, and turns a deep AttributeError into an
    actionable startup diagnostic.
    """

    def _decorate(func: F) -> F:
        func.__deerflow_api__ = api  # type: ignore[attr-defined]
        func.__deerflow_name__ = name  # type: ignore[attr-defined]
        return func

    return _decorate
