"""Tests for ProjectRepository (SQLAlchemy-backed)."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.schema import DropSchema
from support.postgres import asyncpg_test_url

from deerflow.persistence.projects import ProjectInstructionsConflictError, ProjectRepository


@pytest.fixture
async def repo(tmp_path, request):
    from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine

    schema = None
    if getattr(request, "param", "sqlite") == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = f"test_projects_{uuid4().hex}"
        await init_engine("postgres", url=asyncpg_test_url(uri), postgres_schema=schema)
    else:
        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    try:
        yield ProjectRepository(get_session_factory())
    finally:
        if schema:
            async with get_engine().begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await close_engine()


class TestProjectRepository:
    @pytest.mark.anyio
    async def test_create_and_get(self, repo):
        row = await repo.create(name="Infra overhaul", user_id="u1")
        assert row["status"] == "active"
        assert row["instructions"] == ""
        fetched = await repo.get(row["id"], user_id="u1")
        assert fetched is not None and fetched["name"] == "Infra overhaul"

    @pytest.mark.anyio
    async def test_get_is_fail_closed_for_foreign_user(self, repo):
        row = await repo.create(name="p", user_id="u1")
        assert await repo.get(row["id"], user_id="u2") is None

    @pytest.mark.anyio
    async def test_list_filters_status(self, repo):
        a = await repo.create(name="a", user_id="u1")
        b = await repo.create(name="b", user_id="u1")
        await repo.set_status(b["id"], "archived", user_id="u1")
        active = await repo.list(status="active", user_id="u1")
        assert [r["id"] for r in active] == [a["id"]]
        archived = await repo.list(status="archived", user_id="u1")
        assert [r["id"] for r in archived] == [b["id"]]
        # other users see nothing
        assert await repo.list(user_id="u2") == []

    @pytest.mark.anyio
    async def test_patch_rename_and_instructions(self, repo):
        row = await repo.create(name="old", user_id="u1")
        updated = await repo.patch(row["id"], name="new", instructions="ctx", presentation={"icon": "folder"}, user_id="u1")
        assert updated is not None
        assert updated["name"] == "new" and updated["instructions"] == "ctx"
        assert updated["presentation"] == {"icon": "folder"}

    @pytest.mark.anyio
    async def test_patch_foreign_is_none(self, repo):
        row = await repo.create(name="p", user_id="u1")
        assert await repo.patch(row["id"], name="x", user_id="u2") is None

    @pytest.mark.anyio
    @pytest.mark.parametrize("repo", ["sqlite", "postgres"], indirect=True)
    async def test_only_one_draft_can_replace_the_same_instructions(self, repo):
        project = await repo.create(name="Finance", user_id="u1")
        start = asyncio.Barrier(2)

        async def save(instructions):
            await start.wait()
            return await repo.patch(project["id"], instructions=instructions, expected_instructions="", user_id="u1")

        results = await asyncio.gather(save("Use USD"), save("Use EUR"), return_exceptions=True)
        assert sum(isinstance(result, ProjectInstructionsConflictError) for result in results) == 1
        (winner,) = [result for result in results if isinstance(result, dict)]
        stored = await repo.get(project["id"], user_id="u1")
        assert stored["instructions"] == winner["instructions"]

    @pytest.mark.anyio
    async def test_set_status_is_idempotent(self, repo):
        row = await repo.create(name="p", user_id="u1")
        first = await repo.set_status(row["id"], "archived", user_id="u1")
        second = await repo.set_status(row["id"], "archived", user_id="u1")
        assert first is not None and second is not None
        assert first["status"] == second["status"] == "archived"

    @pytest.mark.anyio
    async def test_delete_returns_false_for_missing_or_foreign(self, repo):
        row = await repo.create(name="p", user_id="u1")
        assert await repo.delete(row["id"], user_id="u2") is False
        assert await repo.delete("nope", user_id="u1") is False
        assert await repo.delete(row["id"], user_id="u1") is True
        assert await repo.get(row["id"], user_id="u1") is None

    @pytest.mark.anyio
    async def test_delete_clears_membership_and_keeps_thread(self, repo, tmp_path):
        from deerflow.persistence.thread_meta import ThreadMetaRepository

        threads = ThreadMetaRepository(repo._sf)
        p = await repo.create(name="P", user_id="u1")
        await threads.create("t1", user_id="u1", project_id=p["id"])

        assert await repo.delete(p["id"], user_id="u1") is True
        record = await threads.get("t1", user_id="u1")
        assert record is not None  # thread row intact
        assert "deerflow_project_id" not in record["metadata"]
