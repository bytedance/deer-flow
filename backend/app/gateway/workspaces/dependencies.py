"""Authenticated HTTP management dependency; selectors never authenticate."""

import inspect
from functools import wraps

from fastapi import HTTPException, Request

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.deps import get_current_user_from_request
from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied


def get_workspace_service(request: Request):
    service = getattr(request.app.state, "workspace_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Workspace services are not activated")
    return service


async def require_workspace_session(request: Request, *, action):
    user = await get_current_user_from_request(request)
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION:
        raise HTTPException(status_code=403, detail="Workspace management requires a browser session")
    auth = getattr(request.state, "auth", None)
    if auth is None or auth.user is None or str(auth.user.id) != str(user.id) or not auth.has_permission("workspaces", action):
        raise HTTPException(status_code=403, detail="Workspace permission denied")
    return user


async def resolve_workspace_context(request: Request, *, selector=None):
    user = await require_workspace_session(request, action="read")
    service = get_workspace_service(request)
    header = request.headers.get("X-Deerflow-Workspace")
    if header is not None and selector is not None and header != selector:
        raise HTTPException(status_code=404, detail="Workspace or resource not found")
    return await service.resolve_context(str(user.id), header if header is not None else selector)


def workspace_resource_scope(*, allow_query_selector=False):
    """Bind only a live native-session scope for a resource request and its workers.

    Bind before native owner-check decorators, which require trusted scope.
    Plain native permissions may remain outside. Query selectors are permitted
    only on routes explicitly supporting browser file navigation.
    """

    def decorate(function):
        signature = inspect.signature(inspect.unwrap(function), eval_str=True)

        @wraps(function)
        async def scoped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            request = bound.arguments["request"]
            service = getattr(request.app.state, "workspace_service", None)
            if service is None:
                if getattr(request.app.state, "workspace_mode_enabled", False):
                    raise HTTPException(status_code=503, detail="Workspace services are not activated")
                return await function(*args, **kwargs)
            selector = request.query_params.get("workspace_id") if allow_query_selector else None
            context = await resolve_workspace_context(request, selector=selector)
            token = set_current_workspace(context)
            try:
                result = await function(*args, **kwargs)
                await service.revalidate(context)
                return result
            except WorkspaceAccessDenied:
                raise HTTPException(status_code=404, detail="Workspace or resource not found") from None
            finally:
                reset_current_workspace(token)

        scoped.__signature__ = signature
        return scoped

    return decorate
