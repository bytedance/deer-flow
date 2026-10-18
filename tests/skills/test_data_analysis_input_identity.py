"""Real DuckDB regressions for multi-file loading, lookup, and cache identity."""

import os
import runpy
from pathlib import Path

import pytest

# Real-engine regressions require explicitly prepared optional dependencies.
duckdb = pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


@pytest.fixture
def analysis():
    return runpy.run_path(str(SCRIPT))


def csv_file(root, name, value):
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(f"value\n{value}\n", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    "names, expected",
    [
        (
            ["report.csv", "report.csv", "report_1.csv"],
            ["report", "report_1", "report_1_1"],
        ),
        (["Report.csv", "report.csv"], ["Report", "report_1"]),
        (["sales-2026.csv", "sales_2026.csv"], ["sales_2026", "sales_2026_1"]),
        (["a-b.csv", "a b.csv", "a_b.csv"], ["a_b", "a_b_1", "a_b_2"]),
    ],
)
def test_each_input_keeps_a_distinct_queryable_table(
    analysis, tmp_path, names, expected
):
    table_map = {}
    with duckdb.connect() as con:
        for i, name in enumerate(names, 1):
            analysis["_load_csv"](con, csv_file(tmp_path / str(i), name, i), table_map)
        assert list(table_map.values()) == expected
        assert len(table_map) == len(names)
        # Map-driven SQL queries and summaries must select the same data as the
        # canonical SQL name printed by inspect; no alias may redirect that name.
        for i, table in enumerate(expected, 1):
            output = analysis["action_query"](
                con, f'SELECT value FROM "{table}"', table_map
            )
            assert output.splitlines()[2].strip() == str(i)
            summary = analysis["action_summary"](con, table, table_map)
            assert f"  mean    : {float(i)}" in summary


def test_cache_reopen_keeps_all_duplicate_inputs(analysis, tmp_path):
    files = [csv_file(tmp_path / str(i), "report.csv", i) for i in (1, 2)]
    db = tmp_path / "loaded.duckdb"
    table_map = {}
    with duckdb.connect(str(db)) as con:
        for file in files:
            analysis["_load_csv"](con, file, table_map)
    # Exercise the actual JSON persistence used on a cache hit.
    analysis["save_table_map"].__globals__["CACHE_DIR"] = str(tmp_path)
    key = analysis["compute_files_hash"](files)
    analysis["save_table_map"](key, table_map)
    restored = analysis["load_table_map"](key)
    assert restored == {"report": "report", "report_1": "report_1"}
    with duckdb.connect(str(db), read_only=True) as con:
        output = analysis["action_query"](
            con, "SELECT a.value, b.value FROM report a CROSS JOIN report_1 b", restored
        )
        assert output.splitlines()[2].replace(" ", "") == "1|2"


def test_cache_identity_changes_with_duplicate_input_order(analysis, tmp_path):
    files = [csv_file(tmp_path / str(i), "report.csv", i) for i in (1, 2)]
    assert analysis["compute_files_hash"](files) != analysis["compute_files_hash"](
        files[::-1]
    )


def test_cache_identity_changes_when_file_is_renamed(analysis, tmp_path):
    original = csv_file(tmp_path, "before.csv", 1)
    renamed = csv_file(tmp_path, "after.csv", 1)
    assert analysis["compute_files_hash"]([original]) != analysis["compute_files_hash"](
        [renamed]
    )


def test_cache_identity_preserves_file_boundaries(analysis, tmp_path):
    # Both streams concatenate to b"abc", but their per-file data differs.
    files = [tmp_path / "a.csv", tmp_path / "b.csv"]
    files[0].write_bytes(b"a")
    files[1].write_bytes(b"bc")
    before = analysis["compute_files_hash"]([str(p) for p in files])
    files[0].write_bytes(b"ab")
    files[1].write_bytes(b"c")
    assert analysis["compute_files_hash"]([str(p) for p in files]) != before


