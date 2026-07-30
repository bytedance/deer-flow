"""Gateway-side extension plumbing: policy projection, routers, services."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from deerflow_extension_api import ExtensionRuntimeDeps, HostPolicySnapshot

from deerflow.extensions.loader import Diagnostic
from deerflow.extensions.registry import LoadedExtensions

logger = logging.getLogger(__name__)

#: A hung stop() would block Gateway shutdown; a Gateway that cannot shut down
#: is worse than a lost observation, so stop() is bounded. Per service rather
#: than shared, so one hung service cannot starve the rest of their stop().
DEFAULT_STOP_TIMEOUT_SECONDS = 30.0

_PATH_PARAMETER_GROUP = re.compile(r"\(\?P<[^>]+>")
_PATH_PARAMETER = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?}")
_RouteMethods = frozenset[str] | None
_RouteScopes = frozenset[str]


@dataclass(frozen=True)
class _RouteClaim:
    path: str
    matcher: str
    methods: _RouteMethods
    scopes: _RouteScopes
    mount_prefix: str | None = None


_RouteOwners = list[tuple[_RouteClaim, str]]


def project_host_policy(app_config: Any) -> HostPolicySnapshot:
    """Project the host's enforced limits into the extension-facing snapshot.

    Deliberately narrow: exposing AppConfig itself would pin every extension to
    the harness release cadence. Read with ``getattr`` defaults so a host whose
    config predates a field — or omits the section entirely — degrades to the
    snapshot's own defaults instead of failing extension startup.
    """
    token_budget = getattr(app_config, "token_budget", None)
    subagents = getattr(app_config, "subagents", None)
    return HostPolicySnapshot(
        token_budget_enabled=bool(getattr(token_budget, "enabled", False)),
        max_input_tokens=getattr(token_budget, "max_input_tokens", None),
        max_output_tokens=getattr(token_budget, "max_output_tokens", None),
        max_total_tokens=getattr(token_budget, "max_tokens", None),
        budget_warn_fraction=getattr(token_budget, "warn_threshold", None),
        budget_hard_fraction=getattr(token_budget, "hard_stop_threshold", None),
        max_subagents_per_run=getattr(subagents, "max_total_per_run", None),
    )


def _route_path_matcher(route: Any) -> str | None:
    path = getattr(route, "path", None)
    if path is None:
        return None
    pattern = getattr(getattr(route, "path_regex", None), "pattern", None)
    if not pattern:
        return path
    return _PATH_PARAMETER_GROUP.sub("(?:", pattern)


def _route_methods(route: Any) -> _RouteMethods:
    methods = getattr(route, "methods", None)
    return frozenset(methods) if methods else None


def _route_scopes(route: Any) -> _RouteScopes:
    from starlette.routing import Mount, Route, WebSocketRoute

    if isinstance(route, WebSocketRoute):
        return frozenset({"websocket"})
    if isinstance(route, Route):
        return frozenset({"http"})
    if isinstance(route, Mount):
        return frozenset({"http", "websocket"})
    return frozenset({"http", "websocket"})


def _route_claim(route: Any) -> _RouteClaim | None:
    from starlette.routing import Mount

    path = getattr(route, "path", None)
    matcher = _route_path_matcher(route)
    if path is None or matcher is None:
        return None
    return _RouteClaim(
        path=path,
        matcher=matcher,
        methods=_route_methods(route),
        scopes=_route_scopes(route),
        mount_prefix=path.rstrip("/") if isinstance(route, Mount) else None,
    )


def _router_routes(router: Any) -> list[_RouteClaim]:
    from starlette.routing import Mount

    claims: list[_RouteClaim] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, Mount):
            raise TypeError("contributed router contains a Starlette Mount, which FastAPI.include_router() ignores")
        claim = _route_claim(route)
        if claim is not None:
            claims.append(claim)
    return claims


def _methods_overlap(left: _RouteMethods, right: _RouteMethods) -> bool:
    return left is None or right is None or not left.isdisjoint(right)


def _dispatches_overlap(left: _RouteClaim, right: _RouteClaim) -> bool:
    shared_scopes = left.scopes & right.scopes
    if "websocket" in shared_scopes:
        return True
    return "http" in shared_scopes and _methods_overlap(left.methods, right.methods)


def _path_shape(path: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    literals: list[str] = []
    convertors: list[str] = []
    cursor = 0
    for match in _PATH_PARAMETER.finditer(path):
        literals.append(path[cursor : match.start()])
        convertors.append(match.group(2) or "str")
        cursor = match.end()
    literals.append(path[cursor:])
    return tuple(literals), tuple(convertors)


def _convertor_covers(owner: str, candidate: str) -> bool:
    if owner == candidate or owner == "path":
        return True
    if owner == "str":
        return candidate in {"str", "int", "float", "uuid"}
    if owner == "float":
        return candidate in {"float", "int"}
    return False


def _path_segments(
    path: str,
) -> tuple[tuple[str, str], ...] | None:
    """Parse simple slash-delimited static/parameter segments.

    Parameters embedded inside literal text are retained as opaque compound
    segments. They fall back to the compiled-matcher and literal-skeleton
    checks unless they occur after an owner's terminal ``:path`` parameter.
    Keeping them opaque avoids guessing at custom regex-language inclusion.
    """
    if not path.startswith("/"):
        return None
    if path == "/":
        return ()

    segments: list[tuple[str, str]] = []
    for segment in path[1:].split("/"):
        match = _PATH_PARAMETER.fullmatch(segment)
        if match is not None:
            segments.append(("parameter", match.group(2) or "str"))
        elif _PATH_PARAMETER.search(segment):
            segments.append(("compound", segment))
        else:
            segments.append(("literal", segment))
    return tuple(segments)


def _static_segment_matches(convertor: str, value: str) -> bool:
    from starlette.convertors import CONVERTOR_TYPES

    registered = CONVERTOR_TYPES.get(convertor)
    return registered is not None and re.fullmatch(registered.regex, value) is not None


def _segment_covers(
    owner: tuple[str, str],
    candidate: tuple[str, str],
) -> bool:
    owner_kind, owner_value = owner
    candidate_kind, candidate_value = candidate
    if owner_kind == "literal":
        return candidate_kind == "literal" and owner_value == candidate_value
    if owner_kind == "compound" or candidate_kind == "compound":
        return False
    if candidate_kind == "literal":
        return _static_segment_matches(owner_value, candidate_value)
    return _convertor_covers(owner_value, candidate_value)


def _segmented_path_covers(owner_path: str, candidate_path: str) -> bool:
    owner = _path_segments(owner_path)
    candidate = _path_segments(candidate_path)
    if owner is None or candidate is None:
        return False

    # A terminal :path parameter consumes every remaining candidate segment.
    if owner and owner[-1] == ("parameter", "path"):
        prefix = owner[:-1]
        # The slash before ``{rest:path}`` is still literal. A candidate with
        # exactly the prefix's segment count (for example ``/org/{id}`` versus
        # ``/org/{tenant}/{rest:path}``) does not contain that slash and remains
        # reachable.
        return len(candidate) > len(prefix) and all(
            _segment_covers(owner_segment, candidate_segment)
            for owner_segment, candidate_segment in zip(
                prefix,
                candidate,
                strict=False,
            )
        )

    return len(owner) == len(candidate) and all(
        _segment_covers(owner_segment, candidate_segment)
        for owner_segment, candidate_segment in zip(
            owner,
            candidate,
            strict=True,
        )
    )


def _matcher_covers(owner: _RouteClaim, candidate: _RouteClaim) -> bool:
    """Whether every candidate path is consumed by the earlier owner.

    Exact compiled matchers cover renamed parameters. The structural cases
    below handle Starlette's built-in convertors conservatively: a dynamic
    segment can cover a later static route, broader convertors cover narrower
    ones with the same literal skeleton, and a terminal ``path`` convertor
    covers every route below its fixed prefix. Unknown/custom shapes fall back
    to non-conflicting rather than guessing at regex-language inclusion.
    """
    if owner.matcher == candidate.matcher:
        return True

    owner_literals, owner_convertors = _path_shape(owner.path)
    candidate_literals, candidate_convertors = _path_shape(candidate.path)

    # Compiled regex matching is exact for a static candidate and handles
    # custom/embedded parameters that the structural parser intentionally
    # treats as opaque.
    if not candidate_convertors:
        return re.fullmatch(owner.matcher, candidate.path) is not None

    # Starlette Mount stores its implicit terminal ``{path:path}`` only in the
    # compiled matcher, not ``route.path``. A root mount is normalized to an
    # empty path. In both cases every descendant is dispatched to the mounted
    # app before a later route can be considered; the mount's own exact prefix
    # remains available to a later route (Starlette's matcher requires "/").
    if owner.mount_prefix is not None:
        if owner.mount_prefix == "":
            return True
        return _segmented_path_covers(
            f"{owner.mount_prefix}/{{mount_path:path}}",
            candidate.path,
        )

    if _segmented_path_covers(owner.path, candidate.path):
        return True

    return (
        owner_literals == candidate_literals
        and len(owner_convertors) == len(candidate_convertors)
        and all(
            _convertor_covers(owner_convertor, candidate_convertor)
            for owner_convertor, candidate_convertor in zip(
                owner_convertors,
                candidate_convertors,
                strict=True,
            )
        )
    )


def _find_route_clash(routes: list[_RouteClaim], owners: _RouteOwners) -> tuple[str, str] | None:
    for route in routes:
        for owner, holder in owners:
            if _dispatches_overlap(route, owner) and _matcher_covers(owner, route):
                return route.path, holder
    return None


def include_contributed_routers(app: Any, extensions: LoadedExtensions) -> list[Diagnostic]:
    """Include extension routers without installing unreachable routes.

    First writer wins when its matcher fully covers a later route for an
    overlapping protocol/method. Silently including the later router would
    leave its endpoint unreachable and make behavior depend on load order; the
    conflict is reported instead, naming both the extension that lost and the
    existing owner. Contributed ``Mount`` entries are rejected explicitly
    because FastAPI's ``include_router`` silently ignores them.

    Fail-open per router: one malformed contribution must not cost the Gateway
    every other extension's routes.
    """
    diagnostics: list[Diagnostic] = []
    if not extensions.routers:
        return diagnostics

    mounted: list[str] = []
    owners: _RouteOwners = []
    for route in getattr(app, "routes", []):
        claim = _route_claim(route)
        if claim is not None:
            owners.append((claim, "host"))

    for source, router in extensions.routers:
        try:
            routes = _router_routes(router)
            if not routes:
                raise TypeError(f"contributed router exposes no routes: {router!r}")
            clash = _find_route_clash(routes, owners)
            if clash is not None:
                path, holder = clash
                message = f"router path {path} is already served by {holder}; this router was not mounted"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
                continue
            app.include_router(router)
            for route in routes:
                owners.append((route, source))
                mounted.append(f"{source} -> {route.path}")
        except Exception as exc:
            message = f"router could not be mounted; continuing without it: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)

    # Which URLs the Gateway just handed to third-party code is operational
    # information, so it is reported rather than left to be discovered by
    # reading /openapi.json. Attributed per path, like every other diagnostic
    # in this module.
    if mounted:
        logger.info("Extension routers mounted: %s", "; ".join(mounted))
    return diagnostics


async def start_services(
    extensions: LoadedExtensions,
    app_config: Any,
    session_factory: Any | None,
) -> list[Diagnostic]:
    """Start every extension service. Fail-open per service."""
    diagnostics: list[Diagnostic] = []
    if not extensions.services:
        return diagnostics

    deps = ExtensionRuntimeDeps(
        app_store=extensions.app_store,
        policy=project_host_policy(app_config),
        session_factory=session_factory,
    )
    for source, service in extensions.services:
        try:
            await service.start(deps)
        except Exception as exc:
            message = f"service start() failed; continuing without it: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)
    return diagnostics


async def stop_services(
    extensions: LoadedExtensions,
    timeout_seconds: float = DEFAULT_STOP_TIMEOUT_SECONDS,
) -> list[Diagnostic]:
    """Stop services in reverse start order, bounded and fail-open."""
    diagnostics: list[Diagnostic] = []
    for source, service in reversed(extensions.services):
        try:
            await asyncio.wait_for(service.stop(), timeout=timeout_seconds)
        except TimeoutError:
            message = f"service stop() timed out after {timeout_seconds}s; continuing shutdown"
            diagnostics.append(Diagnostic.error(source, message))
            logger.error("Extension %s: %s", source, message)
        except Exception as exc:
            message = f"service stop() failed; continuing shutdown: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)
    return diagnostics
