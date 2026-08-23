"""Stateless, authenticated reverse proxy for RAGFlow knowledge management."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from python_multipart.multipart import MultipartParser, parse_options_header

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, require_admin_user
from app.gateway.knowledge import build_ragflow_client as _build_client
from app.gateway.knowledge import ragflow_api_key as _api_key
from app.gateway.knowledge.watcher import get_knowledge_watcher
from deerflow.community.ragflow.client import (
    RAGFlowAPIError,
    RAGFlowConnectionError,
    RAGFlowProtocolError,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.knowledge_base_config import KnowledgeBaseConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
_MAX_UPLOAD_REQUEST_BYTES = 100 * 1024 * 1024
_MAX_UPLOAD_FILES = 10
_ADMIN_REQUIRED_DETAIL = "Admin privileges are required to delete shared knowledge-base data."

_Identifier = Annotated[str, Field(min_length=1, max_length=256)]
_DatasetId = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
]


class DatasetCreateRequest(BaseModel):
    """RAGFlow dataset creation fields used by the management UI."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=65535)

    @field_validator("name")
    @classmethod
    def _non_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Dataset name must not be blank")
        return value


class ParseDocumentsRequest(BaseModel):
    document_ids: list[_Identifier] = Field(min_length=1, max_length=1000)


class DeleteDocumentsRequest(BaseModel):
    ids: list[_Identifier] = Field(min_length=1, max_length=1000)


class _UploadValidationError(Exception):
    def __init__(self, detail: str, *, status_code: int) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class _MultipartUploadValidator:
    """Incrementally validate multipart metadata without retaining file bytes."""

    def __init__(self, boundary: bytes, *, max_files: int, max_file_bytes: int) -> None:
        self.file_count = 0
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._current_file = False
        self._current_file_bytes = 0
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._headers: dict[bytes, bytes] = {}
        self.complete = False
        self.parser = MultipartParser(
            boundary,
            callbacks={
                "on_part_begin": self._on_part_begin,
                "on_header_field": self._on_header_field,
                "on_header_value": self._on_header_value,
                "on_header_end": self._on_header_end,
                "on_headers_finished": self._on_headers_finished,
                "on_part_data": self._on_part_data,
                "on_end": self._on_end,
            },
        )

    def _on_part_begin(self) -> None:
        self._current_file = False
        self._current_file_bytes = 0
        self._header_name.clear()
        self._header_value.clear()
        self._headers.clear()

    def _on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name.extend(data[start:end])

    def _on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value.extend(data[start:end])

    def _on_header_end(self) -> None:
        self._headers[bytes(self._header_name).lower()] = bytes(self._header_value)
        self._header_name.clear()
        self._header_value.clear()

    def _on_headers_finished(self) -> None:
        disposition = self._headers.get(b"content-disposition")
        if disposition is None:
            return
        _disposition_type, options = parse_options_header(disposition)
        if b"filename" not in options:
            return
        self._current_file = True
        self.file_count += 1
        if self.file_count > self._max_files:
            raise _UploadValidationError(
                f"A maximum of {self._max_files} files may be uploaded per request.",
                status_code=413,
            )

    def _on_part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._current_file:
            return
        self._current_file_bytes += end - start
        if self._current_file_bytes > self._max_file_bytes:
            raise _UploadValidationError(
                f"Each uploaded file must be at most {self._max_file_bytes} bytes.",
                status_code=413,
            )

    def _on_end(self) -> None:
        self.complete = True

    def write(self, chunk: bytes) -> None:
        try:
            self.parser.write(chunk)
        except _UploadValidationError:
            raise
        except Exception:
            raise _UploadValidationError("Malformed multipart upload.", status_code=400) from None

    def finalize(self) -> None:
        try:
            self.parser.finalize()
        except _UploadValidationError:
            raise
        except Exception:
            raise _UploadValidationError("Malformed multipart upload.", status_code=400) from None
        if not self.complete:
            raise _UploadValidationError("Incomplete multipart upload.", status_code=400)
        if self.file_count == 0:
            raise _UploadValidationError("The multipart request must contain at least one file.", status_code=400)


def _redact(value: object, api_key: str | None) -> str:
    text = str(value)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    return text


def _settings(config: AppConfig) -> KnowledgeBaseConfig:
    settings = config.knowledge_base
    if not settings.enabled:
        raise HTTPException(status_code=503, detail="Knowledge-base integration is disabled.")
    if _api_key(settings) is None:
        raise HTTPException(status_code=503, detail="RAGFlow API Key is not configured.")
    return settings


