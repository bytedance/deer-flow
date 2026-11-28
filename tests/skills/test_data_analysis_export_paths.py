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


def run_cached_export(tmp_path, sources, sql, output):
    # Build the real CSV cache without requiring the optional spatial extension.
    # The subprocess then exercises main's normal cache-hit and export branches.
    temp_dir = tmp_path / "runtime"
    cache_dir = temp_dir / ".data-analysis-cache"
    cache_dir.mkdir(parents=True)
    analysis = runpy.run_path(str(SCRIPT))
    scope = analysis["main"].__globals__
    scope["CACHE_DIR"] = str(cache_dir)

    def load_csv(con, files):
        table_map = {}
        for path in files:
            analysis["_load_csv"](con, path, table_map)
        return table_map

    scope["load_files"] = load_csv
    with analysis["open_analysis_cache"]([str(source) for source in sources]):
        pass
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--files",
            *(str(source) for source in sources),
            "--action",
            "query",
            "--sql",
            sql,
            "--output-file",
            str(output),
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
        timeout=30,
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
    source = tmp_path / "source.csv"
    source.write_text("answer,label\n42,分析\n", encoding="utf-8")
    output = f"report.{extension}"
    completed = run_cached_export(tmp_path, [source], "SELECT * FROM source", output)
    assert completed.returncode == 0, completed.stderr
    assert "Cache hit!" in completed.stderr
    assert f"Results exported to {output} (1 rows)" in completed.stdout
    assert_export(tmp_path / output, extension)


@pytest.fixture
def input_sources(tmp_path):
    sources = [tmp_path / "first.csv", tmp_path / "second.csv"]
    for source, value in zip(sources, [10, 20]):
        source.write_text(f"amount\n{value}\n", encoding="utf-8")
    return sources


@pytest.mark.parametrize(
    "path_kind",
    ["absolute", "relative", "parent", "second", "hardlink", "symlink"],
)
def test_cli_rejects_export_over_an_input(input_sources, tmp_path, path_kind):
    sources = input_sources
    original = [source.read_bytes() for source in sources]
    output = sources[0]
    if path_kind == "relative":
        output = Path("first.csv")
    elif path_kind == "parent":
        (tmp_path / "nested").mkdir()
        output = Path("nested/../first.csv")
    elif path_kind == "second":
        output = sources[1]
    elif path_kind in {"hardlink", "symlink"}:
        output = tmp_path / "alias.json"
        try:
            if path_kind == "hardlink":
                output.hardlink_to(sources[0])
            else:
                output.symlink_to(sources[0])
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"{path_kind} unavailable: {exc}")

    completed = run_cached_export(tmp_path, sources, "SELECT amount * 2 AS doubled FROM first", output)

    assert [source.read_bytes() for source in sources] == original
    assert completed.returncode == 2
    input_file = sources[1] if path_kind == "second" else sources[0]
    assert (
        f"--output-file {output} refers to input file {input_file}" in completed.stderr
    )
    assert "Traceback" not in completed.stderr
    assert "Results exported" not in completed.stdout


def test_cli_still_overwrites_a_separate_result(input_sources, tmp_path):
    sources = input_sources
    original = [source.read_bytes() for source in sources]
    output = tmp_path / "result.csv"
    output.write_text("previous result\n", encoding="utf-8")

    completed = run_cached_export(tmp_path, sources, "SELECT amount * 2 AS doubled FROM first", output)

    assert completed.returncode == 0, completed.stderr
    assert "Cache hit!" in completed.stderr
    with output.open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == [["doubled"], ["20"]]
    assert [source.read_bytes() for source in sources] == original
