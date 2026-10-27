"""Session-authenticated management of operator-scoped RAGFlow datasets.

The existing knowledge_search configuration owns the credential and dataset
allowlist. Read access follows its tool policy; only administrators may mutate
the shared corpus. Agent tools remain read-only.
"""

import asyncio
import math
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.auth import require_session_source
from deerflow.authz.provider import AuthzDecision, AuthzRequest, Principal
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.community.ragflow.client import RAGFlowError
from deerflow.community.ragflow.tools import _api_key, _build_client, _settings_from_extra
from deerflow.config import get_app_config

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base"], dependencies=[Depends(require_session_source)])
Identifier = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,256}$")]
MAX_FILE_BYTES = 50 * 1024 * 1024


def _error(status: int, code: str, message: str):
    return HTTPException(status, detail={"code": code, "message": message})


async def _access(request: Request, *, write: bool = False):
    user = await get_current_user_from_request(request)
    admin = user.system_role == "admin"
    if write and not admin:
        raise _error(403, "knowledge_admin_required", "Administrator access is required to change the shared knowledge base.")
    config = await asyncio.to_thread(get_app_config)
    if config.authorization.enabled:
        try:
            provider = await asyncio.to_thread(resolve_authorization_provider, config.authorization)
            decision = await provider.aauthorize(AuthzRequest(principal=Principal(user_id=str(user.id), role=user.system_role), resource="tool", action="call", target="knowledge_search"))
            allowed = isinstance(decision, AuthzDecision) and decision.allow
        except Exception:
            allowed = False
        if not allowed:
            raise _error(403, "knowledge_access_denied", "Knowledge search permission is required.")
    tool = config.get_tool_config("knowledge_search")
    if tool is None or tool.use != "deerflow.community.ragflow.tools:knowledge_search_tool":
        raise _error(503, "ragflow_not_configured", "Knowledge management requires the RAGFlow knowledge_search provider.")
    try:
        settings = _settings_from_extra(tool.model_extra or {})
    except ValidationError:
        raise _error(503, "ragflow_not_configured", "Invalid RAGFlow settings in config.yaml.") from None
    if not _api_key(settings):
        raise _error(503, "ragflow_not_configured", "Configure the RAGFlow knowledge_search tool URL and API key in config.yaml.")
    return settings, _build_client(settings), admin


@asynccontextmanager
async def _provider_errors():
    try:
        yield
    except RAGFlowError:
        # Upstream errors can contain credentials, paths or document contents.
        raise _error(502, "ragflow_unavailable", "RAGFlow request failed. Check its connection, API key and model configuration, then retry.") from None


async def _dataset(client, settings, dataset_id: str):
    if settings.datasets is not None and dataset_id not in settings.datasets:
        raise _error(404, "dataset_not_found", "Knowledge base not found.")
    datasets = await client.list_datasets(dataset_id=dataset_id)
    if not any(item.get("id") == dataset_id for item in datasets):
        raise _error(404, "dataset_not_found", "Knowledge base not found.")


def _dataset_view(item):
    return {"id": str(item["id"]), "name": str(item.get("name", "")), "document_count": item.get("document_count", 0), "chunk_count": item.get("chunk_count", 0)}


def _document_view(item):
    raw = str(item.get("run", "UNSTART")).upper()
    status = {"0": "pending", "1": "parsing", "2": "cancelled", "3": "ready", "4": "failed", "UNSTART": "pending", "RUNNING": "parsing", "CANCEL": "cancelled", "DONE": "ready", "FAIL": "failed"}.get(raw, "unknown")
    progress = item.get("progress", 0)
    progress = min(1, max(0, progress)) if isinstance(progress, (int, float)) and math.isfinite(progress) else 0
    return {"id": str(item["id"]), "name": str(item.get("name", "")), "size": item.get("size", 0), "chunk_count": item.get("chunk_count", 0), "status": status, "progress": progress}


