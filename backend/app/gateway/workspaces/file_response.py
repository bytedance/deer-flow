"""Workspace file publication checks before ASGI emits response headers."""

import asyncio
import logging

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)


class WorkspaceFileResponse(FileResponse):
    def __init__(self, path, *, workspace_service, repository, context, project_id, document_id, **kwargs):
        super().__init__(path, **kwargs)
        self._workspace_service = workspace_service
        self._repository = repository
        self._context = context
        self._project_id = project_id
        self._document_id = document_id
        self.headers["Cache-Control"] = "private, no-store"

    async def __call__(self, scope, receive, send):
        token = set_current_workspace(self._context)
        try:
            await self._workspace_service.revalidate(self._context)
            row = await self._repository.get(self._document_id, user_id=self._context.actor_user_id)
            if row is None or row["project_id"] != self._project_id:
                raise HTTPException(status_code=404, detail="Workspace or resource not found")
            await super().__call__(scope, receive, send)
        except WorkspaceAccessDenied:
            raise HTTPException(status_code=404, detail="Workspace or resource not found") from None
        finally:
            reset_current_workspace(token)


class WorkspaceThreadResponse(Response):
    """Fence native file and bounded archive responses before any ASGI headers."""

    def __init__(self, response, *, workspace_service, repository, context, thread_id, incarnation, close_unpublished=None):
        super().__init__(status_code=response.status_code, media_type=response.media_type, background=response.background)
        self.raw_headers = response.raw_headers
        self.headers["Cache-Control"] = "private, no-store"
        self._response = response
        self._workspace_service = workspace_service
        self._repository = repository
        self._context = context
        self._thread_id = thread_id
        self._incarnation = incarnation
        self._close_unpublished = close_unpublished

    async def discard_unpublished(self):
        """Release only this response's owned resource, never arbitrary background work."""
        close, self._close_unpublished = self._close_unpublished, None
        if close is not None:
            try:
                await await_drained(asyncio.to_thread(close))
            except Exception as exc:
                # Preserve authorization/transport failures without logging paths.
                logger.error("Failed to close owned workspace response (%s)", type(exc).__name__)

    async def __call__(self, scope, receive, send):
        token = set_current_workspace(self._context)
        try:
            await self._workspace_service.revalidate(self._context)
            row = await self._repository.get(self._thread_id, user_id=self._context.actor_user_id)
            if row is None or row["incarnation"] != self._incarnation:
                raise HTTPException(status_code=404, detail="Workspace or resource not found")
            # FastAPI may attach background tasks after this wrapper was built.
            self._response.background = self.background
            await self._response(scope, receive, send)
        except WorkspaceAccessDenied:
            raise HTTPException(status_code=404, detail="Workspace or resource not found") from None
        finally:
            try:
                await self.discard_unpublished()
            finally:
                reset_current_workspace(token)
