"""Knowledge base REST API router."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.gateway.deps import get_current_user_from_request
from app.gateway.routers.knowledge_base_schemas import (
    CreateDocumentRequest,
    CreateKnowledgeBaseRequest,
    DocumentDetailResponse,
    DocumentResponse,
    GrantPermissionRequest,
    KnowledgeBaseResponse,
    PermissionResponse,
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


async def _enrich_owner_display_names(items: list[dict]) -> list[dict]:
    """Add owner_display_name to KB dicts by looking up user emails."""
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.user.model import UserRow

    owner_ids = {item["owner_user_id"] for item in items if item.get("owner_user_id")}
    if not owner_ids:
        return items

    sf = get_session_factory()
    if sf is None:
        return items

    from sqlalchemy import select

    async with sf() as session:
        stmt = select(UserRow.id, UserRow.email).where(UserRow.id.in_(owner_ids))
        result = await session.execute(stmt)
        id_to_email = {row.id: row.email for row in result}

    for item in items:
        uid = item.get("owner_user_id")
        email = id_to_email.get(uid) if uid else None
        item["owner_display_name"] = email.split("@")[0] if email else None

    return items


# ---------------------------------------------------------------------------
# Knowledge Base CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    request: Request,
    visibility: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    items = await svc.list_knowledge_bases(
        tenant_id=user.tenant_id,
        user_id=str(user.id),
        visibility_filter=visibility,
        limit=limit,
        offset=offset,
    )
    await _enrich_owner_display_names(items)
    return items


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(
    body: CreateKnowledgeBaseRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)

    from deerflow.knowledge_base.access_control import UserContext

    user_ctx = UserContext(user_id=str(user.id), tenant_id=user.tenant_id, role=user.system_role)
    if not svc.access_control.can_create(user_ctx, body.visibility):
        raise HTTPException(status_code=403, detail="Not allowed to create knowledge base with this visibility")

    kb = await svc.create_knowledge_base(
        tenant_id=user.tenant_id,
        owner_user_id=str(user.id),
        name=body.name,
        description=body.description,
        visibility=body.visibility,
    )
    return kb


# ---------------------------------------------------------------------------
# Admin View (must be before /{kb_id} to avoid path parameter capture)
# ---------------------------------------------------------------------------


@router.get("/admin/all", response_model=list[KnowledgeBaseResponse])
async def list_admin_knowledge_bases(
    request: Request,
    visibility: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        items = await svc.list_admin_knowledge_bases(
            tenant_id=user.tenant_id,
            role=user.system_role,
            visibility_filter=visibility,
            limit=limit,
            offset=offset,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin role required")
    await _enrich_owner_display_names(items)
    return items


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    kb_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    kb = await svc.get_kb_with_permissions(
        kb_id, user_id=str(user.id), tenant_id=user.tenant_id, role=user.system_role
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    await _enrich_owner_display_names([kb])
    return kb


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: str,
    body: UpdateKnowledgeBaseRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        await svc.check_admin_permission(
            kb_id, user_id=str(user.id), tenant_id=user.tenant_id, role=user.system_role
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access required to update knowledge base")

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
    try:
        await svc.check_admin_permission(
            kb_id, user_id=str(user.id), tenant_id=user.tenant_id, role=user.system_role
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access required to delete knowledge base")

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
    try:
        docs = await svc.list_documents_with_access_check(
            kb_id,
            user_id=str(user.id),
            tenant_id=user.tenant_id,
            limit=limit,
            offset=offset,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
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
        doc = await svc.create_document_with_access_check(
            kb_id,
            user_id=str(user.id),
            tenant_id=user.tenant_id,
            role=user.system_role,
            title=body.title,
            content=body.content,
            content_format=body.content_format,
            source_name=body.source_name,
            metadata_json=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Write access denied")
    return doc


@router.get("/{kb_id}/documents/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(
    kb_id: str,
    doc_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    doc = await svc.get_document_with_access_check(kb_id, doc_id, user_id=str(user.id), tenant_id=user.tenant_id)
    if doc is None:
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
    try:
        doc = await svc.update_document_with_access_check(
            kb_id,
            doc_id,
            user_id=str(user.id),
            tenant_id=user.tenant_id,
            role=user.system_role,
            title=body.title,
            content=body.content,
            content_format=body.content_format,
            source_name=body.source_name,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Write access denied")
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
    try:
        deleted = await svc.delete_document_with_access_check(
            kb_id,
            doc_id,
            user_id=str(user.id),
            tenant_id=user.tenant_id,
            role=user.system_role,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Write access denied")
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
    try:
        doc = await svc.reindex_document_with_access_check(
            kb_id,
            doc_id,
            user_id=str(user.id),
            tenant_id=user.tenant_id,
            role=user.system_role,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Write access denied")
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/{kb_id}/reindex-all", status_code=202)
async def reindex_all(
    kb_id: str,
    request: Request,
):
    """Tear down the KB's vector collection and re-queue every doc.

    Admin-only (superadmin / tenant_admin). Repairs KBs flagged
    ``vector_metric_stale`` after Sprint A.10 — Chroma cosine metadata
    is immutable per collection so a fresh collection is the only fix.
    Returns 202 because per-doc indexing happens asynchronously through
    the dispatcher.
    """
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        report = await svc.reindex_all_for_kb(
            kb_id,
            tenant_id=user.tenant_id,
            role=user.system_role,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin role required")
    return report


# ---------------------------------------------------------------------------
# Permission Management
# ---------------------------------------------------------------------------


@router.get("/{kb_id}/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    kb_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        perms = await svc.list_permissions(
            kb_id, user_id=str(user.id), tenant_id=user.tenant_id, role=user.system_role
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access required")
    return perms


@router.post("/{kb_id}/permissions", response_model=PermissionResponse, status_code=201)
async def grant_permission(
    kb_id: str,
    body: GrantPermissionRequest,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        perm = await svc.grant_permission(
            kb_id,
            grantor_user_id=str(user.id),
            grantor_tenant_id=user.tenant_id,
            grantor_role=user.system_role,
            target_user_id=body.user_id,
            role=body.role,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        raise HTTPException(status_code=400, detail=detail)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access required")
    return perm


@router.delete("/{kb_id}/permissions/{target_user_id}", status_code=204)
async def revoke_permission(
    kb_id: str,
    target_user_id: str,
    request: Request,
):
    user = await get_current_user_from_request(request)
    svc = _get_kb_service(request)
    try:
        revoked = await svc.revoke_permission(
            kb_id,
            grantor_user_id=str(user.id),
            grantor_tenant_id=user.tenant_id,
            grantor_role=user.system_role,
            target_user_id=target_user_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Admin access required")
    if not revoked:
        raise HTTPException(status_code=404, detail="Permission not found")


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

    try:
        await svc.check_write_permission(kb_id, user_id=str(user.id), tenant_id=user.tenant_id, role=user.system_role)
    except ValueError:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Write access denied")

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
        doc = await svc.create_document_with_access_check(
            kb_id,
            user_id=str(user.id),
            tenant_id=user.tenant_id,
            role=user.system_role,
            title=doc_title,
            content=content,
            content_format="markdown",
            source_name=filename,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Write access denied")
    return doc


async def _convert_binary_file(content_bytes: bytes, filename: str) -> str:
    """Convert a binary document (PDF/DOCX) to Markdown text.

    Failures from :func:`convert_file_to_markdown` are mapped to a 422 with a
    structured detail body ``{code, message, filename}`` so the frontend can
    show a code-keyed toast instead of generic "failed to convert". The
    EMPTY_RESULT guard is enforced inside ``convert_file_to_markdown`` itself
    (Sprint C.3.2) — short outputs (< 200 non-whitespace chars) come back as
    failures, not as a successful md_path with empty content.
    """
    from deerflow.utils.file_conversion import (
        ConversionErrorCode,
        convert_file_to_markdown,
    )

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = Path(tmp.name)

    try:
        result = await convert_file_to_markdown(tmp_path)
        if result.failed:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": result.error.value,
                    "message": result.error_detail or "Failed to convert file",
                    "filename": filename,
                },
            )
        content = result.md_path.read_text(encoding="utf-8")
        if not content.strip():
            # Belt-and-braces: convert_file_to_markdown already enforces
            # EMPTY_RESULT, but a downstream caller could pass in a path
            # whose .md file got truncated between the write and the read.
            raise HTTPException(
                status_code=422,
                detail={
                    "code": ConversionErrorCode.EMPTY_RESULT.value,
                    "message": "Converted file produced no text content",
                    "filename": filename,
                },
            )
        return content
    finally:
        tmp_path.unlink(missing_ok=True)
        md_candidate = tmp_path.with_suffix(".md")
        if md_candidate.exists():
            md_candidate.unlink(missing_ok=True)
