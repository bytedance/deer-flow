"""Layer 1 authorization for middleware-declared tools.

LangChain's ``create_agent`` folds ``middleware.tools`` into the bound toolset
*after* the host's explicit tool list was filtered
(``langchain/agents/factory.py``: ``middleware_tools + regular_tools``), so a
middleware declaration would otherwise bypass Layer 1 entirely. This module
closes that gap with a five-step pass that runs once per build, after the
middleware stack exists:

1. **Record** — :func:`layer_one_outcome` captures the ordinary pass's verdict
   as two name sets at the existing Layer-1 call site.
2. **Collect** — :func:`collect_declared_tools` reads ``getattr(m, "tools",
   ())`` off the built stack. Entries that are not ``BaseTool`` instances with
   a usable name cannot be authorized by name; with authorization enabled they
   are warned about here and removed from the bound stack at view time
   (LangChain would otherwise convert them through ``create_tool`` and bind
   them unchecked). A contributor who needs a plain callable must wrap it in
   a ``StructuredTool``.
3. **Decide, seeded** — :func:`decide_declared_tools` submits only names the
   ordinary pass never saw, through the *same* provider instance, context, and
   app config. A name the ordinary pass already decided reuses that verdict:
   a name denied for this build stays denied for this build, whatever the
   middlewares declare (the seed also keeps a fail-closed provider failure
   from being silently undone by a recovered second call).
4. **Narrow, build-locally** — :func:`apply_declared_tool_view` returns a new
   stack. Fully-authorized middlewares keep their identity and position; a
   middleware with a denied or non-collectable declaration is replaced by an
   independent copy whose ``tools`` is a new tuple of its authorized
   declarations. The original (possibly caller-owned, possibly shared across
   builds) is never mutated.
5. **Verify after the last copy** — :func:`verify_declared_tool_view`
   re-collects declared names from the exact stack being bound (after the
   final ``normalize_middleware_state_schemas``) and raises
   :class:`DeclaredToolViewError` if any survived narrowing. This is the
   backstop for third-party ``__copy__`` implementations that rebuild from
   constructor arguments and would otherwise restore denied declarations
   during ``delta`` normalization.

Copy contract for declaring middlewares: ``copy.copy`` must return an
*independent* instance that *preserves current instance state*. A ``__copy__``
returning ``self`` is rejected at view time; one that rebuilds from
constructor arguments is caught by the post-chain verification; one that
raises fails the build loudly. The narrowed assignment is safe by
precondition: it writes ``clone.__dict__["tools"]`` directly (bypassing
``__setattr__`` overrides and property setters) and only after
``inspect.getattr_static`` confirms no data descriptor named ``tools`` exists
on the class — a forwarding property would redirect the write into storage a
shallow copy shares, so that shape is refused *before any write* and the
build fails with the caller's instance fully intact.

When ``authorization.enabled`` is not true the ordinary pass returns
``provider=None`` and every step here is skipped: nothing is collected,
nothing is narrowed, and the stack handed to ``create_agent`` is the original
list object (:func:`narrow_declared_tools` returns it unchanged).
"""

from __future__ import annotations

import copy
import inspect
import logging
from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

from deerflow.authz.provider import AuthorizationProvider
from deerflow.authz.tool_filter import apply_tool_authorization
from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)


class DeclaredToolViewError(RuntimeError):
    """A middleware-declared tool view could not be built or verified safely.

    Always a configuration/integration error worth stopping the build for:
    never falls back to mutating a caller-owned instance, and never silently
    re-admits a denied declaration.
    """


@dataclass(frozen=True, slots=True)
class LayerOneOutcome:
    """What the ordinary Layer 1 pass decided for this build (names, not objects)."""

    submitted: frozenset[str]
    """Every candidate name Layer 1 saw."""
    allowed: frozenset[str]
    """Names Layer 1 kept."""


def layer_one_outcome(candidates: Sequence[BaseTool], authorized: Sequence[BaseTool]) -> LayerOneOutcome:
    """Capture the ordinary Layer 1 pass's verdict at its existing call site.

    When authorization is disabled the pass returns its input unchanged, so
    ``submitted == allowed`` and nothing can be denied downstream.
    """
    return LayerOneOutcome(
        submitted=frozenset(tool.name for tool in candidates),
        allowed=frozenset(tool.name for tool in authorized),
    )


def _collectable(tool: object) -> bool:
    """A declaration this module can authorize: a ``BaseTool`` with a usable name."""
    return isinstance(tool, BaseTool) and isinstance(tool.name, str) and bool(tool.name)


