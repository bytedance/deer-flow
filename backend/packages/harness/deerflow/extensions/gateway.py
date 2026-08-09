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
_HOST_PUBLIC_EXACT_PATHS = frozenset(
    {
        "/api/v1/auth/login/local",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/setup-status",
        "/api/v1/auth/initialize",
        "/api/v1/auth/providers",
    }
)
_HOST_CSRF_EXEMPT_EXACT_PATHS = frozenset({"/api/v1/auth/me"})
_CSRF_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
_STANDARD_CONVERTOR_REGEXES = {
    "str": "[^/]+",
    "path": ".*",
    "int": "[0-9]+",
    "float": r"[0-9]+(\.[0-9]+)?",
    "uuid": "[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}",
}


@dataclass(frozen=True)
class _RouteClaim:
    path: str
    matcher: str
    methods: _RouteMethods
    scopes: _RouteScopes
    mount_prefix: str | None = None
    standard_convertors: bool = True


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


def _route_claim(route: Any, *, recompile: bool = False) -> _RouteClaim | None:
    from starlette.routing import Mount, compile_path

    path = getattr(route, "path", None)
    if recompile and path is not None:
        path_regex, _path_format, param_convertors = compile_path(path)
        matcher = _PATH_PARAMETER_GROUP.sub("(?:", path_regex.pattern)
    else:
        matcher = _route_path_matcher(route)
        param_convertors = getattr(route, "param_convertors", {})
    if path is None or matcher is None:
        return None
    is_mount = isinstance(route, Mount)
    return _RouteClaim(
        path=path,
        matcher=matcher,
        methods=_route_methods(route),
        scopes=_route_scopes(route),
        mount_prefix=path.rstrip("/") if is_mount else None,
        standard_convertors=_uses_standard_convertors(
            path,
            param_convertors,
            is_mount=is_mount,
        ),
    )


def _uses_standard_convertors(
    path: str,
    param_convertors: Any,
    *,
    is_mount: bool,
) -> bool:
    for match in _PATH_PARAMETER.finditer(path):
        parameter_name = match.group(1)
        convertor_name = match.group(2) or "str"
        expected_regex = _STANDARD_CONVERTOR_REGEXES.get(convertor_name)
        actual_regex = getattr(param_convertors.get(parameter_name), "regex", None)
        if expected_regex is None or actual_regex != expected_regex:
            return False

    if is_mount:
        return getattr(param_convertors.get("path"), "regex", None) == _STANDARD_CONVERTOR_REGEXES["path"]
    return True


def _convertor_can_extend_prefix(convertor: str, prefix: str) -> bool:
    """Return a proven built-in-convertor witness beginning with ``prefix``.

    Public-route protection is a security boundary, so an unknown custom
    convertor fails closed when its value could begin inside a public prefix.
    Shadow detection remains separate and continues to allow relationships it
    cannot prove.
    """
    if convertor == "path":
        return True
    if convertor == "str":
        return "/" not in prefix
    if convertor == "int":
        return all(character in "0123456789" for character in prefix)
    if convertor == "float":
        if not prefix:
            return True
        return bool(re.fullmatch(r"[0-9]+", prefix) or re.fullmatch(r"[0-9]+\.", prefix) or re.fullmatch(r"[0-9]+\.[0-9]+", prefix))
    if convertor == "uuid":
        groups = (8, 4, 4, 4, 12)
        for mask in range(1 << (len(groups) - 1)):
            shape = ""
            for index, width in enumerate(groups):
                shape += "h" * width
                if index < len(groups) - 1 and mask & (1 << index):
                    shape += "-"
            if len(prefix) <= len(shape) and all((expected == "h" and character in "0123456789abcdefABCDEF") or character == expected for character, expected in zip(prefix, shape, strict=False)):
                return True
        return False
    return True


