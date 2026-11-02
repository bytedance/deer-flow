"""Host-authenticated platform routes; no caller-provided identities or credentials."""

import logging
import sqlite3
from typing import Literal

from deerflow_extension_api.auth import arequire_plugin_management
from deerflow_extension_knowledge_management.contracts import IngestRequest, ManagementCredentialUnavailable, ProcessingOptions
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .models import Update
from .store import RevisionConflict, administrator

NAMESPACE = "knowledge-platform"
logger = logging.getLogger(__name__)


async def principal(request: Request):
    try:
        result = await arequire_plugin_management(request, NAMESPACE, scope="read" if request.method == "GET" else "write")
        if result.is_internal or not result.user_id:
            raise PermissionError
        return result
    except PermissionError:
        raise HTTPException(403, "Knowledge platform access denied") from None


async def manager(request: Request, caller=Depends(principal)):
    try:
        administrator(caller)
        await arequire_plugin_management(request, "knowledge-management", scope="read" if request.method == "GET" else "write")
        return caller
    except PermissionError:
        raise HTTPException(403, "Knowledge management access denied") from None


async def invoke(awaitable):
    try:
        return await awaitable
    except PermissionError:
        raise HTTPException(403, "Space or provider access denied") from None
    except RevisionConflict:
        raise HTTPException(409, "Policy changed; reload and reconcile before retrying") from None
    except FileNotFoundError:
        raise HTTPException(404, "Provider resource unavailable") from None
    except FileExistsError:
        raise HTTPException(409, "Resource conflict; reconcile before retrying") from None
    except NotImplementedError:
        raise HTTPException(422, "Unsupported capability or processing option") from None
    except ValueError:
        raise HTTPException(422, "Invalid platform policy or request") from None
    except ManagementCredentialUnavailable:
        raise HTTPException(503, "Management credential is not configured") from None
    except sqlite3.Error as exc:
        logger.warning("Knowledge platform storage failed: %s", type(exc).__name__)
        raise HTTPException(503, "Policy storage is busy or unavailable; reload policy before retrying") from None
    except RuntimeError as exc:
        logger.warning("Knowledge platform provider failed: %s", type(exc).__name__)
        raise HTTPException(502, "Provider request failed; reconcile before retrying a write") from None


async def bounded(request, limit):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise HTTPException(413, "Platform request exceeds size limit")
        data.extend(chunk)
    return bytes(data)


async def body(request, model):
    data = await bounded(request, 1024 * 1024)
    try:
        return model.model_validate_json(data)
    except ValidationError:
        raise HTTPException(422, "Invalid platform request") from None


def build_router(platform):
    router = APIRouter(prefix="/api/extensions/knowledge-platform", tags=[NAMESPACE])

    @router.get("/policy")
    async def policy(caller=Depends(principal)):
        return await invoke(platform.policy(caller))

    @router.put("/policy")
    async def replace(request: Request, caller=Depends(principal)):
        if not caller.is_admin:
            raise HTTPException(403, "Policy changes require an administrator")
        update = await body(request, Update)
        return await invoke(platform.replace(caller, update.policy, update.revision))

    @router.get("/spaces")
    async def spaces(caller=Depends(principal)):
        return await invoke(platform.spaces(caller))

    @router.get("/spaces/{space}")
    async def effective(space: str, caller=Depends(principal)):
        return await invoke(platform.effective(caller, space))

    prefix = "/spaces/{space}/resources/{resource}"

    @router.get(prefix + "/capabilities")
    async def capabilities(space: str, resource: str, caller=Depends(manager)):
        return await invoke(platform.invoke(caller, space, resource, "capabilities"))

    @router.post(prefix + "/documents", status_code=202)
    async def ingest(request: Request, space: str, resource: str, caller=Depends(manager)):
        data = await body(request, IngestRequest)
        return await invoke(platform.invoke(caller, space, resource, data.kind, data))

    @router.post(prefix + "/files", status_code=202)
    async def upload(request: Request, space: str, resource: str, filename: str, caller=Depends(manager)):
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
            raise HTTPException(415, "Use application/octet-stream")
        try:
            options = ProcessingOptions.model_validate_json(request.headers.get("x-processing-options", "{}"))
        except ValidationError:
            raise HTTPException(422, "Invalid processing options") from None
        data = await bounded(request, 16 * 1024 * 1024)
        return await invoke(platform.invoke(caller, space, resource, "upload", options, filename=filename, content=data))

    @router.get(prefix + "/documents/{document}")
    async def status(space: str, resource: str, document: str, caller=Depends(manager)):
        return await invoke(platform.invoke(caller, space, resource, "status", document))

    @router.post(prefix + "/documents/{document}/{action}", status_code=202)
    async def process(request: Request, space: str, resource: str, document: str, action: Literal["reprocess", "cancel"], caller=Depends(manager)):
        options = await body(request, ProcessingOptions)
        return await invoke(platform.invoke(caller, space, resource, action, options, document=document))

    return router
