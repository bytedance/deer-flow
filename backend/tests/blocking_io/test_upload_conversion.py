"""Regression anchor: upload conversion lifecycle must not block the event loop."""

from __future__ import annotations

import asyncio

import pytest

from deerflow.uploads.conversion import convert_uploaded_file_to_markdown

pytestmark = pytest.mark.asyncio


async def test_real_upload_conversion_lifecycle_does_not_block_event_loop(tmp_path, monkeypatch):
    uploads = tmp_path / "user-data" / "uploads"
    await asyncio.to_thread(uploads.mkdir, parents=True)
    source = uploads / "report.pdf"
    await asyncio.to_thread(source.write_bytes, b"PDF")
    monkeypatch.setattr(
        "deerflow.utils.file_conversion._do_convert",
        lambda path, converter: "# converted",
    )

    result = await convert_uploaded_file_to_markdown(source)

    assert result is not None
    assert await asyncio.to_thread(result.read_text, encoding="utf-8") == "# converted"
