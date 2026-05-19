"""Tests for the /api/system/pdf-converter admin endpoint (Sprint C.3.3)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from _router_auth_helpers import call_unwrapped

from app.gateway.routers import system as system_router
from deerflow.utils.file_conversion import ResolvedPdfConverter


def test_pdf_converter_status_returns_resolved_snapshot():
    snap = ResolvedPdfConverter(
        configured="auto",
        effective="pymupdf4llm",
        pymupdf4llm_available=True,
        markitdown_available=True,
        warning="",
    )
    with patch(
        "deerflow.utils.file_conversion.resolve_pdf_converter",
        return_value=snap,
    ):
        result = asyncio.run(
            call_unwrapped(system_router.get_pdf_converter_status)
        )
    assert result.configured == "auto"
    assert result.effective == "pymupdf4llm"
    assert result.pymupdf4llm_available is True
    assert result.markitdown_available is True
    assert result.warning == ""


def test_pdf_converter_status_surfaces_warning_for_misconfig():
    snap = ResolvedPdfConverter(
        configured="pymupdf4llm",
        effective="markitdown",
        pymupdf4llm_available=False,
        markitdown_available=True,
        warning="pdf_converter=pymupdf4llm but pymupdf4llm is not installed; falling back to markitdown.",
    )
    with patch(
        "deerflow.utils.file_conversion.resolve_pdf_converter",
        return_value=snap,
    ):
        result = asyncio.run(
            call_unwrapped(system_router.get_pdf_converter_status)
        )
    assert result.configured == "pymupdf4llm"
    assert result.effective == "markitdown"
    assert "not installed" in result.warning


def test_pdf_converter_status_reports_no_converter_when_neither_installed():
    snap = ResolvedPdfConverter(
        configured="auto",
        effective="none",
        pymupdf4llm_available=False,
        markitdown_available=False,
        warning="pdf_converter=auto but neither pymupdf4llm nor markitdown is installed; PDF uploads will fail.",
    )
    with patch(
        "deerflow.utils.file_conversion.resolve_pdf_converter",
        return_value=snap,
    ):
        result = asyncio.run(
            call_unwrapped(system_router.get_pdf_converter_status)
        )
    assert result.effective == "none"
    assert "fail" in result.warning.lower()
