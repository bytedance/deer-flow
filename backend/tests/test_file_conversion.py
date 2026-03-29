import asyncio
import sys
from types import SimpleNamespace

import deerflow.utils.file_conversion as file_conversion


def test_convert_file_to_markdown_offloads_blocking_work(monkeypatch, tmp_path):
    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"pdf-bytes")

    class FakeMarkItDown:
        def convert(self, path: str):
            return SimpleNamespace(text_content=f"converted:{path}")

    monkeypatch.setitem(sys.modules, "markitdown", SimpleNamespace(MarkItDown=FakeMarkItDown))

    to_thread_calls: list[str] = []

    async def fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(getattr(func, "__name__", type(func).__name__))
        return func(*args, **kwargs)

    monkeypatch.setattr(file_conversion.asyncio, "to_thread", fake_to_thread)

    md_path = asyncio.run(file_conversion.convert_file_to_markdown(file_path))

    assert md_path == file_path.with_suffix(".md")
    assert md_path.read_text(encoding="utf-8") == f"converted:{file_path}"
    assert len(to_thread_calls) >= 2
