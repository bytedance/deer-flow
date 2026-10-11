"""CSV analysis must not install or load Excel-only dependencies."""

import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


def test_import_does_not_install_openpyxl_for_csv(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "duckdb", SimpleNamespace(DuckDBPyConnection=object)
    )
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    def unexpected_install(*args, **kwargs):
        pytest.fail("Importing the CSV analyzer must not install openpyxl")

    monkeypatch.setattr(subprocess, "run", unexpected_install)
    runpy.run_path(str(SCRIPT))


def test_missing_duckdb_installs_only_duckdb(monkeypatch):
    monkeypatch.setitem(sys.modules, "duckdb", None)
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    installs = []

    def install(command, **kwargs):
        installs.append((command, kwargs))
        monkeypatch.setitem(
            sys.modules, "duckdb", SimpleNamespace(DuckDBPyConnection=object)
        )

    monkeypatch.setattr(subprocess, "run", install)
    runpy.run_path(str(SCRIPT))
    assert installs == [
        ([sys.executable, "-m", "pip", "install", "duckdb", "-q"], {"check": True})
    ]


@pytest.mark.parametrize("missing_openpyxl", [True, False])
def test_csv_cli_works_without_excel_dependencies_or_extension_repository(
    tmp_path, monkeypatch, capsys, missing_openpyxl
):
    duckdb = pytest.importorskip("duckdb")
    if missing_openpyxl:
        monkeypatch.setitem(sys.modules, "openpyxl", None)
    else:
        pytest.importorskip("openpyxl")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("CSV analysis attempted a package install"),
    )
    module = runpy.run_path(str(SCRIPT))
    repository = tmp_path / "empty-extension-repository"
    repository.mkdir()
    source = tmp_path / "sales.csv"
    source.write_text("amount\n10\n20\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    module["main"].__globals__["CACHE_DIR"] = str(cache)
    connect = duckdb.connect

    def offline_connect(*args, **kwargs):
        kwargs["config"] = {
            "extension_directory": str(tmp_path / "extensions"),
            "custom_extension_repository": repository.as_uri(),
        }
        return connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", offline_connect)
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
            "SELECT SUM(amount) AS total FROM sales",
        ],
    )
    module["main"]()
    assert "30" in capsys.readouterr().out
    module["main"]()  # Reopen the cached database under the same offline policy.
    assert "30" in capsys.readouterr().out
    assert list(cache.glob("*.duckdb"))
    assert not list((tmp_path / "extensions").rglob("*.duckdb_extension"))


def test_mixed_inputs_initialize_spatial_once_at_first_existing_workbook(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(
        sys.modules, "duckdb", SimpleNamespace(DuckDBPyConnection=object)
    )
    monkeypatch.setitem(sys.modules, "openpyxl", SimpleNamespace())
    module = runpy.run_path(str(SCRIPT))
    events = []

    class Connection:
        def execute(self, sql):
            events.append(sql)

    globals_ = module["load_files"].__globals__
    monkeypatch.setitem(
        globals_, "_load_csv", lambda con, path, tables: events.append(Path(path).name)
    )
    monkeypatch.setitem(
        globals_,
        "_load_excel",
        lambda con, path, tables: events.append(Path(path).name),
    )
    names = [
        "missing.xlsx",
        "first.csv",
        "notes.txt",
        "one.xlsx",
        "two.xls",
        "last.csv",
    ]
    for name in names[1:]:
        (tmp_path / name).touch()
    module["load_files"](Connection(), [str(tmp_path / name) for name in names])
    assert events == [
        "first.csv",
        "INSTALL spatial; LOAD spatial;",
        "one.xlsx",
        "two.xls",
        "last.csv",
    ]


def test_excel_retains_missing_openpyxl_install_fallback(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "duckdb", SimpleNamespace(DuckDBPyConnection=object)
    )
    monkeypatch.setitem(sys.modules, "openpyxl", SimpleNamespace())
    module = runpy.run_path(str(SCRIPT))
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    installs = []
    workbook = SimpleNamespace(sheetnames=[], close=lambda: None)

    def install(command, **kwargs):
        installs.append((command, kwargs))
        monkeypatch.setitem(
            sys.modules,
            "openpyxl",
            SimpleNamespace(load_workbook=lambda *args, **kwargs: workbook),
        )

    monkeypatch.setattr(subprocess, "run", install)
    module["_load_excel"](None, str(tmp_path / "book.xlsx"), {})
    assert installs == [
        ([sys.executable, "-m", "pip", "install", "openpyxl", "-q"], {"check": True})
    ]
