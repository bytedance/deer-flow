"""Read real BIFF workbooks without treating them as OOXML or requiring GDAL."""

import builtins
import datetime
import gzip
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")
pytest.importorskip("pandas")
pytest.importorskip("xlrd")
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/public/data-analysis/scripts/analyze.py"
FIXTURE = Path(__file__).parent / "fixtures/legacy-xls/workbook.xls"


@pytest.fixture
def analysis():
    return runpy.run_path(str(SCRIPT))


def test_real_legacy_xls_keeps_all_sheets_and_cell_types(analysis, tmp_path):
    path = tmp_path / "owner's report.xls"
    shutil.copyfile(FIXTURE, path)
    assert path.read_bytes()[:8] == bytes.fromhex("d0cf11e0a1b11ae1")
    table_map = {}
    with duckdb.connect() as con:
        analysis["_load_excel"](con, str(path), table_map)
        assert table_map == {"owner's sales": "owner_s_sales", "Mixed": "Mixed"}
        assert con.execute(
            "SELECT * FROM owner_s_sales ORDER BY amount DESC"
        ).fetchall() == [
            (7, datetime.datetime(2026, 1, 2), "first", True),
            (3, datetime.datetime(2026, 1, 3), None, False),
        ]
        assert con.execute('SELECT value FROM "Mixed"').fetchall() == [
            ("1",),
            ("text",),
            (None,),
        ]


def test_legacy_xls_names_share_the_existing_allocator(analysis):
    table_map = {}
    with duckdb.connect() as con:
        for _ in range(2):
            analysis["_load_excel"](con, str(FIXTURE), table_map)
        assert table_map == {
            "owner's sales": "owner_s_sales",
            "Mixed": "Mixed",
            "owner_s_sales_1": "owner_s_sales_1",
            "Mixed_1": "Mixed_1",
        }
        assert con.execute("SELECT SUM(amount) FROM owner_s_sales_1").fetchone() == (
            10,
        )


@pytest.mark.parametrize("dependency", ["pandas", "xlrd"])
def test_legacy_xls_missing_dependency_has_setup_instruction(
    analysis, monkeypatch, dependency
):
    original_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == dependency:
            raise ImportError(f"No module named {dependency!r}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with (
        duckdb.connect() as con,
        pytest.raises(SystemExit, match="python -m pip install pandas xlrd"),
    ):
        analysis["_load_excel"](con, str(FIXTURE), {})


def test_failed_legacy_sheet_does_not_reserve_an_alias(analysis):
    table_map = {}
    with duckdb.connect() as con:
        con.execute("CREATE TABLE owner_s_sales (existing INTEGER)")
        analysis["_load_excel"](con, str(FIXTURE), table_map)
        assert table_map == {"Mixed": "Mixed"}
        assert con.execute("DESCRIBE owner_s_sales").fetchone()[0] == "existing"


def test_legacy_xls_cache_reopens_complete_read_only_tables(
    analysis,
    tmp_path,
    monkeypatch,
):
    scope = analysis["main"].__globals__
    scope["CACHE_DIR"] = str(tmp_path / "cache")
    for _ in range(2):
        with analysis["open_analysis_cache"]([str(FIXTURE)]) as (con, table_map):
            assert table_map == {"owner's sales": "owner_s_sales", "Mixed": "Mixed"}
            output = analysis["action_query"](
                con,
                'SELECT SUM(amount) AS total FROM "owner\'s sales"',
                table_map,
            )
            assert output.splitlines()[2].strip() == "10"
            with pytest.raises(duckdb.Error, match="read-only"):
                con.execute("CREATE TABLE forbidden (value INTEGER)")
        monkeypatch.setitem(
            scope, "load_files", lambda *_: pytest.fail("cache hit must not reload XLS")
        )


def test_missing_legacy_dependency_cleans_unpublished_cache(
    analysis,
    tmp_path,
    monkeypatch,
):
    scope = analysis["main"].__globals__
    cache = tmp_path / "cache"
    scope["CACHE_DIR"] = str(cache)
    original_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "xlrd":
            raise ImportError("No module named xlrd")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(SystemExit, match="python -m pip install pandas xlrd"):
        with analysis["open_analysis_cache"]([str(FIXTURE)]):
            pytest.fail("missing XLS engine must not publish a connection")
    assert list((cache / "generations-v1").iterdir()) == []


