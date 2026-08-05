"""Regression coverage for file-conversion metadata IO on the event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deerflow.utils.file_conversion import convert_file_to_markdown

pytestmark = pytest.mark.asyncio


async def test_file_conversion_metadata_io_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "report.pdf"
    await asyncio.to_thread(source.write_bytes, b"%PDF-1.4 test")

    monkeypatch.setattr(
        "deerflow.utils.file_conversion._get_pdf_converter",
        lambda: "auto",
    )
    monkeypatch.setattr(
        "deerflow.utils.file_conversion._do_convert",
        lambda _path, _converter: "# Report\n",
    )

    result = await convert_file_to_markdown(source)

    assert result == source.with_suffix(".md")
    assert await asyncio.to_thread(result.read_text, encoding="utf-8") == "# Report\n"
