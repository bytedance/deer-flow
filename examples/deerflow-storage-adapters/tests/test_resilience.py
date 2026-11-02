from dataclasses import replace

import pytest
from deerflow_storage import Database, DatabaseConfig, EngineOptions
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, OperationalError


@pytest.mark.parametrize(
    "changes",
    [
        {"pool_size": 0},
        {"pool_size": True},
        {"max_overflow": -1},
        {"read_timeout": float("inf")},
        {"write_timeout": float("nan")},
        {"connect_timeout": 0},
        {"sqlite_busy_timeout": -1},
        {"sqlite_wal": "yes"},
    ],
)
def test_invalid_connection_budgets_fail_early(changes):
    with pytest.raises(ValueError):
        replace(EngineOptions(), **changes)


def test_sqlite_pragmas_apply_to_every_connection_and_foreign_keys_are_enforced(tmp_path):
    metadata = MetaData()
    Table("parent", metadata, Column("id", Integer, primary_key=True))
    child = Table("child", metadata, Column("id", Integer, primary_key=True), Column("parent_id", ForeignKey("parent.id")))
    options = EngineOptions(sqlite_busy_timeout=0.2)
    db = Database(DatabaseConfig("sqlite", URL.create("sqlite", database=str(tmp_path / "fk.db")), options), initialize=metadata.create_all)
    try:
        with db.engine.connect() as first, db.engine.connect() as second:
            for connection in (first, second):
                assert connection.scalar(text("PRAGMA foreign_keys")) == 1
                assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
                assert connection.scalar(text("PRAGMA busy_timeout")) == 200
                assert connection.scalar(text("PRAGMA synchronous")) == 2
        with pytest.raises(IntegrityError):
            with db.transaction() as session:
                session.execute(child.insert().values(id=1, parent_id=999))
    finally:
        db.dispose()


def test_sqlite_writer_contention_is_bounded_and_reader_can_continue(tmp_path):
    table = Table("record", MetaData(), Column("id", Integer, primary_key=True))
    db = Database(DatabaseConfig("sqlite", URL.create("sqlite", database=str(tmp_path / "locks.db")), EngineOptions(sqlite_busy_timeout=0.05)), initialize=table.metadata.create_all)
    try:
        with db.transaction() as session:
            session.execute(table.insert().values(id=1))
        with db.session() as writer:
            writer.execute(table.insert().values(id=2))
            with db.session() as reader:
                assert reader.scalar(text("SELECT COUNT(*) FROM record")) == 1
            with pytest.raises(OperationalError, match="locked"):
                with db.transaction() as contender:
                    contender.execute(table.insert().values(id=3))
            writer.rollback()
        with db.transaction() as session:
            session.execute(table.insert().values(id=3))
        with db.session() as session:
            assert session.scalar(text("SELECT COUNT(*) FROM record")) == 2
    finally:
        db.dispose()
