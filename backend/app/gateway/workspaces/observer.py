"""Delivery-time authorization around native read-only SSE observation."""

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from fastapi.responses import Response

from app.gateway.auth import decode_token
from app.gateway.auth.jwt import TokenPayload
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.authz import resolve_route_permissions
from app.gateway.deps import get_current_user_from_request, get_run_store, get_thread_store
from app.gateway.workspaces.checkpoints import capture_checkpoint_thread_identity
from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.runtime.runs.stream_cleanup import close_agent_stream

logger = logging.getLogger(__name__)


async def wrap_private_observer(response, request: Request, *, thread_id, run_id):
    context = get_current_workspace()
    if context is None:
        return response
    runs, threads = get_run_store(request), get_thread_store(request)
    if not isinstance(runs, RunRepository) or not isinstance(threads, ThreadMetaRepository) or runs._sf is not threads._sf:
        raise HTTPException(status_code=503, detail="Private observation requires compatible durable storage")
    incarnation = await capture_checkpoint_thread_identity(request, thread_id)
    user = await get_current_user_from_request(request)
    payload = decode_token(request.cookies.get("access_token", ""))
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION or not isinstance(payload, TokenPayload) or payload.sub != context.actor_user_id or payload.ver != user.token_version:
        raise HTTPException(status_code=401, detail="Private observation requires a current browser session")
    # Retain only native principal attributes; no password hash or JWT is
    # copied into the observer receipt, database, bridge or response metadata.
    principal = user.model_copy(update={"password_hash": None}, deep=True)
    return WorkspaceObserverResponse(response, runs=runs, context=context, thread_id=thread_id, run_id=run_id, incarnation=incarnation, principal=principal, expires_at=payload.exp)


class WorkspaceObserverResponse(Response):
    def __init__(self, response, *, runs, context, thread_id, run_id, incarnation, principal, expires_at):
        super().__init__(status_code=response.status_code, media_type=response.media_type, background=response.background)
        self.raw_headers = response.raw_headers
        self.headers["Cache-Control"] = "private, no-store"
        self._response = response
        self._runs = runs
        self._context = context
        self._thread_id = thread_id
        self._run_id = run_id
        self._incarnation = incarnation
        self._principal = principal
        self._expires_at = expires_at

    async def _authorize(self):
        if datetime.now(UTC) >= self._expires_at or "runs:read" not in await resolve_route_permissions(self._principal, is_internal=False):
            raise WorkspaceAccessDenied("observer authority expired")
        allowed = await self._runs.can_observe_private_run(
            self._run_id,
            thread_id=self._thread_id,
            incarnation=self._incarnation,
            user_id=self._context.actor_user_id,
            token_version=self._principal.token_version,
            system_role=self._principal.system_role,
            oauth_provider=self._principal.oauth_provider,
            oauth_id=self._principal.oauth_id,
        )
        if not allowed or datetime.now(UTC) >= self._expires_at:
            raise WorkspaceAccessDenied("observer authority changed")

    async def _guarded(self, source):
        try:
            async for chunk in source:
                try:
                    await self._authorize()
                except WorkspaceAccessDenied:
                    return  # Transport closure is not a native Run completion.
                except Exception:
                    logger.exception("Private observer authorization unavailable; closing delivery")
                    return
                yield chunk
        finally:
            await close_agent_stream(source)

    async def __call__(self, scope, receive, send):
        token = set_current_workspace(self._context)
        original = self._response.body_iterator
        try:
            try:
                await self._authorize()
            except WorkspaceAccessDenied:
                raise HTTPException(status_code=404, detail="Workspace or resource not found") from None
            except Exception:
                raise HTTPException(status_code=503, detail="Private observation authorization unavailable") from None
            self._response.body_iterator = self._guarded(original)
            self._response.background = self.background
            await self._response(scope, receive, send)
        finally:
            try:
                await close_agent_stream(self._response.body_iterator)
                await close_agent_stream(original)
            finally:
                reset_current_workspace(token)
