"""Workspace file publication checks before ASGI emits response headers."""

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied


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

    def __init__(self, response, *, workspace_service, repository, context, thread_id, incarnation):
        super().__init__(status_code=response.status_code, media_type=response.media_type, background=response.background)
        self.raw_headers = response.raw_headers
        self.headers["Cache-Control"] = "private, no-store"
        self._response = response
        self._workspace_service = workspace_service
        self._repository = repository
        self._context = context
        self._thread_id = thread_id
        self._incarnation = incarnation

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
            reset_current_workspace(token)