@router.get("/datasets")
async def list_datasets(request: Request):
    settings, client, admin = await _access(request)
    async with _provider_errors():
        datasets = await client.list_datasets()
    visible = [item for item in datasets if isinstance(item.get("id"), str) and (settings.datasets is None or item["id"] in settings.datasets)]
    return {"datasets": [_dataset_view(item) for item in visible], "can_upload": admin, "can_create": admin and settings.datasets is None, "max_file_bytes": MAX_FILE_BYTES}


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def clean_name(cls, name):
        if not name.strip():
            raise ValueError("Name must not be blank")
        return name.strip()


@router.post("/datasets")
async def create_dataset(request: Request, body: DatasetCreate):
    settings, client, _ = await _access(request, write=True)
    if settings.datasets is not None:
        raise _error(403, "dataset_creation_disabled", "New knowledge bases must be added to the operator dataset allowlist first.")
    async with _provider_errors():
        return _dataset_view(await client.create_dataset(body.name))


@router.get("/datasets/{dataset_id}/documents")
async def list_documents(request: Request, dataset_id: Identifier, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    settings, client, _ = await _access(request)
    async with _provider_errors():
        await _dataset(client, settings, dataset_id)
        data = await client.list_documents(dataset_id, page=page, page_size=page_size)
    return {"documents": [_document_view(item) for item in data["docs"] if isinstance(item, dict) and isinstance(item.get("id"), str)], "total": data["total"]}


class _UploadTooLarge(MultiPartException):
    pass


class _UploadParser(MultiPartParser):
    def on_part_data(self, data, start, end):
        # One file per request, so the cumulative file count is also its size.
        if self._current_part.file is not None:
            self.file_bytes = getattr(self, "file_bytes", 0) + end - start
            if self.file_bytes > MAX_FILE_BYTES:
                raise _UploadTooLarge("File exceeds the upload limit.")
        super().on_part_data(data, start, end)


async def _bounded_stream(request):
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_FILE_BYTES + 1024 * 1024:
            raise _UploadTooLarge("File exceeds the upload limit.")
        yield chunk


@router.post("/datasets/{dataset_id}/documents")
async def upload_document(request: Request, dataset_id: Identifier):
    settings, client, _ = await _access(request, write=True)
    async with _provider_errors():
        await _dataset(client, settings, dataset_id)
        if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "multipart/form-data":
            raise _error(422, "invalid_upload", "Select a file to upload.")
        form = None
        try:
            form = await _UploadParser(request.headers, _bounded_stream(request), max_files=1, max_fields=0).parse()
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise _error(422, "invalid_upload", "The file field is required.")
            name = file.filename or ""
            if not name.strip() or name in {".", ".."} or len(name) > 255 or any(c in name for c in "/\\\r\n\x00"):
                raise _error(422, "invalid_upload", "Invalid filename.")
            content = await file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise _UploadTooLarge("File exceeds the upload limit.")
            if not content:
                raise _error(422, "invalid_upload", "Empty files cannot be uploaded.")
            documents = await client.upload_document(dataset_id, filename=name, content=content, content_type=file.content_type or "application/octet-stream")
        except _UploadTooLarge:
            raise _error(413, "upload_too_large", "File exceeds the upload limit.") from None
        except MultiPartException:
            raise _error(400, "invalid_upload", "Upload exactly one file per request.") from None
        finally:
            if form is not None:
                await form.close()
        parsing_started = True
        try:
            await client.parse_documents(dataset_id, [item["id"] for item in documents])
        except RAGFlowError:
            parsing_started = False
        return {"documents": [_document_view(item) for item in documents], "parsing_started": parsing_started}


@router.post("/datasets/{dataset_id}/documents/{document_id}/parse")
async def parse_document(request: Request, dataset_id: Identifier, document_id: Identifier):
    settings, client, _ = await _access(request, write=True)
    async with _provider_errors():
        await _dataset(client, settings, dataset_id)
        data = await client.list_documents(dataset_id, document_id=document_id)
        if not any(item.get("id") == document_id for item in data["docs"]):
            raise _error(404, "document_not_found", "Document not found.")
        await client.parse_documents(dataset_id, [document_id])
    return {"parsing_started": True}
