"""A cancelled conversion must retain its source until its worker exits."""

from __future__ import annotations

import asyncio
import threading

import pytest

from deerflow.utils import file_conversion


@pytest.mark.asyncio
@pytest.mark.parametrize("conversion_fails", [False, True], ids=["success", "failure"])
async def test_cancelled_conversion_drains_worker_before_source_cleanup(tmp_path, monkeypatch, conversion_fails):
    source = tmp_path / "large.pdf"
    source.write_bytes(b"x" * (file_conversion._ASYNC_THRESHOLD_BYTES + 1))
    output = tmp_path / "converted.md"
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    source_read = threading.Event()
    cleanup_before_finish = []
    loop = asyncio.get_running_loop()
    worker_started = asyncio.Event()

    def convert(path, _converter):
        started.set()
        loop.call_soon_threadsafe(worker_started.set)
        try:
            assert release.wait(timeout=10), "test did not release conversion worker"
            # A converter may reopen/read the source throughout conversion.
            assert path.read_bytes().startswith(b"x")
            source_read.set()
            if conversion_fails:
                raise ValueError("synthetic converter failure")
            return "# Converted document"
        finally:
            finished.set()

    monkeypatch.setattr(file_conversion, "_get_pdf_converter", lambda: "auto")
    monkeypatch.setattr(file_conversion, "_do_convert", convert)

    async def ingest():
        try:
            return await file_conversion.convert_file_to_markdown(source, output_path=output)
        finally:
            # UploadIngestionSession removes its private source in a finally.
            cleanup_before_finish.append(not finished.is_set())
            source.unlink(missing_ok=True)

    task = asyncio.create_task(ingest())
    try:
        await asyncio.wait_for(worker_started.wait(), timeout=10)
        assert started.is_set()
        task.cancel()
        # Yield scheduler turns, not a wall-clock delay, so cancellation reaches
        # the suspended await while the worker is held by the release event.
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not cleanup_before_finish, "caller cleaned the source while the converter was still running"
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(finished.wait, 10)

    assert cleanup_before_finish == [False]
    assert source_read.is_set()
    assert not source.exists()
    assert not output.exists()
