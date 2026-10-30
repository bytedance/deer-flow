"""Queries must not change the cached snapshot of unchanged source files."""

import json
import os
import runpy
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    extension_dir = os.environ.get("DEERFLOW_TEST_SPATIAL_DIRECTORY")
    if not extension_dir:
        pytest.skip("set DEERFLOW_TEST_SPATIAL_DIRECTORY for real CLI integration")
    analysis = runpy.run_path(str(SCRIPT))
    cache = tmp_path / "cache"
    analysis["main"].__globals__["CACHE_DIR"] = str(cache)
    connect = duckdb.connect
    # Only redirect the installed, signed extension location. Loading, SQL,
    # hashing, cache selection/reopening, and dispatch are production code.
    monkeypatch.setattr(
        duckdb,
        "connect",
        lambda *args, **kwargs: connect(
            *args, **kwargs, config={"extension_directory": extension_dir}
        ),
    )

    def run(source, *options):
        monkeypatch.setattr(
            sys, "argv", [str(SCRIPT), "--files", str(source), *options]
        )
        analysis["main"]()

    return run, analysis, cache


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE source SET value = 999",
        "INSERT INTO source VALUES (999)",
        "DELETE FROM source",
        "ALTER TABLE source ADD COLUMN extra INTEGER",
        "CREATE TABLE unexpected AS SELECT 999 AS value",
    ],
)
def test_first_query_cannot_modify_cached_sources(cli, tmp_path, capsys, sql):
    run, analysis, cache = cli
    source = tmp_path / "source.csv"
    original = b"value\n7\n"
    source.write_bytes(original)

    run(source, "--action", "query", "--sql", sql)

    assert "read-only" in capsys.readouterr().out.lower()
    assert source.read_bytes() == original
    key = analysis["compute_files_hash"]([str(source)])
    with duckdb.connect(str(cache / f"{key}.duckdb"), read_only=True) as con:
        assert con.execute("SELECT * FROM source").fetchall() == [(7,)]
        assert [col[0] for col in con.execute("DESCRIBE source").fetchall()] == [
            "value"
        ]
        assert con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
        ).fetchall() == [("source",)]

    output = tmp_path / "result.json"
    run(
        source,
        "--action",
        "query",
        "--sql",
        "SELECT SUM(value) AS total FROM source",
        "--output-file",
        str(output),
    )
    assert json.loads(output.read_text(encoding="utf-8")) == [{"total": 7}]


def test_fresh_and_reused_queries_keep_aliases_ctes_and_exports(cli, tmp_path):
    run, _, _ = cli
    source = tmp_path / "sales-2026.csv"
    source.write_text("value\n7\n", encoding="utf-8")
    sql = 'WITH totals AS (SELECT SUM(value) AS total FROM "sales-2026") SELECT * FROM totals'
    for name in ("fresh.json", "reused.json"):
        output = tmp_path / name
        run(
            source,
            "--action",
            "query",
            "--sql",
            sql,
            "--output-file",
            str(output),
        )
        assert json.loads(output.read_text(encoding="utf-8")) == [{"total": 7}]


def test_legacy_writable_cache_is_rebuilt_from_source(cli, tmp_path):
    run, _, cache = cli
    source = tmp_path / "source.csv"
    source.write_bytes(b"value\n7\n")
    cache.mkdir()
    # Frozen v2 key for these exact input bytes and basename. That namespace
    # allowed the first query to update/delete its persistent source tables.
    legacy_key = "a66521a561ca7edb2660d587330160134f57d0e7ff0615465b8f690ff738d336"
    legacy_db = cache / f"{legacy_key}.duckdb"
    with duckdb.connect(str(legacy_db)) as con:
        con.execute("CREATE TABLE source AS SELECT 999 AS value")
    (cache / f"{legacy_key}.table_map.json").write_text(
        json.dumps({"source": "source"}), encoding="utf-8"
    )
    output = tmp_path / "result.json"

    run(
        source,
        "--action",
        "query",
        "--sql",
        "SELECT value FROM source",
        "--output-file",
        str(output),
    )

    assert json.loads(output.read_text(encoding="utf-8")) == [{"value": 7}]
    with duckdb.connect(str(legacy_db), read_only=True) as con:
        assert con.execute("SELECT * FROM source").fetchall() == [(999,)]
