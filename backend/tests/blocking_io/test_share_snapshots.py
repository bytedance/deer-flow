"""Snapshot capture and Fork copy real files without blocking the event loop."""

import asyncio
import os
from types import SimpleNamespace

import pytest

from app.gateway import extension_artifacts, share_fork
from app.gateway.persistent_writes import run_drained_write
from deerflow.config.paths import Paths


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Descriptor-confined snapshots require POSIX")
async def test_share_capture_and_fork_file_publication(tmp_path, monkeypatch):
    paths = await asyncio.to_thread(Paths, base_dir=tmp_path)
    monkeypatch.setattr(extension_artifacts, "get_paths", lambda: paths)
    monkeypatch.setattr(share_fork, "get_paths", lambda: paths)
    monkeypatch.setattr(extension_artifacts, "get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=True))
    content = b"share data\x00\xff" * 1024
    artifact = {"path": "nested/report.txt", "content": content}
    await run_drained_write("Write source outputs", share_fork._write_fork_files, (), "alice", "source", [artifact])
    captured = await extension_artifacts.read_snapshot(None, "alice", "source", "/mnt/user-data/outputs/nested/report.txt", max_bytes=20 * 1024 * 1024)
    await run_drained_write("Import shared outputs", share_fork._write_fork_files, (), "bob", "copy", [{**artifact, "content": captured}])
    actual = await asyncio.to_thread((paths.sandbox_outputs_dir("copy", user_id="bob") / artifact["path"]).read_bytes)
    assert actual == content
