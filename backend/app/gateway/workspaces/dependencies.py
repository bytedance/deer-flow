"""Authenticated HTTP management dependency; selectors never authenticate."""

from fastapi import HTTPException, Request

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.deps import get_current_user_from_request


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


async def resolve_workspace_context(request: Request):
    user = await require_workspace_session(request, action="read")
    service = get_workspace_service(request)
    return await service.resolve_context(str(user.id), request.headers.get("X-Deerflow-Workspace"))
