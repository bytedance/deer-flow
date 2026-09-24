"""Regression anchor: ``convert_file_to_markdown`` must not block the event loop.

The converter itself is offloaded to a thread for files above 1 MB
(``_ASYNC_THRESHOLD_BYTES``), but the converted markdown was written back with
a synchronous ``Path.write_text`` on the event loop — a multi-megabyte blocking
write in the upload ingestion path (``app/gateway/upload_ingestion.py`` calls
this per uploaded document). This anchor drives the real
``convert_file_to_markdown`` under the strict Blockbuster gate with the
converter patched to return a large payload, so only the write-back is
exercised.

If the write regresses back onto the event loop, Blockbuster raises
``BlockingError`` — which the function's broad ``except`` turns into a ``None``
return, so this test fails on the missing output file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_convert_file_to_markdown_write_does_not_block_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deerflow.utils import file_conversion

    large_text = "x" * (2 * 1024 * 1024)  # 2 MB conversion result
    monkeypatch.setattr(file_conversion, "_do_convert", lambda *_args, **_kwargs: large_text)

    source = tmp_path / "doc.txt"
    source.write_text("source", encoding="utf-8")  # test-side seeding (not in scanned_modules)

    md_path = await file_conversion.convert_file_to_markdown(source)

    assert md_path is not None, "conversion failed — see captured logs for the swallowed error"
    assert md_path.read_text(encoding="utf-8") == large_text
