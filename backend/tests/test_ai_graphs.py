"""Tests for the AI Graphs community tools."""

import json
import os
import tempfile
import uuid

import pytest


# --------------------------------------------------------------------------- #
# DuckDB Client Tests
# --------------------------------------------------------------------------- #

class TestDuckDBClient:
    """Tests for the DuckDB client module."""

    def test_init_db(self):
        from src.community.ai_graphs.duckdb_client import init_db, _get_db_path

        init_db()
        assert os.path.exists(_get_db_path())

    def test_table_name_basic(self):
        from src.community.ai_graphs.duckdb_client import table_name

        assert table_name("sales_data.csv") == "sales_data"
        assert table_name("My File (1).xlsx") == "my_file__1_"

    def test_table_name_with_id(self):
        from src.community.ai_graphs.duckdb_client import table_name

        result = table_name("data.csv", "abcd1234-5678-9012")
        assert result == "data_abcd1234"

    def test_table_name_leading_digit(self):
        from src.community.ai_graphs.duckdb_client import table_name

        result = table_name("123report.csv")
        assert result.startswith("_")

    def test_validate_query_select(self):
        from src.community.ai_graphs.duckdb_client import validate_query

        valid, error = validate_query("SELECT * FROM test")
        assert valid is True
        assert error is None

    def test_validate_query_with(self):
        from src.community.ai_graphs.duckdb_client import validate_query

        valid, error = validate_query("WITH cte AS (SELECT 1) SELECT * FROM cte")
        assert valid is True

    def test_validate_query_insert_rejected(self):
        from src.community.ai_graphs.duckdb_client import validate_query

        valid, error = validate_query("INSERT INTO test VALUES (1)")
        assert valid is False
        assert "Only SELECT" in error

    def test_validate_query_drop_rejected(self):
        from src.community.ai_graphs.duckdb_client import validate_query

        valid, error = validate_query("SELECT 1; DROP TABLE test")
        assert valid is False
        assert "forbidden" in error.lower()

    def test_insert_and_query_dataset(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset, execute_query, get_dataset_meta

        ds_id = str(uuid.uuid4())
        columns = [
            {"name": "name", "type": "string"},
            {"name": "value", "type": "number"},
        ]
        data = [
            {"name": "Alice", "value": 100},
            {"name": "Bob", "value": 200},
            {"name": "Charlie", "value": 300},
        ]

        insert_dataset(ds_id, "test_data.csv", columns, data)

        # Check metadata
        meta = get_dataset_meta(ds_id)
        assert meta is not None
        assert meta["id"] == ds_id
        assert meta["fileName"] == "test_data.csv"
        assert meta["rowCount"] == 3
        assert len(meta["columns"]) == 2

        # Query the data
        result = execute_query(f'SELECT * FROM "{meta["tableName"]}" ORDER BY value')
        assert result["rowCount"] == 3
        assert result["data"][0]["name"] == "Alice"
        assert result["data"][0]["value"] == 100.0

    def test_get_datasets_multiple(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset, get_datasets

        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        insert_dataset(id1, "file1.csv", [{"name": "a", "type": "string"}], [{"a": "x"}])
        insert_dataset(id2, "file2.csv", [{"name": "b", "type": "number"}], [{"b": 1}])

        results = get_datasets([id1, id2])
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert id1 in ids
        assert id2 in ids

    def test_get_datasets_empty(self):
        from src.community.ai_graphs.duckdb_client import get_datasets

        assert get_datasets([]) == []

    def test_get_dataset_meta_not_found(self):
        from src.community.ai_graphs.duckdb_client import get_dataset_meta

        result = get_dataset_meta("nonexistent-id")
        assert result is None

    def test_execute_query_with_limit(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset, execute_query

        ds_id = str(uuid.uuid4())
        columns = [{"name": "x", "type": "number"}]
        data = [{"x": i} for i in range(50)]
        insert_dataset(ds_id, "big.csv", columns, data)

        result = execute_query(f'SELECT * FROM "{ds_id[:8]}"', limit=10)
        # The limit caps the returned rows
        assert result["rowCount"] <= 10

    def test_execute_query_invalid_sql(self):
        from src.community.ai_graphs.duckdb_client import execute_query

        result = execute_query("DELETE FROM test")
        assert result["error"] is not None

    def test_insert_dataset_with_nulls(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset, execute_query, get_dataset_meta

        ds_id = str(uuid.uuid4())
        columns = [
            {"name": "name", "type": "string"},
            {"name": "value", "type": "number"},
        ]
        data = [
            {"name": "Alice", "value": 100},
            {"name": "Bob", "value": None},
            {"name": "", "value": ""},
        ]
        insert_dataset(ds_id, "nulls.csv", columns, data)
        meta = get_dataset_meta(ds_id)
        assert meta["rowCount"] == 3


# --------------------------------------------------------------------------- #
# Upload Tests
# --------------------------------------------------------------------------- #

class TestUpload:
    """Tests for the file upload parser."""

    def test_parse_csv(self):
        from src.community.ai_graphs.upload import parse_and_store_file

        csv_content = b"name,value\nAlice,100\nBob,200\n"
        result = parse_and_store_file(csv_content, "test.csv")

        assert result["fileName"] == "test.csv"
        assert result["rowCount"] == 2
        assert len(result["columns"]) == 2
        assert result["columns"][0]["name"] == "name"
        assert result["columns"][1]["type"] == "number"

    def test_parse_csv_with_id(self):
        from src.community.ai_graphs.upload import parse_and_store_file

        csv_content = b"a,b\n1,2\n3,4\n"
        ds_id = str(uuid.uuid4())
        result = parse_and_store_file(csv_content, "data.csv", dataset_id=ds_id)
        assert result["id"] == ds_id

    def test_unsupported_file_type(self):
        from src.community.ai_graphs.upload import parse_and_store_file

        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_and_store_file(b"content", "file.pdf")

    def test_empty_csv(self):
        from src.community.ai_graphs.upload import parse_and_store_file

        with pytest.raises(ValueError, match="No data found"):
            parse_and_store_file(b"", "empty.csv")

    def test_infer_column_types_numbers(self):
        from src.community.ai_graphs.upload import _infer_column_types

        data = [
            {"price": "9.99", "name": "Widget"},
            {"price": "19.99", "name": "Gadget"},
        ]
        cols = _infer_column_types(data)
        assert cols[0] == {"name": "price", "type": "number"}
        assert cols[1] == {"name": "name", "type": "string"}

    def test_infer_column_types_empty(self):
        from src.community.ai_graphs.upload import _infer_column_types

        assert _infer_column_types([]) == []


# --------------------------------------------------------------------------- #
# Tool Tests
# --------------------------------------------------------------------------- #

class TestTools:
    """Tests for the LangChain tool functions."""

    def test_run_sql_tool_exists(self):
        from src.community.ai_graphs.tools import run_sql

        assert run_sql.name == "run_sql"

    def test_create_visualization_tool_exists(self):
        from src.community.ai_graphs.tools import create_visualization

        assert create_visualization.name == "create_visualization"

    def test_run_sql_empty_query(self):
        from src.community.ai_graphs.tools import run_sql

        result = json.loads(run_sql.invoke({"sql": ""}))
        assert "error" in result

    def test_run_sql_select(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset
        from src.community.ai_graphs.tools import run_sql

        ds_id = str(uuid.uuid4())
        insert_dataset(ds_id, "tool_test.csv", [{"name": "x", "type": "number"}], [{"x": 42}])

        from src.community.ai_graphs.duckdb_client import get_dataset_meta
        meta = get_dataset_meta(ds_id)

        result = json.loads(run_sql.invoke({"sql": f'SELECT * FROM "{meta["tableName"]}"'}))
        assert result["rowCount"] == 1
        assert result["data"][0]["x"] == 42.0

    def test_run_sql_forbidden(self):
        from src.community.ai_graphs.tools import run_sql

        result = json.loads(run_sql.invoke({"sql": "DROP TABLE test"}))
        assert "error" in result

    def test_create_visualization_with_sql(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset, get_dataset_meta
        from src.community.ai_graphs.tools import create_visualization

        ds_id = str(uuid.uuid4())
        insert_dataset(
            ds_id,
            "viz_test.csv",
            [{"name": "category", "type": "string"}, {"name": "revenue", "type": "number"}],
            [
                {"category": "A", "revenue": 100},
                {"category": "B", "revenue": 200},
            ],
        )
        meta = get_dataset_meta(ds_id)

        result = json.loads(create_visualization.invoke({
            "queries": [
                {"sql": f'SELECT * FROM "{meta["tableName"]}"', "label": "Revenue by Category"}
            ],
            "artifact": {
                "title": "Test Dashboard",
                "charts": [
                    {
                        "id": "c1",
                        "title": "Revenue",
                        "datasetIndex": 0,
                        "option": {
                            "xAxis": {"type": "category"},
                            "yAxis": {"type": "value"},
                            "series": [{"type": "bar", "encode": {"x": "category", "y": "revenue"}}],
                        },
                    }
                ],
                "metrics": [],
                "data": [],
            },
        }))

        assert "artifact" in result
        assert "queryResults" in result
        assert len(result["queryResults"]) == 1
        assert result["queryResults"][0]["rowCount"] == 2

        # Check dataset was injected into chart option
        chart = result["artifact"]["charts"][0]
        assert "dataset" in chart["option"]
        assert len(chart["option"]["dataset"]["source"]) == 3  # header + 2 rows

    def test_create_visualization_with_inline_data(self):
        from src.community.ai_graphs.tools import create_visualization

        result = json.loads(create_visualization.invoke({
            "queries": [
                {
                    "sql": "",
                    "label": "AI Recommendations",
                    "data": [
                        {"action": "Improve onboarding", "impact": "High"},
                        {"action": "Add integrations", "impact": "Medium"},
                    ],
                }
            ],
            "artifact": {
                "title": "Recommendations",
                "charts": [],
                "metrics": [],
                "data": [],
            },
        }))

        assert "artifact" in result
        assert result["queryResults"][0]["source"] == "ai"
        assert result["queryResults"][0]["rowCount"] == 2

    def test_create_visualization_sql_error(self):
        from src.community.ai_graphs.tools import create_visualization

        result = json.loads(create_visualization.invoke({
            "queries": [
                {"sql": "SELECT * FROM nonexistent_table_xyz", "label": "Bad Query"}
            ],
            "artifact": {"title": "Test", "charts": [], "metrics": [], "data": []},
        }))

        assert "errors" in result

    def test_exports(self):
        """Verify the __init__ exports the tools."""
        from src.community.ai_graphs import run_sql, create_visualization

        assert callable(run_sql.invoke)
        assert callable(create_visualization.invoke)


# --------------------------------------------------------------------------- #
# Data Editing Tests
# --------------------------------------------------------------------------- #

class TestDataEditing:
    """Tests for data editing functions (get_table_data, update_cell, add/delete row/column)."""

    def _create_test_dataset(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset
        ds_id = str(uuid.uuid4())
        columns = [
            {"name": "name", "type": "string"},
            {"name": "value", "type": "number"},
        ]
        data = [
            {"name": "Alice", "value": 100},
            {"name": "Bob", "value": 200},
            {"name": "Charlie", "value": 300},
        ]
        insert_dataset(ds_id, "edit_test.csv", columns, data)
        return ds_id

    def test_get_table_data(self):
        from src.community.ai_graphs.duckdb_client import get_table_data
        ds_id = self._create_test_dataset()
        result = get_table_data(ds_id)
        assert "error" not in result
        assert result["rowCount"] == 3
        assert result["totalRows"] == 3
        assert "_rowid" in result["data"][0]

    def test_get_table_data_pagination(self):
        from src.community.ai_graphs.duckdb_client import get_table_data
        ds_id = self._create_test_dataset()
        result = get_table_data(ds_id, offset=1, limit=1)
        assert result["rowCount"] == 1
        assert result["totalRows"] == 3

    def test_get_table_data_not_found(self):
        from src.community.ai_graphs.duckdb_client import get_table_data
        result = get_table_data("nonexistent-id")
        assert "error" in result

    def test_update_cell(self):
        from src.community.ai_graphs.duckdb_client import get_table_data, update_cell
        ds_id = self._create_test_dataset()

        data = get_table_data(ds_id)
        row_id = data["data"][0]["_rowid"]

        result = update_cell(ds_id, row_id, "name", "Updated")
        assert result["success"] is True

        updated_data = get_table_data(ds_id)
        first_row = next(r for r in updated_data["data"] if r["_rowid"] == row_id)
        assert first_row["name"] == "Updated"

    def test_update_cell_invalid_column(self):
        from src.community.ai_graphs.duckdb_client import update_cell
        ds_id = self._create_test_dataset()
        result = update_cell(ds_id, 0, "nonexistent_col", "val")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_update_cell_not_found(self):
        from src.community.ai_graphs.duckdb_client import update_cell
        result = update_cell("nonexistent-id", 0, "name", "val")
        assert result["success"] is False

    def test_add_row(self):
        from src.community.ai_graphs.duckdb_client import add_row, get_table_data
        ds_id = self._create_test_dataset()
        result = add_row(ds_id, {"name": "Dave", "value": 400})
        assert result["success"] is True
        assert result["rowCount"] == 4

        data = get_table_data(ds_id)
        names = [r["name"] for r in data["data"]]
        assert "Dave" in names

    def test_delete_row(self):
        from src.community.ai_graphs.duckdb_client import delete_row, get_table_data
        ds_id = self._create_test_dataset()

        data = get_table_data(ds_id)
        row_id = data["data"][0]["_rowid"]

        result = delete_row(ds_id, row_id)
        assert result["success"] is True
        assert result["rowCount"] == 2

    def test_add_column(self):
        from src.community.ai_graphs.duckdb_client import add_column, get_table_data
        ds_id = self._create_test_dataset()
        result = add_column(ds_id, "category", "string", "default")
        assert result["success"] is True
        assert any(c["name"] == "category" for c in result["columns"])

    def test_add_column_duplicate(self):
        from src.community.ai_graphs.duckdb_client import add_column
        ds_id = self._create_test_dataset()
        result = add_column(ds_id, "name", "string")
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_delete_column(self):
        from src.community.ai_graphs.duckdb_client import delete_column, get_dataset_meta
        ds_id = self._create_test_dataset()
        result = delete_column(ds_id, "value")
        assert result["success"] is True
        assert all(c["name"] != "value" for c in result["columns"])

        meta = get_dataset_meta(ds_id)
        assert all(c["name"] != "value" for c in meta["columns"])

    def test_delete_column_not_found(self):
        from src.community.ai_graphs.duckdb_client import delete_column
        ds_id = self._create_test_dataset()
        result = delete_column(ds_id, "nonexistent_col")
        assert result["success"] is False

    def test_delete_last_column_rejected(self):
        from src.community.ai_graphs.duckdb_client import delete_column
        ds_id = self._create_test_dataset()
        delete_column(ds_id, "value")
        result = delete_column(ds_id, "name")
        assert result["success"] is False
        assert "last column" in result["error"]

    def test_export_to_csv(self):
        from src.community.ai_graphs.duckdb_client import export_to_csv
        ds_id = self._create_test_dataset()
        result = export_to_csv(ds_id)
        assert "csv" in result
        assert "Alice" in result["csv"]
        assert "Bob" in result["csv"]
        assert result["fileName"] == "edit_test.csv"

    def test_export_to_csv_not_found(self):
        from src.community.ai_graphs.duckdb_client import export_to_csv
        result = export_to_csv("nonexistent-id")
        assert "error" in result


# --------------------------------------------------------------------------- #
# Data Editing Tool Tests
# --------------------------------------------------------------------------- #

class TestEditingTools:
    """Tests for the LangChain editing tool wrappers."""

    def _create_test_dataset(self):
        from src.community.ai_graphs.duckdb_client import insert_dataset
        ds_id = str(uuid.uuid4())
        columns = [
            {"name": "product", "type": "string"},
            {"name": "sales", "type": "number"},
        ]
        data = [
            {"product": "Widget", "sales": 100},
            {"product": "Gadget", "sales": 200},
        ]
        insert_dataset(ds_id, "tools_edit_test.csv", columns, data)
        return ds_id

    def test_get_table_data_tool(self):
        from src.community.ai_graphs.tools import get_table_data
        ds_id = self._create_test_dataset()
        result = json.loads(get_table_data.invoke({"dataset_id": ds_id}))
        assert result["rowCount"] == 2
        assert "_rowid" in result["data"][0]

    def test_update_cell_tool(self):
        from src.community.ai_graphs.tools import get_table_data, update_cell
        ds_id = self._create_test_dataset()
        data = json.loads(get_table_data.invoke({"dataset_id": ds_id}))
        row_id = data["data"][0]["_rowid"]

        result = json.loads(update_cell.invoke({
            "dataset_id": ds_id,
            "row_id": row_id,
            "column_name": "product",
            "new_value": "SuperWidget",
        }))
        assert result["success"] is True

    def test_add_row_tool(self):
        from src.community.ai_graphs.tools import add_row
        ds_id = self._create_test_dataset()
        result = json.loads(add_row.invoke({
            "dataset_id": ds_id,
            "row_data": {"product": "Doohickey", "sales": 300},
        }))
        assert result["success"] is True
        assert result["rowCount"] == 3

    def test_delete_row_tool(self):
        from src.community.ai_graphs.tools import get_table_data, delete_row
        ds_id = self._create_test_dataset()
        data = json.loads(get_table_data.invoke({"dataset_id": ds_id}))
        row_id = data["data"][0]["_rowid"]

        result = json.loads(delete_row.invoke({"dataset_id": ds_id, "row_id": row_id}))
        assert result["success"] is True

    def test_add_column_tool(self):
        from src.community.ai_graphs.tools import add_column
        ds_id = self._create_test_dataset()
        result = json.loads(add_column.invoke({
            "dataset_id": ds_id,
            "column_name": "region",
            "column_type": "string",
        }))
        assert result["success"] is True

    def test_delete_column_tool(self):
        from src.community.ai_graphs.tools import delete_column
        ds_id = self._create_test_dataset()
        result = json.loads(delete_column.invoke({
            "dataset_id": ds_id,
            "column_name": "sales",
        }))
        assert result["success"] is True

    def test_export_csv_tool(self):
        from src.community.ai_graphs.tools import export_csv
        ds_id = self._create_test_dataset()
        result = json.loads(export_csv.invoke({"dataset_id": ds_id}))
        assert "csv" in result
        assert "Widget" in result["csv"]
