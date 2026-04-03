"""Tests for file_conversion utilities (PR1: pymupdf4llm + asyncio.to_thread; PR2: extract_outline)."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from deerflow.utils.file_conversion import (
    _ASYNC_THRESHOLD_BYTES,
    _MIN_CHARS_PER_PAGE,
    MAX_OUTLINE_ENTRIES,
    _do_convert,
    _pymupdf_output_too_sparse,
    convert_file_to_markdown,
    extract_outline,
)


def _make_pymupdf_mock(page_count: int) -> ModuleType:
    """Return a fake *pymupdf* module whose ``open()`` reports *page_count* pages."""
    mock_doc = MagicMock()
    mock_doc.__len__ = MagicMock(return_value=page_count)
    fake_pymupdf = ModuleType("pymupdf")
    fake_pymupdf.open = MagicMock(return_value=mock_doc)  # type: ignore[attr-defined]
    return fake_pymupdf


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

        # 10 pages × 10 000 chars → 1000/page ≫ threshold
        with patch.dict(sys.modules, {"pymupdf": _make_pymupdf_mock(page_count=10)}):
            result = _pymupdf_output_too_sparse("x" * 10_000, pdf)
        assert result is False

    def test_image_based_pdf_is_sparse(self, tmp_path):
        """Image-based PDF: near-zero chars per page → sparse."""
        pdf = tmp_path / "image.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        # 612 chars / 31 pages ≈ 19.7/page < _MIN_CHARS_PER_PAGE (50)
        with patch.dict(sys.modules, {"pymupdf": _make_pymupdf_mock(page_count=31)}):
            result = _pymupdf_output_too_sparse("x" * 612, pdf)
        assert result is True

    def test_fallback_when_pymupdf_unavailable(self, tmp_path):
        """When pymupdf is not installed, fall back to absolute 200-char threshold."""
        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        # Remove pymupdf from sys.modules so the `import pymupdf` inside the
        # function raises ImportError, triggering the absolute-threshold fallback.
        with patch.dict(sys.modules, {"pymupdf": None}):
            sparse = _pymupdf_output_too_sparse("x" * 100, pdf)
            not_sparse = _pymupdf_output_too_sparse("x" * 300, pdf)

        assert sparse is True
        assert not_sparse is False

    def test_exactly_at_threshold_is_not_sparse(self, tmp_path):
        """Chars-per-page == threshold is treated as NOT sparse (boundary inclusive)."""
        pdf = tmp_path / "boundary.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        # 2 pages × _MIN_CHARS_PER_PAGE chars = exactly at threshold
        with patch.dict(sys.modules, {"pymupdf": _make_pymupdf_mock(page_count=2)}):
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
            patch("deerflow.utils.file_conversion._convert_with_markitdown") as mock_md,
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
            patch("deerflow.utils.file_conversion._convert_with_markitdown") as mock_md,
        ):
            result = _do_convert(pdf, "pymupdf4llm")

        mock_md.assert_not_called()
        assert result == sparse_text

    def test_pdf_explicit_markitdown_skips_pymupdf4llm(self, tmp_path):
        """'markitdown' mode: never attempt pymupdf4llm."""
        pdf = tmp_path / "force_md.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with (
            patch("deerflow.utils.file_conversion._convert_pdf_with_pymupdf4llm") as mock_pymu,
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


# ---------------------------------------------------------------------------
# extract_outline
# ---------------------------------------------------------------------------


class TestExtractOutline:
    """Tests for extract_outline()."""

    def test_empty_file_returns_empty(self, tmp_path):
        """Empty markdown file yields no outline entries."""
        md = tmp_path / "empty.md"
        md.write_text("", encoding="utf-8")
        assert extract_outline(md) == []

    def test_missing_file_returns_empty(self, tmp_path):
        """Non-existent path returns [] without raising."""
        assert extract_outline(tmp_path / "nonexistent.md") == []

    def test_standard_markdown_headings(self, tmp_path):
        """# / ## / ### headings are all recognised."""
        md = tmp_path / "doc.md"
        md.write_text(
            "# Chapter One\n\nSome text.\n\n## Section 1.1\n\nMore text.\n\n### Sub 1.1.1\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert len(outline) == 3
        assert outline[0] == {"title": "Chapter One", "line": 1}
        assert outline[1] == {"title": "Section 1.1", "line": 5}
        assert outline[2] == {"title": "Sub 1.1.1", "line": 9}

    def test_bold_sec_item_heading(self, tmp_path):
        """**ITEM N. TITLE** lines in SEC filings are recognised."""
        md = tmp_path / "10k.md"
        md.write_text(
            "Cover page text.\n\n**ITEM 1. BUSINESS**\n\nBody.\n\n**ITEM 1A. RISK FACTORS**\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert len(outline) == 2
        assert outline[0] == {"title": "ITEM 1. BUSINESS", "line": 3}
        assert outline[1] == {"title": "ITEM 1A. RISK FACTORS", "line": 7}

    def test_bold_part_heading(self, tmp_path):
        """**PART I** / **PART II** headings are recognised."""
        md = tmp_path / "10k.md"
        md.write_text("**PART I**\n\n**PART II**\n\n**PART III**\n", encoding="utf-8")
        outline = extract_outline(md)
        assert len(outline) == 3
        titles = [e["title"] for e in outline]
        assert "PART I" in titles
        assert "PART II" in titles
        assert "PART III" in titles

    def test_sec_cover_page_boilerplate_excluded(self, tmp_path):
        """Address lines and short cover boilerplate must NOT appear in outline."""
        md = tmp_path / "8k.md"
        md.write_text(
            "## **UNITED STATES SECURITIES AND EXCHANGE COMMISSION**\n\n**WASHINGTON, DC 20549**\n\n**CURRENT REPORT**\n\n**SIGNATURES**\n\n**TESLA, INC.**\n\n**ITEM 2.02. RESULTS OF OPERATIONS**\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        titles = [e["title"] for e in outline]
        # Cover-page boilerplate should be excluded
        assert "WASHINGTON, DC 20549" not in titles
        assert "CURRENT REPORT" not in titles
        assert "SIGNATURES" not in titles
        assert "TESLA, INC." not in titles
        # Real SEC heading must be included
        assert "ITEM 2.02. RESULTS OF OPERATIONS" in titles

    def test_chinese_headings_via_standard_markdown(self, tmp_path):
        """Chinese annual report headings emitted as # by pymupdf4llm are captured."""
        md = tmp_path / "annual.md"
        md.write_text(
            "# 第一节 公司简介\n\n内容。\n\n## 第三节 管理层讨论与分析\n\n分析内容。\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert len(outline) == 2
        assert outline[0]["title"] == "第一节 公司简介"
        assert outline[1]["title"] == "第三节 管理层讨论与分析"

    def test_outline_capped_at_max_entries(self, tmp_path):
        """When truncated, result has MAX_OUTLINE_ENTRIES real entries + 1 sentinel."""
        lines = [f"# Heading {i}" for i in range(MAX_OUTLINE_ENTRIES + 10)]
        md = tmp_path / "long.md"
        md.write_text("\n".join(lines), encoding="utf-8")
        outline = extract_outline(md)
        # Last entry is the truncation sentinel
        assert outline[-1] == {"truncated": True}
        # Visible entries are exactly MAX_OUTLINE_ENTRIES
        visible = [e for e in outline if not e.get("truncated")]
        assert len(visible) == MAX_OUTLINE_ENTRIES

    def test_no_truncation_sentinel_when_under_limit(self, tmp_path):
        """Short documents produce no sentinel entry."""
        lines = [f"# Heading {i}" for i in range(5)]
        md = tmp_path / "short.md"
        md.write_text("\n".join(lines), encoding="utf-8")
        outline = extract_outline(md)
        assert len(outline) == 5
        assert not any(e.get("truncated") for e in outline)

    def test_blank_lines_and_whitespace_ignored(self, tmp_path):
        """Blank lines between headings do not produce empty entries."""
        md = tmp_path / "spaced.md"
        md.write_text("\n\n# Title One\n\n\n\n# Title Two\n\n", encoding="utf-8")
        outline = extract_outline(md)
        assert len(outline) == 2
        assert all(e["title"] for e in outline)

    def test_inline_bold_not_confused_with_heading(self, tmp_path):
        """Mid-sentence bold text must not be mistaken for a heading."""
        md = tmp_path / "prose.md"
        md.write_text(
            "This sentence has **bold words** inside it.\n\nAnother with **MULTIPLE CAPS** inline.\n",
            encoding="utf-8",
        )
        outline = extract_outline(md)
        assert outline == []
