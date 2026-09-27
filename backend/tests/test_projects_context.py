"""Tests for deerflow.projects.context.resolve_project_context (spec §7.1).

One admission-time resolution per run: threads_meta membership -> owner-scoped
project row -> pinned ``{project_id, name, instructions}`` snapshot. Every
failure degrades to ``None`` (run proceeds unassigned) with a warning.
"""

import logging
from types import SimpleNamespace

import pytest

from deerflow.projects.context import resolve_project_context
from deerflow.runtime.user_context import reset_current_user, set_current_user


@pytest.fixture
async def repos(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.projects import ProjectRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    yield ThreadMetaRepository(sf), ProjectRepository(sf)
    await close_engine()


@pytest.fixture
def user_a():
    token = set_current_user(SimpleNamespace(id="user-a"))
    yield "user-a"
    reset_current_user(token)


class TestResolveProjectContext:
    @pytest.mark.anyio
    async def test_assigned_thread_resolves_pinned_snapshot(self, repos, user_a):
        thread_store, project_repo = repos
        project = await project_repo.create(name="Roadmap", instructions="Prefer boring solutions.")
        await thread_store.create("t1", project_id=project["id"])

        snapshot = await resolve_project_context(thread_store, project_repo, "t1")

        assert snapshot == {
            "project_id": project["id"],
            "name": "Roadmap",
            "instructions": "Prefer boring solutions.",
        }

    @pytest.mark.anyio
    async def test_archived_project_still_resolves(self, repos, user_a):
        thread_store, project_repo = repos
        project = await project_repo.create(name="Old", instructions="ctx")
        await thread_store.create("t1", project_id=project["id"])
        await project_repo.set_status(project["id"], "archived")

        snapshot = await resolve_project_context(thread_store, project_repo, "t1")

        assert snapshot is not None
        assert snapshot["project_id"] == project["id"]

    @pytest.mark.anyio
    async def test_unassigned_thread_resolves_none_without_warning(self, repos, user_a, caplog):
        thread_store, project_repo = repos
        await thread_store.create("t1")

        with caplog.at_level(logging.WARNING):
            snapshot = await resolve_project_context(thread_store, project_repo, "t1")

        assert snapshot is None
        assert caplog.records == []

    @pytest.mark.anyio
    async def test_missing_thread_row_degrades_with_warning(self, repos, user_a, caplog):
        thread_store, project_repo = repos

        with caplog.at_level(logging.WARNING):
            snapshot = await resolve_project_context(thread_store, project_repo, "missing-thread")

        assert snapshot is None
        assert "unassigned" in caplog.text

    @pytest.mark.anyio
    async def test_missing_project_row_degrades_with_warning(self, repos, user_a, caplog):
        thread_store, project_repo = repos
        project = await project_repo.create(name="P")
        await thread_store.create("t1", project_id=project["id"])
        await project_repo.delete(project["id"])  # clears membership; re-point by hand to simulate a dangling row

        async with thread_store._sf() as session:
            from sqlalchemy import update

            from deerflow.persistence.thread_meta.model import ThreadMetaRow

            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "t1").values(project_id=project["id"]))
            await session.commit()

        with caplog.at_level(logging.WARNING):
            snapshot = await resolve_project_context(thread_store, project_repo, "t1")

        assert snapshot is None
        assert "unassigned" in caplog.text

    @pytest.mark.anyio
    async def test_foreign_project_row_is_invisible(self, repos, user_a, caplog):
        thread_store, project_repo = repos
        foreign = await project_repo.create(name="Theirs", user_id="user-b")
        await thread_store.create("t1")
        async with thread_store._sf() as session:
            from sqlalchemy import update

            from deerflow.persistence.thread_meta.model import ThreadMetaRow

            await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "t1").values(project_id=foreign["id"]))
            await session.commit()

        with caplog.at_level(logging.WARNING):
            snapshot = await resolve_project_context(thread_store, project_repo, "t1")

        assert snapshot is None
        assert "unassigned" in caplog.text

    @pytest.mark.anyio
    async def test_unavailable_repository_degrades_with_warning(self, repos, user_a, caplog):
        thread_store, _ = repos
        await thread_store.create("t1")

        with caplog.at_level(logging.WARNING):
            snapshot = await resolve_project_context(thread_store, None, "t1")

        assert snapshot is None
        assert "unassigned" in caplog.text

    @pytest.mark.anyio
    async def test_store_error_degrades_with_warning(self, user_a, caplog):
        class _BoomStore:
            async def get(self, thread_id, **kwargs):
                raise RuntimeError("database is down")

        class _Repo:
            async def get(self, project_id, **kwargs):
                raise AssertionError("must not be reached")

        with caplog.at_level(logging.WARNING):
            snapshot = await resolve_project_context(_BoomStore(), _Repo(), "t1")

        assert snapshot is None
        assert "unassigned" in caplog.text

    @pytest.mark.anyio
    async def test_resolution_never_writes_membership(self, repos, user_a):
        """Admission reads membership; it must not create or modify thread rows."""
        thread_store, project_repo = repos
        project = await project_repo.create(name="P")
        await thread_store.create("t1", project_id=project["id"])

        before = await thread_store.get("t1")
        await resolve_project_context(thread_store, project_repo, "t1")
        await resolve_project_context(thread_store, project_repo, "brand-new-thread")
        after = await thread_store.get("t1")

        assert after == before
        assert await thread_store.get("brand-new-thread") is None
