"""Tests for resolve_pdf_converter (Sprint C.3.1).

The function is the boot-time + admin-endpoint source of truth for "what
will actually run when a user uploads a PDF". The matrix below covers
all six combinations of configured value × installed packages.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from deerflow.utils.file_conversion import (
    log_pdf_converter_status,
    resolve_pdf_converter,
)


def _patch_packages(*, pymupdf: bool, markitdown: bool):
    return (
        patch("deerflow.utils.file_conversion._is_pymupdf4llm_available", return_value=pymupdf),
        patch("deerflow.utils.file_conversion._is_markitdown_available", return_value=markitdown),
    )


class TestResolvePdfConverter:
    def test_auto_prefers_pymupdf4llm_when_available(self):
        a, b = _patch_packages(pymupdf=True, markitdown=True)
        with patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"), a, b:
            snap = resolve_pdf_converter()
        assert snap.configured == "auto"
        assert snap.effective == "pymupdf4llm"
        assert snap.warning == ""

    def test_auto_falls_back_to_markitdown_without_pymupdf(self):
        a, b = _patch_packages(pymupdf=False, markitdown=True)
        with patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"), a, b:
            snap = resolve_pdf_converter()
        assert snap.effective == "markitdown"
        assert snap.warning == ""

    def test_auto_with_neither_installed_warns(self):
        a, b = _patch_packages(pymupdf=False, markitdown=False)
        with patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"), a, b:
            snap = resolve_pdf_converter()
        assert snap.effective == "none"
        assert "uploads will fail" in snap.warning

    def test_explicit_pymupdf_with_package_missing_warns_and_falls_back(self):
        a, b = _patch_packages(pymupdf=False, markitdown=True)
        with patch(
            "deerflow.utils.file_conversion._get_pdf_converter",
            return_value="pymupdf4llm",
        ), a, b:
            snap = resolve_pdf_converter()
        assert snap.configured == "pymupdf4llm"
        assert snap.effective == "markitdown"
        assert "pymupdf4llm" in snap.warning
        assert "fall" in snap.warning.lower()

    def test_explicit_pymupdf_with_neither_installed_reports_no_converter(self):
        a, b = _patch_packages(pymupdf=False, markitdown=False)
        with patch(
            "deerflow.utils.file_conversion._get_pdf_converter",
            return_value="pymupdf4llm",
        ), a, b:
            snap = resolve_pdf_converter()
        assert snap.effective == "none"
        assert "fail" in snap.warning.lower()

    def test_explicit_markitdown_without_package_warns(self):
        a, b = _patch_packages(pymupdf=True, markitdown=False)
        with patch(
            "deerflow.utils.file_conversion._get_pdf_converter",
            return_value="markitdown",
        ), a, b:
            snap = resolve_pdf_converter()
        assert snap.configured == "markitdown"
        assert snap.effective == "none"
        assert "markitdown" in snap.warning.lower()

    def test_carries_availability_probes(self):
        a, b = _patch_packages(pymupdf=True, markitdown=False)
        with patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"), a, b:
            snap = resolve_pdf_converter()
        assert snap.pymupdf4llm_available is True
        assert snap.markitdown_available is False


class TestLogPdfConverterStatus:
    def test_logs_info_when_no_warning(self, caplog):
        a, b = _patch_packages(pymupdf=True, markitdown=True)
        with caplog.at_level(logging.INFO, logger="deerflow.utils.file_conversion"):
            with patch(
                "deerflow.utils.file_conversion._get_pdf_converter",
                return_value="auto",
            ), a, b:
                snap = log_pdf_converter_status()
        assert snap.effective == "pymupdf4llm"
        # The single boot-time line must mention the effective converter so
        # operators see it in the gateway log without grepping.
        info_records = [
            r for r in caplog.records if r.levelno == logging.INFO and "pdf_converter status" in r.getMessage()
        ]
        assert info_records, "expected one INFO log about pdf_converter status"

    def test_logs_warning_when_misconfigured(self, caplog):
        a, b = _patch_packages(pymupdf=False, markitdown=False)
        with caplog.at_level(logging.WARNING, logger="deerflow.utils.file_conversion"):
            with patch(
                "deerflow.utils.file_conversion._get_pdf_converter",
                return_value="auto",
            ), a, b:
                log_pdf_converter_status()
        warns = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("pdf_converter status" in r.getMessage() for r in warns)