def _middleware_name(middleware: object) -> str:
    return getattr(middleware, "name", None) or type(middleware).__name__


def _iter_declared(middleware: object) -> tuple[Any, ...]:
    tools = getattr(middleware, "tools", None)
    if tools is None:
        return ()
    if not isinstance(tools, (list, tuple)):
        logger.warning(
            "Middleware %s declares 'tools' as %s, not a list/tuple; skipping its tool declarations",
            _middleware_name(middleware),
            type(tools).__name__,
        )
        return ()
    return tuple(tools)


def collect_declared_tools(middlewares: Sequence[object]) -> list[BaseTool]:
    """Return the collectable ``BaseTool`` declarations in middleware order.

    Entries that are not collectable are dropped with a warning: they cannot
    be authorized by name, and :func:`apply_declared_tool_view` removes them
    from the bound stack when authorization is enabled. The middleware itself
    is left untouched here — dropping only excludes the entry from the
    authorization decision.
    """
    declared: list[BaseTool] = []
    for middleware in middlewares:
        for tool in _iter_declared(middleware):
            if _collectable(tool):
                declared.append(tool)
            else:
                logger.warning(
                    "Middleware %s declares a tool that is not a BaseTool with a usable name (%r); it cannot be authorized and is removed from the bound stack when authorization is enabled",
                    _middleware_name(middleware),
                    tool,
                )
    return declared


def decide_declared_tools(
    declared: Sequence[BaseTool],
    *,
    outcome: LayerOneOutcome,
    context: Mapping[str, Any],
    app_config: AppConfig,
    authorization_provider: AuthorizationProvider | None,
) -> frozenset[str]:
    """Authorize declared names, seeded by the ordinary pass's verdict.

    Only names the ordinary pass never submitted are sent to the provider —
    through the *same* provider instance, context, and app config, so both
    passes decide with one principal. A name in ``outcome.submitted`` reuses
    the recorded verdict and is never re-submitted; in particular a denial
    (including a fail-closed provider failure) cannot be undone by a
    same-named middleware declaration.

    ``authorization_provider=None`` (authorization disabled) authorizes every
    declared name, matching ``filter_tools_by_authorization``'s keep-all
    behavior.
    """
    # Dedupe by first occurrence of the name: two middlewares declaring the
    # same never-submitted name must reach the provider as one candidate, so
    # counting or audit-logging providers see each name once.
    seen: set[str] = set()
    new_declarations: list[BaseTool] = []
    for tool in declared:
        if tool.name in outcome.submitted or tool.name in seen:
            continue
        seen.add(tool.name)
        new_declarations.append(tool)
    if not new_declarations or authorization_provider is None:
        newly_authorized = {tool.name for tool in new_declarations}
        return frozenset(outcome.allowed | newly_authorized)
    authorized_new, _ = apply_tool_authorization(
        list(new_declarations),
        context=context,
        app_config=app_config,
        authorization_provider=authorization_provider,
    )
    return frozenset(outcome.allowed | {tool.name for tool in authorized_new})


def _independent_copy(middleware: object) -> Any:
    try:
        clone = copy.copy(middleware)
    except Exception as exc:
        raise DeclaredToolViewError(
            f"Middleware {_middleware_name(middleware)} ({type(middleware).__name__}) declares tools denied by policy "
            "but cannot be copied for build-local narrowing "
            f"({type(exc).__name__}: {exc}). Give it a state-preserving __copy__ or remove the denied declaration."
        ) from exc
    if clone is middleware:
        raise DeclaredToolViewError(
            f"Middleware {_middleware_name(middleware)} ({type(middleware).__name__}) has a __copy__ that returns self; "
            "narrowing its declared tools would mutate an instance the build does not own. "
            "__copy__ must return an independent, state-preserving instance."
        )
    return clone


