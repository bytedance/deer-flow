"""Knowledge base REST API router."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.knowledge_base_schemas import (
    CreateDocumentRequest,
    CreateKnowledgeBaseRequest,
    DocumentDetailResponse,
    DocumentResponse,
    KnowledgeBaseResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    UpdateDocumentRequest,
    UpdateKnowledgeBaseRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


def _get_kb_service(request: Request):
    from deerflow.knowledge_base.service import KnowledgeBaseService

    svc: KnowledgeBaseService | None = getattr(request.app.state, "kb_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Knowledge base service not available")
    return svc


# ---------------------------------------------------------------------------
# Knowledge Base CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    request: Request,
    limit: int = 50,
    offset: int = 0,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    items = await svc.list_knowledge_bases(
        tenant_id=user.tenant_id,
        owner_user_id=str(user.id),
        limit=limit,
        offset=offset,
    )
    return items


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(
    body: CreateKnowledgeBaseRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    kb = await svc.create_knowledge_base(
        tenant_id=user.tenant_id,
        owner_user_id=str(user.id),
        name=body.name,
        description=body.description,
    )
    return kb


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    kb_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    kb = await svc.get_knowledge_base(kb_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: str,
    body: UpdateKnowledgeBaseRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    kb = await svc.update_knowledge_base(
        kb_id,
        tenant_id=user.tenant_id,
        owner_user_id=str(user.id),
        name=body.name,
        description=body.description,
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    deleted = await svc.delete_knowledge_base(kb_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge base not found")


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    docs = await svc.list_documents(
        kb_id,
        tenant_id=user.tenant_id,
        owner_user_id=str(user.id),
        limit=limit,
        offset=offset,
    )
    return docs


@router.post("/{kb_id}/documents", response_model=DocumentDetailResponse, status_code=201)
async def create_document(
    kb_id: str,
    body: CreateDocumentRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        doc = await svc.create_document(
            kb_id,
            tenant_id=user.tenant_id,
            owner_user_id=str(user.id),
            title=body.title,
            content=body.content,
            content_format=body.content_format,
            source_name=body.source_name,
            metadata_json=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return doc


@router.get("/{kb_id}/documents/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(
    kb_id: str,
    doc_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    doc = await svc.get_document(doc_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if doc is None or doc.get("knowledge_base_id") != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.patch("/{kb_id}/documents/{doc_id}", response_model=DocumentDetailResponse)
async def update_document(
    kb_id: str,
    doc_id: str,
    body: UpdateDocumentRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    # Verify doc belongs to this KB
    existing = await svc.get_document(doc_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if existing is None or existing.get("knowledge_base_id") != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = await svc.update_document(
        doc_id,
        tenant_id=user.tenant_id,
        owner_user_id=str(user.id),
        title=body.title,
        content=body.content,
        content_format=body.content_format,
        source_name=body.source_name,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: str,
    doc_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    # Verify doc belongs to this KB
    existing = await svc.get_document(doc_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if existing is None or existing.get("knowledge_base_id") != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")

    deleted = await svc.delete_document(doc_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")


@router.post("/{kb_id}/documents/{doc_id}/reindex", response_model=DocumentDetailResponse)
async def reindex_document(
    kb_id: str,
    doc_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    existing = await svc.get_document(doc_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if existing is None or existing.get("knowledge_base_id") != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = await svc.reindex_document(doc_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.post("/{kb_id}/search", response_model=SearchResponse)
async def search_knowledge_base(
    kb_id: str,
    body: SearchRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        results = await svc.search(
            kb_id,
            tenant_id=user.tenant_id,
            owner_user_id=str(user.id),
            query=body.query,
            top_k=body.top_k,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return SearchResponse(
        results=[SearchResultItem(**r) for r in results],
        query=body.query,
        knowledge_base_id=kb_id,
    )


# ---------------------------------------------------------------------------
# File Upload
# ---------------------------------------------------------------------------

_UPLOAD_MAX_SIZE = 20 * 1024 * 1024  # 20 MB
_ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".md", ".txt"}


@router.post("/{kb_id}/documents/upload", response_model=DocumentDetailResponse, status_code=201)
async def upload_document(
    kb_id: str,
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None),
):
    """Upload a file and create a knowledge base document from its content.

    Supports PDF, DOCX, Markdown, and plain text files. Binary formats are
    converted to Markdown via the file conversion pipeline.
    """
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)

    kb = await svc.get_knowledge_base(kb_id, tenant_id=user.tenant_id, owner_user_id=str(user.id))
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    filename = file.filename or "untitled"
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    content_bytes = await file.read()
    if len(content_bytes) > _UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    if ext in {".md", ".txt"}:
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File is not valid UTF-8 text")
    else:
        content = await _convert_binary_file(content_bytes, filename)

    doc_title = title or Path(filename).stem
    try:
        doc = await svc.create_document(
            kb_id,
            tenant_id=user.tenant_id,
            owner_user_id=str(user.id),
            title=doc_title,
            content=content,
            content_format="markdown",
            source_name=filename,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return doc


async def _convert_binary_file(content_bytes: bytes, filename: str) -> str:
    """Convert a binary document (PDF/DOCX) to Markdown text."""
    import asyncio

    from deerflow.utils.file_conversion import convert_file_to_markdown

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = Path(tmp.name)

    try:
        loop = asyncio.get_running_loop()
        md_path = await loop.run_in_executor(None, convert_file_to_markdown, tmp_path)
        if md_path is None:
            raise HTTPException(status_code=422, detail="Failed to convert file to text")
        content = md_path.read_text(encoding="utf-8")
        if not content.strip():
            raise HTTPException(status_code=422, detail="Converted file produced no text content")
        return content
    finally:
        tmp_path.unlink(missing_ok=True)
        md_candidate = tmp_path.with_suffix(".md")
        if md_candidate.exists():
            md_candidate.unlink(missing_ok=True)
