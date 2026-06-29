from pathlib import Path

import pytest

from ai_report.definition_store import connect_definitions, init_definition_schema


@pytest.fixture
def definitions_db(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    con = connect_definitions(db_path)
    init_definition_schema(con)
    try:
        yield con
    finally:
        con.close()