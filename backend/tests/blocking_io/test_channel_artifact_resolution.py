"""Regression coverage for IM artifact resolution on the event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.channels.manager import _prepare_artifact_delivery

pytestmark = pytest.mark.asyncio


async def test_channel_artifact_resolution_does_not_block_event_loop(tmp_path: Path) -> None:
    outputs_dir = tmp_path / "outputs"
    artifact = outputs_dir / "report.pdf"
    await asyncio.to_thread(outputs_dir.mkdir)
    await asyncio.to_thread(artifact.write_bytes, b"%PDF-1.4")

    paths = MagicMock()
    paths.sandbox_outputs_dir.return_value = outputs_dir
    paths.resolve_virtual_path.return_value = artifact

    with patch("deerflow.config.paths.get_paths", return_value=paths):
        text, attachments = await _prepare_artifact_delivery(
            "thread-1",
            "Report ready",
            ["/mnt/user-data/outputs/report.pdf"],
            user_id="user-1",
        )

    assert text.startswith("Report ready")
    assert text.endswith("report.pdf")
    assert len(attachments) == 1
    assert attachments[0].actual_path == artifact
    assert attachments[0].size == len(b"%PDF-1.4")
