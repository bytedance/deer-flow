"""LangChain tools for AI Graphs data analysis and visualization.

Provides ``run_sql`` for exploring data and ``create_visualization`` for
building chart artifacts with live SQL data injection.
"""

import json
import logging

from langchain.tools import tool

from .duckdb_client import (
    add_column as db_add_column,
    add_row as db_add_row,
    delete_column as db_delete_column,
    delete_row as db_delete_row,
    execute_query,
    export_to_csv as db_export_to_csv,
    get_table_data as db_get_table_data,
    update_cell as db_update_cell,
    validate_query,
)

logger = logging.getLogger(__name__)


@tool("run_sql", parse_docstring=True)
def run_sql(sql: str) -> str:
    """Execute a read-only SQL query against the AI Graphs DuckDB database and return results.

    Use this tool to explore uploaded datasets before creating visualizations.
    Supports DuckDB/PostgreSQL-compatible SQL. Only SELECT and WITH statements are allowed.
    Results are limited to 1000 rows.

    Args:
        sql: The SQL query to execute. Must be a read-only SELECT or WITH statement.
    """
    if not sql or not sql.strip():
        return json.dumps({"error": "Empty SQL query"})

    result = execute_query(sql, limit=1000)

    if result.get("error"):
        return json.dumps({"error": result["error"]})

    return json.dumps({
        "columns": list(result["data"][0].keys()) if result["data"] else [],
        "data": result["data"],
        "rowCount": result["rowCount"],
    }, default=str)


@tool("create_visualization", parse_docstring=True)
def create_visualization(queries: list[dict], artifact: dict) -> str:
    """Execute SQL queries and create a visualization artifact with data populated.

    Each query in the queries list is executed, and its results are injected into
    the corresponding chart in the artifact via ECharts dataset format. Charts
    reference queries by ``datasetIndex`` (0-based index into the queries list).

    The artifact follows the format:
    - title: Dashboard title
    - metrics: List of metric cards with id, label, value, change
    - charts: List of charts with id, title, datasetIndex, and ECharts option
    - data: Populated with the first query result for backward compatibility

    Args:
        queries: List of query objects, each with "sql" (str), "label" (str), and optionally "data" (list of dicts for AI-generated inline data when sql is empty).
        artifact: The visualization artifact JSON with title, charts, metrics, and data fields.
    """
    query_results: list[dict] = []
    errors: list[str] = []

    for i, q in enumerate(queries):
        q_sql = q.get("sql", "")
        q_label = q.get("label", f"Query {i + 1}")
        q_data = q.get("data")

        if q_data and (not q_sql or not q_sql.strip()):
            # Inline AI-generated data
            query_results.append({
                "sql": "",
                "label": q_label,
                "data": q_data,
                "rowCount": len(q_data),
                "source": "ai",
            })
        elif q_sql and q_sql.strip():
            result = execute_query(q_sql, limit=10000)
            if result.get("error"):
                errors.append(f'Query "{q_label}": {result["error"]}')
            else:
                query_results.append({
                    "sql": q_sql,
                    "label": q_label,
                    "data": result["data"],
                    "rowCount": result["rowCount"],
                    "source": "sql",
                })
        else:
            errors.append(f'Query "{q_label}": must provide either "sql" or "data"')

    if errors:
        return json.dumps({"errors": errors})

    # Inject query result data into each chart's ECharts option via dataset
    charts = artifact.get("charts", [])
    for chart in charts:
        ds_idx = chart.get("datasetIndex", 0)
        if isinstance(ds_idx, int) and 0 <= ds_idx < len(query_results):
            qr = query_results[ds_idx]
            if qr["data"]:
                option = chart.get("option", {})
                cols = list(qr["data"][0].keys())
                source = [cols] + [
                    [row.get(c) for c in cols] for row in qr["data"]
                ]
                option["dataset"] = {"source": source}
                chart["option"] = option

    # Populate artifact.data with first query result for backward compat
    if query_results:
        artifact["data"] = query_results[0]["data"]

    return json.dumps({
        "artifact": artifact,
        "queryResults": query_results,
    }, default=str)


@tool("get_table_data", parse_docstring=True)
def get_table_data(dataset_id: str, offset: int = 0, limit: int = 500) -> str:
    """Retrieve paginated data from an uploaded dataset for viewing or editing.

    Returns rows with a ``_rowid`` field that can be used with ``update_cell``,
    ``delete_row``, etc. to modify the data.

    Args:
        dataset_id: The dataset ID returned from file upload.
        offset: Number of rows to skip (for pagination). Defaults to 0.
        limit: Maximum number of rows to return. Defaults to 500.
    """
    result = db_get_table_data(dataset_id, offset=offset, limit=limit)
    return json.dumps(result, default=str)


@tool("update_cell", parse_docstring=True)
def update_cell(dataset_id: str, row_id: int, column_name: str, new_value: str) -> str:
    """Update a single cell value in a dataset table.

    Use the ``_rowid`` from ``get_table_data`` results to identify the row.

    Args:
        dataset_id: The dataset ID.
        row_id: The row ID (_rowid from get_table_data results).
        column_name: The column name to update.
        new_value: The new value for the cell (as a string; numbers will be auto-converted).
    """
    result = db_update_cell(dataset_id, row_id, column_name, new_value)
    return json.dumps(result, default=str)


@tool("add_row", parse_docstring=True)
def add_row(dataset_id: str, row_data: dict) -> str:
    """Add a new row to a dataset table.

    Args:
        dataset_id: The dataset ID.
        row_data: A dict mapping column names to values for the new row.
    """
    result = db_add_row(dataset_id, row_data)
    return json.dumps(result, default=str)


@tool("delete_row", parse_docstring=True)
def delete_row(dataset_id: str, row_id: int) -> str:
    """Delete a row from a dataset table.

    Use the ``_rowid`` from ``get_table_data`` results to identify the row.

    Args:
        dataset_id: The dataset ID.
        row_id: The row ID (_rowid from get_table_data results).
    """
    result = db_delete_row(dataset_id, row_id)
    return json.dumps(result, default=str)


@tool("add_column", parse_docstring=True)
def add_column(dataset_id: str, column_name: str, column_type: str = "string", default_value: str = "") -> str:
    """Add a new column to a dataset table.

    Args:
        dataset_id: The dataset ID.
        column_name: Name for the new column.
        column_type: Either "number" or "string". Defaults to "string".
        default_value: Default value for existing rows. Defaults to empty string.
    """
    dv = default_value if default_value else None
    result = db_add_column(dataset_id, column_name, column_type, dv)
    return json.dumps(result, default=str)


@tool("delete_column", parse_docstring=True)
def delete_column(dataset_id: str, column_name: str) -> str:
    """Remove a column from a dataset table.

    Args:
        dataset_id: The dataset ID.
        column_name: The column name to remove.
    """
    result = db_delete_column(dataset_id, column_name)
    return json.dumps(result, default=str)


@tool("export_csv", parse_docstring=True)
def export_csv(dataset_id: str) -> str:
    """Export a dataset back to CSV format, including any edits made.

    Args:
        dataset_id: The dataset ID to export.
    """
    result = db_export_to_csv(dataset_id)
    return json.dumps(result, default=str)
