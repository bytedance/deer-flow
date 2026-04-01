"""Tests for file_conversion utilities (PR1: pymupdf4llm + asyncio.to_thread)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.utils.file_conversion import (
    _MIN_CHARS_PER_PAGE,
    _ASYNC_THRESHOLD_BYTES,
    _do_convert,
    _pymupdf_output_too_sparse,
    convert_file_to_markdown,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# _pymupdf_output_too_sparse
# ---------------------------------------------------------------------------


class TestPymupdfOutputTooSparse:
    """Check the chars-per-page sparsity heuristic."""

    def test_dense_text_pdf_not_sparse(self, tmp_path):
        """Normal text PDF: many chars per page → not sparse."""
        pdf = tmp_path / "dense.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        # Mock pymupdf to say 10 pages; text has 10 000 chars → 1000/page ≫ threshold
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=10)
        with patch("pymupdf.open", return_value=mock_doc):
            result = _pymupdf_output_too_sparse("x" * 10_000, pdf)
        assert result is False

    def test_image_based_pdf_is_sparse(self, tmp_path):
        """Image-based PDF: near-zero chars per page → sparse."""
        pdf = tmp_path / "image.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=31)
        # 612 chars / 31 pages ≈ 19.7/page < _MIN_CHARS_PER_PAGE (50)
        with patch("pymupdf.open", return_value=mock_doc):
            result = _pymupdf_output_too_sparse("x" * 612, pdf)
        assert result is True

    def test_fallback_when_pymupdf_unavailable(self, tmp_path):
        """When pymupdf itself fails, fall back to absolute 200-char threshold."""
        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with patch("pymupdf.open", side_effect=ImportError):
            sparse = _pymupdf_output_too_sparse("x" * 100, pdf)
            not_sparse = _pymupdf_output_too_sparse("x" * 300, pdf)

        assert sparse is True
        assert not_sparse is False

    def test_exactly_at_threshold_is_not_sparse(self, tmp_path):
        """Chars-per-page == threshold is treated as NOT sparse (boundary inclusive)."""
        pdf = tmp_path / "boundary.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2)
        # 2 pages × _MIN_CHARS_PER_PAGE chars = exactly at threshold
        with patch("pymupdf.open", return_value=mock_doc):
            result = _pymupdf_output_too_sparse("x" * (_MIN_CHARS_PER_PAGE * 2), pdf)
        assert result is False


# ---------------------------------------------------------------------------
# _do_convert — routing logic
# ---------------------------------------------------------------------------


class TestDoConvert:
    """Verify that _do_convert routes to the right sub-converter."""

    def test_non_pdf_always_uses_markitdown(self, tmp_path):
        """DOCX / XLSX / PPTX always go through MarkItDown regardless of setting."""
        docx = tmp_path / "report.docx"
        docx.write_bytes(b"PK fake docx")

        with patch(
            "deerflow.utils.file_conversion._convert_with_markitdown",
            return_value="# Markdown from MarkItDown",
        ) as mock_md:
            result = _do_convert(docx, "auto")

        mock_md.assert_called_once_with(docx)
        assert result == "# Markdown from MarkItDown"

    def test_pdf_auto_uses_pymupdf4llm_when_dense(self, tmp_path):
        """auto mode: use pymupdf4llm output when it's dense enough."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        dense_text = "# Heading\n" + "word " * 2000  # clearly dense

        with (
            patch(
                "deerflow.utils.file_conversion._convert_pdf_with_pymupdf4llm",
                return_value=dense_text,
            ),
            patch(
                "deerflow.utils.file_conversion._pymupdf_output_too_sparse",
                return_value=False,
            ),
            patch(
                "deerflow.utils.file_conversion._convert_with_markitdown"
            ) as mock_md,
        ):
            result = _do_convert(pdf, "auto")

        mock_md.assert_not_called()
        assert result == dense_text

    def test_pdf_auto_falls_back_when_sparse(self, tmp_path):
        """auto mode: fall back to MarkItDown when pymupdf4llm output is sparse."""
        pdf = tmp_path / "scanned.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with (
            patch(
                "deerflow.utils.file_conversion._convert_pdf_with_pymupdf4llm",
                return_value="x" * 612,  # 19.7 chars/page for 31-page doc
            ),
            patch(
                "deerflow.utils.file_conversion._pymupdf_output_too_sparse",
                return_value=True,
            ),
            patch(
                "deerflow.utils.file_conversion._convert_with_markitdown",
                return_value="OCR result via MarkItDown",
            ) as mock_md,
        ):
            result = _do_convert(pdf, "auto")

        mock_md.assert_called_once_with(pdf)
        assert result == "OCR result via MarkItDown"

    def test_pdf_explicit_pymupdf4llm_skips_sparsity_check(self, tmp_path):
        """'pymupdf4llm' mode: use output as-is even if sparse."""
        pdf = tmp_path / "explicit.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        sparse_text = "x" * 10  # very short

        with (
            patch(
                "deerflow.utils.file_conversion._convert_pdf_with_pymupdf4llm",
                return_value=sparse_text,
            ),
            patch(
                "deerflow.utils.file_conversion._convert_with_markitdown"
            ) as mock_md,
        ):
            result = _do_convert(pdf, "pymupdf4llm")

        mock_md.assert_not_called()
        assert result == sparse_text

    def test_pdf_explicit_markitdown_skips_pymupdf4llm(self, tmp_path):
        """'markitdown' mode: never attempt pymupdf4llm."""
        pdf = tmp_path / "force_md.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with (
            patch(
                "deerflow.utils.file_conversion._convert_pdf_with_pymupdf4llm"
            ) as mock_pymu,
            patch(
                "deerflow.utils.file_conversion._convert_with_markitdown",
                return_value="MarkItDown result",
            ),
        ):
            result = _do_convert(pdf, "markitdown")

        mock_pymu.assert_not_called()
        assert result == "MarkItDown result"

    def test_pdf_auto_falls_back_when_pymupdf4llm_not_installed(self, tmp_path):
        """auto mode: if pymupdf4llm is not installed, use MarkItDown directly."""
        pdf = tmp_path / "no_pymupdf.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with (
            patch(
                "deerflow.utils.file_conversion._convert_pdf_with_pymupdf4llm",
                return_value=None,  # None signals not installed
            ),
            patch(
                "deerflow.utils.file_conversion._convert_with_markitdown",
                return_value="MarkItDown fallback",
            ) as mock_md,
        ):
            result = _do_convert(pdf, "auto")

        mock_md.assert_called_once_with(pdf)
        assert result == "MarkItDown fallback"


