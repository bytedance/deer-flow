"""Knowledge-base management API (spec §5.3, Phase-1 subset).

Thin router: resolve caller → owner-only gate (``can_access`` → 403) →
delegate to :class:`KnowledgeService`. Uploads return 202 — indexing runs
in the background worker (spec §3.7), progress is polled via the documents
list.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.gateway.services.knowledge_service import (
    KnowledgeService,
    has_degraded_leg,
)
from deerflow.knowledge.access import can_access
from deerflow.knowledge.parser import supported_upload_suffixes

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


class KbCreateRequest(BaseModel):
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class KbUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("name must not be blank")
        return value


def _service(request: Request) -> KnowledgeService:
    service = getattr(request.app.state, "knowledge_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Knowledge service not available")
    return service


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user.id)


async def _require_kb_access(request: Request, kb_id: str) -> KnowledgeService:
    """404 when the KB is missing, 403 when the caller is not the owner."""
    service = _service(request)
    kb = await service.store.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if not await can_access(service.store, _user_id(request), kb_id):
        raise HTTPException(status_code=403, detail="You do not have access to this knowledge base")
    return service


async def _get_document_or_404(service: KnowledgeService, kb_id: str, doc_id: str) -> dict:
    document = await service.store.get_document(doc_id)
    if document is None or document["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("")
async def list_knowledge_bases(request: Request):
    service = _service(request)
    return await service.store.list_kbs(_user_id(request))


@router.post("", status_code=201)
async def create_knowledge_base(request: Request, body: KbCreateRequest):
    service = _service(request)
    return await service.store.create_kb(
        kb_id=uuid.uuid4().hex,
        owner_id=_user_id(request),
        name=body.name,
        description=body.description,
    )


@router.get("/supported-formats")
async def supported_formats():
    """Upload allowlist (Task 6, spec §6). Registered before ``/{kb_id}`` so
    the literal segment wins over the path parameter. Config-gated union
    (spec 2026-09-09 §4): spreadsheet suffixes (.xlsx/.xls/.tsv) appear only when
    ``rag.table.enabled`` is on — the frontend uses this for the file-picker
    ``accept`` and pre-upload intercept."""
    return {"suffixes": sorted(supported_upload_suffixes())}


@router.get("/{kb_id}")
async def get_knowledge_base(request: Request, kb_id: str):
    service = await _require_kb_access(request, kb_id)
    return await service.store.get_kb(kb_id)


@router.patch("/{kb_id}")
async def update_knowledge_base(request: Request, kb_id: str, body: KbUpdateRequest):
    service = await _require_kb_access(request, kb_id)
    return await service.store.update_kb(kb_id, name=body.name, description=body.description)


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(request: Request, kb_id: str):
    service = await _require_kb_access(request, kb_id)
    await service.delete_kb_cascade(kb_id=kb_id)
    return Response(status_code=204)


@router.get("/{kb_id}/documents")
async def list_documents(request: Request, kb_id: str):
    service = await _require_kb_access(request, kb_id)
    # service 层组装：path_status 携带 vector/graph，wiki 为库级镜像注入（spec §5）
    return await service.list_documents(kb_id)


@router.post("/{kb_id}/documents", status_code=202)
async def upload_document(request: Request, kb_id: str, file: UploadFile = File(...)):
    """Accept a document and return immediately; indexing runs in the worker."""
    service = await _require_kb_access(request, kb_id)
    content = await file.read()
    try:
        return await service.upload_document(
            kb_id=kb_id,
            uploader_id=_user_id(request),
            filename=file.filename or "document",
            content=content,
        )
    except ValueError as exc:  # unsafe filename
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(request: Request, kb_id: str, doc_id: str):
    service = await _require_kb_access(request, kb_id)
    deleted = await service.delete_document_cascade(kb_id=kb_id, doc_id=doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=204)


@router.post("/{kb_id}/documents/{doc_id}/retry", status_code=202)
async def retry_document(request: Request, kb_id: str, doc_id: str):
    service = await _require_kb_access(request, kb_id)
    document = await _get_document_or_404(service, kb_id, doc_id)
    degraded = document["status"] == "ready" and has_degraded_leg(document)
    if document["status"] != "failed" and not degraded:
        raise HTTPException(status_code=409, detail="Only failed or degraded documents can be retried")
    return await service.retry_document(kb_id=kb_id, doc_id=doc_id)


@router.get("/{kb_id}/documents/{doc_id}/chunks")
async def list_document_chunks(
    request: Request,
    kb_id: str,
    doc_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    service = await _require_kb_access(request, kb_id)
    await _get_document_or_404(service, kb_id, doc_id)
    return await service.list_document_chunks(kb_id=kb_id, doc_id=doc_id, offset=offset, limit=limit)


@router.get("/{kb_id}/chunks")
async def list_chunks_by_ids(
    request: Request,
    kb_id: str,
    ids: list[str] = Query(min_length=1, max_length=200),
):
    """Batch-fetch chunks by id (2026-09-05 条目↔切片血缘).

    The wiki entry drawer expands ``source_chunk_ids`` into read-only cards:
    one batched request returns the rows in the *requested* order, each
    carrying its source document's name. Unknown ids drop silently (the
    chunk may have been deleted; the UI reports the count delta); ids that
    belong to another knowledge base are filtered out (resource scope).
    """
    service = await _require_kb_access(request, kb_id)
    items = await service.store.get_chunks_by_ids(ids, kb_id=kb_id)
    names: dict[str, str] = {}
    for doc_id in {item["doc_id"] for item in items}:
        document = await service.store.get_document(doc_id)
        if document:
            names[doc_id] = document["name"]
    for item in items:
        item["doc_name"] = names.get(item["doc_id"])
    return {"items": items}


@router.get("/{kb_id}/documents/{doc_id}/files/{file_path:path}")
async def get_document_file(request: Request, kb_id: str, doc_id: str, file_path: str):
    """Serve parser-extracted assets (``images/…``) referenced by chunk markdown.

    The path must resolve inside the document's own ``images/`` directory —
    traversal attempts and the source document itself get a plain 404. The
    worker persists the images next to ``storage_path`` after each parse.
    """
    service = await _require_kb_access(request, kb_id)
    document = await _get_document_or_404(service, kb_id, doc_id)
    doc_dir = Path(document["storage_path"]).parent.resolve()
    images_root = doc_dir / "images"
    target = (doc_dir / file_path).resolve()
    if not target.is_relative_to(images_root) or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@router.get("/{kb_id}/documents/{doc_id}/source")
async def download_document_source(request: Request, kb_id: str, doc_id: str):
    """Serve the original uploaded file for round-trip export (2026-09-10).

    The route takes no user-supplied path segment — it serves exactly the
    row's recorded ``storage_path`` — so traversal is structurally impossible;
    ``filename`` restores the upload name in ``Content-Disposition``. Auth
    mirrors document read; a source gone off disk is a plain 404.
    """
    service = await _require_kb_access(request, kb_id)
    document = await _get_document_or_404(service, kb_id, doc_id)
    source = await service.resolve_source_document(kb_id=kb_id, doc_id=doc_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source file not found")
    return FileResponse(source, filename=document["name"])


@router.post("/{kb_id}/reindex", status_code=202)
async def reindex_knowledge_base(request: Request, kb_id: str):
    """Re-embed the library's existing chunks (spec 2026-09-14 §5 / P4).

    The only exit after switching the embedding provider or dimension: it reads the
    stored chunks and re-embeds them, **never re-parsing** the source documents — which
    is why it also works for documents whose original upload is gone. ``already_running``
    when a rebuild is in flight for this KB. Progress is polled via
    ``GET /{kb_id}/reindex/status``.
    """
    service = await _require_kb_access(request, kb_id)
    enqueued = service.trigger_reindex(kb_id)
    return {"status": "enqueued" if enqueued else "already_running"}


@router.get("/{kb_id}/reindex/status")
async def reindex_status(request: Request, kb_id: str):
    service = await _require_kb_access(request, kb_id)
    return service.reindex_status(kb_id)


class ChunkPositionsRequest(BaseModel):
    """批量切片位次查询（2026-09-05）：图谱实体抽屉行内「切片 #K」数据源。"""

    chunk_ids: list[str] = Field(default_factory=list, max_length=1000)


@router.post("/{kb_id}/chunk-positions")
async def chunk_positions(request: Request, kb_id: str, body: ChunkPositionsRequest):
    """批量 chunk_id → 文档存活切片中的位次（chunk_index 升序，空洞不占位）。

    与 recall-test 的 chunk_position / 切片抽屉 #K 同源同词汇；畸形/已删 id
    缺键（前端诚实缺省不显）。只读轻查询，每文档一次索引列。
    """
    service = await _require_kb_access(request, kb_id)
    return await service.chunk_positions(chunk_ids=body.chunk_ids)
