"""Unit tests for report_templates.repository.FileSystemReportTemplateRepository."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from deerflow.report_templates.records import (
    ReportRunRecord,
    new_report_run_id,
    now_iso,
)
from deerflow.report_templates.repository import (
    BuiltinNotWritableError,
    EtagMismatchError,
    FileSystemReportTemplateRepository,
    ImmutablePublishedError,
    RepositoryError,
    Scope,
    TemplateNotFoundError,
    VersionNotFoundError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> FileSystemReportTemplateRepository:
    return FileSystemReportTemplateRepository(
        runtime_root=tmp_path / "runtime",
        builtin_root=tmp_path / "builtin",
    )


@pytest.fixture
def user_scope() -> Scope:
    return Scope.private("user_alice")


SAMPLE_DSL = {
    "dsl_version": "1",
    "name": "demo",
    "display_name": "Demo",
    "form_steps": [
        {
            "id": "scope",
            "title": "S",
            "fields": [{"name": "x", "label": "X", "type": "text"}],
            "next": "generate",
        }
    ],
    "sections": [
        {"id": "overview", "title": "Overview", "component": "markdown", "source": "$.steps.x.y"}
    ],
}

SAMPLE_YAML = "dsl_version: '1'\nname: demo\n# real YAML omitted for brevity\n"


def _create_draft(
    repo: FileSystemReportTemplateRepository,
    scope: Scope = None,
    owner: str = "user_alice",
):
    scope = scope or Scope.private(owner)
    return repo.create_template(
        scope=scope,
        name="demo",
        display_name="Demo",
        owner_user_id=owner,
        tenant_id="tenant_a",
        description="d",
        tags=["t1"],
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_creates_template_file(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        assert rec.id.startswith("tpl_")
        # Files on disk.
        template_path = (
            repo._scope_root(user_scope) / rec.id / "template.json"
        )
        assert template_path.exists()
        on_disk = json.loads(template_path.read_text(encoding="utf-8"))
        assert on_disk["display_name"] == "Demo"
        assert on_disk["status"] == "draft"
        assert on_disk["current_version"] == 0

    def test_writes_index_entry(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        listed = repo.list_templates(user_scope)
        assert len(listed) == 1
        assert listed[0].id == rec.id
        assert listed[0].name == "demo"

    def test_builtin_create_rejected(self, repo):
        with pytest.raises(BuiltinNotWritableError):
            repo.create_template(
                scope=Scope.builtin(),
                name="x",
                display_name="X",
                owner_user_id="u",
                tenant_id="t",
            )

    def test_isolates_by_user(self, repo):
        a = _create_draft(repo, Scope.private("alice"), owner="alice")
        _ = _create_draft(repo, Scope.private("bob"), owner="bob")
        assert len(repo.list_templates(Scope.private("alice"))) == 1
        assert len(repo.list_templates(Scope.private("bob"))) == 1
        assert repo.list_templates(Scope.private("alice"))[0].id == a.id

    def test_isolates_by_tenant(self, repo):
        repo.create_template(
            scope=Scope.tenant("ten_a"),
            name="a",
            display_name="A",
            owner_user_id="u1",
            tenant_id="ten_a",
        )
        repo.create_template(
            scope=Scope.tenant("ten_b"),
            name="b",
            display_name="B",
            owner_user_id="u2",
            tenant_id="ten_b",
        )
        assert len(repo.list_templates(Scope.tenant("ten_a"))) == 1
        assert len(repo.list_templates(Scope.tenant("ten_b"))) == 1


# ---------------------------------------------------------------------------
# Save draft
# ---------------------------------------------------------------------------


class TestSaveDraft:
    def test_writes_working_copy_and_updates_metadata(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        updated = repo.save_draft(
            scope=user_scope,
            template_id=rec.id,
            dsl=SAMPLE_DSL,
            dsl_yaml=SAMPLE_YAML,
            display_name="Updated",
            expected_etag=rec.etag,
        )
        assert updated.display_name == "Updated"
        assert updated.etag != rec.etag

        # v0 working copy exists.
        v0 = repo._version_json(user_scope, rec.id, 0)
        assert v0.exists()
        data = json.loads(v0.read_text(encoding="utf-8"))
        assert data["version"] == 0
        assert data["dsl"]["name"] == "demo"
        assert data["dsl_yaml"] == SAMPLE_YAML
        assert data["checksum"].startswith("sha256:")

    def test_rejects_stale_etag(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        with pytest.raises(EtagMismatchError):
            repo.save_draft(
                scope=user_scope,
                template_id=rec.id,
                dsl=SAMPLE_DSL,
                dsl_yaml=SAMPLE_YAML,
                expected_etag="not_the_real_etag",
            )

    def test_published_template_cannot_be_edited_in_place(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        rec = repo.save_draft(
            scope=user_scope,
            template_id=rec.id,
            dsl=SAMPLE_DSL,
            dsl_yaml=SAMPLE_YAML,
            expected_etag=rec.etag,
        )
        published = repo.publish(
            scope=user_scope,
            template_id=rec.id,
            expected_current_version=0,
        )
        with pytest.raises(ImmutablePublishedError):
            repo.save_draft(
                scope=user_scope,
                template_id=rec.id,
                dsl=SAMPLE_DSL,
                dsl_yaml=SAMPLE_YAML,
                expected_etag=published.etag,
            )

    def test_overwrites_working_copy(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        rec = repo.save_draft(
            scope=user_scope, template_id=rec.id,
            dsl={"dsl_version": "1", "name": "v1"},
            dsl_yaml="dsl_version: '1'\nname: v1\n",
            expected_etag=rec.etag,
        )
        rec = repo.save_draft(
            scope=user_scope, template_id=rec.id,
            dsl={"dsl_version": "1", "name": "v2"},
            dsl_yaml="dsl_version: '1'\nname: v2\n",
            expected_etag=rec.etag,
        )
        v0 = repo._version_json(user_scope, rec.id, 0)
        data = json.loads(v0.read_text(encoding="utf-8"))
        assert data["dsl"]["name"] == "v2"


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class TestPublish:
    def test_publish_creates_immutable_v1(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        rec = repo.save_draft(
            scope=user_scope, template_id=rec.id,
            dsl=SAMPLE_DSL, dsl_yaml=SAMPLE_YAML,
            expected_etag=rec.etag,
        )
        published = repo.publish(
            scope=user_scope,
            template_id=rec.id,
            expected_current_version=0,
            changelog="first release",
        )
        assert published.status == "published"
        assert published.current_version == 1

        v1 = repo.get_version(user_scope, rec.id, 1)
        assert v1.version == 1
        assert v1.changelog == "first release"
        assert v1.dsl_yaml == SAMPLE_YAML
        # listed_versions returns v1 only (v0 is hidden working copy)
        assert repo.list_versions(user_scope, rec.id) == [1]

    def test_publish_with_wrong_current_version_rejected(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        rec = repo.save_draft(
            scope=user_scope, template_id=rec.id,
            dsl=SAMPLE_DSL, dsl_yaml=SAMPLE_YAML,
            expected_etag=rec.etag,
        )
        with pytest.raises(EtagMismatchError):
            repo.publish(
                scope=user_scope,
                template_id=rec.id,
                expected_current_version=99,
            )

    def test_publish_without_working_copy_fails(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        with pytest.raises(RepositoryError, match="no working draft"):
            repo.publish(scope=user_scope, template_id=rec.id, expected_current_version=0)

    def test_two_publishes_increment_version(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        rec = repo.save_draft(
            scope=user_scope, template_id=rec.id,
            dsl=SAMPLE_DSL, dsl_yaml=SAMPLE_YAML,
            expected_etag=rec.etag,
        )
        rec = repo.publish(scope=user_scope, template_id=rec.id, expected_current_version=0)
        # In real flow there would be a "start_new_draft" step here. For the
        # MVP test we just inspect that publishing twice would need new save_draft;
        # publishing again without a new draft is a no-op (uses existing v0 which
        # was overwritten by publish? no — v0 stays intact). Test idempotent error path:
        rec = repo.publish(scope=user_scope, template_id=rec.id, expected_current_version=1)
        assert rec.current_version == 2
        assert repo.list_versions(user_scope, rec.id) == [1, 2]


# ---------------------------------------------------------------------------
# Fork
# ---------------------------------------------------------------------------


class TestFork:
    def test_fork_creates_new_draft_with_provenance(self, repo, user_scope):
        # Build a published source.
        src = _create_draft(repo, user_scope)
        src = repo.save_draft(
            scope=user_scope, template_id=src.id,
            dsl=SAMPLE_DSL, dsl_yaml=SAMPLE_YAML,
            expected_etag=src.etag,
        )
        src = repo.publish(scope=user_scope, template_id=src.id, expected_current_version=0)

        # Bob forks alice's template.
        forked = repo.fork(
            source_scope=user_scope,
            source_template_id=src.id,
            source_version=1,
            target_scope=Scope.private("bob"),
            target_owner_user_id="bob",
            target_tenant_id="tenant_a",
            new_name="bob_demo",
            new_display_name="Bob Demo",
        )
        assert forked.owner_user_id == "bob"
        assert forked.status == "draft"
        assert forked.current_version == 0

        # v0 working copy carries source_template_id / version.
        v0 = repo.get_version(Scope.private("bob"), forked.id, 0)
        assert v0.source_template_id == src.id
        assert v0.source_template_version == 1
        assert v0.dsl == SAMPLE_DSL

    def test_fork_target_cannot_be_builtin(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        rec = repo.save_draft(
            scope=user_scope, template_id=rec.id,
            dsl=SAMPLE_DSL, dsl_yaml=SAMPLE_YAML,
            expected_etag=rec.etag,
        )
        rec = repo.publish(scope=user_scope, template_id=rec.id, expected_current_version=0)
        with pytest.raises(BuiltinNotWritableError):
            repo.fork(
                source_scope=user_scope,
                source_template_id=rec.id,
                source_version=1,
                target_scope=Scope.builtin(),
                target_owner_user_id="u",
                target_tenant_id="t",
                new_name="n",
                new_display_name="N",
            )

    def test_fork_missing_source_version_raises(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        with pytest.raises(VersionNotFoundError):
            repo.fork(
                source_scope=user_scope,
                source_template_id=rec.id,
                source_version=99,
                target_scope=Scope.private("bob"),
                target_owner_user_id="bob",
                target_tenant_id="tenant_a",
                new_name="n",
                new_display_name="N",
            )


# ---------------------------------------------------------------------------
# Archive / Delete
# ---------------------------------------------------------------------------


class TestArchiveDelete:
    def test_archive_sets_status(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        archived = repo.archive(
            scope=user_scope, template_id=rec.id, expected_etag=rec.etag
        )
        assert archived.status == "archived"

    def test_delete_removes_directory_and_index(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        repo.delete(scope=user_scope, template_id=rec.id, expected_etag=rec.etag)
        with pytest.raises(TemplateNotFoundError):
            repo.get_template(user_scope, rec.id)
        assert repo.list_templates(user_scope) == []
        # Directory gone.
        assert not (repo._scope_root(user_scope) / rec.id).exists()

    def test_delete_rejects_bad_etag(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        with pytest.raises(EtagMismatchError):
            repo.delete(scope=user_scope, template_id=rec.id, expected_etag="wrong")


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_invalid_template_id_rejected(self, repo, user_scope):
        # Even the read path rejects malformed IDs before touching the FS.
        with pytest.raises(ValueError):
            repo.get_template(user_scope, "../escape")

    def test_invalid_user_id_rejected(self, repo):
        with pytest.raises(ValueError):
            Scope.private("../escape")

    def test_invalid_tenant_id_rejected(self, repo):
        with pytest.raises(ValueError):
            Scope.tenant("../escape")


# ---------------------------------------------------------------------------
# Concurrent writes
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_save_drafts_serialised(self, repo, user_scope):
        """Two threads racing save_draft on the same template — both succeed
        but only one wins per etag, so we expect at least one EtagMismatchError."""
        rec = _create_draft(repo, user_scope)
        errors: list[BaseException] = []
        successes: list[str] = []

        def worker(label: str, etag: str):
            try:
                updated = repo.save_draft(
                    scope=user_scope,
                    template_id=rec.id,
                    dsl=SAMPLE_DSL,
                    dsl_yaml=f"# {label}\n",
                    display_name=label,
                    expected_etag=etag,
                )
                successes.append(updated.display_name)
            except EtagMismatchError as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=("A", rec.etag))
        t2 = threading.Thread(target=worker, args=("B", rec.etag))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(successes) == 1
        assert len(errors) == 1
        # After the race, the surviving on-disk file must be intact and match
        # the successful write.
        final = repo.get_template(user_scope, rec.id)
        assert final.display_name in {"A", "B"}
        assert final.display_name == successes[0]


# ---------------------------------------------------------------------------
# Report runs
# ---------------------------------------------------------------------------


class TestReportRuns:
    def test_create_and_list_runs(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        run = ReportRunRecord(
            id=new_report_run_id(),
            template_id=rec.id,
            template_version=1,
            thread_id="thread-1",
            run_id="run-1",
            user_id="user_alice",
            tenant_id="tenant_a",
            created_at=now_iso(),
        )
        repo.create_report_run(scope=user_scope, record=run)
        listed = repo.list_report_runs(user_scope, rec.id)
        assert len(listed) == 1
        assert listed[0].id == run.id

    def test_duplicate_run_id_rejected(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        run = ReportRunRecord(
            id=new_report_run_id(),
            template_id=rec.id,
            thread_id="t",
            run_id="r",
            user_id="user_alice",
            tenant_id="tenant_a",
            created_at=now_iso(),
        )
        repo.create_report_run(scope=user_scope, record=run)
        with pytest.raises(RepositoryError, match="already exists"):
            repo.create_report_run(scope=user_scope, record=run)

    def test_update_overwrites_existing_run(self, repo, user_scope):
        rec = _create_draft(repo, user_scope)
        run = ReportRunRecord(
            id=new_report_run_id(),
            template_id=rec.id,
            thread_id="t",
            run_id="r",
            user_id="user_alice",
            tenant_id="tenant_a",
            created_at=now_iso(),
        )
        repo.create_report_run(scope=user_scope, record=run)
        updated = run.model_copy(update={"status": "succeeded"})
        repo.update_report_run(scope=user_scope, record=updated)
        got = repo.get_report_run(user_scope, rec.id, run.id)
        assert got is not None and got.status == "succeeded"