async def _proxy_result(
    operation: Awaitable[dict[str, Any]],
    *,
    settings: KnowledgeBaseConfig,
) -> dict[str, Any]:
    api_key = _api_key(settings)
    try:
        return await operation
    except _UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except RAGFlowAPIError as exc:
        logger.warning("RAGFlow rejected a knowledge-management request (code=%s)", exc.code)
        raise HTTPException(status_code=400, detail=_redact(exc, api_key)) from None
    except RAGFlowConnectionError:
        logger.warning("RAGFlow knowledge-management request could not connect")
        raise HTTPException(status_code=502, detail="Unable to connect to RAGFlow.") from None
    except RAGFlowProtocolError as exc:
        logger.warning("RAGFlow returned an invalid knowledge-management response")
        raise HTTPException(status_code=502, detail=_redact(exc, api_key)) from None
    except Exception as exc:
        logger.error("Unexpected RAGFlow knowledge-management failure (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="RAGFlow request failed.") from None


def _multipart_boundary(content_type: str | None) -> bytes:
    if content_type is None:
        raise HTTPException(status_code=400, detail="Content-Type must be multipart/form-data.")
    media_type, options = parse_options_header(content_type.encode("latin-1"))
    boundary = options.get(b"boundary")
    if media_type.lower() != b"multipart/form-data" or not boundary:
        raise HTTPException(status_code=400, detail="Content-Type must be multipart/form-data with a boundary.")
    return boundary


def _check_content_length(request: Request) -> None:
    raw_length = request.headers.get("content-length")
    if raw_length is None:
        return
    try:
        content_length = int(raw_length)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from None
    if content_length < 0:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
    if content_length > _MAX_UPLOAD_REQUEST_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"The multipart request must be at most {_MAX_UPLOAD_REQUEST_BYTES} bytes.",
        )


async def _validated_upload_body(request: Request, boundary: bytes) -> AsyncIterable[bytes]:
    validator = _MultipartUploadValidator(
        boundary,
        max_files=_MAX_UPLOAD_FILES,
        max_file_bytes=_MAX_UPLOAD_FILE_BYTES,
    )
    total_bytes = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > _MAX_UPLOAD_REQUEST_BYTES:
            raise _UploadValidationError(
                f"The multipart request must be at most {_MAX_UPLOAD_REQUEST_BYTES} bytes.",
                status_code=413,
            )
        validator.write(chunk)
        yield chunk
    validator.finalize()


async def _require_knowledge_admin(request: Request) -> None:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)


@router.get("/datasets")
@require_permission("threads", "read")
async def list_datasets(request: Request, config: AppConfig = Depends(get_config)) -> dict[str, Any]:
    settings = _settings(config)
    client = _build_client(settings)
    return await _proxy_result(
        client.list_datasets_page(params=list(request.query_params.multi_items())),
        settings=settings,
    )


@router.post("/datasets")
@require_permission("threads", "write")
async def create_dataset(
    request: Request,
    body: DatasetCreateRequest,
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    settings = _settings(config)
    client = _build_client(settings)
    return await _proxy_result(
        client.create_dataset(body.model_dump(exclude_none=True)),
        settings=settings,
    )


@router.delete("/datasets/{dataset_id}", dependencies=[Depends(_require_knowledge_admin)])
@require_permission("threads", "write")
async def delete_dataset(
    dataset_id: _DatasetId,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    settings = _settings(config)
    client = _build_client(settings)
    return await _proxy_result(client.delete_dataset(dataset_id), settings=settings)


@router.get("/datasets/{dataset_id}/documents")
@require_permission("threads", "read")
async def list_documents(
    dataset_id: _DatasetId,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    settings = _settings(config)
    client = _build_client(settings)
    return await _proxy_result(
        client.list_documents(dataset_id, params=list(request.query_params.multi_items())),
        settings=settings,
    )


@router.post("/datasets/{dataset_id}/documents")
@require_permission("threads", "write")
async def upload_documents(
    dataset_id: _DatasetId,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    settings = _settings(config)
    content_type = request.headers.get("content-type")
    boundary = _multipart_boundary(content_type)
    _check_content_length(request)
    client = _build_client(settings)
    result = await _proxy_result(
        client.upload_documents(
            dataset_id,
            content_type=content_type or "",
            content=_validated_upload_body(request, boundary),
        ),
        settings=settings,
    )
    get_knowledge_watcher().wake()
    return result


@router.post("/datasets/{dataset_id}/parse")
@require_permission("threads", "write")
async def parse_documents(
    dataset_id: _DatasetId,
    request: Request,
    body: ParseDocumentsRequest,
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    settings = _settings(config)
    client = _build_client(settings)
    result = await _proxy_result(
        client.parse_documents(dataset_id, body.document_ids),
        settings=settings,
    )
    get_knowledge_watcher().wake()
    return result


@router.get("/events")
@require_permission("threads", "read")
async def knowledge_events(
    request: Request,
    config: AppConfig = Depends(get_config),
) -> StreamingResponse:
    _settings(config)
    watcher = get_knowledge_watcher()

    async def event_stream():
        async for event in watcher.subscribe():
            if await request.is_disconnected():
                break
            yield ": keep-alive\n\n" if event is None else event.to_sse()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete(
    "/datasets/{dataset_id}/documents",
    dependencies=[Depends(_require_knowledge_admin)],
)
@require_permission("threads", "write")
async def delete_documents(
    dataset_id: _DatasetId,
    request: Request,
    body: DeleteDocumentsRequest,
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    settings = _settings(config)
    client = _build_client(settings)
    return await _proxy_result(
        client.delete_documents(dataset_id, body.ids),
        settings=settings,
    )
