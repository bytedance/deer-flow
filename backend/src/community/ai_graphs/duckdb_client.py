"""Local DuckDB client for AI Graphs data storage and querying.

Provides a self-contained local DuckDB database for storing uploaded datasets
and executing SQL queries against them. The database is stored at
``backend/.deer-flow/graphs.duckdb``.
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Database path
# --------------------------------------------------------------------------- #

_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".deer-flow")
_DB_PATH = os.path.join(_DB_DIR, "graphs.duckdb")

# --------------------------------------------------------------------------- #
# Thread-safe singleton connection
# --------------------------------------------------------------------------- #

_lock = threading.Lock()
_initialized = False


def _get_db_path() -> str:
    """Return the absolute path to the DuckDB file, creating the parent dir if needed."""
    path = os.path.abspath(_DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _get_connection() -> duckdb.DuckDBPyConnection:
    """Return a new DuckDB connection to the local database file."""
    return duckdb.connect(_get_db_path())


def init_db() -> None:
    """Ensure the registry table exists. Safe to call multiple times."""
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        conn = _get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _dataset_registry (
                    id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    columns JSON NOT NULL,
                    row_count INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("[ai_graphs] Registry table ensured at %s", _get_db_path())
            _initialized = True
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def table_name(file_name: str, dataset_id: str | None = None) -> str:
    """Derive a safe SQL table name from a file name and optional dataset ID."""
    base = re.sub(r"\.[^.]+$", "", file_name)
    base = re.sub(r"[^a-zA-Z0-9_]", "_", base)
    base = re.sub(r"^(\d)", r"_\1", base)
    base = base.lower()
    if dataset_id:
        suffix = dataset_id.replace("-", "")[:8]
        return f"{base}_{suffix}"
    return base


# --------------------------------------------------------------------------- #
# Read-only query validation
# --------------------------------------------------------------------------- #

_READ_ONLY_PATTERN = re.compile(r"^\s*(SELECT|WITH|DESCRIBE|SHOW|PRAGMA|EXPLAIN)\b", re.IGNORECASE)
_FORBIDDEN_PATTERN = re.compile(
    r"\b(DROP|DELETE|UPDATE|ALTER|TRUNCATE|GRANT|REVOKE|COPY|EXPORT|IMPORT|ATTACH|DETACH|LOAD|INSTALL)\b",
    re.IGNORECASE,
)


def validate_query(sql: str) -> tuple[bool, str | None]:
    """Validate that a SQL string is read-only.

    Returns:
        A tuple of ``(is_valid, error_message)``.
    """
    trimmed = sql.strip()
    if not _READ_ONLY_PATTERN.match(trimmed):
        return False, "Only SELECT and WITH queries are allowed"
    if _FORBIDDEN_PATTERN.search(trimmed):
        return False, "Query contains forbidden keywords (DROP, DELETE, INSERT, etc.)"
    return True, None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def insert_dataset(
    dataset_id: str,
    file_name: str,
    columns: list[dict[str, str]],
    data: list[dict[str, Any]],
) -> None:
    """Create a table for *data* and register it in the dataset registry.

    Args:
        dataset_id: Unique identifier for the dataset.
        file_name: Original file name (used to derive the table name).
        columns: List of ``{"name": str, "type": str}`` column descriptors.
        data: Row data as a list of dicts.
    """
    init_db()
    name = table_name(file_name, dataset_id)
    conn = _get_connection()
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')

        col_defs = ", ".join(
            f'"{c["name"]}" {"DOUBLE" if c["type"] == "number" else "VARCHAR"}'
            for c in columns
        )
        conn.execute(f'CREATE TABLE "{name}" ({col_defs})')

        if data:
            # Build parameterised INSERT for safety
            placeholders = ", ".join("?" for _ in columns)
            insert_sql = f'INSERT INTO "{name}" VALUES ({placeholders})'
            for row in data:
                values = []
                for c in columns:
                    v = row.get(c["name"])
                    if v is None or v == "":
                        values.append(None)
                    elif c["type"] == "number":
                        try:
                            values.append(float(v))
                        except (ValueError, TypeError):
                            values.append(None)
                    else:
                        values.append(str(v))
                conn.execute(insert_sql, values)

        # Upsert into registry
        conn.execute("DELETE FROM _dataset_registry WHERE id = ?", [dataset_id])
        conn.execute(
            """
            INSERT INTO _dataset_registry (id, file_name, table_name, columns, row_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                dataset_id,
                file_name,
                name,
                json.dumps(columns),
                len(data),
                datetime.now(timezone.utc),
            ],
        )
        logger.info("[ai_graphs] Inserted dataset %s (%s) with %d rows", dataset_id, name, len(data))
    finally:
        conn.close()


