"""Tests for per-user data migration."""

import json
from pathlib import Path

import pytest

from deerflow.config.paths import Paths


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def paths(base_dir: Path) -> Paths:
    return Paths(base_dir)


class TestMigrateThreadDirs:
    def test_moves_thread_to_user_dir(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "threads" / "t1" / "user-data" / "workspace"
        legacy.mkdir(parents=True)
        (legacy / "file.txt").write_text("hello")

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"})

        expected = base_dir / "users" / "alice" / "threads" / "t1" / "user-data" / "workspace" / "file.txt"
        assert expected.exists()
        assert expected.read_text() == "hello"
        assert not (base_dir / "threads" / "t1").exists()

    def test_unowned_thread_goes_to_default(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "threads" / "t2" / "user-data" / "workspace"
        legacy.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={})

        expected = base_dir / "users" / "default" / "threads" / "t2"
        assert expected.exists()

    def test_idempotent_skip_already_migrated(self, base_dir: Path, paths: Paths):
        new_dir = base_dir / "users" / "alice" / "threads" / "t1" / "user-data" / "workspace"
        new_dir.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"})
        assert new_dir.exists()

    def test_conflict_preserved(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "threads" / "t1" / "user-data" / "workspace"
        legacy.mkdir(parents=True)
        (legacy / "old.txt").write_text("old")

        dest = base_dir / "users" / "alice" / "threads" / "t1" / "user-data" / "workspace"
        dest.mkdir(parents=True)
        (dest / "new.txt").write_text("new")

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"})

        assert (dest / "new.txt").read_text() == "new"
        conflicts = base_dir / "migration-conflicts" / "t1"
        assert conflicts.exists()

    def test_cleans_up_empty_legacy_dir(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "threads" / "t1" / "user-data"
        legacy.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        migrate_thread_dirs(paths, thread_owner_map={})

        assert not (base_dir / "threads").exists()

    def test_dry_run_does_not_move(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "threads" / "t1" / "user-data"
        legacy.mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_thread_dirs

        report = migrate_thread_dirs(paths, thread_owner_map={"t1": "alice"}, dry_run=True)

        assert len(report) == 1
        assert (base_dir / "threads" / "t1").exists()  # not moved
        assert not (base_dir / "users" / "alice" / "threads" / "t1").exists()


class TestMigrateMemory:
    def test_moves_global_memory(self, base_dir: Path, paths: Paths):
        legacy_mem = base_dir / "memory.json"
        legacy_mem.write_text(json.dumps({"version": "1.0", "facts": []}))

        from scripts.migrate_user_isolation import migrate_memory

        migrate_memory(paths, user_id="default")

        expected = base_dir / "users" / "default" / "memory.json"
        assert expected.exists()
        assert not legacy_mem.exists()

    def test_skips_if_destination_exists(self, base_dir: Path, paths: Paths):
        legacy_mem = base_dir / "memory.json"
        legacy_mem.write_text(json.dumps({"version": "old"}))

        dest = base_dir / "users" / "default" / "memory.json"
        dest.parent.mkdir(parents=True)
        dest.write_text(json.dumps({"version": "new"}))

        from scripts.migrate_user_isolation import migrate_memory

        migrate_memory(paths, user_id="default")

        assert json.loads(dest.read_text())["version"] == "new"
        assert (base_dir / "memory.legacy.json").exists()

    def test_no_legacy_memory_is_noop(self, base_dir: Path, paths: Paths):
        from scripts.migrate_user_isolation import migrate_memory

        migrate_memory(paths, user_id="default")  # should not raise
