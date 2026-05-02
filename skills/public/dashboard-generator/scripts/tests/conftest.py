"""Shared test fixtures for dashboard-generator tests."""

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
    """Create a small CSV with revenue/customer_id/order_date columns."""
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
def con():
    """Provide an in-memory DuckDB connection."""
    c = duckdb.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def sample_data():
    """Return sample data rows matching the CSV schema."""
    return [
        {"order_date": "2024-01-01", "revenue": 100.0, "customer_id": "C001"},
        {"order_date": "2024-01-02", "revenue": 200.0, "customer_id": "C002"},
        {"order_date": "2024-01-03", "revenue": 150.0, "customer_id": "C001"},
        {"order_date": "2024-01-04", "revenue": 300.0, "customer_id": "C003"},
        {"order_date": "2024-01-05", "revenue": 50.0, "customer_id": "C002"},
    ]


@pytest.fixture
def minimal_spec():
    """Return a minimal dashboard spec."""
    return {
        "title": "Test Dashboard",
        "layout": "grid",
        "charts": [
            {
                "id": "chart1",
                "type": "line",
                "x": "order_date",
                "y": ["revenue"],
                "title": "Revenue Trend",
            }
        ],
        "kpis": [
            {"label": "Total Revenue", "format": "currency"},
        ],
        "filters": [],
    }
