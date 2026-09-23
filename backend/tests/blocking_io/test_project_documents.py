"""Regression anchors: project shelf async paths must keep FS work off the loop.

Guards the Phase-2 Slice-B filesystem surfaces (spec §13): upload staging
and the atomic rename into the document namespace, dedup-hit staging
cleanup, the conversion publish path (temp file + atomic rename of
``derived/converted.md``), and the ``read_project_document`` tool's sampled
text detection and content reads.

A real ``init_engine`` cannot run under the strict Blockbuster gate
(SQLAlchemy's sync ``create_engine`` stats paths; the same constraint
``test_persistence_bootstrap.py`` documents), so these anchors are marked
``allow_blocking_io`` and instead spy on the production offload,
``run_file_io``: every anchor asserts the specific worker functions for its
branch were dispatched through it. Removing an offload (the mutation) drops
that dispatch and turns the anchor red; the full-suite GREEN run proves the
real path still works end to end against a real engine and real files.
"""

from __future__ import annotations

import functools
import json
from types import SimpleNamespace

import pytest

from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.projects import documents as documents_mod
from deerflow.projects.documents import add_staged_document, original_file_path, stage_document_bytes
from deerflow.projects.tools import _read_project_document_impl
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY
from deerflow.utils.file_io import run_file_io as _real_run_file_io

pytestmark = [pytest.mark.asyncio, pytest.mark.allow_blocking_io]

_USER = "u1"


def _spy_offload(monkeypatch) -> list[str]:
    """Record every ``run_file_io`` dispatch in the shelf modules (call-through)."""
    calls: list[str] = []

    async def spy(func, /, *args, **kwargs):
        target = func.func if isinstance(func, functools.partial) else func
        calls.append(getattr(target, "__name__", repr(target)))
        return await _real_run_file_io(func, *args, **kwargs)

    monkeypatch.setattr("deerflow.projects.documents.run_file_io", spy)
    monkeypatch.setattr("deerflow.projects.tools.run_file_io", spy)
    monkeypatch.setattr("app.gateway.routers.project_documents.run_file_io", spy)
    return calls


async def _make_env(tmp_path, monkeypatch) -> SimpleNamespace:
    import deerflow.config.paths as paths_mod

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    project = await ProjectRepository(sf).create(name="P", user_id=_USER)
    return SimpleNamespace(paths=paths_mod.get_paths(), docs=ProjectDocumentRepository(sf), project_id=project["id"])


def _runtime(project_id: str) -> SimpleNamespace:
    return SimpleNamespace(context={"user_id": _USER, PROJECT_CONTEXT_KEY: {"project_id": project_id, "name": "P", "instructions": ""}})


async def test_upload_staging_and_rename_dispatch_off_the_loop(tmp_path, monkeypatch) -> None:
    """Staging spool (``_open_staging``/chunk writes) and the file-before-row
    atomic rename (``_place_staging``) must go through ``run_file_io``."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:

        async def _chunks():
            for i in range(4):
                yield f"chunk-{i}\n".encode()

        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=_chunks(), max_bytes=1 << 20)
        result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name="notes.txt", staged=staged)
        assert result is not None and result[1] is True
        row = result[0]
        assert original_file_path(env.paths, user_id=_USER, row=row).is_file()
        assert not staged.staging_path.exists()
        assert "_open_staging" in calls
        assert "write" in calls
        # Symlink-resolving shelf path resolution is offloaded too.
        assert "resolve_document_paths" in calls
        assert "_place_staging" in calls
    finally:
        await close_engine()


async def test_list_content_missing_check_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """The shelf list's batched original integrity check (``_content_intact_batch``,
    one pass for the whole page) must go through ``run_file_io``."""
    from _router_auth_helpers import call_unwrapped

    from app.gateway.routers import project_documents as docs_router

    monkeypatch.setattr(docs_router, "get_effective_user_id", lambda: _USER)
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=[b"listed"], max_bytes=1 << 20)
        result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name="notes.txt", staged=staged)
        assert result is not None
        state = SimpleNamespace(project_repo=ProjectRepository(get_session_factory()), project_document_repo=env.docs)
        request = SimpleNamespace(app=SimpleNamespace(state=state))
        from deerflow.runtime.user_context import reset_current_user, set_current_user

        token = set_current_user(SimpleNamespace(id=_USER))
        try:
            calls.clear()
            response = await call_unwrapped(docs_router.list_project_documents, env.project_id, request=request, limit=100, offset=0)
        finally:
            reset_current_user(token)
        assert [d.content_missing for d in response.documents] == [False]
        assert "_content_intact_batch" in calls
    finally:
        await close_engine()


async def test_dedup_hit_staging_cleanup_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """The dedup-hit branch removes the staged duplicate via the offload."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        first = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=[b"same"], max_bytes=1 << 20)
        await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name="first.txt", staged=first)
        calls.clear()
        duplicate = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=[b"same"], max_bytes=1 << 20)
        result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name="second.txt", staged=duplicate)
        assert result is not None and result[1] is False
        assert not duplicate.staging_path.exists()
        assert "_remove_staging" in calls
        # No placement happened for the discarded duplicate.
        assert "_place_staging" not in calls
    finally:
        await close_engine()


async def test_tool_read_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """The original integrity check (``_content_intact``), text detection
    (``is_text_file_by_content``), the windowed content read
    (``_read_text_window``) and the cached count (``_cached_char_count``)
    must go through ``run_file_io``."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=[b"hello shelf"], max_bytes=1 << 20)
        result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name="notes.txt", staged=staged)
        row, _ = result
        calls.clear()
        payload = json.loads(await _read_project_document_impl(_runtime(env.project_id), document_id=row["id"], offset=0, limit=100))
        assert payload["content"] == "hello shelf"
        assert "_content_intact" in calls
        assert "resolve_document_paths" in calls
        assert "is_text_file_by_content" in calls
        assert "_read_text_window" in calls
        assert "_cached_char_count" in calls
    finally:
        await close_engine()


async def test_conversion_publish_path_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """First read of a convertible document validates the original
    (``_content_intact``) and runs the whole convert + temp write + atomic
    rename (``_convert_and_publish``, inside the locked conversion callback)
    through the offload."""

    async def fake_convert(file_path, output_path=None):
        output_path.write_text("# converted markdown", encoding="utf-8")
        return output_path

    monkeypatch.setattr(documents_mod, "convert_file_to_markdown", fake_convert)
    monkeypatch.setattr("deerflow.projects.tools._resolve_auto_convert", lambda: True)
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=[b"\x00docx"], max_bytes=1 << 20)
        result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name="report.docx", staged=staged)
        row, _ = result
        calls.clear()
        payload = json.loads(await _read_project_document_impl(_runtime(env.project_id), document_id=row["id"], offset=0, limit=100))
        assert payload["content"] == "# converted markdown"
        assert "_content_intact" in calls
        assert "resolve_document_paths" in calls
        assert "_convert_and_publish" in calls
        assert "_read_text_window" in calls
        assert "_cached_char_count" in calls
    finally:
        await close_engine()
