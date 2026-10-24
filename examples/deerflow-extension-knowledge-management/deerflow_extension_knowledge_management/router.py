"""Session-authenticated, bounded HTTP surface independent of provider APIs."""

import logging
from typing import Literal

from deerflow_extension_api.auth import arequire_plugin_management
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .contracts import IngestRequest, ManagementContext, ManagementCredentialUnavailable, ManagementProvider, ProcessingOptions

logger = logging.getLogger(__name__)

NAMESPACE = "knowledge-management"
MAX_UPLOAD_BYTES = 16 * 1024 * 1024


async def _context(request: Request) -> ManagementContext:
    try:
        principal = await arequire_plugin_management(request, NAMESPACE, scope="read" if request.method == "GET" else "write")
        if not principal.is_admin or principal.is_internal:
            raise PermissionError
    except PermissionError:
        raise HTTPException(403, "Knowledge management access denied") from None
    return ManagementContext(principal=principal)


async def _invoke(awaitable):
    try:
        return await awaitable
    except PermissionError:
        raise HTTPException(403, "Knowledge resource access denied") from None
    except FileNotFoundError:
        raise HTTPException(404, "Knowledge resource unavailable") from None
    except FileExistsError:
        raise HTTPException(409, "Knowledge resource conflict; reconcile before retrying") from None
    except NotImplementedError:
        raise HTTPException(422, "Unsupported knowledge capability") from None
    except ValueError:
        raise HTTPException(422, "Invalid management request") from None
    except ManagementCredentialUnavailable as exc:
        logger.warning("Knowledge management local configuration failed: %s", type(exc).__name__)
        raise HTTPException(503, "Management credential is not configured") from None
    except RuntimeError as exc:
        # Exception text/chains can contain provider credentials or source data.
        logger.warning("Knowledge management provider invocation failed: %s", type(exc).__name__)
        raise HTTPException(502, "Provider request failed; reconcile state before retrying a write") from None


async def _json(request: Request, model):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 2 * 1024 * 1024:
            raise HTTPException(413, "Management JSON exceeds 2 MiB")
        content.extend(chunk)
    try:
        return model.model_validate_json(content)
    except ValidationError:
        raise HTTPException(422, "Invalid management request") from None


def build_router(provider: ManagementProvider) -> APIRouter:
    router = APIRouter(prefix="/api/extensions/knowledge-management", tags=["knowledge-management"])
    prefix = "/connections/{connection}/bases/{base}"

    @router.get(prefix + "/capabilities")
    async def capabilities(connection: str, base: str, context: ManagementContext = Depends(_context)):
        return await _invoke(provider.capabilities(context, connection, base))

    @router.post(prefix + "/documents", status_code=202)
    async def ingest(request: Request, connection: str, base: str, context: ManagementContext = Depends(_context)):
        body = await _json(request, IngestRequest)
        return await _invoke(provider.ingest(context, connection, base, body))

    @router.post(prefix + "/files", status_code=202)
    async def upload(request: Request, connection: str, base: str, filename: str, context: ManagementContext = Depends(_context)):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/octet-stream":
            raise HTTPException(415, "Use application/octet-stream")
        try:
            options = ProcessingOptions.model_validate_json(request.headers.get("x-processing-options", "{}"))
        except ValidationError:
            raise HTTPException(422, "Invalid processing options") from None
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Upload exceeds 16 MiB")
            content.extend(chunk)
        return await _invoke(provider.upload(context, connection, base, filename, bytes(content), options))

    @router.get(prefix + "/documents/{document}")
    async def status(connection: str, base: str, document: str, context: ManagementContext = Depends(_context)):
        return await _invoke(provider.status(context, connection, base, document))

    @router.post(prefix + "/documents/{document}/{action}", status_code=202)
    async def process(request: Request, connection: str, base: str, document: str, action: Literal["reprocess", "cancel"], context: ManagementContext = Depends(_context)):
        body = await _json(request, ProcessingOptions)
        return await _invoke(provider.process(context, connection, base, document, action, body))

    return router