# ---------------------------------------------------------------------------
# convert_file_to_markdown — async + file writing
# ---------------------------------------------------------------------------


class TestConvertFileToMarkdown:
    def test_small_file_runs_synchronously(self, tmp_path):
        """Small files (< 1 MB) are converted in the event loop thread."""
        pdf = tmp_path / "small.pdf"
        pdf.write_bytes(b"%PDF-1.4 " + b"x" * 100)  # well under 1 MB

        with (
            patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"),
            patch(
                "deerflow.utils.file_conversion._do_convert",
                return_value="# Small PDF",
            ) as mock_convert,
            patch("asyncio.to_thread") as mock_thread,
        ):
            md_path = _run(convert_file_to_markdown(pdf))

        # asyncio.to_thread must NOT have been called
        mock_thread.assert_not_called()
        mock_convert.assert_called_once()
        assert md_path == pdf.with_suffix(".md")
        assert md_path.read_text() == "# Small PDF"

    def test_large_file_offloaded_to_thread(self, tmp_path):
        """Large files (> 1 MB) are offloaded via asyncio.to_thread."""
        pdf = tmp_path / "large.pdf"
        # Write slightly more than the threshold
        pdf.write_bytes(b"%PDF-1.4 " + b"x" * (_ASYNC_THRESHOLD_BYTES + 1))

        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"),
            patch(
                "deerflow.utils.file_conversion._do_convert",
                return_value="# Large PDF",
            ),
            patch("asyncio.to_thread", side_effect=fake_to_thread) as mock_thread,
        ):
            md_path = _run(convert_file_to_markdown(pdf))

        mock_thread.assert_called_once()
        assert md_path == pdf.with_suffix(".md")
        assert md_path.read_text() == "# Large PDF"

    def test_returns_none_on_conversion_error(self, tmp_path):
        """If conversion raises, return None without propagating the exception."""
        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with (
            patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"),
            patch(
                "deerflow.utils.file_conversion._do_convert",
                side_effect=RuntimeError("conversion failed"),
            ),
        ):
            result = _run(convert_file_to_markdown(pdf))

        assert result is None

    def test_writes_utf8_markdown_file(self, tmp_path):
        """Generated .md file is written with UTF-8 encoding."""
        pdf = tmp_path / "report.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        chinese_content = "# 中文报告\n\n这是测试内容。"

        with (
            patch("deerflow.utils.file_conversion._get_pdf_converter", return_value="auto"),
            patch(
                "deerflow.utils.file_conversion._do_convert",
                return_value=chinese_content,
            ),
        ):
            md_path = _run(convert_file_to_markdown(pdf))

        assert md_path is not None
        assert md_path.read_text(encoding="utf-8") == chinese_content
