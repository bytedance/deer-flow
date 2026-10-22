"""JSON record exports must not silently discard duplicate SQL columns."""

import csv
import json
import os
import runpy
import subprocess
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
def analysis():
    return runpy.run_path(str(SCRIPT))


@pytest.mark.parametrize("columns", [["id", "id"], ["数量", "数量"]])
@pytest.mark.parametrize("rows", [[(1, 2)], []])
@pytest.mark.parametrize("existing", [False, True])
def test_json_export_rejects_duplicate_keys_before_writing(
    analysis, tmp_path, columns, rows, existing
):
    output = tmp_path / "result.json"
    original = b'[{"previous": "keep me"}]\n'
    if existing:
        output.write_bytes(original)

    with pytest.raises(ValueError, match="unique column names.*SQL aliases"):
        analysis["_export_results"](columns, rows, str(output))

    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 AS id, 2 AS id",
        "SELECT a.id, b.id FROM (VALUES (1)) a(id) CROSS JOIN (VALUES (2)) b(id)",
        "SELECT 1 AS id, 2 AS id WHERE FALSE",
    ],
)
def test_query_json_export_rejects_duplicate_result_columns(analysis, tmp_path, sql):
    output = tmp_path / "result.JSON"
    with duckdb.connect() as con:
        assert [column[0] for column in con.execute(sql).description] == ["id", "id"]
        with pytest.raises(ValueError, match="unique column names.*SQL aliases"):
            analysis["action_query"](con, sql, {}, str(output))
    assert not output.exists()


def test_json_export_preserves_unique_and_case_distinct_keys(analysis, tmp_path):
    output = tmp_path / "result.json"
    with duckdb.connect() as con:
        analysis["action_query"](
            con, 'SELECT 1 AS id, 2 AS ID, 3 AS "数量"', {}, str(output)
        )
    assert json.loads(output.read_text(encoding="utf-8")) == [
        {"id": 1, "ID": 2, "数量": 3}
    ]


@pytest.mark.parametrize("extension", ["csv", "md"])
def test_non_json_exports_keep_duplicate_columns(analysis, tmp_path, extension):
    output = tmp_path / f"result.{extension}"
    with duckdb.connect() as con:
        analysis["action_query"](con, "SELECT 1 AS id, 2 AS id", {}, str(output))
    if extension == "csv":
        with output.open(encoding="utf-8", newline="") as exported:
            assert list(csv.reader(exported)) == [["id", "id"], ["1", "2"]]
    else:
        assert output.read_text(encoding="utf-8").splitlines() == [
            "| id | id |",
            "| --- | --- |",
            "| 1 | 2 |",
        ]


@pytest.mark.parametrize("existing", [False, True])
def test_cli_rejects_duplicate_json_columns_without_overwriting(
    analysis, tmp_path, existing
):
    # Seed the real persisted cache so CLI coverage needs no spatial extension
    # installation or network access. The input file and table map agree.
    source = tmp_path / "input.csv"
    source.write_text("id\n1\n", encoding="utf-8")
    temp_root = tmp_path / "temp"
    cache = temp_root / ".data-analysis-cache"
    analysis["get_cache_db_path"].__globals__["CACHE_DIR"] = str(cache)
    key = analysis["compute_files_hash"]([str(source)])
    database = analysis["get_cache_db_path"](key)
    table_map = {}
    with duckdb.connect(database) as con:
        analysis["_load_csv"](con, str(source), table_map)
    analysis["save_table_map"](key, table_map)

    output = tmp_path / "result.json"
    original = b'[{"previous": "keep me"}]\n'
    if existing:
        output.write_bytes(original)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--files",
            str(source),
            "--action",
            "query",
            "--sql",
            "SELECT id, id + 1 AS id FROM input",
            "--output-file",
            str(output),
        ],
        env={**os.environ, "TMPDIR": str(temp_root)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode != 0
    assert "unique column names" in completed.stderr
    assert "SQL aliases" in completed.stderr
    assert "Results exported" not in completed.stdout
    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()