def _path_template_can_start_with(path: str, prefix: str) -> bool:
    """Whether a built-in route template has a concrete path under ``prefix``."""
    from functools import cache

    tokens: list[tuple[str, str]] = []
    cursor = 0
    for match in _PATH_PARAMETER.finditer(path):
        literal = path[cursor : match.start()]
        if literal:
            tokens.append(("literal", literal))
        tokens.append(("parameter", match.group(2) or "str"))
        cursor = match.end()
    trailing_literal = path[cursor:]
    if trailing_literal:
        tokens.append(("literal", trailing_literal))

    @cache
    def can_match(token_index: int, prefix_index: int) -> bool:
        if prefix_index == len(prefix):
            return True
        if token_index == len(tokens):
            return False

        kind, value = tokens[token_index]
        remaining = prefix[prefix_index:]
        if kind == "literal":
            if value.startswith(remaining):
                return True
            if remaining.startswith(value):
                return can_match(token_index + 1, prefix_index + len(value))
            return False

        registered_regex = _STANDARD_CONVERTOR_REGEXES.get(value)
        if registered_regex is None:
            return False
        for end_index in range(prefix_index, len(prefix) + 1):
            concrete = prefix[prefix_index:end_index]
            if re.fullmatch(registered_regex, concrete) is not None and can_match(
                token_index + 1,
                end_index,
            ):
                return True
        return _convertor_can_extend_prefix(value, remaining)

    return can_match(0, 0)


def _claim_can_enter_prefix(claim: _RouteClaim, prefix: str) -> bool:
    if claim.standard_convertors:
        return _path_template_can_start_with(claim.path, prefix)
    literal_prefix = claim.path.partition("{")[0]
    return claim.path.startswith(prefix) or prefix.startswith(literal_prefix)


def _claim_can_enter_exact_path(claim: _RouteClaim, exact_path: str) -> bool:
    """Whether a route can dispatch to ``exact_path`` plus trailing slashes."""
    if not claim.standard_convertors:
        return _claim_can_enter_prefix(claim, exact_path)

    # Auth and CSRF normalize with rstrip("/"), so two or more trailing
    # slashes are just as exempt as one. For built-in convertors, a shortest
    # slash-only witness is bounded by the template's literal length because
    # ``path`` may be empty and every other built-in rejects slash.
    for slash_count in range(len(claim.path) + 2):
        if (
            re.fullmatch(
                claim.matcher,
                exact_path + "/" * slash_count,
            )
            is not None
        ):
            return True

    # Custom regex language inclusion is deliberately not guessed at a
    # security boundary. If its template can reach the exact-path prefix,
    # reject it fail-closed; shadow matching below remains fail-open.
    return False


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
        # FastAPI.include_router() reconstructs every route from ``route.path``
        # using the converter registry at include time. Preflight must project
        # those same semantics, not the router object's older compiled regex.
        claim = _route_claim(route, recompile=True)
        if claim is not None:
            enters_public_exact_path = any(_claim_can_enter_exact_path(claim, public_path) for public_path in _HOST_PUBLIC_EXACT_PATHS)
            enters_csrf_exact_path = _methods_overlap(
                claim.methods,
                _CSRF_STATE_CHANGING_METHODS,
            ) and any(_claim_can_enter_exact_path(claim, exempt_path) for exempt_path in _HOST_CSRF_EXEMPT_EXACT_PATHS)
            enters_public_prefix = any(_claim_can_enter_prefix(claim, public_prefix) for public_prefix in _HOST_PUBLIC_PATH_PREFIXES)
            if enters_public_prefix:
                raise TypeError(f"contributed route {claim.path} can enter a host public namespace")
            if enters_public_exact_path or enters_csrf_exact_path:
                raise TypeError(f"contributed route {claim.path} can enter a host-reserved exact path")
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
    if owner == candidate:
        return True
    if owner == "path":
        return candidate in {"int", "float", "uuid"}
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
    registered_regex = _STANDARD_CONVERTOR_REGEXES.get(convertor)
    return registered_regex is not None and re.fullmatch(registered_regex, value) is not None


