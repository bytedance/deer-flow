"""Artifact import must keep real file publication off the Gateway event loop."""

import asyncio
import os
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Descriptor-confined imports require POSIX")
async def test_import_retained_artifact_does_not_block_event_loop(tmp_path, monkeypatch):
    from app.gateway import extension_artifacts
    from deerflow.config.paths import get_paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(extension_artifacts, "get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=True))
    content = b"binary\x00\xff" * 1024
    result = await extension_artifacts.import_snapshot(None, "alice", "thread", "fixture", "report.pdf", content)
    captured = await asyncio.to_thread(lambda: (get_paths().sandbox_uploads_dir("thread", user_id="alice") / result["filename"]).read_bytes())
    assert captured == content
