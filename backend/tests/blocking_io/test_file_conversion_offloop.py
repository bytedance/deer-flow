"""Regression anchor: ``convert_file_to_markdown`` must not block the event loop.

Parsing and Markdown write-back must stay off-loop for every source size.
The converted Markdown used to be written back with a synchronous
``Path.write_text`` on the event loop — a multi-megabyte blocking write in the
upload ingestion path (``app/gateway/upload_ingestion.py`` calls this per
uploaded document). This anchor drives the real
``convert_file_to_markdown`` under the strict Blockbuster gate with the
converter patched to read its tiny source and return a large payload, so both
parsing IO and write-back are exercised.

If the write regresses back onto the event loop, Blockbuster raises
``BlockingError`` — which the function's broad ``except`` turns into a ``None``
return, so this test fails on the missing output file.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_convert_file_to_markdown_parse_and_write_do_not_block_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from deerflow.utils import file_conversion

    large_text = "x" * (2 * 1024 * 1024)  # 2 MB conversion result
    monkeypatch.setattr(file_conversion, "_do_convert", lambda path, _converter: path.read_text(encoding="utf-8") + large_text)

    source = tmp_path / "doc.txt"
    source.write_text("source", encoding="utf-8")  # test-side seeding (not in scanned_modules)

    md_path = await file_conversion.convert_file_to_markdown(source)

    assert md_path is not None, "conversion failed — see captured logs for the swallowed error"
    assert md_path.read_text(encoding="utf-8") == "source" + large_text


async def test_cancelled_conversion_cleanup_failure_preserves_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing cleanup ``unlink`` must not swallow the cancellation.

    The cleanup ran bare inside the ``CancelledError`` handler: an unlink
    OSError escaped the handler, was converted into an ordinary conversion
    failure (``None`` return) by the broad ``except``, and left both the
    caller's cancellation and the staging output behind. Cleanup failures
    are now caught and logged inside the handler, and the captured
    cancellation is always re-raised.
    """
    from deerflow.utils import file_conversion

    large_text = "x" * (2 * 1024 * 1024)
    monkeypatch.setattr(file_conversion, "_do_convert", lambda *_args, **_kwargs: large_text)

    source = tmp_path / "doc.txt"
    source.write_text("source", encoding="utf-8")

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    real_run_file_io = file_conversion.run_file_io
    started = threading.Event()
    finish = threading.Event()

    async def gated_run_file_io(fn, *args, **kwargs):
        if getattr(fn, "__name__", "") == "write_text":
            # Hold the write-back worker start until the test has cancelled
            # the task, so the cancellation arrives while the write is in
            # flight (deterministic ordering, no sleeps).
            started.set()
            await asyncio.to_thread(finish.wait, 5)
        return await real_run_file_io(fn, *args, **kwargs)

    monkeypatch.setattr(file_conversion, "run_file_io", gated_run_file_io)

    task = asyncio.create_task(file_conversion.convert_file_to_markdown(source))
    try:
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        finish.set()

    assert any("partial conversion output" in record.getMessage() for record in caplog.records), "cleanup failure should be logged inside the handler, not escaped"


@pytest.mark.parametrize("pdf_converter", ["markitdown", "pymupdf4llm"])
@pytest.mark.parametrize("warm_cache", [False, True], ids=["cold_config", "cached_config"])
async def test_conversion_resolves_real_config_in_the_parser_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pdf_converter: str, warm_cache: bool) -> None:
    from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config
    from deerflow.config.extensions_config import reset_extensions_config
    from deerflow.utils import file_conversion

    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    source = tmp_path / "document.pdf"

    def seed_files() -> None:
        config_path.write_text(f"sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\nuploads:\n  pdf_converter: {pdf_converter}\n", encoding="utf-8")
        extensions_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
        source.write_text("synthetic source", encoding="utf-8")

    await asyncio.to_thread(seed_files)
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()
    reset_extensions_config()
    config_threads: list[int] = []
    parser_threads: list[int] = []
    selected: list[str] = []
    loop_thread = threading.get_ident()

    def load_config() -> AppConfig:
        config_threads.append(threading.get_ident())
        return get_app_config()

    def parse_document(path: Path, converter: str) -> str:
        parser_threads.append(threading.get_ident())
        selected.append(converter)
        return path.read_text(encoding="utf-8") + " converted"

    monkeypatch.setattr(file_conversion, "get_app_config", load_config)
    monkeypatch.setattr(file_conversion, "_do_convert", parse_document)
    try:
        if warm_cache:
            await asyncio.to_thread(get_app_config)
        output = await file_conversion.convert_file_to_markdown(source)
    finally:
        reset_app_config()
        reset_extensions_config()

    assert config_threads == parser_threads
    assert len(config_threads) == 1 and config_threads[0] != loop_thread
    assert selected == [pdf_converter]
    assert output is not None
    assert output == source.with_suffix(".md")
    assert output.read_text(encoding="utf-8") == "synthetic source converted"
