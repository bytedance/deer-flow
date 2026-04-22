"""Validation helpers for config-driven auth route policies."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.plugins.auth.injection.registry_loader import RoutePolicyRegistry

_IGNORED_METHODS = frozenset({"HEAD", "OPTIONS"})


def _iter_route_keys(app: FastAPI) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if method in _IGNORED_METHODS:
                continue
            keys.add((method, route.path))
    return keys


def validate_route_policy_registry(app: FastAPI, registry: RoutePolicyRegistry) -> None:
    route_keys = _iter_route_keys(app)
    missing = sorted(route_keys - registry.keys)
    extra = sorted(registry.keys - route_keys)
    problems: list[str] = []
    if missing:
        problems.append("Missing route policy entries:\n" + "\n".join(f"  - {method} {path}" for method, path in missing))
    if extra:
        problems.append("Unknown route policy entries:\n" + "\n".join(f"  - {method} {path}" for method, path in extra))
    if problems:
        raise RuntimeError("\n\n".join(problems))


__all__ = ["validate_route_policy_registry"]
