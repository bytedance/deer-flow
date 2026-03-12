"""File upload parser for AI Graphs.

Parses CSV and Excel files, infers column types, and stores them in the local
DuckDB database via :mod:`duckdb_client`.
"""

import csv
import io
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .duckdb_client import insert_dataset

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Column type inference
# --------------------------------------------------------------------------- #

def _infer_column_types(data: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Infer column types from the first 100 rows of data.

    Types returned are ``"number"``, ``"date"``, or ``"string"``.
    """
    if not data:
        return []

    keys = list(data[0].keys())
    result: list[dict[str, str]] = []

    for name in keys:
        sample = [row.get(name) for row in data[:100] if row.get(name) is not None and row.get(name) != ""]
        if sample and all(_is_numeric(v) for v in sample):
            result.append({"name": name, "type": "number"})
        elif sample and all(_is_date(v) for v in sample):
            result.append({"name": name, "type": "string"})  # store dates as string for SQL flexibility
        else:
            result.append({"name": name, "type": "string"})

    return result


def _is_numeric(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
            return True
        except (ValueError, AttributeError):
            return False
    return False


def _is_date(value: Any) -> bool:
    if isinstance(value, datetime):
        return True
    if isinstance(value, str):
        # Common date patterns
        patterns = [
            r"\d{4}-\d{2}-\d{2}",
            r"\d{2}/\d{2}/\d{4}",
            r"\d{2}-\d{2}-\d{4}",
        ]
        return any(re.match(p, value.strip()) for p in patterns)
    return False


# --------------------------------------------------------------------------- #
# Normalize Excel dates
# --------------------------------------------------------------------------- #

_DATE_NAME_PATTERN = re.compile(
    r"date|time|created|updated|signed|started|ended|month|year|day|period",
    re.IGNORECASE,
)


def _normalize_dates(data: list[dict[str, Any]]) -> None:
    """Convert ``datetime`` objects and Excel serial numbers to ISO date strings in-place."""
    if not data:
        return

    keys = list(data[0].keys())
    date_columns: set[str] = set()

    # Detect columns with datetime objects
    for key in keys:
        for row in data[:10]:
            if isinstance(row.get(key), datetime):
                date_columns.add(key)
                break

    # Detect columns that look like Excel serial numbers
    for key in keys:
        if key in date_columns:
            continue
        if not _DATE_NAME_PATTERN.search(key):
            continue
        sample = [row.get(key) for row in data[:10] if row.get(key) is not None]
        if sample and all(isinstance(v, (int, float)) and 1 < v < 200000 for v in sample):
            date_columns.add(key)

    for row in data:
        for key in date_columns:
            v = row.get(key)
            if isinstance(v, datetime):
                row[key] = v.strftime("%Y-%m-%d")
            elif isinstance(v, (int, float)) and 1 < v < 200000:
                try:
                    dt = datetime.fromtimestamp((v - 25569) * 86400)
                    row[key] = dt.strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    pass


# --------------------------------------------------------------------------- #
# Parse CSV
# --------------------------------------------------------------------------- #

def _parse_csv(content: bytes, file_name: str) -> list[dict[str, Any]]:
    """Parse CSV bytes into a list of row dicts."""
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    data = [dict(row) for row in reader]
    return data


# --------------------------------------------------------------------------- #
# Parse Excel
# --------------------------------------------------------------------------- #

def _parse_excel(content: bytes, file_name: str) -> list[dict[str, Any]]:
    """Parse XLSX/XLS bytes into a list of row dicts (first sheet only)."""
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl is required for Excel file parsing. Install it with: uv add openpyxl")

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return []

    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        wb.close()
        return []

    headers = [str(h) if h is not None else f"column_{i}" for i, h in enumerate(rows[0])]
    data: list[dict[str, Any]] = []
    for row in rows[1:]:
        row_dict: dict[str, Any] = {}
        for i, val in enumerate(row):
            if i < len(headers):
                row_dict[headers[i]] = val
        data.append(row_dict)

    wb.close()
    _normalize_dates(data)
    return data


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def parse_and_store_file(
    content: bytes,
    file_name: str,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    """Parse an uploaded file and store it in DuckDB.

    Supports ``.csv``, ``.xlsx``, and ``.xls`` files.

    Args:
        content: Raw file bytes.
        file_name: Original file name (used to determine format).
        dataset_id: Optional dataset ID. Generated if not provided.

    Returns:
        A dict with ``id``, ``fileName``, ``columns``, ``rowCount``.

    Raises:
        ValueError: If the file type is unsupported.
    """
    lower_name = file_name.lower()
    if lower_name.endswith(".csv"):
        data = _parse_csv(content, file_name)
    elif lower_name.endswith((".xlsx", ".xls")):
        data = _parse_excel(content, file_name)
    else:
        raise ValueError(f"Unsupported file type: {file_name}. Use .csv, .xlsx, or .xls")

    if not data:
        raise ValueError(f"No data found in {file_name}")

    columns = _infer_column_types(data)
    ds_id = dataset_id or str(uuid.uuid4())

    insert_dataset(ds_id, file_name, columns, data)

    return {
        "id": ds_id,
        "fileName": file_name,
        "columns": columns,
        "rowCount": len(data),
    }
