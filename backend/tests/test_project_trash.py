"""Tests for the trash tier service (Phase-2 spec §8.2/§8.3/§13).

Covers the real-filesystem behavior the repository tests fake: purge file
ordering and FileNotFoundError tolerance, partial-failure retry, restore
re-pointing without file moves, merge cleanup confinement, and the retention
sweep (expiry purge, 24-hour orphan guard, row-side reconciliation that
detects but never deletes, empty-parent rmdir).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
from deerflow.projects.documents import add_staged_document, converted_markdown_path, original_file_path, stage_document_bytes
from deerflow.projects.trash import make_purge_file_remover, restore_document, run_trash_retention_sweep

pytestmark = pytest.mark.anyio

_USER = "u1"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    import deerflow.config.paths as paths_mod

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths_mod, "_paths", None)
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    yield SimpleNamespace(paths=paths_mod.get_paths(), projects=ProjectRepository(sf), docs=ProjectDocumentRepository(sf))
    await close_engine()


async def _add(env: SimpleNamespace, project_id: str, *, name: str, data: bytes, user_id: str = _USER) -> dict:
    staged = await stage_document_bytes(env.paths, user_id=user_id, project_id=project_id, chunks=[data], max_bytes=1 << 20)
    result = await add_staged_document(env.docs, env.paths, user_id=user_id, project_id=project_id, name=name, staged=staged)
    assert result is not None and result[1] is True
    return result[0]


async def _trash(env: SimpleNamespace, row: dict, *, user_id: str = _USER) -> dict:
    assert await env.docs.trash(row["id"], user_id=user_id) is True
    trashed = await env.docs.get(row["id"], include_trashed=True, user_id=user_id)
    assert trashed is not None
    return trashed


async def _set_column(document_id: str, **values) -> None:
    from sqlalchemy import update as sa_update

    from deerflow.persistence.projects.model import ProjectDocumentRow

    sf = get_session_factory()
    async with sf() as session:
        await session.execute(sa_update(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).values(**values))
        await session.commit()


def _namespace(env: SimpleNamespace, row: dict, user_id: str = _USER) -> Path:
    return env.paths.project_document_path(user_id, row["stored_relpath"])


def _age(path: Path, *, hours: float) -> None:
    ts = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()
    os.utime(path, (ts, ts))


class TestPurgeFiles:
    async def test_purge_unlinks_namespace_files_and_rmdirs_empty_parents(self, env):
        project = await env.projects.create(name="P", user_id=_USER)
        row = await _add(env, project["id"], name="notes.txt", data=b"hello")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_text("# converted")
        original = original_file_path(env.paths, user_id=_USER, row=row)
        namespace = _namespace(env, row)
        documents_dir = env.paths.project_documents_dir(_USER, project["id"])
        await _trash(env, row)

        purged = await env.docs.purge(row["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER)

        assert purged is True
        assert not original.exists()
        assert not derived.exists()
        # Empty parents rmdir'd best-effort; the documents dir itself stays.
        assert not namespace.exists()
        assert not namespace.parent.exists()
        assert documents_dir.is_dir()
        assert await env.docs.get(row["id"], include_trashed=True, user_id=_USER) is None

    async def test_purge_tolerates_already_missing_original_and_conversion(self, env):
        """FileNotFoundError counts as already removed (§8.3): a partial
        earlier attempt or external removal never blocks the purge."""
        project = await env.projects.create(name="P", user_id=_USER)
        row = await _add(env, project["id"], name="notes.txt", data=b"hello")
        original = original_file_path(env.paths, user_id=_USER, row=row)
        original.unlink()  # bytes already gone; no conversion ever existed
        await _trash(env, row)

        purged = await env.docs.purge(row["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER)

        assert purged is True
        assert await env.docs.get(row["id"], include_trashed=True, user_id=_USER) is None

    async def test_partial_unlink_failure_retains_row_and_retry_completes(self, env, monkeypatch):
        """§13 purge ordering: original unlinked, derived unlink raises —
        the row stays trashed (retryable); the retry tolerates the missing
        original and finishes."""
        project = await env.projects.create(name="P", user_id=_USER)
        row = await _add(env, project["id"], name="notes.txt", data=b"hello")
        derived = converted_markdown_path(env.paths, user_id=_USER, row=row)
        derived.parent.mkdir(parents=True, exist_ok=True)
        derived.write_text("# converted")
        original = original_file_path(env.paths, user_id=_USER, row=row)
        await _trash(env, row)

        failed = False
        real_unlink = Path.unlink

        def flaky_unlink(self: Path, *args, **kwargs):
            nonlocal failed
            if self.name == "converted.md" and not failed:
                failed = True
                raise OSError("disk full")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", flaky_unlink)
        remover = make_purge_file_remover(env.paths, user_id=_USER)
        with pytest.raises(OSError):
            await env.docs.purge(row["id"], remove_files=remover, user_id=_USER)

        # Partial filesystem progress happened, but the row was retained.
        assert not original.exists()
        still = await env.docs.get(row["id"], include_trashed=True, user_id=_USER)
        assert still is not None and still["trashed_at"]

        assert await env.docs.purge(row["id"], remove_files=remover, user_id=_USER) is True
        assert not derived.exists()
        assert await env.docs.get(row["id"], include_trashed=True, user_id=_USER) is None


class TestRestoreService:
    async def test_restore_repoints_without_moving_files(self, env):
        project = await env.projects.create(name="P", user_id=_USER)
        target = await env.projects.create(name="T", user_id=_USER)
        row = await _add(env, project["id"], name="notes.txt", data=b"hello shelf")
        original = original_file_path(env.paths, user_id=_USER, row=row)
        await _trash(env, row)

        outcome, restored = await restore_document(env.docs, env.paths, user_id=_USER, document_id=row["id"], target_project_id=target["id"])

        assert outcome == "restored"
        assert restored["project_id"] == target["id"]
        assert restored["stored_relpath"] == row["stored_relpath"]
        # The bytes never moved and still serve (§10.6).
        assert original.read_bytes() == b"hello shelf"

    async def test_restore_with_missing_content_leaves_row_trashed(self, env):
        project = await env.projects.create(name="P", user_id=_USER)
        row = await _add(env, project["id"], name="notes.txt", data=b"hello")
        await _trash(env, row)
        original_file_path(env.paths, user_id=_USER, row=row).unlink()

        outcome, doc = await restore_document(env.docs, env.paths, user_id=_USER, document_id=row["id"], target_project_id=project["id"])

        assert outcome == "content_missing"
        assert doc is None
        still = await env.docs.get(row["id"], include_trashed=True, user_id=_USER)
        assert still is not None and still["trashed_at"]

    async def test_restore_with_size_mismatch_is_content_missing(self, env):
        project = await env.projects.create(name="P", user_id=_USER)
        row = await _add(env, project["id"], name="notes.txt", data=b"hello")
        await _trash(env, row)
        original_file_path(env.paths, user_id=_USER, row=row).write_bytes(b"tampered!")

        outcome, _doc = await restore_document(env.docs, env.paths, user_id=_USER, document_id=row["id"], target_project_id=project["id"])
        assert outcome == "content_missing"


class TestLifecycleCycles:
    async def test_upload_trash_same_name_reupload_then_merge(self, env):
        """§13: upload → trash → identical same-name re-upload → restore the
        old row into the same project merges; only the discarded namespace is
        unlinked (post-commit); the new row and its conversion survive."""
        project = await env.projects.create(name="P", user_id=_USER)
        old = await _add(env, project["id"], name="report.txt", data=b"same bytes")
        old_namespace = _namespace(env, old)
        await _trash(env, old)
        new = await _add(env, project["id"], name="report.txt", data=b"same bytes")
        assert new["id"] != old["id"]
        assert new["stored_relpath"] != old["stored_relpath"]
        new_derived = converted_markdown_path(env.paths, user_id=_USER, row=new)
        new_derived.parent.mkdir(parents=True, exist_ok=True)
        new_derived.write_text("# converted")

        outcome, doc = await restore_document(env.docs, env.paths, user_id=_USER, document_id=old["id"], target_project_id=project["id"])

        assert outcome == "merged"
        assert doc["id"] == new["id"]
        assert not old_namespace.exists()
        assert original_file_path(env.paths, user_id=_USER, row=new).read_bytes() == b"same bytes"
        assert new_derived.read_text() == "# converted"
        assert await env.docs.count_active(project["id"], user_id=_USER) == 1

    async def test_upload_trash_reupload_then_purge_old_row_cleanup_confined(self, env):
        """§13: purging the old row removes only its own namespace; the new
        row's content and conversion survive."""
        project = await env.projects.create(name="P", user_id=_USER)
        old = await _add(env, project["id"], name="report.txt", data=b"same bytes")
        old_namespace = _namespace(env, old)
        await _trash(env, old)
        new = await _add(env, project["id"], name="report.txt", data=b"same bytes")
        new_derived = converted_markdown_path(env.paths, user_id=_USER, row=new)
        new_derived.parent.mkdir(parents=True, exist_ok=True)
        new_derived.write_text("# converted")

        purged = await env.docs.purge(old["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER)

        assert purged is True
        assert not old_namespace.exists()
        assert original_file_path(env.paths, user_id=_USER, row=new).read_bytes() == b"same bytes"
        assert new_derived.read_text() == "# converted"

    async def test_restore_into_another_project_yields_distinct_namespaces(self, env):
        """§13: restore into another project keeps both namespaces valid;
        a later purge of the restored row stays confined to its namespace."""
        project = await env.projects.create(name="P", user_id=_USER)
        other = await env.projects.create(name="O", user_id=_USER)
        old = await _add(env, project["id"], name="report.txt", data=b"same bytes")
        await _trash(env, old)
        new = await _add(env, project["id"], name="report.txt", data=b"same bytes")

        outcome, restored = await restore_document(env.docs, env.paths, user_id=_USER, document_id=old["id"], target_project_id=other["id"])

        assert outcome == "restored"
        assert restored["project_id"] == other["id"]
        restored_original = original_file_path(env.paths, user_id=_USER, row=restored)
        new_original = original_file_path(env.paths, user_id=_USER, row=new)
        assert restored_original != new_original
        assert restored_original.read_bytes() == b"same bytes"
        assert new_original.read_bytes() == b"same bytes"
        # Trash it again from its new project, then purge: cleanup stays
        # confined to the restored row's own namespace.
        await _trash(env, restored)
        purged = await env.docs.purge(old["id"], remove_files=make_purge_file_remover(env.paths, user_id=_USER), user_id=_USER)
        assert purged is True
        assert not _namespace(env, restored).exists()
        assert new_original.read_bytes() == b"same bytes"


class TestRetentionSweep:
    async def test_expired_rows_purged_with_files_fresh_rows_untouched(self, env):
        project = await env.projects.create(name="P", user_id=_USER)
        expired = await _add(env, project["id"], name="old.txt", data=b"old")
        fresh = await _add(env, project["id"], name="fresh.txt", data=b"fresh")
        expired_ns = _namespace(env, expired)
        await _trash(env, expired)
        await _trash(env, fresh)
        await _set_column(expired["id"], trashed_at=datetime.now(UTC) - timedelta(days=31))

        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)

        assert report.purged == 1
        assert report.purge_failures == 0
        assert await env.docs.get(expired["id"], include_trashed=True, user_id=_USER) is None
        assert not expired_ns.exists()
        still = await env.docs.get(fresh["id"], include_trashed=True, user_id=_USER)
        assert still is not None and still["trashed_at"]
        assert original_file_path(env.paths, user_id=_USER, row=still).read_bytes() == b"fresh"

    async def test_staging_and_orphan_collection_respect_the_24h_guard(self, env):
        """§13: nothing younger than 24h is ever collected — a fresh staging
        file survives; old staging/orphans go; a row protects its namespace."""
        project = await env.projects.create(name="P", user_id=_USER)
        documents_dir = env.paths.project_documents_dir(_USER, project["id"])
        staging = documents_dir / ".staging"
        staging.mkdir(parents=True)
        young_staging = staging / "young"
        young_staging.write_bytes(b"x")
        old_staging = staging / "old"
        old_staging.write_bytes(b"x")
        _age(old_staging, hours=25)

        ghost = documents_dir / "ab" / ("ab" * 32) / "ghost" / "original"
        ghost.mkdir(parents=True)
        orphan_young = ghost / "young.bin"
        orphan_young.write_bytes(b"x")
        orphan_old = ghost / "old.bin"
        orphan_old.write_bytes(b"x")
        _age(orphan_old, hours=25)

        row = await _add(env, project["id"], name="keep.txt", data=b"keep")
        protected = original_file_path(env.paths, user_id=_USER, row=row)
        _age(protected, hours=25)  # old on disk, but a row references it

        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)

        assert report.staging_removed == 1
        assert young_staging.exists()
        assert not old_staging.exists()
        assert report.orphans_removed == 1
        assert orphan_young.exists()
        assert not orphan_old.exists()
        assert protected.exists()

    async def test_reconciliation_free_sweep_purges_but_skips_the_scan(self, env):
        """§8.3 debounce support: include_reconciliation=False keeps the
        expiry purge (the retention guarantee) and skips the O(rows + files)
        reconciliation, leaving aged staging to the next full sweep."""
        project = await env.projects.create(name="P", user_id=_USER)
        documents_dir = env.paths.project_documents_dir(_USER, project["id"])
        staging = documents_dir / ".staging"
        staging.mkdir(parents=True)
        old_staging = staging / "old"
        old_staging.write_bytes(b"x")
        _age(old_staging, hours=25)

        expired = await _add(env, project["id"], name="expired.txt", data=b"old")
        await _trash(env, expired)
        await _set_column(expired["id"], trashed_at=datetime.now(UTC) - timedelta(days=31))

        report = await run_trash_retention_sweep(
            env.docs,
            env.paths,
            retention_days=30,
            user_id=_USER,
            include_reconciliation=False,
        )

        assert report.purged == 1
        assert await env.docs.get(expired["id"], include_trashed=True, user_id=_USER) is None
        assert report.staging_removed == 0
        assert old_staging.exists()

    async def test_fully_collected_namespace_tree_is_rmdired(self, env):
        project = await env.projects.create(name="P", user_id=_USER)
        documents_dir = env.paths.project_documents_dir(_USER, project["id"])
        ghost_ns = documents_dir / "cd" / ("cd" * 32) / "ghost"
        (ghost_ns / "original").mkdir(parents=True)
        stale = ghost_ns / "original" / "stale.bin"
        stale.write_bytes(b"x")
        _age(stale, hours=25)

        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)

        assert report.orphans_removed == 1
        assert not ghost_ns.exists()
        assert not ghost_ns.parent.exists()
        assert documents_dir.is_dir()

    async def test_row_reconciliation_detects_logs_and_never_deletes(self, env, caplog):
        """§8.3/§15.17: a row whose content vanished past the 24h guard is
        surfaced as content_missing (log + report) but the row is retained —
        it is the user's only record of the document."""
        project = await env.projects.create(name="P", user_id=_USER)
        row = await _add(env, project["id"], name="gone.txt", data=b"gone")
        original_file_path(env.paths, user_id=_USER, row=row).unlink()

        # Younger than the guard: not flagged.
        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)
        assert row["id"] not in report.content_missing

        await _set_column(row["id"], created_at=datetime.now(UTC) - timedelta(hours=25))
        with caplog.at_level(logging.WARNING):
            report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)

        assert row["id"] in report.content_missing
        assert any("content" in record.message and row["id"] in record.message for record in caplog.records)
        # Detection never deletes: the row survives intact (§15.17).
        assert await env.docs.get(row["id"], user_id=_USER) is not None

    async def test_size_mismatch_flagged_same_as_missing(self, env):
        project = await env.projects.create(name="P", user_id=_USER)
        row = await _add(env, project["id"], name="tampered.txt", data=b"abc")
        original_file_path(env.paths, user_id=_USER, row=row).write_bytes(b"abcdef")
        await _set_column(row["id"], created_at=datetime.now(UTC) - timedelta(hours=25))

        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)
        assert row["id"] in report.content_missing
        assert await env.docs.get(row["id"], user_id=_USER) is not None

    async def test_all_users_mode_sweeps_every_user_at_startup(self, env):
        p1 = await env.projects.create(name="P1", user_id=_USER)
        p2 = await env.projects.create(name="P2", user_id="u2")
        r1 = await _add(env, p1["id"], name="a.txt", data=b"a", user_id=_USER)
        r2 = await _add(env, p2["id"], name="b.txt", data=b"b", user_id="u2")
        await _trash(env, r1)
        await _trash(env, r2, user_id="u2")
        old = datetime.now(UTC) - timedelta(days=31)
        await _set_column(r1["id"], trashed_at=old)
        await _set_column(r2["id"], trashed_at=old)

        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=None)

        assert report.purged == 2
        assert await env.docs.get(r1["id"], include_trashed=True, user_id=_USER) is None
        assert await env.docs.get(r2["id"], include_trashed=True, user_id="u2") is None

    async def test_purge_failure_inside_sweep_keeps_row_and_continues(self, env, monkeypatch):
        project = await env.projects.create(name="P", user_id=_USER)
        bad = await _add(env, project["id"], name="bad.txt", data=b"bad")
        good = await _add(env, project["id"], name="good.txt", data=b"good")
        await _trash(env, bad)
        await _trash(env, good)
        old = datetime.now(UTC) - timedelta(days=31)
        await _set_column(bad["id"], trashed_at=old - timedelta(days=1))  # oldest first
        await _set_column(good["id"], trashed_at=old)

        real_unlink = Path.unlink

        def flaky_unlink(self: Path, *args, **kwargs):
            if self.name == "bad.txt":
                raise OSError("disk full")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", flaky_unlink)
        report = await run_trash_retention_sweep(env.docs, env.paths, retention_days=30, user_id=_USER)

        assert report.purged == 1
        assert report.purge_failures == 1
        still = await env.docs.get(bad["id"], include_trashed=True, user_id=_USER)
        assert still is not None and still["trashed_at"]
        assert await env.docs.get(good["id"], include_trashed=True, user_id=_USER) is None


