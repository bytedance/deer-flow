"""CLI exports must preserve every input, including filesystem aliases."""

import csv
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


@pytest.fixture
def inputs(tmp_path):
    sources = [tmp_path / "first.csv", tmp_path / "second.csv"]
    for source, value in zip(sources, [10, 20]):
        source.write_text(f"amount\n{value}\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    # Use the real cache publisher and CSV loader without installing spatial.
    analysis = runpy.run_path(str(SCRIPT))
    scope = analysis["main"].__globals__
    scope["CACHE_DIR"] = str(runtime / ".data-analysis-cache")

    def load_csv(con, files):
        table_map = {}
        for path in files:
            analysis["_load_csv"](con, path, table_map)
        return table_map

    scope["load_files"] = load_csv
    with analysis["open_analysis_cache"]([str(source) for source in sources]):
        pass
    return sources, runtime


def run_export(sources, runtime, output, cwd):
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
            "SELECT amount * 2 AS doubled FROM first",
            "--output-file",
            str(output),
        ],
        cwd=cwd,
        env={
            **os.environ,
            "TMPDIR": str(runtime),
            "TEMP": str(runtime),
            "TMP": str(runtime),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize(
    "path_kind",
    ["absolute", "relative", "parent", "second", "hardlink", "symlink"],
)
def test_cli_rejects_export_over_an_input(inputs, tmp_path, path_kind):
    sources, runtime = inputs
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

    completed = run_export(sources, runtime, output, tmp_path)

    assert [source.read_bytes() for source in sources] == original
    assert completed.returncode == 2
    input_file = sources[1] if path_kind == "second" else sources[0]
    assert (
        f"--output-file {output} refers to input file {input_file}" in completed.stderr
    )
    assert "Traceback" not in completed.stderr
    assert "Results exported" not in completed.stdout


def test_cli_still_overwrites_a_separate_result(inputs, tmp_path):
    sources, runtime = inputs
    original = [source.read_bytes() for source in sources]
    output = tmp_path / "result.csv"
    output.write_text("previous result\n", encoding="utf-8")

    completed = run_export(sources, runtime, output, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "Cache hit!" in completed.stderr
    with output.open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == [["doubled"], ["20"]]
    assert [source.read_bytes() for source in sources] == original
