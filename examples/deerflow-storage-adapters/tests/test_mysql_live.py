"""Opt-in real MySQL checks using a disposable database supplied by the caller."""

import os
import uuid

import pytest
from deerflow_storage import Database, DatabaseConfig, EngineOptions
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text
from sqlalchemy.exc import DBAPIError, TimeoutError


def mysql_url():
    url = os.getenv("STORAGE_TEST_MYSQL_URL")
    if not url:
        pytest.skip("Set STORAGE_TEST_MYSQL_URL to a disposable MySQL database")
    return url


@pytest.mark.mysql
def test_mysql_pool_exhaustion_recovers_after_connection_returned():
    db = Database(DatabaseConfig("mysql", mysql_url(), EngineOptions(pool_size=1, max_overflow=0, pool_timeout=0.05)))
    try:
        with db.engine.connect() as held:
            assert held.scalar(text("SELECT 1")) == 1
            with pytest.raises(TimeoutError):
                db.engine.connect()
        with db.session() as session:
            assert session.scalar(text("SELECT 1")) == 1
    finally:
        db.dispose()


@pytest.mark.mysql
def test_mysql_read_timeout_invalidates_connection_and_next_session_recovers():
    db = Database(DatabaseConfig("mysql", mysql_url(), EngineOptions(read_timeout=0.1, write_timeout=0.5)))
    try:
        with pytest.raises(DBAPIError) as error:
            with db.session() as session:
                session.execute(text("SELECT SLEEP(1)"))
        assert error.value.connection_invalidated
        with db.session() as session:
            assert session.scalar(text("SELECT 1")) == 1
    finally:
        db.dispose()


@pytest.mark.mysql
def test_mysql_dead_idle_connection_is_replaced_by_pre_ping():
    db = Database(DatabaseConfig("mysql", mysql_url()))
    try:
        with db.engine.connect() as controller:
            with db.engine.connect() as victim:
                connection_id = int(victim.scalar(text("SELECT CONNECTION_ID()")))
            controller.execute(text(f"KILL CONNECTION {connection_id}"))
        with db.session() as session:
            assert session.scalar(text("SELECT 1")) == 1
    finally:
        db.dispose()


@pytest.mark.mysql
def test_mysql_transaction_upsert_and_rollback():
    url = os.getenv("STORAGE_TEST_MYSQL_URL")
    if not url:
        pytest.skip("Set STORAGE_TEST_MYSQL_URL to a disposable MySQL database")
    table = Table("storage_test_" + uuid.uuid4().hex, MetaData(), Column("id", Integer, primary_key=True), Column("value", String(40)))
    db = Database(DatabaseConfig("mysql", url), initialize=table.metadata.create_all)
    engine = None
    try:
        engine = db.engine
        with db.transaction() as session:
            session.execute(db.upsert(table, {"id": 1, "value": "before"}, {"value": "before"}))
            session.execute(db.upsert(table, {"id": 1, "value": "after"}, {"value": "after"}))
        with pytest.raises(RuntimeError):
            with db.transaction() as session:
                session.execute(table.insert().values(id=2, value="rollback"))
                raise RuntimeError("test rollback")
        with db.session() as session:
            assert session.execute(select(table)).all() == [(1, "after")]
    finally:
        # Only this test's random table is removed; no application metadata is imported.
        try:
            if engine is not None:
                table.drop(engine, checkfirst=True)
        finally:
            db.dispose()
