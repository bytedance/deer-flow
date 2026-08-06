"""Tests for publication of system-owned Markdown upload conversions."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.uploads.conversion import convert_uploaded_file_to_markdown
from deerflow.uploads.layout import conversion_path_for_upload


@pytest.mark.asyncio
async def test_conversion_uses_owned_full_filename_target(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    pdf = uploads / "report.pdf"
    docx = uploads / "report.docx"
    pdf.write_bytes(b"PDF")
    docx.write_bytes(b"DOCX")

    async def fake_convert(source: Path, output_path: Path | None = None):
        assert output_path is not None
        output_path.write_text(f"from:{source.name}", encoding="utf-8")
        return output_path

    with patch(
        "deerflow.uploads.conversion.convert_file_to_markdown",
        AsyncMock(side_effect=fake_convert),
    ):
        pdf_md = await convert_uploaded_file_to_markdown(pdf)
        docx_md = await convert_uploaded_file_to_markdown(docx)

    assert pdf_md == conversion_path_for_upload(pdf)
    assert docx_md == conversion_path_for_upload(docx)
    assert pdf_md.read_text(encoding="utf-8") == "from:report.pdf"
    assert docx_md.read_text(encoding="utf-8") == "from:report.docx"


@pytest.mark.asyncio
async def test_conversion_failure_cleans_stage_and_keeps_user_markdown(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    source = uploads / "report.pdf"
    source.write_bytes(b"PDF")
    user_markdown = uploads / "report.md"
    user_markdown.write_text("user", encoding="utf-8")

    with patch(
        "deerflow.uploads.conversion.convert_file_to_markdown",
        AsyncMock(return_value=None),
    ):
        assert await convert_uploaded_file_to_markdown(source) is None

    assert user_markdown.read_text(encoding="utf-8") == "user"
    conversion_dir = uploads.parent / ".upload-conversions"
    assert not list(conversion_dir.glob(".upload-*.part"))


@pytest.mark.asyncio
async def test_conversion_directory_symlink_is_rejected(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    source = uploads / "report.pdf"
    source.write_bytes(b"PDF")
    outside = tmp_path / "outside"
    outside.mkdir()
    (uploads.parent / ".upload-conversions").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="conversion directory"):
        await convert_uploaded_file_to_markdown(source)

    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_unexpected_converter_output_is_rejected_and_cleaned(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    source = uploads / "report.pdf"
    source.write_bytes(b"PDF")
    unexpected = uploads / "report.md"

    with patch(
        "deerflow.uploads.conversion.convert_file_to_markdown",
        AsyncMock(return_value=unexpected),
    ):
        with pytest.raises(ValueError, match="unexpected output path"):
            await convert_uploaded_file_to_markdown(source)

    assert not unexpected.exists()
    conversion_dir = uploads.parent / ".upload-conversions"
    assert not list(conversion_dir.glob(".upload-*.part"))
