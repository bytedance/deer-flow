"""System-level admin endpoints (Sprint C.3.3).

Currently exposes the active PDF-converter snapshot so platform admins can
diagnose "why are PDF uploads silently failing?" without SSH'ing into the
gateway and grepping logs. Restricted to admins because the response
includes installed-package telemetry (i.e. it's gateway-internal info, not
something every tenant needs to see).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.gateway.auth.dependencies import CurrentUser, require_admin

router = APIRouter(prefix="/api/system", tags=["system"])


class PdfConverterStatusResponse(BaseModel):
    """Mirrors :class:`deerflow.utils.file_conversion.ResolvedPdfConverter`.

    ``configured`` is what config.yaml asked for; ``effective`` is what
    will actually run on the next upload (they differ when the requested
    backend's package isn't installed). ``warning`` is the human-readable
    install hint to surface in the admin UI; empty when the configuration
    is healthy.
    """

    configured: str = Field(..., description="config.yaml uploads.pdf_converter")
    effective: str = Field(
        ...,
        description="Converter that will actually run; 'none' when no backend is installed",
    )
    pymupdf4llm_available: bool
    markitdown_available: bool
    warning: str = ""


@router.get(
    "/pdf-converter",
    response_model=PdfConverterStatusResponse,
    summary="Active PDF converter snapshot",
)
async def get_pdf_converter_status(
    _admin: CurrentUser = Depends(require_admin),
) -> PdfConverterStatusResponse:
    """Return what the gateway will use for the next PDF upload.

    Same data the gateway logs at boot (Sprint C.3.1) — exposed so admins
    can pull it on demand without restarting the process.
    """
    from deerflow.utils.file_conversion import resolve_pdf_converter

    snap = resolve_pdf_converter()
    return PdfConverterStatusResponse(
        configured=snap.configured,
        effective=snap.effective,
        pymupdf4llm_available=snap.pymupdf4llm_available,
        markitdown_available=snap.markitdown_available,
        warning=snap.warning,
    )
