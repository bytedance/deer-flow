"""Exercise data-analysis input names with DuckDB, without extension downloads."""

import importlib.util
from pathlib import Path

import pytest

# The script installs missing dependencies at import time. Optional test
# dependencies must be admitted first so collection never invokes pip.
duckdb = pytest.importorskip("duckdb")
openpyxl = pytest.importorskip("openpyxl")

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)
spec = importlib.util.spec_from_file_location("data_analysis_sql_literals", SCRIPT)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)


class OfflineSpatialConnection:
    """Adapt ST_Read's named-argument syntax to an offline table macro."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=None):
        # Table functions accept `name = value`; macros require `name := value`.
        sql = sql.replace("layer =", "layer :=").replace(
            "open_options =", "open_options :="
        )
        return self.connection.execute(sql, parameters)


@pytest.mark.parametrize(
    ("directory", "filename", "table_name"),
    [
        ("uploads", "report.csv", "report"),
        ("O'Brien", "report.csv", "report"),
        ("uploads", "O'Brien.csv", "O_Brien"),
        ("上传资料", "季度'报告.csv", "季度_报告"),
    ],
)
def test_load_csv_preserves_file_path(tmp_path, directory, filename, table_name):
    folder = tmp_path / directory
    folder.mkdir()
    path = folder / filename
    path.write_text("category,amount\nBooks,12\nMusic,7\n", encoding="utf-8")
    table_map = {}

    with duckdb.connect() as con:
        analyze._load_csv(con, str(path), table_map)

        assert table_map == {path.stem: table_name}
        assert con.execute(
            f'SELECT * FROM "{table_name}" ORDER BY amount'
        ).fetchall() == [
            ("Music", 7),
            ("Books", 12),
        ]


@pytest.mark.parametrize(
    ("filename", "sheet_name", "table_name"),
    [
        ("report.xlsx", "Sales", "Sales"),
        ("O'Brien.xlsx", "Sales", "Sales"),
        ("report.xlsx", "Q1's sales", "Q1_s_sales"),
        ("季度'报告.xlsx", "季度'销售", "季度_销售"),
    ],
)
def test_load_excel_preserves_path_and_sheet_name(
    tmp_path, filename, sheet_name, table_name
):
    path = tmp_path / filename
    workbook = openpyxl.Workbook()
    workbook.active.title = sheet_name
    workbook.active.append(["amount"])
    workbook.active.append([12])
    workbook.save(path)
    workbook.close()
    table_map = {}

    with duckdb.connect() as con:
        # ST_Read requires spatial/GDAL, which may download an extension.
        # This table macro keeps the real DuckDB parser, parameter binding,
        # CREATE TABLE and subsequent query while exposing the reader inputs.
        con.execute("""
            CREATE MACRO st_read(file_path, layer := NULL, open_options := []) AS TABLE
            SELECT file_path AS source_path, layer AS sheet_name, open_options AS options
        """)

        analyze._load_excel(OfflineSpatialConnection(con), str(path), table_map)

        assert table_map == {sheet_name: table_name}
        assert con.execute(f'SELECT * FROM "{table_name}"').fetchall() == [
            (str(path), sheet_name, ["HEADERS=FORCE", "FIELD_TYPES=AUTO"])
        ]
