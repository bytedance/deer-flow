"""Upgrade/downgrade preserves project instructions and initializes no facts."""

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_project_memory_upgrade_and_downgrade(tmp_path):
    migration = importlib.import_module("deerflow.persistence.migrations.versions.0053_project_memory")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE projects (id TEXT PRIMARY KEY, instructions TEXT)"))
            conn.execute(text("INSERT INTO projects VALUES ('p1', 'Keep this instruction')"))
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                migration.upgrade()
                assert conn.execute(text("SELECT instructions, memory FROM projects")).one() == ("Keep this instruction", None)
                migration.downgrade()
                assert "memory" not in {c["name"] for c in inspect(conn).get_columns("projects")}
                assert conn.execute(text("SELECT instructions FROM projects")).scalar_one() == "Keep this instruction"
                migration.upgrade()
    finally:
        engine.dispose()
