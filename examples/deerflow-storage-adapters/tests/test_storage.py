"""Schema-free adapter tests. No application modules or real credentials are required."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from deerflow_storage import Database, DatabaseConfig, MySQLProvider, ProviderRegistry, SQLiteProvider
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import URL


@pytest.fixture
def records():
    metadata = MetaData()
    return Table("example_record", metadata, Column("id", Integer, primary_key=True), Column("value", String(40)))


@pytest.fixture
def database(tmp_path, records):
    db = Database(DatabaseConfig("sqlite", URL.create("sqlite", database=str(tmp_path / "nested/store.db"))), initialize=records.metadata.create_all)
    yield db
    db.dispose()


def test_transaction_commits_and_rolls_back(database, records):
    with database.transaction() as session:
        session.execute(records.insert().values(id=1, value="committed"))
    with pytest.raises(ValueError):
        with database.transaction() as session:
            session.execute(records.insert().values(id=2, value="rolled back"))
            raise ValueError("application failure")
    with database.session() as session:
        assert session.execute(select(records)).all() == [(1, "committed")]


def test_plain_session_does_not_commit(database, records):
    with database.session() as session:
        session.execute(records.insert().values(id=1, value="not committed"))
    with database.session() as session:
        assert session.execute(select(records)).all() == []


def test_composite_primary_key_upsert(tmp_path):
    table = Table("setting", MetaData(), Column("owner", String, primary_key=True), Column("key", String, primary_key=True), Column("value", String))
    db = Database(DatabaseConfig("sqlite", URL.create("sqlite", database=str(tmp_path / "settings.db"))), initialize=table.metadata.create_all)
    try:
        with db.transaction() as session:
            for value in ("before", "after"):
                session.execute(db.upsert(table, {"owner": "a", "key": "x", "value": value}, {"value": value}))
            session.execute(db.upsert(table, {"owner": "b", "key": "x", "value": "other"}, {"value": "other"}))
        with db.session() as session:
            assert session.execute(select(table).order_by(table.c.owner)).all() == [("a", "x", "after"), ("b", "x", "other")]
    finally:
        db.dispose()


@pytest.mark.parametrize("backend,url", [("mysql", "sqlite:///local.db"), ("sqlite", "mysql://a:b@host/db"), ("mysql", "mysql://a:b@host"), ("sqlite", "sqlite+aiosqlite:///local.db"), ("unknown", "sqlite://")])
def test_invalid_configuration_never_falls_back(backend, url):
    with pytest.raises(ValueError):
        Database(DatabaseConfig(backend, url))


def test_secrets_not_in_configuration_repr_or_parse_error():
    config = DatabaseConfig("mysql", "mysql://user:private-token@host/db")
    assert "private-token" not in repr(config)
    with pytest.raises(ValueError) as exc:
        Database(DatabaseConfig("mysql", "private-token"))
    assert "private-token" not in str(exc.value)


def test_mysql_url_keeps_special_password_and_utf8mb4():
    url = MySQLProvider().url(URL.create("mysql", username="test", password="a@b:/#?&", host="localhost", database="example"))
    assert url.password == "a@b:/#?&"
    assert url.drivername == "mysql+pymysql"
    assert url.query["charset"] == "utf8mb4"


def test_mysql_upsert_compiles_without_mysql_driver_connection(records):
    db = Database(DatabaseConfig("mysql", "mysql://test:test@localhost/example"))
    statement = db.upsert(records, {"id": 1, "value": "before"}, {"value": "after"})
    assert "ON DUPLICATE KEY UPDATE" in str(statement.compile(dialect=mysql.dialect()))
    db.dispose()


def test_custom_provider_owns_upsert_and_registry_isolation(database, records):
    class CustomProvider(SQLiteProvider):
        name = "custom"

        def upsert(self, table, values, updates):
            return table.insert().values(**values)

    registry = ProviderRegistry()
    registry.register(CustomProvider())
    with pytest.raises(ValueError):
        registry.register(CustomProvider())
    with pytest.raises(ValueError):
        ProviderRegistry().get("custom")
    db = Database(DatabaseConfig("custom", "sqlite://"), registry=registry)
    assert "ON CONFLICT" not in str(db.upsert(records, {"id": 1}, {"value": "x"}))
    db.dispose()


def test_lazy_initializer_runs_once_with_concurrent_callers(tmp_path):
    calls = []

    def initialize(engine):
        calls.append(engine)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE initialized (id INTEGER)"))

    db = Database(DatabaseConfig("sqlite", URL.create("sqlite", database=str(tmp_path / "parallel.db"))), initialize=initialize)
    assert calls == []
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            engines = list(executor.map(lambda _: db.engine, range(16)))
        assert len(calls) == 1
        assert all(engine is engines[0] for engine in engines)
    finally:
        db.dispose()


def test_failed_initializer_disposes_engine_and_allows_retry(tmp_path, monkeypatch):
    attempts, disposed = [], []
    registry = ProviderRegistry()
    adapter = registry.get("sqlite")
    original = adapter.engine

    def make_engine(url, **kwargs):
        engine = original(url, **kwargs)
        original_dispose = engine.dispose

        def dispose():
            disposed.append(engine)
            original_dispose()

        monkeypatch.setattr(engine, "dispose", dispose)
        return engine

    monkeypatch.setattr(adapter, "engine", make_engine)

    def initialize(engine):
        attempts.append(engine)
        if len(attempts) == 1:
            raise RuntimeError("temporary initialization failure")

    db = Database(DatabaseConfig("sqlite", URL.create("sqlite", database=str(tmp_path / "retry.db"))), registry=registry, initialize=initialize)
    with pytest.raises(RuntimeError, match="temporary"):
        db.session()
    assert disposed == [attempts[0]]
    with db.session() as session:
        assert session.scalar(text("SELECT 1")) == 1
    assert len(attempts) == 2
    db.dispose()


def test_dispose_is_terminal_and_idempotent(database):
    database.engine
    database.dispose()
    database.dispose()
    with pytest.raises(RuntimeError, match="disposed"):
        database.session()


def test_no_implicit_schema_creation(tmp_path):
    db = Database(DatabaseConfig("sqlite", URL.create("sqlite", database=str(tmp_path / "empty.db"))))
    try:
        with db.session() as session:
            assert session.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all() == []
    finally:
        db.dispose()


def test_application_environment_cannot_override_explicit_config(monkeypatch):
    monkeypatch.setenv("BUSINESS_DB_BACKEND", "mysql")
    monkeypatch.setenv("BUSINESS_DB_URL", "not a valid connection string")
    db = Database(DatabaseConfig("sqlite", "sqlite://"))
    try:
        with db.session() as session:
            assert session.scalar(text("SELECT 1")) == 1
        assert db.engine.dialect.name == "sqlite"
    finally:
        db.dispose()


def test_upsert_rejects_empty_updates(database, records):
    with pytest.raises(ValueError, match="update"):
        database.upsert(records, {"id": 1}, {})
