from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.types import JSON

os.environ.setdefault("DEER_FLOW_CONFIG_PATH", str(Path(__file__).resolve().parents[2] / "config.example.yaml"))

from store.persistence.json_compat import json_match


def _table():
    metadata = MetaData()
    return Table("t", metadata, Column("data", JSON), Column("id", String))


def test_storage_json_match_compiles_sqlite() -> None:
    from sqlalchemy import create_engine

    table = _table()
    dialect = create_engine("sqlite://").dialect

    assert str(json_match(table.c.data, "k", None).compile(dialect=dialect, compile_kwargs={"literal_binds": True})) == ("json_type(t.data, '$.\"k\"') = 'null'")
    assert str(json_match(table.c.data, "k", True).compile(dialect=dialect, compile_kwargs={"literal_binds": True})) == ("json_type(t.data, '$.\"k\"') = 'true'")

    int_sql = str(json_match(table.c.data, "k", 42).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert "= 'integer'" in int_sql
    assert "CAST" in int_sql

    float_sql = str(json_match(table.c.data, "k", 3.14).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert "IN ('integer', 'real')" in float_sql
    assert "REAL" in float_sql


def test_storage_json_match_compiles_postgres() -> None:
    table = _table()
    dialect = postgresql.dialect()

    assert str(json_match(table.c.data, "k", None).compile(dialect=dialect, compile_kwargs={"literal_binds": True})) == ("json_typeof(t.data -> 'k') = 'null'")
    assert str(json_match(table.c.data, "k", False).compile(dialect=dialect, compile_kwargs={"literal_binds": True})) == ("(json_typeof(t.data -> 'k') = 'boolean' AND (t.data ->> 'k') = 'false')")

    int_sql = str(json_match(table.c.data, "k", 42).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert "CASE WHEN" in int_sql
    assert "BIGINT" in int_sql
    assert "'^-?[0-9]+$'" in int_sql


def test_storage_json_match_compiles_mysql() -> None:
    table = _table()
    dialect = mysql.dialect()

    null_sql = str(json_match(table.c.data, "k", None).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert null_sql == "JSON_TYPE(JSON_EXTRACT(t.data, '$.\"k\"')) = 'NULL'"

    bool_sql = str(json_match(table.c.data, "k", True).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert "JSON_TYPE(JSON_EXTRACT" in bool_sql
    assert "= 'BOOLEAN'" in bool_sql
    assert "= 'true'" in bool_sql

    int_sql = str(json_match(table.c.data, "k", 42).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    assert "= 'INTEGER'" in int_sql
    assert "SIGNED" in int_sql


def test_storage_json_match_rejects_unsafe_keys_and_values() -> None:
    table = _table()

    for bad_key in ["a.b", "bad;key", "with space", "", 42, None]:
        with pytest.raises(ValueError, match="JsonMatch key must match"):
            json_match(table.c.data, bad_key, "x")  # type: ignore[arg-type]

    for bad_value in [[], {}, object()]:
        with pytest.raises(TypeError, match="JsonMatch value must be"):
            json_match(table.c.data, "k", bad_value)

    with pytest.raises(TypeError, match="out of signed 64-bit range"):
        json_match(table.c.data, "k", 2**63)
