"""The extension contracts and their data types.

Compatibility rules enforced throughout this module:
  * every Protocol method carries a default implementation, so adding a method
    later stays additive for already-released extensions;
  * every dataclass field carries a default, so adding a field stays additive.
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
    """Identity of one agent execution.

    Lead and subagent executions are structurally the same thing, so they share
    this type: an extension writes one code path for both. The lead's
    ``task_id`` derives from ``run_id`` (lead task is 1:1 with a run, including
    across goal continuations, which reuse the same task).
    """

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


# --- System model calls (outside the agent graph) ---------------------------


class SystemOperationKind(StrEnum):
    GOAL = "goal"
    MEMORY = "memory"
    TITLE = "title"
    SUMMARIZATION = "summarization"


@dataclass(frozen=True)
class SystemModelRequest:
    """Read-only snapshot taken before the call. Extensions must not mutate."""

    messages: Sequence[Any] = ()
    model_name: str | None = None
    invoke_config: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SystemModelResult:
    """Read-only snapshot taken after the call.

    On failure ``response`` is None and ``error`` is set — the host notifies on
    both paths so extensions do not silently miss failed system calls.
    """

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


# --- Extension service ------------------------------------------------------


@dataclass(frozen=True)
class ExtensionRuntimeDeps:
    """Host dependencies handed to an extension service at binding time.

    Constructed in the Gateway lifespan, after the persistence engine exists.
    An extension that eagerly registers routers may bind this object in
    ``start()`` and expose it through request-time FastAPI dependencies; route
    construction itself remains a registration-phase, capability-free action.
    Adding fields stays additive because every field has a default.
    """

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

    Structural and minimal on purpose: these five methods are the whole
    contract. The host's concrete registry additionally carries host-only
    machinery (attribution, positional rollback, build) that is deliberately
    absent here so the public annotation never advertises it to extensions.
    Runtime-checkable so tests and duck-typed hosts can verify conformance.
    """

    def service(self, service: ExtensionService) -> None:
        return None

    def middlewares(self, contributor: MiddlewareContributor) -> None:
        return None

    def task_lifecycle(self, contributor: TaskLifecycleContributor) -> None:
        return None

    def system_model_observer(self, observer: SystemModelCallObserver) -> None:
        return None

    def routers(self, routers: Sequence[Any]) -> None:
        """Register routers that the extension constructed eagerly.

        Paths and dependency graphs must be fixed during ``install()`` so the
        host can detect conflicts and build stable OpenAPI metadata before it
        serves. Runtime capabilities belong to ``ExtensionRuntimeDeps``:
        register the same object as a service, bind the deps in ``start()``,
        and resolve them from route handlers through FastAPI ``Depends``.
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
