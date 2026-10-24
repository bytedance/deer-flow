"""Failed analysis actions must not look successful to CLI callers."""

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
FAILURES = [
    pytest.param(
        ["--action", "query", "--sql", "SELEC id FROM input"],
        ".csv",
        "SQL Error:",
        id="sql-syntax",
    ),
    pytest.param(
        ["--action", "query", "--sql", "SELECT missing_column FROM input"],
        ".csv",
        "missing_column",
        id="sql-column",
    ),
    pytest.param(
        ["--action", "query", "--sql", "SELECT * FROM missing_table"],
        ".csv",
        "missing_table",
        id="sql-table",
    ),
    pytest.param(
        ["--action", "summary", "--table", "missing_table"],
        ".csv",
        "Table 'missing_table' not found",
        id="summary-table",
    ),
    pytest.param(
        ["--action", "query", "--sql", "SELECT id FROM input"],
        ".txt",
        "Unsupported output format:",
        id="export-format",
    ),
]


@pytest.fixture
def analysis():
    return runpy.run_path(str(SCRIPT))


@pytest.fixture
def cached_source(analysis, tmp_path):
    # Seed the real cache without load_files() downloading a spatial extension.
    source = tmp_path / "input.csv"
    source.write_text("id\n1\n2\n", encoding="utf-8")
    temp_root = tmp_path / "temp"
    analysis["get_cache_db_path"].__globals__["CACHE_DIR"] = str(
        temp_root / ".data-analysis-cache"
    )
    key = analysis["compute_files_hash"]([str(source)])
    tables = {}
    with duckdb.connect(analysis["get_cache_db_path"](key)) as con:
        analysis["_load_csv"](con, str(source), tables)
    analysis["save_table_map"](key, tables)
    return source, temp_root


def run_cli(cached_source, *args):
    source, temp_root = cached_source
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--files", str(source), *args],
        env={
            **os.environ,
            "TMPDIR": str(temp_root),
            "TMP": str(temp_root),
            "TEMP": str(temp_root),
            "PYTHONIOENCODING": "utf-8",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


@pytest.mark.parametrize("args, suffix, diagnostic", FAILURES)
@pytest.mark.parametrize("existing", [False, True])
def test_cli_failure_reports_stderr_without_overwriting(
    cached_source, tmp_path, args, suffix, diagnostic, existing
):
    output = tmp_path / f"result{suffix}"
    original = b"previous result\n"
    if existing:
        output.write_bytes(original)

    completed = run_cli(cached_source, *args, "--output-file", str(output))

    assert completed.returncode == 1
    assert "Error:" in completed.stderr
    assert diagnostic in completed.stderr
    assert "Traceback" not in completed.stderr
    assert completed.stdout == ""
    if suffix != ".txt":
        assert "Available tables:" in completed.stderr
        assert '"input"' in completed.stderr
    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()


@pytest.mark.parametrize(
    "args, expected",
    [
        (["--action", "inspect"], "Rows: 2"),
        (["--action", "query", "--sql", "SELECT SUM(id) AS total FROM input"], "3"),
        (
            ["--action", "query", "--sql", "SELECT id FROM input WHERE FALSE"],
            "Query returned 0 rows.",
        ),
        (["--action", "summary", "--table", "input"], "Total rows: 2"),
    ],
)
def test_cli_success_keeps_stdout_and_zero_exit(cached_source, args, expected):
    completed = run_cli(cached_source, *args)

    assert completed.returncode == 0
    assert expected in completed.stdout
    assert "Error:" not in completed.stderr


@pytest.mark.parametrize("suffix", [".csv", ".json", ".md"])
def test_cli_successful_export_keeps_result(cached_source, tmp_path, suffix):
    output = tmp_path / f"result{suffix}"
    completed = run_cli(
        cached_source,
        "--action",
        "query",
        "--sql",
        "SELECT id FROM input ORDER BY id",
        "--output-file",
        str(output),
    )

    assert completed.returncode == 0
    assert "Results exported to" in completed.stdout
    assert "Error:" not in completed.stderr
    contents = output.read_text(encoding="utf-8")
    if suffix == ".json":
        assert json.loads(contents) == [{"id": 1}, {"id": 2}]
    elif suffix == ".csv":
        assert contents == "id\n1\n2\n"
    else:
        assert contents.splitlines() == ["| id |", "| --- |", "| 1 |", "| 2 |"]


@pytest.mark.parametrize("args, suffix, diagnostic", FAILURES)
def test_main_closes_connection_after_rejected_action(
    analysis, cached_source, tmp_path, monkeypatch, args, suffix, diagnostic
):
    source, _ = cached_source
    connections = []

    def connect(*args, **kwargs):
        con = duckdb.connect(*args, **kwargs)
        connections.append(con)
        return con

    monkeypatch.setitem(
        analysis["main"].__globals__, "duckdb", SimpleNamespace(connect=connect)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--files",
            str(source),
            *args,
            "--output-file",
            str(tmp_path / f"result{suffix}"),
        ],
    )

    try:
        with pytest.raises(SystemExit, match=diagnostic):
            analysis["main"]()
        assert len(connections) == 1
        with pytest.raises(duckdb.ConnectionException, match="closed"):
            connections[0].execute("SELECT 1")
    finally:
        for con in connections:
            con.close()