def get_dataset_meta(dataset_id: str) -> dict[str, Any] | None:
    """Return metadata for a single dataset, or ``None`` if not found."""
    init_db()
    conn = _get_connection()
    try:
        result = conn.execute(
            "SELECT id, file_name, table_name, columns, row_count FROM _dataset_registry WHERE id = ?",
            [dataset_id],
        ).fetchone()
        if result is None:
            return None
        return {
            "id": result[0],
            "fileName": result[1],
            "tableName": result[2],
            "columns": json.loads(result[3]) if isinstance(result[3], str) else result[3],
            "rowCount": result[4],
        }
    except Exception as exc:
        logger.warning("[ai_graphs] get_dataset_meta failed: %s", exc)
        return None
    finally:
        conn.close()


def get_datasets(dataset_ids: list[str]) -> list[dict[str, Any]]:
    """Return metadata for multiple datasets by ID."""
    if not dataset_ids:
        return []
    init_db()
    conn = _get_connection()
    try:
        placeholders = ", ".join("?" for _ in dataset_ids)
        rows = conn.execute(
            f"SELECT id, file_name, table_name, columns, row_count FROM _dataset_registry WHERE id IN ({placeholders})",
            dataset_ids,
        ).fetchall()
        return [
            {
                "id": row[0],
                "fileName": row[1],
                "tableName": row[2],
                "columns": json.loads(row[3]) if isinstance(row[3], str) else row[3],
                "rowCount": row[4],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("[ai_graphs] get_datasets failed: %s", exc)
        return []
    finally:
        conn.close()


def get_table_data(
    dataset_id: str,
    offset: int = 0,
    limit: int = 500,
) -> dict[str, Any]:
    """Return rows from a dataset table with pagination.

    Returns:
        A dict with ``columns``, ``data`` (list of row dicts with ``_rowid``),
        ``rowCount``, ``totalRows``, and ``tableName``.
    """
    meta = get_dataset_meta(dataset_id)
    if meta is None:
        return {"error": f"Dataset {dataset_id} not found"}

    tbl = meta["tableName"]
    init_db()
    conn = _get_connection()
    try:
        # Use rowid for stable row identification during edits
        result = conn.execute(
            f'SELECT rowid AS _rowid, * FROM "{tbl}" LIMIT ? OFFSET ?',
            [limit, offset],
        )
        columns = [desc[0] for desc in result.description]
        rows_raw = result.fetchall()
        data = [dict(zip(columns, row)) for row in rows_raw]

        total_result = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
        total_rows = total_result[0] if total_result else 0

        return {
            "columns": meta["columns"],
            "data": data,
            "rowCount": len(data),
            "totalRows": total_rows,
            "tableName": tbl,
            "datasetId": dataset_id,
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        conn.close()


def update_cell(
    dataset_id: str,
    row_id: int,
    column_name: str,
    new_value: Any,
) -> dict[str, Any]:
    """Update a single cell in a dataset table.

    Args:
        dataset_id: The dataset to update.
        row_id: The DuckDB rowid of the row.
        column_name: Column to update.
        new_value: New value for the cell.

    Returns:
        A dict with ``success`` (bool) and optionally ``error`` (str).
    """
    meta = get_dataset_meta(dataset_id)
    if meta is None:
        return {"success": False, "error": f"Dataset {dataset_id} not found"}

    tbl = meta["tableName"]
    # Validate column name exists
    valid_columns = {c["name"] for c in meta["columns"]}
    if column_name not in valid_columns:
        return {"success": False, "error": f"Column '{column_name}' not found in dataset"}

    init_db()
    conn = _get_connection()
    try:
        conn.execute(
            f'UPDATE "{tbl}" SET "{column_name}" = ? WHERE rowid = ?',
            [new_value, row_id],
        )
        return {"success": True}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def add_row(
    dataset_id: str,
    row_data: dict[str, Any],
) -> dict[str, Any]:
    """Insert a new row into a dataset table.

    Args:
        dataset_id: The dataset to insert into.
        row_data: Dict mapping column names to values.

    Returns:
        A dict with ``success`` (bool) and optionally ``error``.
    """
    meta = get_dataset_meta(dataset_id)
    if meta is None:
        return {"success": False, "error": f"Dataset {dataset_id} not found"}

    tbl = meta["tableName"]
    columns = meta["columns"]

    init_db()
    conn = _get_connection()
    try:
        col_names = ", ".join(f'"{c["name"]}"' for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        values = []
        for c in columns:
            v = row_data.get(c["name"])
            if v is None or v == "":
                values.append(None)
            elif c["type"] == "number":
                try:
                    values.append(float(v))
                except (ValueError, TypeError):
                    values.append(None)
            else:
                values.append(str(v))
        conn.execute(f'INSERT INTO "{tbl}" ({col_names}) VALUES ({placeholders})', values)

        # Update row count in registry
        count_result = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
        new_count = count_result[0] if count_result else 0
        conn.execute("UPDATE _dataset_registry SET row_count = ? WHERE id = ?", [new_count, dataset_id])

        return {"success": True, "rowCount": new_count}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def delete_row(
    dataset_id: str,
    row_id: int,
) -> dict[str, Any]:
    """Delete a row from a dataset table by rowid.

    Returns:
        A dict with ``success`` (bool) and optionally ``error``.
    """
    meta = get_dataset_meta(dataset_id)
    if meta is None:
        return {"success": False, "error": f"Dataset {dataset_id} not found"}

    tbl = meta["tableName"]
    init_db()
    conn = _get_connection()
    try:
        conn.execute(f'DELETE FROM "{tbl}" WHERE rowid = ?', [row_id])

        # Update row count in registry
        count_result = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
        new_count = count_result[0] if count_result else 0
        conn.execute("UPDATE _dataset_registry SET row_count = ? WHERE id = ?", [new_count, dataset_id])

        return {"success": True, "rowCount": new_count}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def add_column(
    dataset_id: str,
    column_name: str,
    column_type: str = "string",
    default_value: Any = None,
) -> dict[str, Any]:
    """Add a new column to a dataset table.

    Args:
        dataset_id: The dataset to modify.
        column_name: Name for the new column.
        column_type: ``"number"`` or ``"string"`` (default).
        default_value: Default value for existing rows.

    Returns:
        A dict with ``success`` (bool) and optionally ``error``.
    """
    meta = get_dataset_meta(dataset_id)
    if meta is None:
        return {"success": False, "error": f"Dataset {dataset_id} not found"}

    tbl = meta["tableName"]
    existing_columns = {c["name"] for c in meta["columns"]}
    if column_name in existing_columns:
        return {"success": False, "error": f"Column '{column_name}' already exists"}

    sql_type = "DOUBLE" if column_type == "number" else "VARCHAR"
    default_clause = ""
    if default_value is not None:
        if column_type == "number":
            default_clause = f" DEFAULT {float(default_value)}"
        else:
            escaped = str(default_value).replace("'", "''")
            default_clause = f" DEFAULT '{escaped}'"

    init_db()
    conn = _get_connection()
    try:
        conn.execute(f'ALTER TABLE "{tbl}" ADD COLUMN "{column_name}" {sql_type}{default_clause}')

        # Update registry columns
        updated_columns = meta["columns"] + [{"name": column_name, "type": column_type}]
        conn.execute(
            "UPDATE _dataset_registry SET columns = ? WHERE id = ?",
            [json.dumps(updated_columns), dataset_id],
        )

        return {"success": True, "columns": updated_columns}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def delete_column(
    dataset_id: str,
    column_name: str,
) -> dict[str, Any]:
    """Remove a column from a dataset table.

    Returns:
        A dict with ``success`` (bool) and optionally ``error``.
    """
    meta = get_dataset_meta(dataset_id)
    if meta is None:
        return {"success": False, "error": f"Dataset {dataset_id} not found"}

    tbl = meta["tableName"]
    existing_columns = [c for c in meta["columns"] if c["name"] != column_name]
    if len(existing_columns) == len(meta["columns"]):
        return {"success": False, "error": f"Column '{column_name}' not found"}
    if not existing_columns:
        return {"success": False, "error": "Cannot delete the last column"}

    init_db()
    conn = _get_connection()
    try:
        conn.execute(f'ALTER TABLE "{tbl}" DROP COLUMN "{column_name}"')

        # Update registry columns
        conn.execute(
            "UPDATE _dataset_registry SET columns = ? WHERE id = ?",
            [json.dumps(existing_columns), dataset_id],
        )

        return {"success": True, "columns": existing_columns}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        conn.close()


def export_to_csv(dataset_id: str) -> dict[str, Any]:
    """Export a dataset table back to CSV string.

    Returns:
        A dict with ``csv`` (str) and ``fileName``, or ``error``.
    """
    meta = get_dataset_meta(dataset_id)
    if meta is None:
        return {"error": f"Dataset {dataset_id} not found"}

    tbl = meta["tableName"]
    init_db()
    conn = _get_connection()
    try:
        result = conn.execute(f'SELECT * FROM "{tbl}"')
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

        import io
        import csv as csv_mod
        output = io.StringIO()
        writer = csv_mod.writer(output)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)

        return {"csv": output.getvalue(), "fileName": meta["fileName"]}
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        conn.close()


def execute_query(
    sql: str,
    limit: int = 1000,
) -> dict[str, Any]:
    """Execute a read-only SQL query and return results.

    Returns:
        A dict with keys ``data`` (list of row dicts), ``rowCount`` (int),
        and optionally ``error`` (str).
    """
    valid, error = validate_query(sql)
    if not valid:
        return {"data": [], "rowCount": 0, "error": error}

    init_db()
    conn = _get_connection()
    try:
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows_raw = result.fetchmany(limit)
        data = [dict(zip(columns, row)) for row in rows_raw]
        return {"data": data, "rowCount": len(data)}
    except Exception as exc:
        return {"data": [], "rowCount": 0, "error": str(exc)}
    finally:
        conn.close()
