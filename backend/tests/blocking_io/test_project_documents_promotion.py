"""Regression anchors: Slice-C async paths must keep FS work off the loop.

Guards the Phase-2 Slice-C filesystem surfaces (spec §13): the attach
path's under-lock staging copy (``_copy_original_under_lock``) and its
staged/source chunk reads (``read_file_chunks``), plus the thread-files
view's directory scans (``list_files_in_dir`` over the uploads and outputs
dirs). Same mutation-verified style as ``test_project_documents.py``: the
anchors spy on the production offload (``run_file_io``, call-through) and
assert the specific worker functions were dispatched through it — removing
an offload drops the dispatch and turns the anchor red.
"""

from __future__ import annotations

import functools
from types import SimpleNamespace

import pytest

from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.projects.documents import add_staged_document, read_file_chunks, stage_document_bytes, stage_document_copy_for_attach
from deerflow.utils.file_io import run_file_io as _real_run_file_io

pytestmark = [pytest.mark.asyncio, pytest.mark.allow_blocking_io]

_USER = "u1"


def _spy_offload(monkeypatch) -> list[str]:
    """Record every ``run_file_io`` dispatch in the Slice-C modules (call-through)."""
    calls: list[str] = []

    async def spy(func, /, *args, **kwargs):
        target = func.func if isinstance(func, functools.partial) else func
        calls.append(getattr(target, "__name__", repr(target)))
        return await _real_run_file_io(func, *args, **kwargs)

    monkeypatch.setattr("deerflow.projects.documents.run_file_io", spy)
    monkeypatch.setattr("app.gateway.routers.project_thread_files.run_file_io", spy)
    monkeypatch.setattr("app.gateway.upload_ingestion.run_file_io", spy)
    return calls


async def _make_env(tmp_path, monkeypatch) -> SimpleNamespace:
    import deerflow.config.paths as paths_mod

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    project = await ProjectRepository(sf).create(name="P", user_id=_USER)
    return SimpleNamespace(paths=paths_mod.get_paths(), docs=ProjectDocumentRepository(sf), project_id=project["id"])


async def _shelf_document(env) -> dict:
    staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=[b"attach anchor"], max_bytes=1 << 20)
    result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name="anchor.txt", staged=staged)
    assert result is not None and result[1] is True
    return result[0]


async def test_attach_staging_copy_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """The under-lock source copy (existence/size check + ``shutil.copyfile``)
    must go through ``run_file_io`` while the row lock is held."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        row = await _shelf_document(env)
        calls.clear()
        result = await stage_document_copy_for_attach(env.docs, env.paths, user_id=_USER, project_id=env.project_id, document_id=row["id"])
        assert result is not None
        staged_row, staged_path = result
        assert staged_row["id"] == row["id"]
        assert staged_path.read_bytes() == b"attach anchor"
        assert "_copy_original_under_lock" in calls
        staged_path.unlink()
    finally:
        await close_engine()


async def test_attach_staged_read_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """``read_file_chunks`` (attach ingestion source + from-thread promote
    source) must dispatch the open, every chunk read, and the close through
    ``run_file_io``."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        row = await _shelf_document(env)
        result = await stage_document_copy_for_attach(env.docs, env.paths, user_id=_USER, project_id=env.project_id, document_id=row["id"])
        assert result is not None
        _row, staged_path = result
        calls.clear()
        chunks = [chunk async for chunk in read_file_chunks(staged_path, chunk_size=4)]
        assert b"".join(chunks) == b"attach anchor"
        assert "_open" in calls
        assert "read" in calls
        assert "close" in calls
        staged_path.unlink()
    finally:
        await close_engine()


async def test_ingestion_open_and_link_commit_dispatch_off_the_loop(tmp_path, monkeypatch) -> None:
    """``open()``'s existing-uploads seed (``list_files_in_dir``) and the
    per-file atomic no-overwrite link commit (``_commit_upload_temp_no_overwrite``)
    must go through ``run_file_io`` — the service never scans or links
    on the event loop."""
    from unittest.mock import MagicMock

    from app.gateway.routers import uploads as uploads_router
    from app.gateway.upload_ingestion import ThreadUploadIngestionService

    provider = MagicMock()
    provider.uses_thread_data_mounts = True
    monkeypatch.setattr(uploads_router, "get_sandbox_provider", lambda: provider)
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        uploads_dir = env.paths.sandbox_uploads_dir("thread-1", user_id=_USER)
        uploads_dir.mkdir(parents=True)
        (uploads_dir / "report.txt").write_bytes(b"existing")
        service = ThreadUploadIngestionService(request=None, thread_id="thread-1", user_id=_USER, app_config=SimpleNamespace(uploads={}))
        await service.open()
        assert service._seen_filenames == {"report.txt"}
        assert "list_files_in_dir" in calls

        async def _chunks():
            yield b"fresh bytes"

        calls.clear()
        info = await service.ingest_chunks(_chunks(), display_name="report.txt")
        # Claimed unique against the seeded name and reserved atomically.
        assert info["filename"] == "report_1.txt"
        assert (uploads_dir / "report_1.txt").read_bytes() == b"fresh bytes"
        assert (uploads_dir / "report.txt").read_bytes() == b"existing"
        assert "_commit_upload_temp_no_overwrite" in calls

        # The converted companion is also staged hidden and link-committed
        # atomically through the offload.
        async def fake_convert(file_path, output_path=None):
            output_path.write_text("md", encoding="utf-8")
            return output_path

        monkeypatch.setattr(uploads_router, "convert_file_to_markdown", fake_convert)
        service._auto_convert = True

        async def _pdf_chunks():
            yield b"pdf-bytes"

        calls.clear()
        info = await service.ingest_chunks(_pdf_chunks(), display_name="doc.pdf")
        assert info["markdown_file"] == "doc.md"
        assert (uploads_dir / "doc.md").read_text(encoding="utf-8") == "md"
        assert "_link_staged_no_overwrite" in calls
        await service.aclose()
    finally:
        await close_engine()


async def test_thread_files_listing_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """The thread-files view's uploads/outputs directory scans must go
    through ``run_file_io`` (the route never scans directories inline)."""
    from app.gateway.routers.project_thread_files import _list_thread_files

    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        uploads_dir = env.paths.sandbox_uploads_dir("thread-1", user_id=_USER)
        outputs_dir = env.paths.sandbox_outputs_dir("thread-1", user_id=_USER)
        uploads_dir.mkdir(parents=True)
        outputs_dir.mkdir(parents=True)
        (uploads_dir / "in.txt").write_bytes(b"in")
        (outputs_dir / "out.txt").write_bytes(b"out")
        calls.clear()
        entries, truncated = await _list_thread_files(env.paths, user_id=_USER, thread_id="thread-1", file_limit=10)
        assert truncated is False
        assert {(e.kind, e.name) for e in entries} == {("upload", "in.txt"), ("output", "out.txt")}
        assert calls.count("list_files_in_dir") == 2
    finally:
        await close_engine()
