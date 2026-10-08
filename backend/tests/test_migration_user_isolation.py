"""Tests for per-user data migration."""

import json
import logging
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from deerflow.config.database_config import DatabaseConfig
from deerflow.config.paths import Paths
from deerflow.persistence.base import Base
from deerflow.persistence.thread_meta.model import ThreadMetaRow


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


class TestMigrateSkills:
    @staticmethod
    def _seed_legacy_skill(base_dir: Path, name: str, *, content: str = "skill doc") -> Path:
        skill_dir = base_dir / "skills" / "custom" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        return skill_dir

    def test_moves_legacy_into_user_layout(self, base_dir: Path, paths: Paths):
        self._seed_legacy_skill(base_dir, "my-skill", content="legacy skill")
        (base_dir / "skills" / "public" / "bootstrap").mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default")

        assert len(report) == 1
        assert report[0]["skill"] == "my-skill"
        assert "moved -> " in report[0]["action"]

        dest = paths.user_custom_skills_dir("default") / "my-skill" / "SKILL.md"
        assert dest.exists()
        assert dest.read_text() == "legacy skill"
        # Legacy custom dir cleaned up
        assert not (base_dir / "skills" / "custom").exists()
        # But skills/ parent survives (public/ still in use)
        assert (base_dir / "skills" / "public").exists()

    def test_dry_run_does_not_move(self, base_dir: Path, paths: Paths):
        legacy_dir = self._seed_legacy_skill(base_dir, "my-skill")

        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default", dry_run=True)

        assert len(report) == 1
        assert legacy_dir.exists(), "dry-run must not touch the filesystem"
        assert not (paths.user_custom_skills_dir("default") / "my-skill").exists()

    def test_existing_destination_is_conflict(self, base_dir: Path, paths: Paths):
        self._seed_legacy_skill(base_dir, "my-skill", content="legacy")
        dest = paths.user_custom_skills_dir("default") / "my-skill"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("preexisting", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default")

        assert report[0]["action"].startswith("conflict -> ")
        assert (dest / "SKILL.md").read_text() == "preexisting"
        conflicts_dir = paths.base_dir / "migration-conflicts" / "skills" / "my-skill"
        assert (conflicts_dir / "SKILL.md").read_text() == "legacy"

    def test_no_legacy_dir_is_noop(self, base_dir: Path, paths: Paths):
        from scripts.migrate_user_isolation import migrate_skills

        report = migrate_skills(paths, user_id="default")
        assert report == []

    def test_migrates_history_dir(self, base_dir: Path, paths: Paths):
        history_dir = base_dir / "skills" / "custom" / ".history"
        history_dir.mkdir(parents=True)
        (history_dir / "log.json").write_text("[]", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_skills

        migrate_skills(paths, user_id="default")

        dest_history = paths.user_custom_skills_dir("default") / ".history" / "log.json"
        assert dest_history.exists()
        assert not history_dir.exists()

    def test_skills_parent_dir_not_deleted_even_if_custom_empty(self, base_dir: Path, paths: Paths):
        """skills/ parent must NOT be deleted — public/ may still be in use."""
        # Create only custom dir (empty), public dir with content
        (base_dir / "skills" / "custom").mkdir(parents=True)
        (base_dir / "skills" / "public" / "bootstrap").mkdir(parents=True)

        from scripts.migrate_user_isolation import migrate_skills

        migrate_skills(paths, user_id="default")

        # custom/ cleaned up (was empty), but skills/ survives
        assert not (base_dir / "skills" / "custom").exists()
        assert (base_dir / "skills").exists()
        assert (base_dir / "skills" / "public").exists()


class TestMigrateUserProfile:
    def test_moves_global_user_md(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "USER.md"
        legacy.write_text("# About me\n", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_user_profile

        migrate_user_profile(paths, user_id="default")

        expected = base_dir / "users" / "default" / "USER.md"
        assert expected.read_text(encoding="utf-8") == "# About me\n"
        assert not legacy.exists()

    def test_conflict_renames_legacy_and_keeps_destination(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "USER.md"
        legacy.write_text("# legacy\n", encoding="utf-8")

        dest = base_dir / "users" / "default" / "USER.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("# current\n", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_user_profile

        migrate_user_profile(paths, user_id="default")

        # The per-user copy wins; the legacy global file is preserved aside
        # instead of silently overwritten.
        assert dest.read_text(encoding="utf-8") == "# current\n"
        assert (base_dir / "USER.legacy.md").read_text(encoding="utf-8") == "# legacy\n"

    def test_no_legacy_user_md_is_noop(self, base_dir: Path, paths: Paths):
        from scripts.migrate_user_isolation import migrate_user_profile

        migrate_user_profile(paths, user_id="default")  # should not raise

    def test_dry_run_moves_nothing(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "USER.md"
        legacy.write_text("# About me\n", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_user_profile

        migrate_user_profile(paths, user_id="default", dry_run=True)

        assert legacy.exists()
        assert not (base_dir / "users" / "default" / "USER.md").exists()

    def test_dry_run_conflict_renames_nothing(self, base_dir: Path, paths: Paths):
        legacy = base_dir / "USER.md"
        legacy.write_text("# legacy\n", encoding="utf-8")
        dest = base_dir / "users" / "default" / "USER.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("# current\n", encoding="utf-8")

        from scripts.migrate_user_isolation import migrate_user_profile

        migrate_user_profile(paths, user_id="default", dry_run=True)

        assert not (base_dir / "USER.legacy.md").exists()
        assert dest.read_text(encoding="utf-8") == "# current\n"
        assert legacy.exists()


def _write_thread_owners(database: DatabaseConfig, owners: dict[str, str | None]) -> None:
    if database.backend == "sqlite":
        Path(database.sqlite_dir).mkdir(parents=True, exist_ok=True)
    engine = create_engine(database.app_sync_sqlalchemy_url)
    try:
        Base.metadata.create_all(engine, tables=[ThreadMetaRow.__table__])
        with engine.begin() as conn:
            conn.execute(ThreadMetaRow.__table__.insert(), [{"thread_id": thread_id, "user_id": user_id} for thread_id, user_id in owners.items()])
    finally:
        engine.dispose()


def _run_migration(monkeypatch, base_dir: Path, database: DatabaseConfig, *argv: str) -> int:
    import scripts.migrate_user_isolation as migration

    monkeypatch.setattr(migration, "get_paths", lambda: Paths(base_dir))
    monkeypatch.setattr(migration, "get_app_config", lambda: SimpleNamespace(database=database))
    monkeypatch.setattr(sys, "argv", ["migrate_user_isolation", *argv])
    return migration.main()


def _make_legacy_threads(base_dir: Path, *thread_ids: str) -> None:
    for thread_id in thread_ids:
        (base_dir / "threads" / thread_id / "user-data").mkdir(parents=True)


class TestThreadOwnersFromDatabase:
    """``main()`` reads owners from the Gateway's configured database, or stops."""

    def test_threads_follow_owners_in_configured_sqlite_database(self, base_dir: Path, monkeypatch):
        # sqlite_dir is deliberately outside base_dir: the owner map must come
        # from the configured database, not from a path guessed under base_dir.
        database = DatabaseConfig(backend="sqlite", sqlite_dir=str(base_dir.parent / "db"))
        _write_thread_owners(database, {"t-alice": "alice", "t-bob": "bob", "t-anon": None})
        _make_legacy_threads(base_dir, "t-alice", "t-bob", "t-anon")

        assert _run_migration(monkeypatch, base_dir, database) == 0

        assert (base_dir / "users" / "alice" / "threads" / "t-alice").is_dir()
        assert (base_dir / "users" / "bob" / "threads" / "t-bob").is_dir()
        assert (base_dir / "users" / "default" / "threads" / "t-anon").is_dir()
        assert not (base_dir / "threads").exists()

    @pytest.mark.parametrize("argv", [(), ("--dry-run",)])
    def test_missing_sqlite_database_stops_before_moving_anything(self, base_dir: Path, monkeypatch, argv):
        database = DatabaseConfig(backend="sqlite", sqlite_dir=str(base_dir / "data"))
        # The directory exists, so a careless connect would create the file.
        Path(database.sqlite_dir).mkdir()
        _make_legacy_threads(base_dir, "t-alice")
        (base_dir / "memory.json").write_text("{}", encoding="utf-8")

        assert _run_migration(monkeypatch, base_dir, database, *argv) == 1

        assert (base_dir / "threads" / "t-alice").is_dir()
        assert (base_dir / "memory.json").exists()
        assert not (base_dir / "users").exists()
        # The lookup must not create the database it failed to find.
        assert not Path(database.sqlite_path).exists()

    def test_unreadable_threads_meta_stops_before_moving_anything(self, base_dir: Path, monkeypatch):
        database = DatabaseConfig(backend="sqlite", sqlite_dir=str(base_dir / "data"))
        Path(database.sqlite_dir).mkdir()
        sqlite3.connect(database.sqlite_path).close()  # a database without threads_meta
        _make_legacy_threads(base_dir, "t-alice")

        assert _run_migration(monkeypatch, base_dir, database) == 1

        assert (base_dir / "threads" / "t-alice").is_dir()
        assert not (base_dir / "users").exists()

    def test_memory_backend_stops_before_moving_anything(self, base_dir: Path, monkeypatch):
        _make_legacy_threads(base_dir, "t-alice")

        assert _run_migration(monkeypatch, base_dir, DatabaseConfig(backend="memory")) == 1

        assert (base_dir / "threads" / "t-alice").is_dir()
        assert not (base_dir / "users").exists()

    def test_missing_postgres_driver_stops_before_moving_anything(self, base_dir: Path, monkeypatch):
        def _no_driver(*_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'psycopg'")

        monkeypatch.setattr("sqlalchemy.create_engine", _no_driver)
        database = DatabaseConfig(backend="postgres", postgres_url="postgresql://user@localhost/deerflow")
        _make_legacy_threads(base_dir, "t-alice")

        assert _run_migration(monkeypatch, base_dir, database) == 1

        assert (base_dir / "threads" / "t-alice").is_dir()

    def test_unusable_database_url_stops_before_moving_anything(self, base_dir: Path, monkeypatch, caplog):
        # An unset $DATABASE_URL leaves postgres_url empty; create_engine raises
        # ArgumentError, which must get the same handling as the other failures.
        database = DatabaseConfig(backend="postgres", postgres_url="")
        _make_legacy_threads(base_dir, "t-alice")

        with caplog.at_level(logging.ERROR, logger="scripts.migrate_user_isolation"):
            assert _run_migration(monkeypatch, base_dir, database) == 1

        assert (base_dir / "threads" / "t-alice").is_dir()
        assert "Nothing was migrated." in caplog.text

    def test_rerun_recovers_threads_moved_back_from_default(self, base_dir: Path, monkeypatch):
        # Documented recovery for installs the pre-fix script sent to default:
        # move the owned threads back to threads/ and run the script again.
        database = DatabaseConfig(backend="sqlite", sqlite_dir=str(base_dir / "data"))
        _write_thread_owners(database, {"t-alice": "alice", "t-bob": "bob"})
        _make_legacy_threads(base_dir, "t-alice", "t-bob")
        for thread_id in ("t-alice", "t-bob"):
            (base_dir / "threads" / thread_id / "user-data" / "legacy.txt").write_text(thread_id, encoding="utf-8")
        # bob kept using the thread after the bad migration.
        newer = base_dir / "users" / "bob" / "threads" / "t-bob" / "user-data"
        newer.mkdir(parents=True)
        (newer / "newer.txt").write_text("newer", encoding="utf-8")

        assert _run_migration(monkeypatch, base_dir, database) == 0

        assert (base_dir / "users" / "alice" / "threads" / "t-alice" / "user-data" / "legacy.txt").read_text(encoding="utf-8") == "t-alice"
        # An existing destination is never overwritten; the old copy is set aside.
        assert (newer / "newer.txt").read_text(encoding="utf-8") == "newer"
        assert not (newer / "legacy.txt").exists()
        assert (base_dir / "migration-conflicts" / "t-bob" / "user-data" / "legacy.txt").read_text(encoding="utf-8") == "t-bob"

    def test_allow_missing_thread_owners_assigns_default(self, base_dir: Path, monkeypatch):
        database = DatabaseConfig(backend="sqlite", sqlite_dir=str(base_dir / "data"))
        _make_legacy_threads(base_dir, "t-legacy")

        assert _run_migration(monkeypatch, base_dir, database, "--allow-missing-thread-owners") == 0

        assert (base_dir / "users" / "default" / "threads" / "t-legacy").is_dir()

    def test_owner_lookup_is_skipped_without_legacy_threads(self, base_dir: Path, monkeypatch):
        import scripts.migrate_user_isolation as migration

        def _unexpected_config():
            raise AssertionError("no legacy threads, so the database must not be consulted")

        (base_dir / "memory.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(migration, "get_paths", lambda: Paths(base_dir))
        monkeypatch.setattr(migration, "get_app_config", _unexpected_config)
        monkeypatch.setattr(sys, "argv", ["migrate_user_isolation"])

        assert migration.main() == 0

        assert (base_dir / "users" / "default" / "memory.json").exists()

    def test_threads_follow_owners_in_configured_postgres_schema(self, base_dir: Path, monkeypatch):
        url = os.getenv("DEERFLOW_TEST_POSTGRES_URL") or os.getenv("TEST_POSTGRES_URI")
        if not url:
            pytest.skip("set TEST_POSTGRES_URI or DEERFLOW_TEST_POSTGRES_URL to run live PostgreSQL tests")
        psycopg = pytest.importorskip("psycopg")
        url = url.replace("postgresql+asyncpg://", "postgresql://")
        schema = f"migrate_owners_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(f'CREATE SCHEMA "{schema}"')
            try:
                database = DatabaseConfig(backend="postgres", postgres_url=url, postgres_schema=schema)
                _write_thread_owners(database, {"t-alice": "alice"})
                _make_legacy_threads(base_dir, "t-alice", "t-anon")

                assert _run_migration(monkeypatch, base_dir, database) == 0

                assert (base_dir / "users" / "alice" / "threads" / "t-alice").is_dir()
                assert (base_dir / "users" / "default" / "threads" / "t-anon").is_dir()
            finally:
                admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
