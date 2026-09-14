"""Tests for the PostgreSQL schema helpers (Issue #3380)."""

from urllib.parse import parse_qs, urlsplit

import pytest

from deerflow.persistence.postgres_schema import (
    build_asyncpg_connect_args,
    build_psycopg_options,
    create_schema_sql,
    dsn_with_search_path,
    normalize_libpq_dsn,
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

    @pytest.mark.parametrize("schema", ['a"; DROP SCHEMA public; --', "MySchema", "a b", "deerflow\n"])
    def test_rejects_non_plain_identifier(self, schema):
        # Defense-in-depth: the SQL-emitting boundary re-validates so a caller
        # that bypasses the pydantic config validator cannot inject.
        with pytest.raises(ValueError):
            create_schema_sql(schema)


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

    def test_preserves_option_value_containing_space(self):
        # libpq's options parameter separates args on spaces unless they are
        # backslash-escaped. shlex.join would emit single-quotes, which libpq
        # treats as literal characters and would corrupt the option. A token
        # carrying a space must round-trip as a single backslash-escaped token.
        from deerflow.persistence.postgres_schema import _merge_search_path_option

        merged = _merge_search_path_option(r"-c application_name=My\ App", "deerflow")
        assert "'" not in merged
        assert r"application_name=My\ App" in merged
        assert merged.endswith("-c search_path=deerflow")

    def test_preserves_option_value_containing_tab(self):
        # Non-space whitespace (TAB/CR/LF) inside an existing escaped token must
        # also be re-escaped on re-join, otherwise libpq re-tokenizes on the bare
        # whitespace byte and the round-trip is lossy.
        from deerflow.persistence.postgres_schema import (
            _merge_search_path_option,
            _split_libpq_options,
        )

        merged = _merge_search_path_option("-c application_name=My\\\tApp", "deerflow")
        assert "'" not in merged
        # The tab-bearing value must round-trip back to a single token.
        tokens = _split_libpq_options(merged)
        assert "application_name=My\tApp" in tokens
        assert merged.endswith("-c search_path=deerflow")


class TestNormalizeLibpqDsn:
    def test_strips_asyncpg_driver_suffix(self):
        assert normalize_libpq_dsn("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"

    def test_leaves_bare_postgres_scheme_unchanged(self):
        dsn = "postgresql://u:p@h:5432/db"
        assert normalize_libpq_dsn(dsn) == dsn

    def test_leaves_keyword_dsn_unchanged(self):
        dsn = "host=localhost dbname=deerflow"
        assert normalize_libpq_dsn(dsn) == dsn

    def test_rejects_non_postgres_scheme(self):
        with pytest.raises(ValueError, match="Unsupported PostgreSQL DSN scheme"):
            normalize_libpq_dsn("mysql://localhost/db")