def test_relocating_the_same_named_inputs_reuses_cache(analysis, tmp_path):
    first = csv_file(tmp_path / "first", "report.csv", 1)
    relocated = csv_file(tmp_path / "other", "report.csv", 1)
    assert analysis["compute_files_hash"]([first]) == analysis["compute_files_hash"](
        [relocated]
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX surrogateescaped filenames")
def test_cache_hash_accepts_non_utf8_filesystem_names(analysis):
    # Even an unreadable POSIX argv path must reach load_files' warning, rather
    # than crashing in the hash function's fallback encoding.
    path = os.fsdecode(b"/missing/report-\xff.csv")
    assert len(analysis["compute_files_hash"]([path])) == 64


def test_excel_duplicate_sheet_names_keep_their_data(analysis, tmp_path):
    # Optional real-spatial integration: no download from the default test run.
    # Supply an already installed official extension directory to opt in.
    extension_dir = os.environ.get("DEERFLOW_TEST_SPATIAL_DIRECTORY")
    if not extension_dir:
        pytest.skip(
            "set DEERFLOW_TEST_SPATIAL_DIRECTORY for real Excel/spatial integration"
        )
    import openpyxl

    table_map = {}
    with duckdb.connect(config={"extension_directory": extension_dir}) as con:
        con.execute("LOAD spatial")
        for i in (1, 2):
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Sheet1"
            sheet.append(["value"])
            sheet.append([i])
            path = tmp_path / f"book{i}.xlsx"
            workbook.save(path)
            workbook.close()
            analysis["_load_excel"](con, str(path), table_map)
        assert table_map == {"Sheet1": "Sheet1", "Sheet1_1": "Sheet1_1"}
        output = analysis["action_query"](
            con,
            "SELECT a.value, b.value FROM Sheet1 a CROSS JOIN Sheet1_1 b",
            table_map,
        )
        assert output.splitlines()[2].replace(" ", "") == "1|2"


def test_cli_cache_reopen_and_reorder_select_the_requested_sources(
    analysis, tmp_path, monkeypatch, capsys, caplog
):
    extension_dir = os.environ.get("DEERFLOW_TEST_SPATIAL_DIRECTORY")
    if not extension_dir:
        pytest.skip(
            "set DEERFLOW_TEST_SPATIAL_DIRECTORY for real CLI/spatial integration"
        )
    import logging
    import sys

    connect = duckdb.connect
    # Redirect only the official extension location. All loading, INSTALL/LOAD,
    # SQL, file hashing, database reopening, and CLI actions remain production code.
    monkeypatch.setattr(
        duckdb,
        "connect",
        lambda *a, **kw: connect(
            *a, **kw, config={"extension_directory": extension_dir}
        ),
    )
    analysis["main"].__globals__["CACHE_DIR"] = str(tmp_path / "cache")
    files = [
        csv_file(tmp_path / "owner's uploads" / str(i), "sales-2026.csv", i)
        for i in (1, 2)
    ]
    sql = 'SELECT a.value, b.value FROM "sales-2026" a CROSS JOIN sales_2026_1 b'

    def query(paths):
        monkeypatch.setattr(
            sys,
            "argv",
            [str(SCRIPT), "--files", *paths, "--action", "query", "--sql", sql],
        )
        caplog.clear()
        with caplog.at_level(logging.INFO):
            analysis["main"]()
        return capsys.readouterr().out.splitlines()[2].replace(" ", "")

    assert query(files) == "1|2"
    assert query(files[::-1]) == "2|1"
    assert "Cache hit!" not in caplog.text
    assert query(files[::-1]) == "2|1"
    assert "Cache hit!" in caplog.text


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT 'sales-2026' AS label FROM sales_2026", {"label": "sales-2026"}),
        ('SELECT value FROM "sales-2026"', {"value": 7}),
        ('SELECT value AS "sales-2026" FROM sales_2026', {"sales-2026": 7}),
        (
            'WITH "sales-2026" AS (SELECT 9 AS value) SELECT * FROM "sales-2026"',
            {"value": 9},
        ),
        (
            'SELECT value FROM "sales-2026" -- sales-2026 is a source alias',
            {"value": 7},
        ),
    ],
)
def test_queries_preserve_sql_semantics(analysis, tmp_path, sql, expected):
    import json

    table_map = {}
    with duckdb.connect() as con:
        analysis["_load_csv"](con, csv_file(tmp_path, "sales-2026.csv", 7), table_map)
        output = tmp_path / "result.json"
        analysis["action_query"](con, sql, table_map, str(output))
        assert output.exists(), "query must succeed without rewriting identifiers"
        assert json.loads(output.read_text()) == [expected]


