"""Gateway-side plumbing for app-scoped extension contributions."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from deerflow_extension_api import ExtensionRuntimeDeps

from deerflow.extensions.loader import Diagnostic
from deerflow.extensions.policy import project_host_policy
from deerflow.extensions.registry import LoadedExtensions

logger = logging.getLogger(__name__)

DEFAULT_STOP_TIMEOUT_SECONDS = 30.0

_PATH_PARAMETER_GROUP = re.compile(r"\(\?P<[^>]+>")
_PATH_PARAMETER = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?}")
_RouteMethods = frozenset[str] | None
_RouteScopes = frozenset[str]
_HOST_PUBLIC_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/oauth/",
    "/api/v1/auth/callback/",
    "/api/webhooks/",
)


@dataclass(frozen=True)
class _RouteClaim:
    path: str
    matcher: str
    methods: _RouteMethods
    scopes: _RouteScopes
    mount_prefix: str | None = None


_RouteOwners = list[tuple[_RouteClaim, str]]


def _cancellation_count() -> int:
    task = asyncio.current_task()
    return task.cancelling() if task is not None else 0


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
    from fastapi.routing import _DefaultLifespan
    from starlette.routing import Mount, Route, WebSocketRoute

    if getattr(router, "on_startup", ()) or getattr(router, "on_shutdown", ()):
        raise TypeError("contributed router lifecycle hooks are not supported; register an ExtensionService instead")
    lifespan_context = getattr(router, "lifespan_context", None)
    if lifespan_context is not None and not isinstance(lifespan_context, _DefaultLifespan):
        raise TypeError("contributed router lifespan is not supported; register an ExtensionService instead")

    claims: list[_RouteClaim] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, Mount):
            raise TypeError("contributed router contains a Starlette Mount, which FastAPI.include_router() ignores")
        if isinstance(route, WebSocketRoute):
            raise TypeError("contributed WebSocket routes are not supported until the host can apply authentication and Origin checks")
        if not isinstance(route, Route):
            raise TypeError(f"contributed router contains an unsupported route item: {type(route).__name__}")
        claim = _route_claim(route)
        if claim is not None:
            literal_prefix = claim.path.partition("{")[0]
            if any(claim.path.startswith(public_prefix) or public_prefix.startswith(literal_prefix) for public_prefix in _HOST_PUBLIC_PATH_PREFIXES):
                raise TypeError(f"contributed route {claim.path} can enter a host public namespace")
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


def _path_segments(path: str) -> tuple[tuple[str, str], ...] | None:
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


def _compound_segment_covers(owner: str, candidate: str) -> bool:
    owner_literals, owner_convertors = _path_shape(owner)
    candidate_literals, candidate_convertors = _path_shape(candidate)
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


def _compound_segment_matches_static(compound: str, value: str) -> bool:
    from starlette.routing import compile_path

    matcher, _path_format, _convertors = compile_path(f"/{compound}")
    return re.fullmatch(matcher.pattern, f"/{value}") is not None


def _segment_covers(owner: tuple[str, str], candidate: tuple[str, str]) -> bool:
    owner_kind, owner_value = owner
    candidate_kind, candidate_value = candidate
    if owner_kind == "literal":
        return candidate_kind == "literal" and owner_value == candidate_value
    if owner_kind == "parameter" and candidate_kind == "compound":
        if owner_value == "path":
            return True
        if owner_value == "str":
            return all((match.group(2) or "str") in {"str", "int", "float", "uuid"} for match in _PATH_PARAMETER.finditer(candidate_value))
        return False
    if owner_kind == "compound":
        if candidate_kind == "literal":
            return _compound_segment_matches_static(owner_value, candidate_value)
        if candidate_kind == "compound":
            return _compound_segment_covers(owner_value, candidate_value)
        return False
    if candidate_kind == "compound":
        return False
    if candidate_kind == "literal":
        return _static_segment_matches(owner_value, candidate_value)
    return _convertor_covers(owner_value, candidate_value)


def _segmented_path_covers(owner_path: str, candidate_path: str) -> bool:
    owner = _path_segments(owner_path)
    candidate = _path_segments(candidate_path)
    if owner is None or candidate is None:
        return False

    if owner and owner[-1] == ("parameter", "path"):
        prefix = owner[:-1]
        return len(candidate) > len(prefix) and all(_segment_covers(owner_segment, candidate_segment) for owner_segment, candidate_segment in zip(prefix, candidate, strict=False))

    return len(owner) == len(candidate) and all(_segment_covers(owner_segment, candidate_segment) for owner_segment, candidate_segment in zip(owner, candidate, strict=True))


def _matcher_covers(owner: _RouteClaim, candidate: _RouteClaim) -> bool:
    """Return whether every candidate path is consumed by an earlier owner."""
    if owner.matcher == candidate.matcher:
        return True

    owner_literals, owner_convertors = _path_shape(owner.path)
    candidate_literals, candidate_convertors = _path_shape(candidate.path)

    if not candidate_convertors:
        return re.fullmatch(owner.matcher, candidate.path) is not None

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


def _find_route_clash(
    routes: list[_RouteClaim],
    owners: _RouteOwners,
    candidate_holder: str,
) -> tuple[str, str] | None:
    tentative_owners = list(owners)
    for route in routes:
        for owner, holder in tentative_owners:
            if _dispatches_overlap(route, owner) and _matcher_covers(owner, route):
                return route.path, holder
        tentative_owners.append((route, candidate_holder))
    return None


def include_contributed_routers(app: Any, extensions: LoadedExtensions) -> list[Diagnostic]:
    """Mount reachable routers in order and reject definite shadows atomically."""
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
            clash = _find_route_clash(routes, owners, source)
            if clash is not None:
                path, holder = clash
                message = f"router path {path} is already served by {holder}; this router was not mounted"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
                continue
            app_routes = getattr(getattr(app, "router", None), "routes", None)
            route_mark = len(app_routes) if isinstance(app_routes, list) else None
            try:
                app.include_router(router)
            except BaseException:
                # FastAPI copies one route at a time. If a later copy fails,
                # remove every route added by this attempt before either
                # continuing fail-open or propagating a host-level exception.
                if route_mark is not None:
                    del app_routes[route_mark:]
                raise
            for route in routes:
                owners.append((route, source))
                mounted.append(f"{source} -> {route.path}")
        except Exception as exc:
            message = f"router could not be mounted; continuing without it: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)

    if mounted:
        logger.info("Extension routers mounted: %s", "; ".join(mounted))
    return diagnostics


async def start_services(
    extensions: LoadedExtensions,
    app_config: Any,
    session_factory: Any | None,
    *,
    attempted_services: list[tuple[str, Any]] | None = None,
) -> list[Diagnostic]:
    """Start extension services in registration order, failing open per item."""
    diagnostics: list[Diagnostic] = []
    if not extensions.services:
        return diagnostics

    deps = ExtensionRuntimeDeps(
        app_store=extensions.app_store,
        policy=project_host_policy(app_config),
        session_factory=session_factory,
    )
    for entry in extensions.services:
        source, service = entry
        if attempted_services is not None:
            # Record before awaiting start(): a service may acquire resources
            # and then fail or be cancelled, so it still owns stop().
            attempted_services.append(entry)
        cancellation_count = _cancellation_count()
        try:
            await service.start(deps)
        except asyncio.CancelledError:
            if _cancellation_count() > cancellation_count:
                raise
            message = "service start() raised CancelledError; continuing without it"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)
        except Exception as exc:
            message = f"service start() failed; continuing without it: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)
    return diagnostics


async def stop_services(
    extensions: LoadedExtensions,
    timeout_seconds: float = DEFAULT_STOP_TIMEOUT_SECONDS,
    *,
    service_entries: tuple[tuple[str, Any], ...] | list[tuple[str, Any]] | None = None,
) -> list[Diagnostic]:
    """Stop services in reverse order with an independent budget per item."""
    diagnostics: list[Diagnostic] = []
    entries = extensions.services if service_entries is None else service_entries
    for source, service in reversed(entries):
        cancellation_count = _cancellation_count()
        timeout = asyncio.timeout(timeout_seconds)
        try:
            async with timeout:
                await service.stop()
        except TimeoutError as exc:
            if timeout.expired():
                message = f"service stop() timed out after {timeout_seconds}s; continuing shutdown"
                diagnostics.append(Diagnostic.error(source, message))
                logger.error("Extension %s: %s", source, message)
            else:
                message = f"service stop() failed; continuing shutdown: {exc}"
                diagnostics.append(Diagnostic.error(source, message))
                logger.exception("Extension %s: %s", source, message)
        except asyncio.CancelledError:
            if _cancellation_count() > cancellation_count:
                raise
            message = "service stop() raised CancelledError; continuing shutdown"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)
        except Exception as exc:
            message = f"service stop() failed; continuing shutdown: {exc}"
            diagnostics.append(Diagnostic.error(source, message))
            logger.exception("Extension %s: %s", source, message)
    return diagnostics
