"""Failed CLI actions must exit nonzero with diagnostics on stderr (#7459)."""

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
    source.write_text("id\n1\n2\n", encoding="utf-8")
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


def run_cli(source, temp_root, extra_args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--files", str(source), *extra_args],
        check=False,
        env={**os.environ, "TMPDIR": str(temp_root)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def test_cli_sql_error_exits_nonzero_with_stderr_diagnostics(cached_source, tmp_path):
    source, temp_root = cached_source
    completed = run_cli(
        source,
        temp_root,
        ["--action", "query", "--sql", "SELECT missing_col FROM input"],
    )

    assert completed.returncode == 1
    assert "Error: SQL Error" in completed.stderr
    assert "Available tables" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Available tables" not in completed.stdout


def test_cli_summary_unknown_table_exits_nonzero_with_stderr_diagnostics(
    cached_source, tmp_path
):
    source, temp_root = cached_source
    completed = run_cli(source, temp_root, ["--action", "summary", "--table", "nope"])

    assert completed.returncode == 1
    assert "Table 'nope' not found" in completed.stderr
    assert "Available tables" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "not found" not in completed.stdout


def test_cli_unsupported_export_format_exits_nonzero_without_writing(
    cached_source, tmp_path
):
    source, temp_root = cached_source
    output = tmp_path / "result.txt"
    completed = run_cli(
        source,
        temp_root,
        [
            "--action",
            "query",
            "--sql",
            "SELECT id FROM input",
            "--output-file",
            str(output),
        ],
    )

    assert completed.returncode == 1
    assert "Error: Unsupported output format" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not output.exists()


def test_export_results_rejects_unknown_format_before_making_dirs(analysis, tmp_path):
    output = tmp_path / "nested" / "result.txt"
    with pytest.raises(ValueError, match="Unsupported output format"):
        analysis["_export_results"](["id"], [(1,)], str(output))
    assert not (tmp_path / "nested").exists()


def test_cli_zero_row_query_still_exits_zero(cached_source, tmp_path):
    source, temp_root = cached_source
    completed = run_cli(
        source,
        temp_root,
        ["--action", "query", "--sql", "SELECT id FROM input WHERE id > 999"],
    )

    assert completed.returncode == 0
    assert "Query returned 0 rows." in completed.stdout


def test_main_closes_connection_after_sql_failure(
    analysis, cached_source, opened_connections, monkeypatch
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
            "SELECT missing_col FROM input",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        analysis["main"]()

    assert "Error: SQL Error" in str(exc_info.value.code)
    assert len(opened_connections) == 1
    try:
        opened_connections[0].execute("SELECT 1")
    except duckdb.Error:
        pass
    else:
        pytest.fail("connection was not closed after the failed action")
