"""JSON record exports must not silently discard duplicate SQL columns."""

import csv
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture
def cached_source(analysis, tmp_path):
    # A real matching cache keeps CLI tests offline without a spatial download.
    source = tmp_path / "input.csv"
    source.write_text("id\n1\n", encoding="utf-8")
    temp_root = tmp_path / "temp"
    analysis["get_cache_db_path"].__globals__["CACHE_DIR"] = str(
        temp_root / ".data-analysis-cache"
    )
    key = analysis["compute_files_hash"]([str(source)])
    table_map = {}
    with duckdb.connect(analysis["get_cache_db_path"](key)) as con:
        analysis["_load_csv"](con, str(source), table_map)
    analysis["save_table_map"](key, table_map)
    return source, temp_root


@pytest.fixture
def opened_connections(analysis, monkeypatch):
    connections = []

    def connect(*args, **kwargs):
        con = duckdb.connect(*args, **kwargs)
        connections.append(con)
        return con

    monkeypatch.setitem(
        analysis["main"].__globals__, "duckdb", SimpleNamespace(connect=connect)
    )
    yield connections
    for con in connections:
        con.close()


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
    "columns, duplicates",
    [
        (["z", "id", "id", "z", "z", "ID", "other"], ["z", "id"]),
        (["数量", "name", "数量", "name", "Name"], ["数量", "name"]),
        (["line\nbreak", "", "line\nbreak", ""], ["line\nbreak", ""]),
    ],
)
def test_json_error_names_exact_duplicates_once_in_column_order(
    analysis, tmp_path, columns, duplicates
):
    with pytest.raises(ValueError) as error:
        analysis["_export_results"](columns, [], str(tmp_path / "result.json"))

    assert str(error.value) == (
        "JSON export requires unique column names; duplicates: "
        + ", ".join(repr(name) for name in duplicates)
        + ". Use SQL aliases (AS) to give each result column a distinct name."
    )
    assert "\n" not in str(error.value)


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


@pytest.mark.parametrize(
    "expression",
    [
        "'NaN'::DOUBLE",
        "'Infinity'::DOUBLE",
        "'-Infinity'::DOUBLE",
        "[1.0, 'NaN'::DOUBLE]",
        "{'nested': 'Infinity'::DOUBLE}",
    ],
)
@pytest.mark.parametrize("existing", [False, True])
def test_json_export_rejects_nonfinite_values_before_writing(
    analysis, tmp_path, expression, existing
):
    output = tmp_path / "result.json"
    original = b'[{"previous": "keep me"}]\n'
    if existing:
        output.write_bytes(original)

    with duckdb.connect() as con:
        with pytest.raises(ValueError, match="Out of range float values"):
            analysis["action_query"](
                con, f"SELECT {expression} AS value", {}, str(output)
            )

    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()


def test_json_export_keeps_finite_numbers_nulls_and_nonfinite_text(analysis, tmp_path):
    output = tmp_path / "result.json"
    with duckdb.connect() as con:
        analysis["action_query"](
            con,
            "SELECT 1.25::DOUBLE AS amount, NULL AS missing, "
            "['NaN', 'Infinity'] AS labels",
            {},
            str(output),
        )
    assert json.loads(output.read_text(encoding="utf-8")) == [
        {"amount": 1.25, "missing": None, "labels": ["NaN", "Infinity"]}
    ]


@pytest.mark.parametrize("existing", [False, True])
def test_cli_rejects_nonfinite_json_without_overwriting(
    cached_source, tmp_path, existing
):
    source, temp_root = cached_source
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
            "SELECT 1.0 / 0.0 AS ratio FROM input",
            "--output-file",
            str(output),
        ],
        env={**os.environ, "TMPDIR": str(temp_root)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 1
    assert "Error: Out of range float values" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Results exported" not in completed.stdout
    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()


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
    cached_source, tmp_path, existing
):
    source, temp_root = cached_source
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

    assert completed.returncode == 1
    assert "Error: JSON export requires unique column names" in completed.stderr
    assert "duplicates: 'id'" in completed.stderr
    assert "SQL aliases" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Results exported" not in completed.stdout
    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()


def test_main_closes_connection_after_duplicate_export(
    analysis, cached_source, opened_connections, tmp_path, monkeypatch
):
    source, _ = cached_source
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--files",
            str(source),
            "--action",
            "query",
            "--sql",
            "SELECT id, id + 1 AS id FROM input",
            "--output-file",
            str(tmp_path / "result.json"),
        ],
    )

    # The subprocess test pins the CLI message; this independently pins cleanup
    # even on the pre-fix version, where the export error escapes as ValueError.
    with pytest.raises((ValueError, SystemExit)):
        analysis["main"]()
    assert len(opened_connections) == 1
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        opened_connections[0].execute("SELECT 1")


@pytest.mark.parametrize(
    "action, extra_args",
    [
        ("inspect", []),
        ("query", ["--sql", "SELECT id FROM input"]),
        ("summary", ["--table", "input"]),
    ],
)
def test_main_closes_connection_after_success(
    analysis, cached_source, opened_connections, monkeypatch, action, extra_args
):
    source, _ = cached_source
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--files", str(source), "--action", action, *extra_args],
    )
    analysis["main"]()
    assert len(opened_connections) == 1
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        opened_connections[0].execute("SELECT 1")


def test_main_closes_connection_without_swallowing_unexpected_errors(
    analysis, cached_source, opened_connections, monkeypatch
):
    source, _ = cached_source
    failure = RuntimeError("unexpected action failure")

    def fail_inspection(con, table_map):
        raise failure

    monkeypatch.setitem(analysis["main"].__globals__, "action_inspect", fail_inspection)
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--files", str(source), "--action", "inspect"]
    )
    with pytest.raises(RuntimeError) as error:
        analysis["main"]()
    assert error.value is failure
    assert len(opened_connections) == 1
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        opened_connections[0].execute("SELECT 1")


def test_empty_cache_is_closed_before_removal(
    analysis, opened_connections, tmp_path, monkeypatch
):
    namespace = analysis["main"].__globals__
    monkeypatch.setitem(namespace, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setitem(namespace, "load_files", lambda con, files: {})
    removed = []

    def remove_closed_database(path):
        assert len(opened_connections) == 1
        with pytest.raises(duckdb.ConnectionException, match="closed"):
            opened_connections[0].execute("SELECT 1")
        removed.append(path)
        os.remove(path)

    monkeypatch.setitem(
        namespace,
        "os",
        SimpleNamespace(**{**vars(os), "remove": remove_closed_database}),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--files", str(tmp_path / "missing.csv"), "--action", "inspect"],
    )
    with pytest.raises(SystemExit) as error:
        analysis["main"]()
    assert error.value.code == 1
    assert len(removed) == 1
    assert not Path(removed[0]).exists()
