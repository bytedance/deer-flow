"""Tests for ProjectDocumentRepository (Phase-2 spec §6.1/§6.3/§8.1).

Covers the shelf row lifecycle at the SQL layer: dedup among active rows
(trashed rows never block a re-add), ``trashed_at`` filtering in every read,
``shelf_snapshot`` ordering/round-trip shape, the guarded trash transition
with its archived-project rejection, project delete trashing the shelf in the
same transaction, and the two hard concurrency guarantees from §13 —
concurrent upload vs project delete, and concurrent duplicate upload.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
async def repos(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    yield ProjectRepository(sf), ProjectDocumentRepository(sf)
    await close_engine()


async def _project(projects: ProjectRepository, *, user_id: str = "u1", name: str = "P") -> dict:
    return await projects.create(name=name, user_id=user_id)


async def _insert(docs: ProjectDocumentRepository, project_id: str, *, sha: str, name: str = "a.txt", user_id: str = "u1", doc_id: str | None = None) -> dict:
    row = await docs.insert_active(
        project_id,
        document_id=doc_id or f"doc-{sha[:8]}-{name}",
        name=name,
        relpath=f"{project_id}/documents/{sha[:2]}/{sha}/x",
        sha256=sha,
        size_bytes=10,
        user_id=user_id,
    )
    assert row is not None
    return row


class TestInsertActive:
    async def test_insert_returns_none_for_missing_foreign_archived(self, repos):
        projects, docs = repos
        assert await docs.insert_active("nope", document_id="d1", name="a", relpath="r", sha256="s", size_bytes=1, user_id="u1") is None
        foreign = await _project(projects, user_id="u2")
        assert await docs.insert_active(foreign["id"], document_id="d1", name="a", relpath="r", sha256="s", size_bytes=1, user_id="u1") is None
        archived = await _project(projects)
        await projects.set_status(archived["id"], "archived", user_id="u1")
        assert await docs.insert_active(archived["id"], document_id="d1", name="a", relpath="r", sha256="s", size_bytes=1, user_id="u1") is None

    async def test_place_file_runs_before_insert_only_on_dedup_miss(self, repos):
        projects, docs = repos
        project = await _project(projects)
        calls: list[str] = []

        async def place() -> None:
            calls.append("placed")
            # File-before-row (§10.3): at placement time the row must not exist yet.
            assert await docs.find_active_by_sha256(project["id"], "sha-x", user_id="u1") is None

        row = await docs.insert_active(project["id"], document_id="d1", name="a", relpath="r", sha256="sha-x", size_bytes=1, place_file=place, user_id="u1")
        assert row is not None and row["id"] == "d1"
        assert calls == ["placed"]

        # Dedup hit: the existing row comes back and placement is skipped.
        calls.clear()
        hit = await docs.insert_active(project["id"], document_id="d2", name="b", relpath="r2", sha256="sha-x", size_bytes=1, place_file=place, user_id="u1")
        assert hit is not None and hit["id"] == "d1" and hit["name"] == "a"
        assert calls == []

    async def test_provenance_columns_round_trip(self, repos):
        projects, docs = repos
        project = await _project(projects)
        row = await docs.insert_active(
            project["id"],
            document_id="d1",
            name="report.md",
            relpath="r",
            sha256="s1",
            size_bytes=5,
            source_thread_id="t-1",
            source_kind="output",
            source_name="draft.md",
            user_id="u1",
        )
        assert row["source_thread_id"] == "t-1"
        assert row["source_kind"] == "output"
        assert row["source_name"] == "draft.md"


class TestReadsFilterTrashed:
    async def test_every_read_excludes_trashed_rows(self, repos):
        projects, docs = repos
        project = await _project(projects)
        a = await _insert(docs, project["id"], sha="a" * 64, name="a.txt")
        b = await _insert(docs, project["id"], sha="b" * 64, name="b.txt")
        assert await docs.trash(a["id"], user_id="u1") is True

        assert [r["id"] for r in await docs.list_active(project["id"], limit=10, offset=0, user_id="u1")] == [b["id"]]
        assert await docs.count_active(project["id"], user_id="u1") == 1
        rows, total = await docs.shelf_snapshot(project["id"], limit=10, user_id="u1")
        assert [r["id"] for r in rows] == [b["id"]] and total == 1
        assert await docs.find_active_by_sha256(project["id"], "a" * 64, user_id="u1") is None
        assert await docs.get(a["id"], user_id="u1") is None
        trashed = await docs.get(a["id"], include_trashed=True, user_id="u1")
        assert trashed is not None and trashed["trashed_at"]

    async def test_trashed_row_does_not_block_readd_of_identical_content(self, repos):
        projects, docs = repos
        project = await _project(projects)
        first = await _insert(docs, project["id"], sha="c" * 64, name="same.txt", doc_id="first")
        assert await docs.trash(first["id"], user_id="u1") is True
        # Re-add after trash: a fresh row with a distinct ID and namespace (§10.9).
        second = await _insert(docs, project["id"], sha="c" * 64, name="same.txt", doc_id="second")
        assert second["id"] == "second"
        assert (await docs.find_active_by_sha256(project["id"], "c" * 64, user_id="u1"))["id"] == "second"

    async def test_reads_are_fail_closed_for_foreign_users(self, repos):
        projects, docs = repos
        project = await _project(projects, user_id="u1")
        row = await _insert(docs, project["id"], sha="d" * 64)
        assert await docs.get(row["id"], user_id="u2") is None
        assert await docs.list_active(project["id"], limit=10, offset=0, user_id="u2") == []
        assert await docs.count_active(project["id"], user_id="u2") == 0
        _, total = await docs.shelf_snapshot(project["id"], limit=10, user_id="u2")
        assert total == 0


class TestShelfSnapshot:
    async def test_ordering_is_updated_desc_id_asc_with_one_round_trip_shape(self, repos):
        projects, docs = repos
        project = await _project(projects)
        rows = []
        for i in range(5):
            rows.append(await _insert(docs, project["id"], sha=f"{i}" * 64, name=f"f{i}.txt", doc_id=f"d{i}"))
        # Re-touch d2 so it becomes the most recently updated row.
        await _insert(docs, project["id"], sha="e" * 64, name="f5.txt", doc_id="d5")
        import sqlalchemy as sa

        from deerflow.persistence.projects.model import ProjectDocumentRow

        async with docs._sf() as session:
            await session.execute(sa.update(ProjectDocumentRow).where(ProjectDocumentRow.id == "d2").values(updated_at=datetime(2999, 1, 1, tzinfo=UTC)))
            await session.commit()

        snapshot_rows, total = await docs.shelf_snapshot(project["id"], limit=3, user_id="u1")
        assert total == 6
        assert [r["id"] for r in snapshot_rows] == ["d2", "d5", "d4"]
        listed = await docs.list_active(project["id"], limit=10, offset=0, user_id="u1")
        assert [r["id"] for r in listed][:3] == ["d2", "d5", "d4"]
        # The +1 row convention: limit N+1 lets the caller decide truncation.
        plus_one, _ = await docs.shelf_snapshot(project["id"], limit=4, user_id="u1")
        assert len(plus_one) == 4

    async def test_pagination_walks_the_whole_shelf_in_order(self, repos):
        projects, docs = repos
        project = await _project(projects)
        for i in range(7):
            await _insert(docs, project["id"], sha=f"{i}" * 64, name=f"f{i}.txt", doc_id=f"d{i}")
        seen: list[str] = []
        offset = 0
        while True:
            page = await docs.list_active(project["id"], limit=3, offset=offset, user_id="u1")
            if not page:
                break
            seen.extend(r["id"] for r in page)
            offset += len(page)
        assert seen == ["d6", "d5", "d4", "d3", "d2", "d1", "d0"]


class TestTrash:
    async def test_trash_sets_fields_and_snapshots_origin(self, repos):
        projects, docs = repos
        project = await _project(projects, name="Roadmap")
        row = await _insert(docs, project["id"], sha="f" * 64)
        assert await docs.trash(row["id"], user_id="u1") is True
        trashed = await docs.get(row["id"], include_trashed=True, user_id="u1")
        assert trashed["trashed_at"]
        assert trashed["trash_origin"] == {"project_id": project["id"], "project_name": "Roadmap"}

    async def test_trash_rejects_archived_foreign_missing_and_retrash(self, repos):
        projects, docs = repos
        project = await _project(projects)
        row = await _insert(docs, project["id"], sha="1" * 64)
        assert await docs.trash("missing", user_id="u1") is False
        assert await docs.trash(row["id"], user_id="u2") is False
        assert await docs.trash(row["id"], user_id="u1") is True
        # Already trashed: the guarded UPDATE matches nothing.
        assert await docs.trash(row["id"], user_id="u1") is False

        archived = await _project(projects, name="A")
        archived_doc = await _insert(docs, archived["id"], sha="2" * 64, doc_id="archived-doc")
        await projects.set_status(archived["id"], "archived", user_id="u1")
        assert await docs.trash(archived_doc["id"], user_id="u1") is False
        assert await docs.get(archived_doc["id"], user_id="u1") is not None

    async def test_expected_project_rejects_sibling_shelf_rows(self, repos):
        projects, docs = repos
        project_a = await _project(projects, name="A")
        project_b = await _project(projects, name="B")
        row = await _insert(docs, project_b["id"], sha="9" * 64, doc_id="b-doc")

        # The expected project gates the probe, the locked re-read and the
        # guarded UPDATE (§6.1): a sibling shelf row is indistinguishable from
        # missing even when the caller owns both projects.
        assert await docs.trash(row["id"], project_id=project_a["id"], user_id="u1") is False
        assert await docs.get(row["id"], user_id="u1") is not None
        assert await docs.trash("missing", project_id=project_a["id"], user_id="u1") is False
        assert await docs.trash(row["id"], project_id=project_b["id"], user_id="u2") is False
        assert await docs.trash(row["id"], project_id=project_b["id"], user_id="u1") is True


class TestProjectDelete:
    async def test_delete_trashes_the_shelf_in_the_same_transaction(self, repos):
        projects, docs = repos
        project = await _project(projects, name="Doomed")
        a = await _insert(docs, project["id"], sha="3" * 64, doc_id="del-a")
        b = await _insert(docs, project["id"], sha="4" * 64, doc_id="del-b")
        already = await _insert(docs, project["id"], sha="5" * 64, doc_id="del-c")
        assert await docs.trash(already["id"], user_id="u1") is True

        assert await projects.delete(project["id"], user_id="u1") is True

        # No active row may point at the deleted project.
        assert await docs.list_active(project["id"], limit=10, offset=0, user_id="u1") == []
        assert await docs.count_active(project["id"], user_id="u1") == 0
        for row_id in (a["id"], b["id"]):
            trashed = await docs.get(row_id, include_trashed=True, user_id="u1")
            assert trashed is not None and trashed["trashed_at"]
            assert trashed["trash_origin"] == {"project_id": project["id"], "project_name": "Doomed"}
        # The previously trashed row keeps its original trash timestamp/origin.
        untouched = await docs.get(already["id"], include_trashed=True, user_id="u1")
        assert untouched["trash_origin"] == {"project_id": project["id"], "project_name": "Doomed"}

    async def test_concurrent_upload_vs_project_delete_never_leaves_an_active_row(self, repos):
        """§13: either the insert sees no active project, or the delete trashes it."""
        projects, docs = repos
        for _ in range(10):
            project = await _project(projects)
            pid = project["id"]

            async def upload(i: int) -> None:
                await docs.insert_active(pid, document_id=f"r-{pid[:6]}-{i}", name="r.txt", relpath="r", sha256=f"{i}" * 64, size_bytes=1, user_id="u1")

            async def delete() -> None:
                await projects.delete(pid, user_id="u1")

            await asyncio.gather(*(upload(i) for i in range(4)), delete())
            assert await docs.count_active(pid, user_id="u1") == 0
            assert await docs.list_active(pid, limit=10, offset=0, user_id="u1") == []

    async def test_concurrent_duplicate_upload_yields_exactly_one_row(self, repos):
        """§13: identical bytes racing → one row, both callers succeed."""
        projects, docs = repos
        project = await _project(projects)
        sha = "9" * 64

        async def upload(i: int) -> dict:
            row = await docs.insert_active(project["id"], document_id=f"dup-{i}", name=f"n{i}.txt", relpath=f"r{i}", sha256=sha, size_bytes=3, user_id="u1")
            assert row is not None
            return row

        results = await asyncio.gather(*(upload(i) for i in range(6)))
        ids = {r["id"] for r in results}
        assert len(ids) == 1
        assert await docs.count_active(project["id"], user_id="u1") == 1
        # First writer's name wins for every caller (§10.9).
        names = {r["name"] for r in results}
        assert len(names) == 1


async def _trashed(docs: ProjectDocumentRepository, projects: ProjectRepository, *, sha: str, doc_id: str, user_id: str = "u1", project: dict | None = None) -> tuple[dict, dict]:
    project = project or await _project(projects)
    row = await _insert(docs, project["id"], sha=sha, doc_id=doc_id, user_id=user_id)
    assert await docs.trash(row["id"], user_id=user_id) is True
    return project, row


async def _set_trashed_at(document_id: str, when: datetime) -> None:
    from sqlalchemy import update as sa_update

    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.projects.model import ProjectDocumentRow

    sf = get_session_factory()
    async with sf() as session:
        await session.execute(sa_update(ProjectDocumentRow).where(ProjectDocumentRow.id == document_id).values(trashed_at=when))
        await session.commit()


class TestListTrashed:
    async def test_lists_only_trashed_rows_with_owner_filter_and_paging(self, repos):
        projects, docs = repos
        project = await _project(projects)
        keep = await _insert(docs, project["id"], sha="aa" * 32, doc_id="lt-keep")
        first = await _insert(docs, project["id"], sha="bb" * 32, doc_id="lt-first")
        second = await _insert(docs, project["id"], sha="cc" * 32, doc_id="lt-second")
        assert await docs.trash(first["id"], user_id="u1") is True
        assert await docs.trash(second["id"], user_id="u1") is True

        rows = await docs.list_trashed(limit=10, offset=0, user_id="u1")
        assert {r["id"] for r in rows} == {"lt-first", "lt-second"}
        assert keep["id"] not in {r["id"] for r in rows}
        assert await docs.count_trashed(user_id="u1") == 2

        page = await docs.list_trashed(limit=1, offset=0, user_id="u1")
        assert len(page) == 1
        rest = await docs.list_trashed(limit=1, offset=1, user_id="u1")
        assert {page[0]["id"], rest[0]["id"]} == {"lt-first", "lt-second"}

        # Foreign users see nothing (fail closed).
        assert await docs.list_trashed(limit=10, offset=0, user_id="u2") == []
        assert await docs.count_trashed(user_id="u2") == 0


class TestRestore:
    async def test_restored_repoints_without_touching_relpath(self, repos):
        """§10.6: restore changes ownership/trash fields only; bytes stay put."""
        projects, docs = repos
        _origin, row = await _trashed(docs, projects, sha="dd" * 32, doc_id="rs-1")
        target = await _project(projects, name="T")
        checked: list[str] = []

        async def check(r: dict) -> bool:
            checked.append(r["id"])
            return True

        outcome, restored = await docs.restore(row["id"], target_project_id=target["id"], check_content=check, user_id="u1")
        assert outcome == "restored"
        assert restored["project_id"] == target["id"]
        assert restored["trashed_at"] is None
        assert restored["trash_origin"] is None
        assert restored["stored_relpath"] == row["stored_relpath"]
        # The content check ran (under the lock) before the re-point.
        assert checked == [row["id"]]
        assert await docs.get(row["id"], user_id="u1") is not None
        active = await docs.list_active(target["id"], limit=10, offset=0, user_id="u1")
        assert [r["id"] for r in active] == [row["id"]]

    async def test_restored_into_same_project_it_was_trashed_from(self, repos):
        projects, docs = repos
        origin, row = await _trashed(docs, projects, sha="ee" * 32, doc_id="rs-2")
        outcome, restored = await docs.restore(row["id"], target_project_id=origin["id"], user_id="u1")
        assert outcome == "restored"
        assert restored["project_id"] == origin["id"]

    async def test_merged_when_target_already_has_identical_active_bytes(self, repos):
        projects, docs = repos
        _origin, row = await _trashed(docs, projects, sha="ff" * 32, doc_id="rm-1")
        target = await _project(projects, name="T")
        surviving = await _insert(docs, target["id"], sha="ff" * 32, doc_id="rm-surviving")

        outcome, doc = await docs.restore(row["id"], target_project_id=target["id"], user_id="u1")
        assert outcome == "merged"
        assert doc["id"] == surviving["id"]
        # The trash row is gone; the surviving row is the only one left.
        assert await docs.get(row["id"], include_trashed=True, user_id="u1") is None
        assert await docs.count_active(target["id"], user_id="u1") == 1

    async def test_not_found_for_missing_active_foreign_and_already_restored(self, repos):
        projects, docs = repos
        origin, row = await _trashed(docs, projects, sha="ab" * 32, doc_id="rn-1")

        assert (await docs.restore("missing", target_project_id=origin["id"], user_id="u1"))[0] == "not_found"
        # Foreign source with an owned target: indistinguishable from missing.
        u2_target = await projects.create(name="U2P", user_id="u2")
        assert (await docs.restore(row["id"], target_project_id=u2_target["id"], user_id="u2"))[0] == "not_found"
        # Active (never trashed) source.
        active = await _insert(docs, origin["id"], sha="ac" * 32, doc_id="rn-active")
        assert (await docs.restore(active["id"], target_project_id=origin["id"], user_id="u1"))[0] == "not_found"
        # Already restored once: the second attempt sees trashed_at IS NULL.
        assert (await docs.restore(row["id"], target_project_id=origin["id"], user_id="u1"))[0] == "restored"
        assert (await docs.restore(row["id"], target_project_id=origin["id"], user_id="u1"))[0] == "not_found"

    async def test_no_target_for_missing_foreign_archived_target(self, repos):
        projects, docs = repos
        _origin, row = await _trashed(docs, projects, sha="ad" * 32, doc_id="rt-1")
        foreign = await projects.create(name="F", user_id="u2")
        archived = await _project(projects, name="A")
        await projects.set_status(archived["id"], "archived", user_id="u1")

        assert (await docs.restore(row["id"], target_project_id="missing", user_id="u1"))[0] == "no_target"
        assert (await docs.restore(row["id"], target_project_id=foreign["id"], user_id="u1"))[0] == "no_target"
        assert (await docs.restore(row["id"], target_project_id=archived["id"], user_id="u1"))[0] == "no_target"
        # The source stays trashed through all of it.
        still = await docs.get(row["id"], include_trashed=True, user_id="u1")
        assert still is not None and still["trashed_at"]

    async def test_content_missing_leaves_source_trashed(self, repos):
        """§8.3: a failed content check under the lock rejects the restore."""
        projects, docs = repos
        origin, row = await _trashed(docs, projects, sha="ae" * 32, doc_id="rc-1")

        async def missing(r: dict) -> bool:
            return False

        outcome, doc = await docs.restore(row["id"], target_project_id=origin["id"], check_content=missing, user_id="u1")
        assert outcome == "content_missing"
        assert doc is None
        still = await docs.get(row["id"], include_trashed=True, user_id="u1")
        assert still is not None and still["trashed_at"]

    async def test_merge_verifies_surviving_target_content_under_its_lock(self, repos):
        projects, docs = repos
        _origin, row = await _trashed(docs, projects, sha="af" * 32, doc_id="rc-2")
        target = await _project(projects, name="T")
        surviving = await _insert(docs, target["id"], sha="af" * 32, doc_id="rc-surviving")
        checked: list[str] = []

        async def check(r: dict) -> bool:
            checked.append(r["id"])
            return r["id"] != surviving["id"]  # surviving target content is broken

        outcome, doc = await docs.restore(row["id"], target_project_id=target["id"], check_content=check, user_id="u1")
        assert outcome == "content_missing"
        assert doc is None
        # Source checked first, then the merge candidate; both rows unchanged.
        assert checked == [row["id"], surviving["id"]]
        still = await docs.get(row["id"], include_trashed=True, user_id="u1")
        assert still is not None and still["trashed_at"]
        assert await docs.get(surviving["id"], user_id="u1") is not None

    async def test_concurrent_restore_into_a_project_being_deleted(self, repos):
        """§13: 404 or a clean trash pass — never an untrashed orphan row."""
        projects, docs = repos
        for _ in range(6):
            origin = await _project(projects)
            target = await _project(projects, name="Doomed")
            row = await _insert(docs, origin["id"], sha="ba" * 32, doc_id=f"rd-{target['id'][:6]}")
            assert await docs.trash(row["id"], user_id="u1") is True

            (outcome, _doc), deleted = await asyncio.gather(
                docs.restore(row["id"], target_project_id=target["id"], user_id="u1"),
                projects.delete(target["id"], user_id="u1"),
            )
            assert deleted is True
            final = await docs.get(row["id"], include_trashed=True, user_id="u1")
            assert final is not None and final["trashed_at"]
            if outcome == "no_target":
                assert final["project_id"] == origin["id"]


class TestPurgeCandidates:
    async def test_boundary_at_exactly_retention_days(self, repos):
        """A row trashed exactly ``retention_days`` ago is eligible (the window
        has fully passed); anything younger is not."""
        from datetime import timedelta

        projects, docs = repos
        project = await _project(projects)
        now = datetime.now(UTC)
        old = await _insert(docs, project["id"], sha="ca" * 32, doc_id="pc-old")
        edge = await _insert(docs, project["id"], sha="cb" * 32, doc_id="pc-edge")
        fresh = await _insert(docs, project["id"], sha="cd" * 32, doc_id="pc-fresh")
        active = await _insert(docs, project["id"], sha="ce" * 32, doc_id="pc-active")
        for row in (old, edge, fresh):
            assert await docs.trash(row["id"], user_id="u1") is True
        await _set_trashed_at(old["id"], now - timedelta(days=31))
        await _set_trashed_at(edge["id"], now - timedelta(days=30))
        await _set_trashed_at(fresh["id"], now - timedelta(days=30) + timedelta(seconds=1))

        candidates = await docs.purge_candidates(30, now=now, user_id="u1")
        ids = [c["id"] for c in candidates]
        assert ids == ["pc-old", "pc-edge"]  # oldest first
        assert active["id"] not in ids
        assert await docs.purge_candidates(30, now=now, user_id="u2") == []


class TestPurge:
    async def test_manual_purge_removes_files_hook_then_row(self, repos):
        """Ordering (§8.3): the file hook runs under the lock, before the row
        deletion; the row is gone only after the hook completed."""
        projects, docs = repos
        _origin, row = await _trashed(docs, projects, sha="da" * 32, doc_id="pg-1")
        events: list[str] = []

        async def remove_files(r: dict) -> None:
            # Under the lock the row still exists and is still trashed.
            assert await docs.get(row["id"], include_trashed=True, user_id="u1") is not None
            assert r["id"] == row["id"] and r["stored_relpath"] == row["stored_relpath"]
            events.append("files")

        assert await docs.purge(row["id"], remove_files=remove_files, user_id="u1") is True
        assert events == ["files"]
        assert await docs.get(row["id"], include_trashed=True, user_id="u1") is None

    async def test_purge_rejects_missing_foreign_and_active_rows(self, repos):
        projects, docs = repos
        project = await _project(projects)
        active = await _insert(docs, project["id"], sha="db" * 32, doc_id="pg-active")
        called = False

        async def remove_files(r: dict) -> None:
            nonlocal called
            called = True

        assert await docs.purge("missing", user_id="u1") is False
        assert await docs.purge(active["id"], user_id="u2") is False
        # An active row is not purgeable — and the file hook never runs.
        assert await docs.purge(active["id"], remove_files=remove_files, user_id="u1") is False
        assert called is False
        assert await docs.get(active["id"], user_id="u1") is not None

    async def test_unlink_oserror_retains_retryable_trashed_row(self, repos):
        """§8.3/§11: a non-FileNotFoundError unlink failure rolls the row
        deletion back; the trashed row survives and a retry succeeds."""
        projects, docs = repos
        _origin, row = await _trashed(docs, projects, sha="dc" * 32, doc_id="pg-2")

        async def failing(r: dict) -> None:
            raise OSError("disk full")

        with pytest.raises(OSError):
            await docs.purge(row["id"], remove_files=failing, user_id="u1")
        still = await docs.get(row["id"], include_trashed=True, user_id="u1")
        assert still is not None and still["trashed_at"]

        async def noop(r: dict) -> None:
            return None

        assert await docs.purge(row["id"], remove_files=noop, user_id="u1") is True
        assert await docs.get(row["id"], include_trashed=True, user_id="u1") is None

    async def test_retention_purge_revalidates_selection_under_the_lock(self, repos):
        """§6.1: a candidate restored and re-trashed is NOT purged on its
        former expiry — the selected trash timestamp is revalidated."""
        from datetime import timedelta

        projects, docs = repos
        origin, row = await _trashed(docs, projects, sha="dd" * 32, doc_id="pg-3")
        first = (await docs.get(row["id"], include_trashed=True, user_id="u1"))["trashed_at"]
        cutoff = datetime.now(UTC) - timedelta(days=30)

        # Restored, then re-trashed: the former selection no longer applies.
        assert (await docs.restore(row["id"], target_project_id=origin["id"], user_id="u1"))[0] == "restored"
        assert await docs.trash(row["id"], user_id="u1") is True
        assert await docs.purge(row["id"], retention_cutoff=cutoff, expected_trashed_at=first, user_id="u1") is False
        still = await docs.get(row["id"], include_trashed=True, user_id="u1")
        assert still is not None and still["trashed_at"]

        # A candidate whose trash is younger than the cutoff: refused.
        assert await docs.purge(row["id"], retention_cutoff=cutoff, expected_trashed_at=still["trashed_at"], user_id="u1") is False
        # Matching selection (old enough + same timestamp): purged.
        await _set_trashed_at(row["id"], cutoff - timedelta(days=1))
        current = (await docs.get(row["id"], include_trashed=True, user_id="u1"))["trashed_at"]
        assert await docs.purge(row["id"], retention_cutoff=cutoff, expected_trashed_at=current, user_id="u1") is True
        assert await docs.get(row["id"], include_trashed=True, user_id="u1") is None

    async def test_concurrent_purge_vs_restore_one_wins_loser_404(self, repos):
        """§13: with healthy storage one wins; both lock-acquisition orders
        exercised — purge holds its document lock across unlink and commit,
        restore cannot pass its source-row lock meanwhile."""
        projects, docs = repos
        for order in ("purge_first", "restore_first"):
            origin = await _project(projects)
            target = await _project(projects, name="T")
            row = await _insert(docs, origin["id"], sha="ea" * 32, doc_id=f"cc-{order}")
            assert await docs.trash(row["id"], user_id="u1") is True
            entered = asyncio.Event()
            release = asyncio.Event()

            if order == "purge_first":

                async def remove_files(r: dict) -> None:
                    entered.set()
                    await asyncio.wait_for(release.wait(), 5)

                async def run_restore() -> tuple[str, dict | None]:
                    await entered.wait()
                    task = asyncio.create_task(docs.restore(row["id"], target_project_id=target["id"], user_id="u1"))
                    release.set()
                    return await task

                purged, (outcome, _) = await asyncio.gather(
                    docs.purge(row["id"], remove_files=remove_files, user_id="u1"),
                    run_restore(),
                )
                assert purged is True
                assert outcome == "not_found"
                assert await docs.get(row["id"], include_trashed=True, user_id="u1") is None
            else:

                async def check_content(r: dict) -> bool:
                    entered.set()
                    await asyncio.wait_for(release.wait(), 5)
                    return True

                async def run_purge() -> bool:
                    await entered.wait()
                    task = asyncio.create_task(docs.purge(row["id"], user_id="u1"))
                    release.set()
                    return await task

                (outcome, _), purged = await asyncio.gather(
                    docs.restore(row["id"], target_project_id=target["id"], check_content=check_content, user_id="u1"),
                    run_purge(),
                )
                assert outcome == "restored"
                assert purged is False
                assert await docs.get(row["id"], user_id="u1") is not None


class TestConvertUnderLiveLock:
    async def test_runs_convert_under_the_lock_and_returns_the_row(self, repos):
        projects, docs = repos
        project = await _project(projects)
        row = await _insert(docs, project["id"], sha="cf" * 32, doc_id="cv-ok")
        seen: list[str] = []

        async def convert(r: dict) -> str:
            seen.append(r["id"])
            return "published"

        result = await docs.convert_under_live_lock(row["id"], project_id=project["id"], convert=convert, user_id="u1")
        assert result is not None
        locked_row, value = result
        assert locked_row["id"] == row["id"]
        assert value == "published"
        assert seen == [row["id"]]

    async def test_declines_missing_foreign_trashed_and_sibling_project(self, repos):
        projects, docs = repos
        project = await _project(projects)
        other = await _project(projects, name="O")
        row = await _insert(docs, project["id"], sha="d0" * 32, doc_id="cv-decline")
        trashed_project, trashed = await _trashed(docs, projects, sha="d1" * 32, doc_id="cv-trashed")
        calls: list[str] = []

        async def convert(r: dict) -> None:
            calls.append(r["id"])

        assert await docs.convert_under_live_lock("missing", project_id=project["id"], convert=convert, user_id="u1") is None
        # Foreign owner, sibling project, and trashed rows all decline without
        # ever invoking the conversion callback.
        assert await docs.convert_under_live_lock(row["id"], project_id=project["id"], convert=convert, user_id="u2") is None
        assert await docs.convert_under_live_lock(row["id"], project_id=other["id"], convert=convert, user_id="u1") is None
        assert await docs.convert_under_live_lock(trashed["id"], project_id=trashed_project["id"], convert=convert, user_id="u1") is None
        assert calls == []

    async def test_concurrent_conversion_vs_purge_purge_commits_first(self, repos):
        """§13: purge holds its document lock across unlink and commit; a
        conversion that blocked on the row lock then finds the row gone and
        converts/publishes nothing."""
        projects, docs = repos
        project = await _project(projects)
        row = await _insert(docs, project["id"], sha="e0" * 32, doc_id="cv-purge-first")
        assert await docs.trash(row["id"], user_id="u1") is True
        entered = asyncio.Event()
        release = asyncio.Event()
        calls: list[str] = []

        async def remove_files(r: dict) -> None:
            entered.set()
            await asyncio.wait_for(release.wait(), 5)

        async def convert(r: dict) -> str:
            calls.append(r["id"])
            return "published"

        async def run_conversion() -> tuple[dict, str] | None:
            await entered.wait()
            task = asyncio.create_task(docs.convert_under_live_lock(row["id"], project_id=project["id"], convert=convert, user_id="u1"))
            release.set()
            return await task

        purged, result = await asyncio.gather(
            docs.purge(row["id"], remove_files=remove_files, user_id="u1"),
            run_conversion(),
        )
        assert purged is True
        assert result is None
        assert calls == []

    async def test_concurrent_conversion_vs_trash_conversion_commits_first(self, repos):
        """§13: conversion holds the document lock through the publish; a
        trash arriving meanwhile blocks and then proceeds."""
        projects, docs = repos
        project = await _project(projects)
        row = await _insert(docs, project["id"], sha="e1" * 32, doc_id="cv-conv-first")
        entered = asyncio.Event()
        release = asyncio.Event()

        async def convert(r: dict) -> str:
            entered.set()
            await asyncio.wait_for(release.wait(), 5)
            return "published"

        async def run_trash() -> bool:
            await entered.wait()
            task = asyncio.create_task(docs.trash(row["id"], user_id="u1"))
            release.set()
            return await task

        result, trashed = await asyncio.gather(
            docs.convert_under_live_lock(row["id"], project_id=project["id"], convert=convert, user_id="u1"),
            run_trash(),
        )
        assert result is not None and result[1] == "published"
        assert trashed is True
        assert (await docs.get(row["id"], include_trashed=True, user_id="u1"))["trashed_at"] is not None


class TestLockedOffloadDrain:
    """Cancellation while a row-locked transaction awaits a filesystem
    offload must drain the worker BEFORE the lock unwinds (§6.3/§8.3): the
    lock is never released over in-flight file mutation, so a concurrent
    reader can never validate bytes an abandoned worker is still deleting."""

    async def test_cancelled_purge_drains_removal_before_releasing_the_lock(self, repos):
        import threading

        projects, docs = repos
        project = await _project(projects)
        target = await _project(projects, name="T")
        row = await _insert(docs, project["id"], sha="d9" * 32, doc_id="purge-cancel")
        assert await docs.trash(row["id"], user_id="u1") is True

        entered = threading.Event()
        finish = threading.Event()
        state = {"unlinked": False}

        def slow_unlink() -> None:
            entered.set()
            assert finish.wait(10)
            state["unlinked"] = True

        async def remove_files(r: dict) -> None:
            await asyncio.to_thread(slow_unlink)

        async def check_content(r: dict) -> bool:
            return not state["unlinked"]

        purge_task = asyncio.create_task(docs.purge(row["id"], remove_files=remove_files, user_id="u1"))
        await asyncio.to_thread(entered.wait, 10)
        purge_task.cancel()
        # While the unlink worker is gated, the purge holds its document lock
        # and keeps draining: a restore cannot pass its source-row lock in
        # this window (never validate-then-lose-bytes).
        restore_task = asyncio.create_task(docs.restore(row["id"], target_project_id=target["id"], check_content=check_content, user_id="u1"))
        await asyncio.sleep(0.3)
        assert not purge_task.done()
        assert not restore_task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await purge_task
        # The worker finished before the cancellation unwound the transaction.
        assert state["unlinked"]
        # Coherent final state per the §8.3 retry contract: the purge rolled
        # back (row still trashed) with the bytes gone, so restore surfaces
        # content_missing instead of activating a byteless row.
        outcome, restored = await restore_task
        assert outcome == "content_missing"
        assert restored is None
        still = await docs.get(row["id"], include_trashed=True, user_id="u1")
        assert still is not None and still["trashed_at"] is not None

    async def test_cancelled_conversion_drains_the_worker_before_unlocking(self, repos):
        import threading

        projects, docs = repos
        project = await _project(projects)
        row = await _insert(docs, project["id"], sha="e7" * 32, doc_id="convert-cancel")

        entered = threading.Event()
        finish = threading.Event()
        state = {"published": False}

        def slow_convert() -> None:
            entered.set()
            assert finish.wait(10)
            state["published"] = True

        async def convert(r: dict) -> bool:
            await asyncio.to_thread(slow_convert)
            return True

        convert_task = asyncio.create_task(docs.convert_under_live_lock(row["id"], project_id=project["id"], convert=convert, user_id="u1"))
        await asyncio.to_thread(entered.wait, 10)
        convert_task.cancel()
        # The document lock stays held while the conversion worker drains: a
        # trash blocks on it, so the publish never lands after the lock is
        # gone (the round-2 serialization survives cancellation).
        trash_task = asyncio.create_task(docs.trash(row["id"], user_id="u1"))
        await asyncio.sleep(0.3)
        assert not convert_task.done()
        assert not trash_task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await convert_task
        assert state["published"]
        assert await trash_task is True
