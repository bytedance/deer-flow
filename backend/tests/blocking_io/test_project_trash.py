"""Regression anchors: trash-tier async paths must keep FS work off the loop.

Phase-2 spec §7.3/§13 (blocking-IO anchors): the purge unlink (inside the
row-locked transaction), the restore content checks, the post-commit merge
cleanup, and the retention sweep's storage/row reconciliation all dispatch
through ``run_file_io``. Each test spies the offload (call-through) and
asserts the specific worker went through it — removing the offload turns the
anchor red (mutation-verified style of this suite).
"""

from __future__ import annotations

import functools
from types import SimpleNamespace

import pytest

from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.projects.documents import add_staged_document, converted_markdown_path, stage_document_bytes
from deerflow.projects.trash import make_purge_file_remover, restore_document, run_trash_retention_sweep
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

    monkeypatch.setattr("deerflow.projects.trash.run_file_io", spy)
    # ``check_document_content``/``_content_intact`` live in the documents
    # module (shared with the serving path); spy its offload too.
    monkeypatch.setattr("deerflow.projects.documents.run_file_io", spy)
    return calls


async def _make_env(tmp_path, monkeypatch) -> SimpleNamespace:
    import deerflow.config.paths as paths_mod

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    projects = ProjectRepository(sf)
    project = await projects.create(name="P", user_id=_USER)
    return SimpleNamespace(paths=paths_mod.get_paths(), projects=projects, docs=ProjectDocumentRepository(sf), project_id=project["id"])


async def _add(env: SimpleNamespace, *, name: str, data: bytes) -> dict:
    staged = await stage_document_bytes(env.paths, user_id=_USER, project_id=env.project_id, chunks=[data], max_bytes=1 << 20)
    result = await add_staged_document(env.docs, env.paths, user_id=_USER, project_id=env.project_id, name=name, staged=staged)
    assert result is not None and result[1] is True
    return result[0]


async def test_purge_unlink_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """The original + ``derived/converted.md`` unlink (``_unlink_document_files``)
    runs through the offload, inside the purge transaction's row lock."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        row = await _add(env, name="notes.txt", data=b"hello")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_text("# converted")
        assert await env.docs.trash(row["id"], user_id=_USER) is True
        calls.clear()

        purged = await env.docs.purge(row["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER)

        assert purged is True
        assert "_unlink_document_files" in calls
        assert not derived.exists()
    finally:
        await close_engine()


async def test_restore_content_checks_dispatch_off_the_loop(tmp_path, monkeypatch) -> None:
    """Restore's original existence/size check (``_content_intact``) runs
    through the offload, under the document lock."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        row = await _add(env, name="notes.txt", data=b"hello")
        assert await env.docs.trash(row["id"], user_id=_USER) is True
        calls.clear()

        outcome, restored = await restore_document(env.docs, env.paths, user_id=_USER, document_id=row["id"], target_project_id=env.project_id)

        assert outcome == "restored"
        assert restored is not None
        assert "_content_intact" in calls
    finally:
        await close_engine()


async def test_merge_cleanup_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """The post-commit merge cleanup (``_remove_namespace_tree``) runs through
    the offload."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        old = await _add(env, name="report.txt", data=b"same bytes")
        assert await env.docs.trash(old["id"], user_id=_USER) is True
        new = await _add(env, name="report.txt", data=b"same bytes")
        calls.clear()

        outcome, doc = await restore_document(env.docs, env.paths, user_id=_USER, document_id=old["id"], target_project_id=env.project_id)

        assert outcome == "merged"
        assert doc["id"] == new["id"]
        assert "_remove_namespace_tree" in calls
    finally:
        await close_engine()


async def test_sweep_reconciliation_dispatches_off_the_loop(tmp_path, monkeypatch) -> None:
    """Both sweep reconciliation passes (``_reconcile_storage`` /
    ``_reconcile_rows``) run through the offload — the sweep walks the user's
    projects tree and stats every row's original."""
    calls = _spy_offload(monkeypatch)
    env = await _make_env(tmp_path, monkeypatch)
    try:
        await _add(env, name="notes.txt", data=b"hello")
        calls.clear()

        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)

        assert report.purged == 0
        assert "_reconcile_storage" in calls
        assert "_reconcile_rows" in calls
    finally:
        await close_engine()
