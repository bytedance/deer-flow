"""Execute integer predicates against JSON values, including oversized numbers."""

import json
import os

import pytest
from sqlalchemy import JSON, Column, MetaData, String, Table, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.json_compat import json_match


@pytest.fixture(params=["sqlite", "postgresql"])
async def json_table(request):
    if request.param == "postgresql":
        url = os.getenv("DEERFLOW_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("set DEERFLOW_TEST_POSTGRES_URL to exercise real PostgreSQL integer matching")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    else:
        url = "sqlite+aiosqlite:///:memory:"

    engine = create_async_engine(url)
    # A connection-local table keeps opt-in PostgreSQL runs isolated from any
    # application schema and is discarded even when an assertion fails.
    table = Table("json_integer_matching", MetaData(), Column("id", String), Column("data", JSON), prefixes=["TEMPORARY"])
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.run_sync(table.create)
                yield connection, table
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("expected", [-(2**63), -(2**63) + 1, -42, -1, 0, 1, 42, 2**63 - 2, 2**63 - 1])
async def test_integer_filter_ignores_unrepresentable_stored_numbers(json_table, expected):
    connection, table = json_table
    integers = [-(2**63), -(2**63) + 1, -42, -1, 0, 1, 42, 2**63 - 2, 2**63 - 1]
    rows = [{"id": str(value), "data": json.dumps({"x": value})} for value in integers]
    rows += [
        {"id": "below-min", "data": json.dumps({"x": -(2**63) - 1})},
        {"id": "above-max", "data": json.dumps({"x": 2**63})},
        {"id": "large-negative", "data": json.dumps({"x": -(10**100)})},
        {"id": "large-positive", "data": json.dumps({"x": 10**100})},
        # PostgreSQL JSON accepts numbers beyond even NUMERIC's precision.
        {"id": "beyond-numeric", "data": '{"x": ' + "9" * 131073 + "}"},
        {"id": "negative-zero", "data": '{"x": -0}'},
        {"id": "float", "data": json.dumps({"x": float(expected)})},
        {"id": "exponent", "data": '{"x": 42e0}'},
        {"id": "string", "data": json.dumps({"x": str(expected)})},
        {"id": "boolean", "data": '{"x": true}'},
        {"id": "null", "data": '{"x": null}'},
        {"id": "array", "data": '{"x": [42]}'},
        {"id": "object", "data": '{"x": {}}'},
        {"id": "missing", "data": "{}"},
    ]
    # Insert raw JSON to retain -0 and exponent spellings on both backends.
    await connection.execute(text("INSERT INTO json_integer_matching (id, data) VALUES (:id, :data)"), rows)
    result = await connection.execute(select(table.c.id).where(json_match(table.c.data, "x", expected)))
    expected_ids = {str(expected)} | ({"negative-zero"} if expected == 0 else set())
    assert set(result.scalars()) == expected_ids