def test_legacy_xls_preserves_text_na_tokens_and_leading_zero_ids(analysis):
    table_map = {}
    with duckdb.connect() as con:
        analysis["_load_excel"](
            con, str(FIXTURE.with_name("literal-text.xls")), table_map
        )
        assert con.execute('SELECT * FROM "Identifiers"').fetchall() == [
            ("NA", "00123"),
            ("NULL", "00456"),
            ("N/A", "00789"),
        ]


@pytest.fixture
def sparse_mixed_workbook(tmp_path):
    path = tmp_path / "sparse mixed.xls"
    path.write_bytes(
        gzip.decompress(FIXTURE.with_name("sparse-mixed.xls.gz").read_bytes())
    )
    return str(path)


@pytest.mark.parametrize("sample_size", [17, 1000, 20000])
def test_legacy_xls_infers_entire_mixed_column_and_restores_sampling(
    analysis,
    sparse_mixed_workbook,
    sample_size,
):
    table_map = {}
    with duckdb.connect() as con:
        con.execute("SET pandas_analyze_sample = ?", [sample_size])
        analysis["_load_excel"](con, sparse_mixed_workbook, table_map)
        assert table_map == {"Mixed": "Mixed"}
        assert con.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE value = 'text') FROM \"Mixed\""
        ).fetchone() == (10001, 1)
        assert con.execute(
            "SELECT COUNT(*) FROM \"Mixed\" WHERE value = '1'"
        ).fetchone() == (10000,)
        assert con.execute(
            "SELECT current_setting('pandas_analyze_sample')"
        ).fetchone() == (sample_size,)


def test_legacy_xls_restores_sampling_when_table_creation_fails(
    analysis,
    sparse_mixed_workbook,
):
    table_map = {}
    with duckdb.connect() as con:
        con.execute("SET pandas_analyze_sample = 17")
        con.execute('CREATE TABLE "Mixed" (existing INTEGER)')
        analysis["_load_excel"](con, sparse_mixed_workbook, table_map)
        assert table_map == {}
        assert con.execute('DESCRIBE "Mixed"').fetchone()[0] == "existing"
        assert con.execute(
            "SELECT current_setting('pandas_analyze_sample')"
        ).fetchone() == (17,)


def test_legacy_xls_cli_runs_offline_with_empty_extension_directory(tmp_path):
    """An XLS-only cold import must not install DuckDB's XLSX reader."""
    extension_dir = tmp_path / "extensions"
    extension_dir.mkdir()
    repository = tmp_path / "empty-extension-repository"
    repository.mkdir()
    cache = tmp_path / "cache"
    # Configure a real connection in a fresh interpreter. An empty local
    # repository makes extension installation fail without any network request;
    # all CLI parsing, XLS reads, SQL and cache publication remain production code.
    bootstrap = """
import functools
import runpy
import sys
import duckdb

script, extensions, repository, cache, *arguments = sys.argv[1:]
duckdb.connect = functools.partial(
    duckdb.connect,
    config={
        "extension_directory": extensions,
        "custom_extension_repository": repository,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    },
)
module = runpy.run_path(script)
module["main"].__globals__["CACHE_DIR"] = cache
sys.argv = [script, *arguments]
module["main"]()
"""
    command = [
        sys.executable,
        "-c",
        bootstrap,
        str(SCRIPT),
        str(extension_dir),
        str(repository),
        str(cache),
        "--files",
        str(FIXTURE),
    ]
    inspected = subprocess.run(
        [*command, "--action", "inspect"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert inspected.returncode == 0, inspected.stderr
    assert "owner's sales" in inspected.stdout
    assert "Mixed" in inspected.stdout

    # A second process reopens the published cache and reads the actual cells.
    queried = subprocess.run(
        [
            *command,
            "--action",
            "query",
            "--sql",
            'SELECT SUM(amount) AS total FROM "owner\'s sales"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert queried.returncode == 0, queried.stderr
    assert queried.stdout.splitlines()[2].strip() == "10"
    assert not list(extension_dir.rglob("*"))
