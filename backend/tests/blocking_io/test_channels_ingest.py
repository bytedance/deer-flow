"""Regression anchor: ingesting inbound channel files must not block the event loop.

``ChannelManager``'s ``_ingest_inbound_files`` ensures the thread uploads
directory (``mkdir``), enumerates it (``iterdir`` / ``is_file``) to de-duplicate
filenames, and writes each downloaded attachment to disk
(``write_upload_file_no_symlink``) — all blocking filesystem IO. The async
function offloads the directory prep and every per-file write via
``asyncio.to_thread`` while keeping the genuinely async network read
(``file_reader``) on the loop. If any of that regresses back onto the event
loop, the strict Blockbuster gate raises ``BlockingError`` and this test fails.

Imports are kept at module top so any import-time IO runs at collection (outside
the gate); the surface under test runs on the event loop inside the gated test.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.channels import manager as mgr
from app.channels.message_bus import InboundMessage
from deerflow.uploads.manager import get_uploads_dir

pytestmark = pytest.mark.asyncio


async def test_ingest_inbound_files_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # Rebuild the cached Paths against the tmp home so uploads resolve under it.
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)

    # Swap the network reader for an in-memory one: no real HTTP, so the only IO
    # left for this anchor to guard is the filesystem work.
    async def _fake_reader(f, client):
        return b"payload-bytes"

    monkeypatch.setattr(mgr, "_read_http_inbound_file", _fake_reader)

    msg = InboundMessage(
        channel_name="unit-test-channel",  # absent from INBOUND_FILE_READERS -> default reader
        chat_id="c1",
        user_id="u1",
        text="hi",
        files=[{"type": "file", "filename": "report.txt"}],
    )

    created = await mgr._ingest_inbound_files("t1", msg)

    assert len(created) == 1
    assert created[0]["filename"] == "report.txt"
    written = await asyncio.to_thread(lambda: (get_uploads_dir("t1") / "report.txt").exists())
    assert written, "inbound file should be written under the tmp uploads dir"