def test_original_aliases_work_on_read_only_cache(analysis, tmp_path):
    import json

    db = tmp_path / "cached.duckdb"
    table_map = {}
    with duckdb.connect(str(db)) as con:
        analysis["_load_csv"](con, csv_file(tmp_path, "sales-2026.csv", 7), table_map)
    # Double quotes are valid SQL alias characters, but Windows forbids them
    # in disk filenames. Exercise alias escaping independently of the CSV path.
    table_map['sales-"2026'] = table_map.pop("sales-2026")
    before = db.read_bytes()
    with duckdb.connect(str(db), read_only=True) as con:
        for i in range(2):
            output = tmp_path / f"result{i}.json"
            analysis["action_query"](
                con, 'SELECT value FROM "sales-""2026"', table_map, str(output)
            )
            assert output.exists(), "original names must work on cache hits too"
            assert json.loads(output.read_text()) == [{"value": 7}]
    assert db.read_bytes() == before
    with duckdb.connect(str(db), read_only=True) as con:
        assert (
            con.execute(
                "SELECT view_name FROM duckdb_views() WHERE NOT internal"
            ).fetchall()
            == []
        )


def test_csv_paths_are_bound_as_values(analysis, tmp_path):
    table_map = {}
    with duckdb.connect() as con:
        path = csv_file(tmp_path / "owner's uploads", "sales'2026.csv", 7)
        analysis["_load_csv"](con, path, table_map)
        assert table_map == {"sales'2026": "sales_2026"}
        assert con.execute("SELECT value FROM sales_2026").fetchall() == [(7,)]


def test_inspect_and_summary_handle_quoted_headers(analysis, tmp_path):
    import csv

    path = tmp_path / "report.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(['net"amount', 'customer"name'])
        writer.writerows([(10, "Alice"), (20, "Alice"), (None, "Bob")])
    table_map = {}
    with duckdb.connect() as con:
        analysis["_load_csv"](con, str(path), table_map)
        inspected = analysis["action_inspect"](con, table_map)
        assert '  net"amount: 2 / 3' in inspected
        assert '  customer"name: 3 / 3' in inspected
        summary = analysis["action_summary"](con, "report", table_map)
        assert "Error computing stats" not in summary
        assert "  mean    : 15.0000" in summary
        assert "  unique  : 2" in summary
        assert "    Alice: 2 (66.7%)" in summary


def test_excel_paths_and_sheet_names_are_bound_as_values(analysis, tmp_path):
    extension_dir = os.environ.get("DEERFLOW_TEST_SPATIAL_DIRECTORY")
    if not extension_dir:
        pytest.skip("set DEERFLOW_TEST_SPATIAL_DIRECTORY for real Excel integration")
    import openpyxl

    path = tmp_path / "owner's report.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "owner's sales"
    workbook.active.append(["value"])
    workbook.active.append([7])
    workbook.save(path)
    workbook.close()
    table_map = {}
    with duckdb.connect(config={"extension_directory": extension_dir}) as con:
        con.execute("LOAD spatial")
        analysis["_load_excel"](con, str(path), table_map)
        assert table_map == {"owner's sales": "owner_s_sales"}
        assert con.execute("SELECT value FROM owner_s_sales").fetchall() == [(7,)]
