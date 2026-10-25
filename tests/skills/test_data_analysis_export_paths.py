"""Exercise output paths with real DuckDB queries and filesystem exports."""

import csv
import json
import os
import runpy
import subprocess
import sys
from contextlib import chdir
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


def assert_export(path, extension, empty=False):
    if extension == "csv":
        with path.open(encoding="utf-8", newline="") as handle:
            assert list(csv.reader(handle)) == (
                [["answer", "label"]]
                if empty
                else [["answer", "label"], ["42", "分析"]]
            )
    elif extension == "json":
        assert json.loads(path.read_text(encoding="utf-8")) == (
            [] if empty else [{"answer": 42, "label": "分析"}]
        )
    else:
        assert path.read_text(encoding="utf-8") == (
            "| answer | label |\n| --- | --- |\n" + ("" if empty else "| 42 | 分析 |\n")
        )


@pytest.mark.parametrize("extension", ["csv", "json", "md"])
@pytest.mark.parametrize("path_kind", ["basename", "dot", "nested", "absolute"])
@pytest.mark.parametrize("empty", [False, True])
def test_query_exports_to_requested_path(tmp_path, extension, path_kind, empty):
    analysis = runpy.run_path(str(SCRIPT))
    name = f"report.{extension}"
    output = {
        "basename": name,
        "dot": f"./{name}",
        "nested": f"new directory/reports/{name}",
        "absolute": str(tmp_path / "absolute" / name),
    }[path_kind]
    sql = "SELECT 42 AS answer, '分析' AS label" + (" WHERE false" if empty else "")
    with chdir(tmp_path), duckdb.connect() as con:
        result = analysis["action_query"](con, sql, {}, output)
        assert result == f"Results exported to {output} ({0 if empty else 1} rows)"
        assert_export(Path(output), extension, empty)


@pytest.mark.parametrize("extension", ["csv", "json", "md"])
def test_cli_exports_basename_from_real_read_only_cache(tmp_path, extension):
    # Build the real CSV cache without requiring the optional spatial extension.
    # The subprocess then exercises main's normal cache-hit and export branches.
    temp_dir = tmp_path / "runtime"
    cache_dir = temp_dir / ".data-analysis-cache"
    cache_dir.mkdir(parents=True)
    source = tmp_path / "source.csv"
    source.write_text("answer,label\n42,分析\n", encoding="utf-8")
    analysis = runpy.run_path(str(SCRIPT))
    key = analysis["compute_files_hash"]([str(source)])
    table_map = {}
    with duckdb.connect(str(cache_dir / f"{key}.duckdb")) as con:
        analysis["_load_csv"](con, str(source), table_map)
    (cache_dir / f"{key}.table_map.json").write_text(
        json.dumps(table_map), encoding="utf-8"
    )
    output = f"report.{extension}"
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--files",
            str(source),
            "--action",
            "query",
            "--sql",
            "SELECT * FROM source",
            "--output-file",
            output,
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "TMPDIR": str(temp_dir),
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Cache hit!" in completed.stderr
    assert f"Results exported to {output} (1 rows)" in completed.stdout
    assert_export(tmp_path / output, extension)
