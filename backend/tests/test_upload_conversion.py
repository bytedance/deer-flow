"""Tests for publication of system-owned Markdown upload conversions."""

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.uploads.conversion import convert_uploaded_file_to_markdown
from deerflow.uploads.layout import (
    conversion_filename_for_upload,
    conversion_path_for_upload,
    conversion_virtual_path,
    existing_conversion_path_for_upload,
)
from deerflow.uploads.manager import delete_file_safe, publish_upload_bytes, publish_upload_bytes_leased


@pytest.mark.asyncio
async def test_delete_and_reupload_cannot_receive_old_conversion(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    publication = publish_upload_bytes_leased(uploads, "report.pdf", b"OLD")
    converter_started = asyncio.Event()
    allow_converter = asyncio.Event()

    async def paused_convert(source, output_path=None):
        converter_started.set()
        await allow_converter.wait()
        output_path.write_text("FROM OLD", encoding="utf-8")
        return output_path

    with patch("deerflow.uploads.conversion.convert_file_to_markdown", side_effect=paused_convert):
        conversion = asyncio.create_task(convert_uploaded_file_to_markdown(publication.path, publication=publication))
        await converter_started.wait()
        deletion = asyncio.create_task(asyncio.to_thread(delete_file_safe, uploads, "report.pdf"))
        await asyncio.sleep(0.05)
        assert not deletion.done()
        allow_converter.set()
        await conversion
        publication.release()
        await deletion

    replacement = publish_upload_bytes(uploads, "report.pdf", b"NEW")
    assert replacement.read_bytes() == b"NEW"
    assert existing_conversion_path_for_upload(replacement) is None


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_leak_name_lease_or_conversion_stage(tmp_path):
    uploads = tmp_path / "user-data" / "uploads"
    uploads.mkdir(parents=True)
    publication = publish_upload_bytes_leased(uploads, "report.pdf", b"OLD")
    conversion = asyncio.create_task(convert_uploaded_file_to_markdown(publication.path))
    await asyncio.sleep(0.05)

    conversion.cancel()
    await asyncio.sleep(0.05)
    assert not conversion.done()
    publication.release()

    with pytest.raises(asyncio.CancelledError):
        await conversion

    delete_file_safe(uploads, "report.pdf")
    replacement = publish_upload_bytes(uploads, "report.pdf", b"NEW")
    assert replacement.read_bytes() == b"NEW"
    conversion_dir = uploads.parent / ".upload-conversions"
    assert not list(conversion_dir.glob(".upload-*.part"))


@pytest.mark.parametrize("byte_length", [252, 253, 254, 255])
def test_long_conversion_filename_fits_component_limit(byte_length, tmp_path):
    filename = "a" * (byte_length - 4) + ".pdf"
    upload = tmp_path / "uploads" / filename
    target = conversion_path_for_upload(upload)

    assert len(target.name.encode("utf-8")) <= 255
    assert target.name == conversion_filename_for_upload(filename)
    assert conversion_virtual_path(filename).endswith(f"/{target.name}")
    assert target.name.endswith(".md")


def test_255_byte_conversion_name_uses_full_digest():
    filename = "a" * 251 + ".pdf"
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()

    assert conversion_filename_for_upload(filename) == f"{'a' * 187}.{digest}.md"


def test_multibyte_long_conversion_name_is_utf8_safe():
    filename = "é" * 125 + ".pdf"
    converted = conversion_filename_for_upload(filename)

    assert len(converted.encode("utf-8")) <= 255
    assert converted.endswith(".md")


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
