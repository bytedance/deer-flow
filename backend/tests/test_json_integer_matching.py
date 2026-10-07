"""Execute numeric predicates against JSON values, including out-of-range numbers."""

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
            pytest.skip("set DEERFLOW_TEST_POSTGRES_URL to exercise real PostgreSQL numeric matching")
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


# Zero and infinite filters are left out on purpose: SQLite saturates stored
# spellings beyond DOUBLE PRECISION to +/-0.0 or +/-inf, whereas PostgreSQL
# treats them as never matching, so only those filters differ by backend.
# (Exact-zero spellings such as 0e400 still match 0.0 on both backends.)
_FINITE_FLOATS = [-1.7976931348623157e308, -1.5, -5e-324, 5e-324, 1.5, 42.0, 1.7976931348623157e308]


@pytest.mark.anyio
@pytest.mark.parametrize("expected", _FINITE_FLOATS)
async def test_float_filter_ignores_out_of_range_stored_numbers(json_table, expected):
    connection, table = json_table
    rows = [{"id": str(value), "data": json.dumps({"x": value})} for value in _FINITE_FLOATS]
    rows += [
        # PostgreSQL refuses to cast these spellings to DOUBLE PRECISION:
        # overflow and underflow to zero both raise SQLSTATE 22003, so a
        # single such row used to fail every float filter on the table.
        # beyond-numeric / huge-exponent would also overflow the NUMERIC
        # bounds check, and 0e400 must take the exact-zero branch for the
        # same reason; overflow-ulp is the first spelling above DBL_MAX.
        # big-integer is the spelling the API can store: json.loads keeps
        # integers exact, while 1e400 becomes inf, which PostgreSQL's json
        # type rejects on write.
        {"id": "big-integer", "data": json.dumps({"x": 10**309})},
        {"id": "overflow", "data": '{"x": 1e400}'},
        {"id": "negative-overflow", "data": '{"x": -1e400}'},
        {"id": "underflow", "data": '{"x": 1e-400}'},
        {"id": "negative-underflow", "data": '{"x": -1e-400}'},
        {"id": "beyond-numeric", "data": '{"x": ' + "9" * 131073 + "}"},
        {"id": "huge-exponent", "data": '{"x": 1e100000}'},
        # NUMERIC keeps at most 16383 fractional digits, so these raised
        # inside the NUMERIC bounds check despite a five-digit exponent.
        {"id": "deep-underflow", "data": '{"x": 1e-16384}'},
        {"id": "deeper-underflow", "data": '{"x": -1e-20000}'},
        {"id": "overflow-ulp", "data": '{"x": 1.7976931348623159e+308}'},
        {"id": "zero-huge-exp", "data": '{"x": 0e400}'},
        # JSON allows leading zeros in the exponent; this is 1.5 and must match.
        {"id": "padded-exponent", "data": '{"x": 15e-000001}'},
        {"id": "integer", "data": '{"x": 42}'},
        {"id": "string", "data": json.dumps({"x": str(expected)})},
        {"id": "nan-string", "data": '{"x": "NaN"}'},
        {"id": "boolean", "data": '{"x": true}'},
        {"id": "null", "data": '{"x": null}'},
        {"id": "array", "data": json.dumps({"x": [expected]})},
        {"id": "missing", "data": "{}"},
    ]
    await connection.execute(text("INSERT INTO json_integer_matching (id, data) VALUES (:id, :data)"), rows)
    result = await connection.execute(select(table.c.id).where(json_match(table.c.data, "x", expected)))
    expected_ids = {str(expected)} | ({"integer"} if expected == 42 else set())
    expected_ids |= {"padded-exponent"} if expected == 1.5 else set()
    assert set(result.scalars()) == expected_ids
