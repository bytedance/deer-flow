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

from deerflow_extension_api.state import ExtensionData

if TYPE_CHECKING:  # pragma: no cover - typing only
    from deerflow_extension_api.placement import AgentBuildContext, MiddlewarePlacement

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


class TaskOutcome(StrEnum):
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


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

    def middlewares(self, contributor: MiddlewareContributor) -> None:
        return None

    def task_lifecycle(self, contributor: TaskLifecycleContributor) -> None:
        return None

    def system_model_observer(self, observer: SystemModelCallObserver) -> None:
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
