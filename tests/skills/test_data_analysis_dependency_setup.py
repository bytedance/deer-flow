"""Missing optional dependencies must not launch package installers."""

import builtins
import runpy
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


@pytest.mark.parametrize("dependency", ["duckdb", "openpyxl"])
def test_missing_dependency_reports_explicit_setup(monkeypatch, dependency):
    if dependency == "openpyxl":
        pytest.importorskip("duckdb")
    original_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == dependency:
            raise ModuleNotFoundError(f"No module named '{dependency}'")
        return original_import(name, *args, **kwargs)

    def forbidden_install(*args, **kwargs):
        pytest.fail("analysis must not launch dependency installers")

    monkeypatch.setattr(builtins, "__import__", missing)
    monkeypatch.setattr(subprocess, "run", forbidden_install)
    with pytest.raises(
        SystemExit, match=f"Missing {dependency}.*pip install duckdb openpyxl"
    ):
        runpy.run_path(str(SCRIPT))
