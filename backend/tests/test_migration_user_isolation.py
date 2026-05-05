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


class TestMigrateAgents:
    @staticmethod
    def _seed_legacy_agent(paths: Paths, name: str, *, soul: str = "soul", description: str = "d") -> Path:
        legacy_dir = paths.agents_dir / name
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "config.yaml").write_text(f"name: {name}\ndescription: {description}\n", encoding="utf-8")
        (legacy_dir / "SOUL.md").write_text(soul, encoding="utf-8")
        return legacy_dir

    def test_moves_legacy_into_user_layout(self, base_dir: Path, paths: Paths):
        self._seed_legacy_agent(paths, "agent-a", soul="soul-a")
        self._seed_legacy_agent(paths, "agent-b", soul="soul-b")

        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default")

        assert {entry["agent"] for entry in report} == {"agent-a", "agent-b"}
        for entry in report:
            assert entry["user_id"] == "default"
            assert "moved -> " in entry["action"]

        for name, soul in [("agent-a", "soul-a"), ("agent-b", "soul-b")]:
            dest = paths.user_agent_dir("default", name)
            assert dest.exists(), f"{name} should have moved into the per-user layout"
            assert (dest / "SOUL.md").read_text() == soul

        # Legacy agents/ root is cleaned up once empty.
        assert not paths.agents_dir.exists()

    def test_dry_run_does_not_move(self, base_dir: Path, paths: Paths):
        legacy_dir = self._seed_legacy_agent(paths, "agent-a")

        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default", dry_run=True)

        assert len(report) == 1
        assert legacy_dir.exists(), "dry-run must not touch the filesystem"
        assert not paths.user_agent_dir("default", "agent-a").exists()

    def test_existing_destination_is_treated_as_conflict(self, base_dir: Path, paths: Paths):
        self._seed_legacy_agent(paths, "agent-a", soul="legacy soul")
        dest = paths.user_agent_dir("default", "agent-a")
        dest.mkdir(parents=True)
        (dest / "SOUL.md").write_text("preexisting", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default")

        assert report[0]["action"].startswith("conflict -> ")
        # Per-user destination must be left untouched.
        assert (dest / "SOUL.md").read_text() == "preexisting"
        # Legacy copy lands under migration-conflicts/agents/.
        conflicts_dir = paths.base_dir / "migration-conflicts" / "agents" / "agent-a"
        assert (conflicts_dir / "SOUL.md").read_text() == "legacy soul"

    def test_no_legacy_dir_is_noop(self, base_dir: Path, paths: Paths):
        from scripts.migrate_user_isolation import migrate_agents

        report = migrate_agents(paths, user_id="default")
        assert report == []
