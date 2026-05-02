"""Shared test fixtures for report-template tests."""

import csv
import os
import tempfile

import duckdb
import pytest


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sample_csv(tmp_dir):
    """Create a CSV with revenue/customer_id/order_date columns."""
    path = os.path.join(tmp_dir, "sales.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_date", "revenue", "customer_id"])
        w.writerow(["2024-01-01", 100.0, "C001"])
        w.writerow(["2024-01-02", 200.0, "C002"])
        w.writerow(["2024-01-03", 150.0, "C001"])
        w.writerow(["2024-01-04", 300.0, "C003"])
        w.writerow(["2024-01-05", 50.0, "C002"])
    return path


@pytest.fixture
def minimal_csv(tmp_dir):
    """Create a CSV WITHOUT revenue/customer_id columns (for graceful degradation tests)."""
    path = os.path.join(tmp_dir, "events.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["event_name", "count"])
        w.writerow(["click", 10])
        w.writerow(["scroll", 25])
        w.writerow(["hover", 5])
    return path


@pytest.fixture
def con():
    """Provide an in-memory DuckDB connection."""
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def con_with_data(con, sample_csv):
    """DuckDB connection with sample CSV loaded as 'data' table."""
    con.execute("CREATE TABLE data AS SELECT * FROM read_csv_auto(?)", [sample_csv])
    return con


@pytest.fixture
def con_with_minimal_data(con, minimal_csv):
    """DuckDB connection with minimal CSV loaded (no revenue/customer_id)."""
    con.execute("CREATE TABLE data AS SELECT * FROM read_csv_auto(?)", [minimal_csv])
    return con


@pytest.fixture
def minimal_template():
    """Return a minimal report template."""
    return {
        "name": "test-report",
        "title": "Test Report",
        "theme": "light",
        "sections": [
            {
                "type": "kpi_row",
                "kpis": [
                    {"label": "Total Revenue", "field": "kpi_revenue", "format": "currency"},
                    {"label": "Total Orders", "field": "kpi_orders", "format": "number"},
                ],
            },
        ],
    }