def _compound_segment_covers(owner: str, candidate: str) -> bool:
    owner_literals, owner_convertors = _path_shape(owner)
    candidate_literals, candidate_convertors = _path_shape(candidate)
    if (
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
    ):
        return True

    if len(owner_convertors) != 1 or owner_convertors[0] != "str":
        return False
    owner_prefix, owner_suffix = owner_literals
    minimum_candidate_length = sum(map(len, candidate_literals)) + sum(0 if convertor == "path" else 1 for convertor in candidate_convertors)
    return (
        candidate_literals[0].startswith(owner_prefix)
        and candidate_literals[-1].endswith(owner_suffix)
        and minimum_candidate_length > len(owner_prefix) + len(owner_suffix)
        and all(convertor in {"str", "int", "float", "uuid"} for convertor in candidate_convertors)
    )


def _compound_is_ascii_digits(compound: str) -> bool:
    literals, convertors = _path_shape(compound)
    return all(character in "0123456789" for literal in literals for character in literal) and all(convertor == "int" for convertor in convertors)


def _segment_excludes_newline(segment: tuple[str, str]) -> bool:
    kind, value = segment
    if kind == "literal":
        return "\n" not in value
    if kind == "parameter":
        return value in {"path", "int", "float", "uuid"}
    literals, convertors = _path_shape(value)
    return all("\n" not in literal for literal in literals) and all(convertor in {"path", "int", "float", "uuid"} for convertor in convertors)


def _compound_segment_matches_static(compound: str, value: str) -> bool:
    pattern = ""
    cursor = 0
    for match in _PATH_PARAMETER.finditer(compound):
        pattern += re.escape(compound[cursor : match.start()])
        convertor = match.group(2) or "str"
        registered_regex = _STANDARD_CONVERTOR_REGEXES.get(convertor)
        if registered_regex is None:
            return False
        pattern += f"(?:{registered_regex})"
        cursor = match.end()
    pattern += re.escape(compound[cursor:])
    return re.fullmatch(pattern, value) is not None


def _segment_covers(owner: tuple[str, str], candidate: tuple[str, str]) -> bool:
    owner_kind, owner_value = owner
    candidate_kind, candidate_value = candidate
    if owner_kind == "literal":
        return candidate_kind == "literal" and owner_value == candidate_value
    if owner_kind == "parameter" and candidate_kind == "compound":
        if owner_value == "path":
            return _segment_excludes_newline(candidate)
        if owner_value == "str":
            return all((match.group(2) or "str") in {"str", "int", "float", "uuid"} for match in _PATH_PARAMETER.finditer(candidate_value))
        if owner_value in {"int", "float"}:
            return _compound_is_ascii_digits(candidate_value)
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
        return (
            len(candidate) > len(prefix)
            and all(
                _segment_covers(owner_segment, candidate_segment)
                for owner_segment, candidate_segment in zip(
                    prefix,
                    candidate,
                    strict=False,
                )
            )
            and all(_segment_excludes_newline(candidate_segment) for candidate_segment in candidate[len(prefix) :])
        )

    return len(owner) == len(candidate) and all(_segment_covers(owner_segment, candidate_segment) for owner_segment, candidate_segment in zip(owner, candidate, strict=True))


def _matcher_covers(owner: _RouteClaim, candidate: _RouteClaim) -> bool:
    """Return whether every candidate path is consumed by an earlier owner."""
    if owner.matcher == candidate.matcher:
        return True

    if not owner.standard_convertors or not candidate.standard_convertors:
        return False

    owner_literals, owner_convertors = _path_shape(owner.path)
    candidate_literals, candidate_convertors = _path_shape(candidate.path)

    if not candidate_convertors:
        return re.fullmatch(owner.matcher, candidate.path) is not None

    if owner.mount_prefix is not None:
        if owner.mount_prefix == "":
            candidate_segments = _path_segments(candidate.path)
            return candidate_segments is not None and all(_segment_excludes_newline(segment) for segment in candidate_segments)
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
