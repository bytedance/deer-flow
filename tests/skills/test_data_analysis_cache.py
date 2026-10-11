"""Cache identity regressions for the data-analysis public skill."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_analyze():
    path = (
        Path(__file__).resolve().parents[2]
        / "skills/public/data-analysis/scripts/analyze.py"
    )
    spec = importlib.util.spec_from_file_location("data_analysis_cache_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hash_analyze(monkeypatch):
    # Hashing needs no optional packages; prevent import-time pip installation.
    monkeypatch.setitem(
        sys.modules, "duckdb", SimpleNamespace(DuckDBPyConnection=object)
    )
    monkeypatch.setitem(sys.modules, "openpyxl", SimpleNamespace())
    return load_analyze()


@pytest.mark.parametrize(
    ("first_name", "second_name"),
    [("orders.csv", "customers.csv"), ("orders.csv", "orders.xlsx")],
)
def test_cache_key_distinguishes_file_names_and_formats(
    hash_analyze, tmp_path, first_name, second_name
):
    first = tmp_path / first_name
    second = tmp_path / second_name
    first.write_bytes(b"value\n1\n")
    second.write_bytes(first.read_bytes())

    assert hash_analyze.compute_files_hash(
        [str(first)]
    ) != hash_analyze.compute_files_hash([str(second)])


def test_cache_key_preserves_duplicate_name_input_order(hash_analyze, tmp_path):
    first = tmp_path / "first" / "data.csv"
    second = tmp_path / "second" / "data.csv"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"value\n1\n")
    second.write_bytes(b"value\n2\n")

    assert hash_analyze.compute_files_hash(
        [str(first), str(second)]
    ) != hash_analyze.compute_files_hash([str(second), str(first)])


def test_cache_key_distinguishes_content_boundaries(hash_analyze, tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_bytes(b"ab")
    second.write_bytes(b"c")
    before = hash_analyze.compute_files_hash([str(first), str(second)])
    first.write_bytes(b"a")
    second.write_bytes(b"bc")

    assert hash_analyze.compute_files_hash([str(first), str(second)]) != before


def test_cache_key_reuses_identical_files_after_relocation(hash_analyze, tmp_path):
    first = tmp_path / "first" / "data.csv"
    second = tmp_path / "second" / "data.csv"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"value\n1\n")
    second.write_bytes(first.read_bytes())

    assert hash_analyze.compute_files_hash(
        [str(first)]
    ) == hash_analyze.compute_files_hash([str(second)])


@pytest.fixture
def cached_analysis(monkeypatch, tmp_path):
    # Skip before importing the script, whose missing-dependency fallback runs pip.
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("openpyxl")
    module = load_analyze()
    monkeypatch.setattr(module, "CACHE_DIR", str(tmp_path / "cache"))
    connect = duckdb.connect

    class OfflineCsvConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=None):
            # CSV does not need spatial; avoid extension installation/network I/O.
            if sql == "INSTALL spatial; LOAD spatial;":
                return self
            return self.connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(
        module.duckdb,
        "connect",
        lambda *args, **kwargs: OfflineCsvConnection(connect(*args, **kwargs)),
    )

    def run(files):
        observed = {}

        def inspect(connection, table_map):
            observed["table_map"] = table_map
            observed["tables"] = {
                name: connection.execute(f'SELECT * FROM "{name}"').fetchall()
                for (name,) in connection.execute("SHOW TABLES").fetchall()
            }

        monkeypatch.setattr(module, "action_inspect", inspect)
        monkeypatch.setattr(
            sys,
            "argv",
            ["analyze.py", "--files", *map(str, files), "--action", "inspect"],
        )
        module.main()
        return observed

    return run


def test_renamed_csv_uses_current_table_name_after_cache_load(
    cached_analysis, tmp_path
):
    orders = tmp_path / "orders.csv"
    customers = tmp_path / "customers.csv"
    orders.write_bytes(b"value\n1\n")
    customers.write_bytes(orders.read_bytes())
    assert cached_analysis([orders])["tables"] == {"orders": [(1,)]}

    assert cached_analysis([customers]) == {
        "table_map": {"customers": "customers"},
        "tables": {"customers": [(1,)]},
    }


def test_reordered_duplicate_csv_names_use_current_table_contents(
    cached_analysis, tmp_path
):
    first = tmp_path / "first" / "data.csv"
    second = tmp_path / "second" / "data.csv"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"value\n1\n")
    second.write_bytes(b"value\n2\n")
    assert cached_analysis([first, second])["tables"] == {
        "data": [(1,)],
        "data_1": [(2,)],
    }

    assert cached_analysis([second, first])["tables"] == {
        "data": [(2,)],
        "data_1": [(1,)],
    }