def _assign_narrowed_tools(clone: Any, original: object, narrowed: tuple[Any, ...]) -> None:
    """Write the narrowed view into *clone* without touching shared storage.

    Safe by precondition, not by post-check: a data descriptor named ``tools``
    on the class (e.g. a forwarding property) would redirect the write into
    storage a shallow copy shares with the caller's instance, so that shape is
    refused *before any write*. The write itself goes straight into
    ``clone.__dict__``, bypassing ``__setattr__`` overrides and property
    setters, so it can only ever affect the clone's own instance dict.
    """
    try:
        static = inspect.getattr_static(clone, "tools")
    except AttributeError:
        static = None
    if static is not None and (hasattr(static, "__set__") or hasattr(static, "__delete__")):
        raise DeclaredToolViewError(
            f"Middleware {_middleware_name(original)} ({type(original).__name__}) defines 'tools' as a data descriptor "
            f"({type(static).__name__}); narrowing it safely is impossible because the write would reach storage "
            "shared with the original instance. Store declared tools as a plain instance attribute."
        )
    try:
        instance_dict = clone.__dict__
    except AttributeError as exc:
        raise DeclaredToolViewError(f"Middleware {_middleware_name(original)} ({type(original).__name__}) has no instance __dict__; build-local narrowing of its declared tools is impossible.") from exc
    instance_dict["tools"] = narrowed


def apply_declared_tool_view(
    middlewares: Sequence[object],
    *,
    authorized_names: Container[str],
) -> list[object]:
    """Return a build-local stack with declarations narrowed to *authorized_names*.

    A middleware whose declarations are all authorized keeps its identity and
    position; a middleware with at least one denied or non-collectable
    declaration is replaced by an independent copy whose ``tools`` is a new
    tuple of its authorized declarations. Non-collectable entries cannot be
    authorized by name, so they are removed here too — otherwise LangChain's
    factory would fold them into ``ToolNode`` verbatim (auto-converting plain
    callables through ``create_tool``) and they would bind with no provider
    decision at all. Never mutates the caller's instances, never reorders,
    never appends.
    """
    view = list(middlewares)
    for index, middleware in enumerate(view):
        tools = _iter_declared(middleware)
        if not tools:
            continue
        kept = tuple(tool for tool in tools if _collectable(tool) and tool.name in authorized_names)
        if len(kept) == len(tools):
            continue
        clone = _independent_copy(middleware)
        _assign_narrowed_tools(clone, middleware, kept)
        view[index] = clone
    return view


def verify_declared_tool_view(
    middlewares: Sequence[object],
    *,
    authorized_names: Container[str] | None,
) -> None:
    """Re-check the exact stack being bound after the last copy in the chain.

    Runs after the final ``normalize_middleware_state_schemas`` and before
    ``create_agent`` / the assembly descriptor. A third-party ``__copy__``
    that rebuilds from constructor arguments would restore denied declarations
    during ``delta`` normalization *after* the view was applied; that cannot
    be prevented at view time, so it is caught here and fails the build
    loudly. ``authorized_names=None`` (authorization disabled) skips the
    check.
    """
    if authorized_names is None:
        return
    for middleware in middlewares:
        for tool in _iter_declared(middleware):
            if not _collectable(tool):
                raise DeclaredToolViewError(
                    f"Middleware {_middleware_name(middleware)} ({type(middleware).__name__}) still declares "
                    f"a tool that is not a BaseTool with a usable name ({tool!r}) after middleware normalization. "
                    "Non-collectable declarations cannot be authorized and must not survive narrowing; "
                    "its __copy__ must preserve instance state instead of rebuilding from constructor arguments."
                )
            if tool.name not in authorized_names:
                raise DeclaredToolViewError(
                    f"Middleware {_middleware_name(middleware)} ({type(middleware).__name__}) still declares "
                    f"tool {tool.name!r}, which is not authorized for this build, after middleware normalization. "
                    "Its __copy__ must preserve instance state instead of rebuilding from constructor arguments."
                )


def narrow_declared_tools(
    middlewares: Sequence[object],
    *,
    outcome: LayerOneOutcome,
    context: Mapping[str, Any],
    app_config: AppConfig,
    authorization_provider: AuthorizationProvider | None,
) -> tuple[list[object], frozenset[str] | None]:
    """Collect → seeded decide → narrowed view, for the synchronous assembly paths.

    Returns ``(view, authorized_names)``; the subagent path performs the same
    steps through the primitives so the decision can cross
    ``asyncio.to_thread``. When authorization is disabled
    (``authorization_provider is None``) this is a strict no-op: the returned
    view is the original list object and ``authorized_names`` is ``None``,
    which also disables :func:`verify_declared_tool_view`.
    """
    if authorization_provider is None:
        return list(middlewares) if not isinstance(middlewares, list) else middlewares, None
    declared = collect_declared_tools(middlewares)
    authorized_names = decide_declared_tools(
        declared,
        outcome=outcome,
        context=context,
        app_config=app_config,
        authorization_provider=authorization_provider,
    )
    return apply_declared_tool_view(middlewares, authorized_names=authorized_names), authorized_names
