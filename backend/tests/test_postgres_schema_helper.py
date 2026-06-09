"""Tests for the PostgreSQL schema helpers (Issue #3380)."""

from urllib.parse import parse_qs, urlsplit

import pytest

from deerflow.persistence.postgres_schema import (
    build_asyncpg_connect_args,
    build_psycopg_options,
    create_schema_sql,
    dsn_with_search_path,
)


class TestBuildAsyncpgConnectArgs:
    def test_sets_search_path_for_schema(self):
        assert build_asyncpg_connect_args("deerflow") == {"server_settings": {"search_path": "deerflow"}}

    def test_empty_schema_returns_empty_dict(self):
        assert build_asyncpg_connect_args("") == {}


class TestBuildPsycopgOptions:
    def test_builds_libpq_options(self):
        assert build_psycopg_options("deerflow") == "-c search_path=deerflow"

    def test_empty_schema_returns_none(self):
        assert build_psycopg_options("") is None


class TestCreateSchemaSql:
    def test_builds_create_schema_statement(self):
        assert create_schema_sql("deerflow") == 'CREATE SCHEMA IF NOT EXISTS "deerflow"'

    def test_empty_schema_returns_none(self):
        assert create_schema_sql("") is None


class TestDsnWithSearchPath:
    def test_empty_schema_returns_dsn_unchanged(self):
        dsn = "postgresql://u:p@h:5432/db"
        assert dsn_with_search_path(dsn, "") == dsn

    def test_appends_options_query_encoded(self):
        dsn = "postgresql://u:p@h:5432/db"
        out = dsn_with_search_path(dsn, "deerflow")
        # libpq only decodes %XX in URI query values; '+' is NOT treated as a
        # space. The space MUST therefore be encoded as %20, never as '+'.
        assert "+" not in out
        assert "options=-c%20search_path%3Ddeerflow" in out
        parts = urlsplit(out)
        query = parse_qs(parts.query)
        assert query["options"] == ["-c search_path=deerflow"]

    def test_merges_with_existing_query(self):
        dsn = "postgresql://u:p@h:5432/db?sslmode=require"
        out = dsn_with_search_path(dsn, "deerflow")
        query = parse_qs(urlsplit(out).query)
        assert query["sslmode"] == ["require"]
        assert query["options"] == ["-c search_path=deerflow"]

    def test_replaces_existing_options_query(self):
        dsn = "postgresql://u:p@h:5432/db?options=-c%20search_path%3Dpublic"
        out = dsn_with_search_path(dsn, "deerflow")
        query = parse_qs(urlsplit(out).query)
        assert query["options"] == ["-c search_path=deerflow"]

    def test_preserves_existing_options_query(self):
        dsn = "postgresql://u:p@h:5432/db?options=-c%20statement_timeout%3D5000"
        out = dsn_with_search_path(dsn, "deerflow")
        query = parse_qs(urlsplit(out).query)
        assert query["options"] == ["-c statement_timeout=5000 -c search_path=deerflow"]

    def test_replaces_only_existing_search_path_option(self):
        dsn = "postgresql://u:p@h:5432/db?options=-c%20statement_timeout%3D5000%20-c%20search_path%3Dpublic"
        out = dsn_with_search_path(dsn, "deerflow")
        query = parse_qs(urlsplit(out).query)
        assert query["options"] == ["-c statement_timeout=5000 -c search_path=deerflow"]

    def test_supports_keyword_dsn(self):
        pytest.importorskip("psycopg")
        from psycopg.conninfo import conninfo_to_dict

        dsn = "host=localhost dbname=deerflow user=postgres"
        out = dsn_with_search_path(dsn, "deerflow")
        assert conninfo_to_dict(out) == {
            "host": "localhost",
            "dbname": "deerflow",
            "user": "postgres",
            "options": "-c search_path=deerflow",
        }

    def test_preserves_keyword_dsn_options(self):
        pytest.importorskip("psycopg")
        from psycopg.conninfo import conninfo_to_dict

        dsn = "host=localhost dbname=deerflow options='-c statement_timeout=5000'"
        out = dsn_with_search_path(dsn, "deerflow")
        assert conninfo_to_dict(out)["options"] == "-c statement_timeout=5000 -c search_path=deerflow"

    def test_normalizes_sqlalchemy_driver_scheme(self):
        # DatabaseConfig.postgres_url may carry a +asyncpg suffix; the libpq DSN
        # produced for psycopg must drop the driver and still inject search_path.
        dsn = "postgresql+asyncpg://u:p@h:5432/db"
        out = dsn_with_search_path(dsn, "deerflow")
        parts = urlsplit(out)
        assert parts.scheme == "postgresql"
        query = parse_qs(parts.query)
        assert query["options"] == ["-c search_path=deerflow"]

    def test_rejects_non_postgres_url_scheme(self):
        try:
            dsn_with_search_path("mysql://localhost/db", "deerflow")
        except ValueError as exc:
            assert "Unsupported PostgreSQL DSN scheme" in str(exc)
        else:
            raise AssertionError("Expected ValueError")

    def test_roundtrip_preserves_host_and_db(self):
        dsn = "postgresql://u:p@h:5432/db"
        out = dsn_with_search_path(dsn, "deerflow")
        parts = urlsplit(out)
        assert parts.hostname == "h"
        assert parts.port == 5432
        assert parts.path == "/db"
