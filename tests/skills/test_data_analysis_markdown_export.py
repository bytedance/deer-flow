"""Markdown exports preserve the shape of real DuckDB query results."""

import runpy
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


@pytest.mark.parametrize(
    "header, value, expected_header, expected_value",
    [
        ("left|right", "a|b", r"left\|right", r"a\|b"),
        ("notes", "first\nsecond", "notes", "first<br>second"),
        ("first\r\nsecond", "a\rb\r\nc", "first<br>second", "a<br>b<br>c"),
        ("path", r"a\|b", "path", r"a\\\|b"),
        ("数量", 12, "数量", "12"),
    ],
)
def test_query_markdown_export_keeps_each_cell_on_one_line(
    tmp_path, header, value, expected_header, expected_value
):
    analysis = runpy.run_path(str(SCRIPT))
    output = tmp_path / "result.md"
    with duckdb.connect() as con:
        con.execute('CREATE TABLE input ("' + header.replace('"', '""') + '" VARCHAR)')
        con.execute("INSERT INTO input VALUES (?)", [value])
        analysis["action_query"](con, "SELECT * FROM input", {}, str(output))
    assert output.read_text(encoding="utf-8").splitlines() == [
        f"| {expected_header} |",
        "| --- |",
        f"| {expected_value} |",
    ]
