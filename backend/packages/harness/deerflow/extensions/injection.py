"""Merging extension-contributed middlewares into the host stack."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence

from deerflow_extension_api import AgentBuildContext, AgentScope, MiddlewarePlacement, Placement
from langchain.agents.middleware import AgentMiddleware

from deerflow.extensions.anchors import PlacementAnchor
from deerflow.extensions.isolation import IsolatedMiddleware, graph_safe_middleware_name
from deerflow.extensions.loader import Diagnostic
from deerflow.extensions.registry import LoadedExtensions

logger = logging.getLogger(__name__)


def inject_middlewares(
    middlewares: Sequence[object],
    anchors: Mapping[Placement, PlacementAnchor],
    scope: AgentScope,
    ctx: AgentBuildContext,
    extensions: LoadedExtensions,
    *,
    isolation_diagnostic_sink: Callable[[Diagnostic], None] | None = None,
) -> tuple[list[object], dict[int, str], list[Diagnostic]]:
    """Insert contributed middlewares at their semantic positions.

    Returns the merged stack, a provenance map from final index to extension
    source (core middlewares are absent from it), and construction diagnostics.
    Later isolation failures go to ``isolation_diagnostic_sink``; when omitted,
    they append to the returned diagnostic list for standalone callers.
    """
    result = list(middlewares)
    diagnostics: list[Diagnostic] = []

    if not extensions.has_middleware_contributors:
        return result, {}, diagnostics

    collected: list[tuple[str, MiddlewarePlacement]] = []
    for source, contributor in extensions.middleware_contributors:
        try:
            contributions = tuple(contributor.contribute_middlewares(extensions.app_store, ctx) or ())
        except Exception as exc:
            message = f"contribute_middlewares() failed: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: contribute_middlewares() failed", source)
            continue
        for index, placement in enumerate(contributions):
            if not isinstance(placement, MiddlewarePlacement):
                message = f"contribution {index} must be a MiddlewarePlacement, got {type(placement).__name__}"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
                continue
            if not isinstance(placement.scope, AgentScope):
                message = f"contribution {index} has invalid scope {placement.scope!r}"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
                continue
            if not isinstance(placement.placement, Placement):
                message = f"contribution {index} has invalid placement {placement.placement!r}"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
                continue
            if not isinstance(placement.order, int) or isinstance(placement.order, bool):
                message = f"contribution {index} has invalid order {placement.order!r}; expected int"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
                continue
            if not isinstance(placement.middleware, AgentMiddleware):
                message = f"contribution {index} middleware must be an AgentMiddleware, got {type(placement.middleware).__name__}"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
                continue
            if not (placement.scope & scope):
                continue
            collected.append((source, placement))

    if not collected:
        return result, {}, diagnostics

    # Sort by declared order, then by registration order, so the outcome is
    # reproducible regardless of dict iteration details.
    ordered = sorted(enumerate(collected), key=lambda item: (item[1][1].order, item[0]))

    # Insert inner-most positions first: each insertion shifts the indices of
    # everything after it, so working from the back keeps earlier anchors valid.
    #
    # `priority` records each contribution's position in `ordered` (already
    # sorted by declared order, then registration order). It breaks ties when
    # two contributions resolve to the *same* target index: inserting always
    # pushes the previous occupant of that index outward, so to make the
    # higher-priority (earlier in `ordered`) contribution end up outermost, it
    # must be the *last* one inserted at that index. Sorting by (index,
    # priority) descending achieves that: lower-priority items are processed
    # — and therefore inserted, and therefore displaced outward — first.
    resolved: list[tuple[int, int, str, object]] = []
    for priority, (_, (source, placement)) in enumerate(ordered):
        anchor = anchors.get(placement.placement)
        if anchor is None:
            diagnostics.append(Diagnostic.error(source, f"no anchor configured for placement {placement.placement.name}"))
            continue
        index, used_primary = anchor.resolve(result)
        if not used_primary:
            message = f"placement {placement.placement.name} fell back to a secondary anchor (primary anchor middleware is absent from this stack); the observation semantics of this placement may differ from its documented guarantee"
            diagnostics.append(Diagnostic.warning(source, message))
            logger.warning("Extension %s: %s", source, message)
        resolved.append((index, priority, source, placement.middleware))

    # LangChain requires names to be unique across the complete stack and uses
    # them as trace identities and, for before/after hooks, LangGraph node IDs.
    used_names = {getattr(middleware, "name", type(middleware).__name__) for middleware in result}
    runtime_diagnostic_sink = isolation_diagnostic_sink if isolation_diagnostic_sink is not None else diagnostics.append
    for index, priority, source, middleware in sorted(resolved, key=lambda item: (item[0], item[1]), reverse=True):
        try:
            inner_name = getattr(middleware, "name", type(middleware).__name__)
            base_name = graph_safe_middleware_name(f"extension:{source}:{inner_name}:{priority}")
            name = base_name
            suffix = 2
            while name in used_names:
                name = f"{base_name}_{suffix}"
                suffix += 1
            wrapped = IsolatedMiddleware(
                middleware,
                source,
                runtime_diagnostic_sink,
                name=name,
            )
        except Exception as exc:
            message = f"middleware construction failed: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)
            continue
        used_names.add(name)
        result.insert(index, wrapped)

    provenance = {index: middleware.source for index, middleware in enumerate(result) if isinstance(middleware, IsolatedMiddleware)}
    return result, provenance, diagnostics
