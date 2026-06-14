"""Regression anchor: serving artifacts must not block the event loop.

``get_artifact`` probes the artifact path (``exists`` / ``is_file``), reads
text/binary content (``read_text`` / ``read_bytes``), sniffs text-ness
(``is_text_file_by_content``), and extracts ``.skill`` archive members — all
blocking filesystem IO. The handler offloads each branch's IO via
``asyncio.to_thread``; if any regresses back onto the event loop, the strict
Blockbuster gate raises ``BlockingError`` and these tests fail.

The ``@require_permission`` decorator is bypassed via ``__wrapped__`` so the
anchor exercises the handler's own filesystem IO, not the authz layer. Imports
sit at module top so any import-time IO runs at collection, outside the gate.
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import pytest

from app.gateway.path_utils import resolve_thread_virtual_path
from app.gateway.routers.artifacts import get_artifact

pytestmark = pytest.mark.asyncio

# The undecorated coroutine (``require_permission`` uses ``functools.wraps``).
_get_artifact = get_artifact.__wrapped__


async def _seed(tmp_path: Path, monkeypatch, thread_id: str, virtual_path: str) -> Path:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    # Rebuild cached Paths against the tmp home so the artifact resolves under it.
    import deerflow.config.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_paths", None)
    # Test-side path resolution also touches the filesystem (`.resolve()`); offload
    # it so this seeding helper doesn't itself trip the gate.
    target = await asyncio.to_thread(resolve_thread_virtual_path, thread_id, virtual_path)
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    return target


async def test_get_artifact_text_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    vpath = "mnt/user-data/outputs/notes.txt"
    target = await _seed(tmp_path, monkeypatch, "t1", vpath)
    await asyncio.to_thread(target.write_text, "hello world", encoding="utf-8")

    resp = await _get_artifact("t1", vpath, request=None, download=False)

    assert resp.status_code == 200
    assert resp.body == b"hello world"


async def test_get_artifact_binary_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    vpath = "mnt/user-data/outputs/blob.bin"
    target = await _seed(tmp_path, monkeypatch, "t1", vpath)
    payload = b"\x00\x01\x02PNGDATA"  # null byte -> binary branch (read_bytes)
    await asyncio.to_thread(target.write_bytes, payload)

    resp = await _get_artifact("t1", vpath, request=None, download=False)

    assert resp.status_code == 200
    assert resp.body == payload


async def test_get_artifact_skill_archive_member_does_not_block_event_loop(tmp_path: Path, monkeypatch) -> None:
    skill_vpath = "mnt/user-data/outputs/demo.skill"
    target = await _seed(tmp_path, monkeypatch, "t1", skill_vpath)

    def _build_skill_zip() -> None:
        with zipfile.ZipFile(target, "w") as zf:
            zf.writestr("SKILL.md", "# demo skill\n")

    await asyncio.to_thread(_build_skill_zip)

    resp = await _get_artifact("t1", f"{skill_vpath}/SKILL.md", request=None, download=False)

    assert resp.status_code == 200
    assert b"# demo skill" in resp.body