class TestStartupSweep:
    async def test_startup_hook_sweeps_all_users_with_configured_retention(self, env):
        """§8.3: the lifespan startup trigger runs one sweep over every user
        with the configured retention window."""
        from fastapi import FastAPI

        from app.gateway.app import _run_startup_trash_sweep
        from deerflow.config.projects_config import ProjectsConfig

        p1 = await env.projects.create(name="P1", user_id=_USER)
        p2 = await env.projects.create(name="P2", user_id="u2")
        r1 = await _add(env, p1["id"], name="a.txt", data=b"a", user_id=_USER)
        r2 = await _add(env, p2["id"], name="b.txt", data=b"b", user_id="u2")
        await _trash(env, r1)
        await _trash(env, r2, user_id="u2")
        old = datetime.now(UTC) - timedelta(days=31)
        await _set_column(r1["id"], trashed_at=old)
        await _set_column(r2["id"], trashed_at=old)

        app = FastAPI()
        app.state.project_document_repo = env.docs
        await _run_startup_trash_sweep(app, SimpleNamespace(projects=ProjectsConfig(trash_retention_days=30)))

        assert await env.docs.get(r1["id"], include_trashed=True, user_id=_USER) is None
        assert await env.docs.get(r2["id"], include_trashed=True, user_id="u2") is None

    async def test_startup_hook_is_nonfatal_on_sweep_failure(self, env, monkeypatch, caplog):
        """A sweep failure is logged and never blocks gateway readiness."""
        from fastapi import FastAPI

        import deerflow.projects.trash as trash_mod
        from app.gateway.app import _run_startup_trash_sweep

        async def failing(*args, **kwargs):
            raise RuntimeError("database gone")

        monkeypatch.setattr(trash_mod, "run_trash_retention_sweep", failing)
        app = FastAPI()
        app.state.project_document_repo = env.docs
        with caplog.at_level(logging.WARNING):
            await _run_startup_trash_sweep(app, SimpleNamespace(projects=None))
        assert any("Trash retention sweep skipped" in record.message for record in caplog.records)

    async def test_startup_hook_is_noop_without_repository(self, env):
        """Memory-backend deployments have no document repo: nothing to sweep."""
        from fastapi import FastAPI

        from app.gateway.app import _run_startup_trash_sweep

        app = FastAPI()
        app.state.project_document_repo = None
        await _run_startup_trash_sweep(app, SimpleNamespace(projects=None))

    async def test_shutdown_hook_cancels_a_sweep_that_overruns_the_budget(self, env, monkeypatch, caplog):
        """A sweep still running at the shutdown deadline stops there.

        The shield keeps the shutdown wait bounded without killing the sweep,
        so an overrun must be cancelled explicitly: an all-users
        reconciliation left running keeps reading rows and files while the
        repo and DB engine are disposed underneath it.
        """
        from fastapi import FastAPI

        import app.gateway.app as gateway_app
        import deerflow.projects.trash as trash_mod

        started = asyncio.Event()
        observed_cancel = asyncio.Event()

        async def overrunning(*args, **kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                observed_cancel.set()
                raise

        monkeypatch.setattr(trash_mod, "run_trash_retention_sweep", overrunning)
        monkeypatch.setattr(gateway_app, "_SHUTDOWN_HOOK_TIMEOUT_SECONDS", 0.05)
        app = FastAPI()
        app.state.project_document_repo = env.docs
        task = asyncio.create_task(gateway_app._run_startup_trash_sweep(app, SimpleNamespace(projects=None)))
        app.state.startup_trash_sweep_task = task
        await asyncio.wait_for(started.wait(), timeout=5)

        with caplog.at_level(logging.WARNING):
            await gateway_app._shutdown_startup_trash_sweep(app)

        assert observed_cancel.is_set()
        assert task.cancelled()
        assert any("Startup trash sweep exceeded" in record.message for record in caplog.records)
