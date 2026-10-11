"""Inspect and summarize CSV headers containing SQL identifier delimiters."""

import csv
import runpy
from pathlib import Path

import pytest

# The script installs missing dependencies on import; keep these tests offline.
duckdb = pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")


@pytest.fixture(
    params=[
        ("amount", "category"),
        ('gross "USD"', 'customer "tier"'),
        ('gross ""USD""', 'customer ""tier""'),
    ],
    ids=["ordinary", "embedded-quotes", "repeated-quotes"],
)
def loaded_csv(request, tmp_path):
    columns = request.param
    csv_path = tmp_path / "sales.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows([(10, "A"), (20, "A"), (None, None), (30, "B")])

    script = (
        Path(__file__).resolve().parents[2]
        / "skills/public/data-analysis/scripts/analyze.py"
    )
    analyzer = runpy.run_path(str(script))
    with duckdb.connect() as connection:
        table_map = {}
        # CSV loading needs no spatial extension or network access.
        analyzer["_load_csv"](connection, str(csv_path), table_map)
        assert table_map == {"sales": "sales"}
        assert [
            row[0] for row in connection.execute("DESCRIBE sales").fetchall()
        ] == list(columns)
        yield analyzer, connection, table_map, columns


def test_inspect_reports_non_null_counts_for_original_column_names(loaded_csv):
    analyzer, connection, table_map, columns = loaded_csv

    report = analyzer["action_inspect"](connection, table_map)

    assert "Rows: 4" in report
    assert "Non-null counts:" in report
    for column in columns:
        assert f"  {column}: 3 / 4" in report


def test_summary_reports_numeric_and_categorical_statistics(loaded_csv):
    analyzer, connection, table_map, columns = loaded_csv

    report = analyzer["action_summary"](connection, "sales", table_map)

    assert "Error computing stats" not in report
    assert "Total rows: 4" in report
    numeric = report.split(f"--- {columns[0]} (BIGINT) ---", 1)[1].split("\n---", 1)[0]
    categorical = report.split(f"--- {columns[1]} (VARCHAR) ---", 1)[1]
    for statistic in [
        "count   : 3",
        "mean    : 20.0000",
        "std     : 10.0000",
        "min     : 10",
        "25%     : 15.0000",
        "50%     : 20.0000",
        "75%     : 25.0000",
        "max     : 30",
        "nulls   : 1",
    ]:
        assert statistic in numeric
    for statistic in [
        "count   : 3",
        "unique  : 2",
        "top     : A",
        "nulls   : 1",
        "A: 2 (50.0%)",
        "B: 1 (25.0%)",
    ]:
        assert statistic in categorical
