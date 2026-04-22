"""Runtime route guard backed by the auth plugin's route policy registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request

from app.plugins.auth.authorization.authentication import (
    authenticate_request,
    get_auth_context,
    set_auth_context,
)
from app.plugins.auth.authorization.authorization import ensure_authenticated
from app.plugins.auth.authorization.hooks import get_authz_hooks
from app.plugins.auth.authorization.policies import require_run_owner, require_thread_owner
from app.plugins.auth.injection.registry_loader import RoutePolicyRegistry, RoutePolicySpec

PolicyGuard = Callable[[Request, RoutePolicySpec], Awaitable[None]]


async def _check_capability(request: Request, spec: RoutePolicySpec) -> None:
    if not spec.capability:
        return

    auth = get_auth_context(request)
    if auth is None:
        raise HTTPException(status_code=500, detail="Missing auth context")

    if ":" not in spec.capability:
        raise RuntimeError(f"Invalid capability format: {spec.capability}")
    resource, action = spec.capability.split(":", 1)
    if not auth.has_permission(resource, action):
        raise HTTPException(status_code=403, detail=f"Permission denied: {spec.capability}")


async def _guard_thread_owner(request: Request, spec: RoutePolicySpec) -> None:
    auth = get_auth_context(request)
    if auth is None:
        raise HTTPException(status_code=500, detail="Missing auth context")
    thread_id = request.path_params.get("thread_id")
    if not isinstance(thread_id, str):
        raise RuntimeError("owner:thread policy requires thread_id path parameter")
    await require_thread_owner(request, auth, thread_id=thread_id, require_existing=spec.require_existing)


async def _guard_run_owner(request: Request, spec: RoutePolicySpec) -> None:
    auth = get_auth_context(request)
    if auth is None:
        raise HTTPException(status_code=500, detail="Missing auth context")
    thread_id = request.path_params.get("thread_id")
    run_id = request.path_params.get("run_id")
    if not isinstance(thread_id, str) or not isinstance(run_id, str):
        raise RuntimeError("owner:run policy requires thread_id and run_id path parameters")
    await require_run_owner(
        request,
        auth,
        thread_id=thread_id,
        run_id=run_id,
        require_existing=spec.require_existing,
    )


_POLICY_GUARDS: dict[str, PolicyGuard] = {
    "owner:thread": _guard_thread_owner,
    "owner:run": _guard_run_owner,
}


async def enforce_route_policy(request: Request) -> None:
    registry = getattr(request.app.state, "auth_route_policy_registry", None)
    if not isinstance(registry, RoutePolicyRegistry):
        raise RuntimeError("Auth route policy registry is not configured")

    route = request.scope.get("route")
    path_template = getattr(route, "path", None)
    if not isinstance(path_template, str):
        raise RuntimeError("Unable to resolve route path for authorization")

    spec = registry.get(request.method, path_template)
    if spec is None:
        raise RuntimeError(f"Missing auth route policy for {request.method} {path_template}")
    if spec.public:
        return

    auth = get_auth_context(request)
    if auth is None:
        hooks = get_authz_hooks(request)
        auth = await authenticate_request(request, permission_provider=hooks.permission_provider)
        set_auth_context(request, auth)

    ensure_authenticated(auth)
    await _check_capability(request, spec)

    for policy_name in spec.policies:
        guard = _POLICY_GUARDS.get(policy_name)
        if guard is None:
            raise RuntimeError(f"Unknown route policy guard: {policy_name}")
        await guard(request, spec)


__all__ = ["enforce_route_policy"]
