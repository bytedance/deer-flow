"""CLI exports must preserve every input, including filesystem aliases."""

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
def cached_inputs(tmp_path):
    analysis = runpy.run_path(str(SCRIPT))
    sources = [tmp_path / "first.csv", tmp_path / "second.csv"]
    for source, value in zip(sources, [10, 20]):
        source.write_text(f"amount\n{value}\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    cache = runtime / ".data-analysis-cache"
    cache.mkdir(parents=True)
    key = analysis["compute_files_hash"]([str(source) for source in sources])
    table_map = {}
    with duckdb.connect(str(cache / f"{key}.duckdb")) as con:
        for source in sources:
            analysis["_load_csv"](con, str(source), table_map)
    (cache / f"{key}.table_map.json").write_text(
        json.dumps(table_map), encoding="utf-8"
    )
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
def test_cli_rejects_export_over_an_input(cached_inputs, tmp_path, path_kind):
    sources, runtime = cached_inputs
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
    assert "--output-file must not overwrite an input file" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Results exported" not in completed.stdout


def test_cli_still_overwrites_a_separate_result(cached_inputs, tmp_path):
    sources, runtime = cached_inputs
    original = [source.read_bytes() for source in sources]
    output = tmp_path / "result.csv"
    output.write_text("previous result\n", encoding="utf-8")

    completed = run_export(sources, runtime, output, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "Cache hit!" in completed.stderr
    with output.open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == [["doubled"], ["20"]]
    assert [source.read_bytes() for source in sources] == original
