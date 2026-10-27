"""Artifact archive construction must stay off the Gateway event loop."""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import pytest

from app.gateway.routers.thread_runs import _build_archive_without_abandoning_worker

pytestmark = pytest.mark.asyncio


async def test_artifact_archive_build_does_not_block_event_loop(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    await asyncio.to_thread(outputs.mkdir)
    await asyncio.to_thread((outputs / "report.txt").write_text, "report", encoding="utf-8")

    result = await _build_archive_without_abandoning_worker(
        outputs,
        outputs.parent,
        ["/mnt/user-data/outputs/report.txt"],
        extra_reserved_dir_names=set(),
    )
    try:
        payload = await asyncio.to_thread(result.file.read)
    finally:
        result.file.close()

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.read("report.txt") == b"report"
