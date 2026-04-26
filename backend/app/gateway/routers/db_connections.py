# backend/app/gateway/routers/db_connections.py
"""Database connections REST API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["db-connections"])


class DbConnectionResponse(BaseModel):
    """Response model for database connection."""

    id: str = Field(..., description="Connection identifier")
    name: str = Field(..., description="Display name")
    type: str = Field(..., description="Database type (mysql, postgres, etc.)")


class DbConnectionsListResponse(BaseModel):
    """Response model for listing connections."""

    connections: list[DbConnectionResponse]


class TableColumnResponse(BaseModel):
    """Response model for table column."""

    name: str
    type: str
    nullable: bool


class TableSchemaResponse(BaseModel):
    """Response model for table schema."""

    columns: list[TableColumnResponse]


class TablesListResponse(BaseModel):
    """Response model for listing tables."""

    tables: list[str]


class TablePreviewResponse(BaseModel):
    """Response model for table preview."""

    rows: list[dict[str, Any]]
    total_rows: int


@router.get("/db-connections", response_model=DbConnectionsListResponse)
async def list_db_connections():
    """Get list of available database connections from config."""
    config = get_app_config()
    connections = []

    if hasattr(config, "db_connections") and config.db_connections:
        for conn in config.db_connections:
            connections.append(
                DbConnectionResponse(
                    id=conn.name,
                    name=conn.name,
                    type=conn.type if hasattr(conn, "type") else "unknown",
                )
            )

    return DbConnectionsListResponse(connections=connections)


@router.get("/db-connections/{connection_id}/tables", response_model=TablesListResponse)
async def list_tables(connection_id: str):
    """List tables in a database connection."""
    config = get_app_config()

    if not hasattr(config, "db_connections") or not config.db_connections:
        raise HTTPException(status_code=404, detail="No database connections configured")

    # Find the connection
    conn = None
    for c in config.db_connections:
        if c.name == connection_id:
            conn = c
            break

    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")

    # Get tables using the connection
    try:
        tables = await _get_tables_from_connection(conn)
        return TablesListResponse(tables=tables)
    except Exception as e:
        logger.error(f"Failed to list tables for {connection_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect: {str(e)}")


@router.get(
    "/db-connections/{connection_id}/tables/{table_name}/schema",
    response_model=TableSchemaResponse,
)
async def get_table_schema(connection_id: str, table_name: str):
    """Get schema for a specific table."""
    config = get_app_config()

    if not hasattr(config, "db_connections") or not config.db_connections:
        raise HTTPException(status_code=404, detail="No database connections configured")

    conn = None
    for c in config.db_connections:
        if c.name == connection_id:
            conn = c
            break

    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")

    try:
        columns = await _get_table_schema(conn, table_name)
        return TableSchemaResponse(columns=columns)
    except Exception as e:
        logger.error(f"Failed to get schema for {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get schema: {str(e)}")


@router.get(
    "/db-connections/{connection_id}/tables/{table_name}/preview",
    response_model=TablePreviewResponse,
)
async def preview_table(connection_id: str, table_name: str, limit: int = 100):
    """Preview data from a table."""
    config = get_app_config()

    if not hasattr(config, "db_connections") or not config.db_connections:
        raise HTTPException(status_code=404, detail="No database connections configured")

    conn = None
    for c in config.db_connections:
        if c.name == connection_id:
            conn = c
            break

    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")

    try:
        rows, total_rows = await _preview_table_data(conn, table_name, limit)
        return TablePreviewResponse(rows=rows, total_rows=total_rows)
    except Exception as e:
        logger.error(f"Failed to preview {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to preview: {str(e)}")


# Helper functions - these will use the actual database connection logic
async def _get_tables_from_connection(conn: Any) -> list[str]:
    """Get list of tables from a database connection."""
    # Import based on connection type
    conn_type = conn.type if hasattr(conn, "type") else "unknown"

    if conn_type in ("mysql", "mariadb"):
        import sqlalchemy
        from sqlalchemy import text

        engine = sqlalchemy.create_engine(_build_connection_url(conn))
        with engine.connect() as connection:
            result = connection.execute(text("SHOW TABLES"))
            return [row[0] for row in result]

    elif conn_type in ("postgres", "postgresql"):
        import sqlalchemy
        from sqlalchemy import text

        engine = sqlalchemy.create_engine(_build_connection_url(conn))
        with engine.connect() as connection:
            result = connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
            return [row[0] for row in result]

    else:
        # Generic approach
        import sqlalchemy
        from sqlalchemy import inspect

        engine = sqlalchemy.create_engine(_build_connection_url(conn))
        inspector = inspect(engine)
        return inspector.get_table_names()


async def _get_table_schema(conn: Any, table_name: str) -> list[TableColumnResponse]:
    """Get column info for a table."""
    import sqlalchemy
    from sqlalchemy import inspect

    engine = sqlalchemy.create_engine(_build_connection_url(conn))
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)

    return [
        TableColumnResponse(
            name=col["name"],
            type=str(col["type"]),
            nullable=col.get("nullable", True),
        )
        for col in columns
    ]


async def _preview_table_data(conn: Any, table_name: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Get preview data from a table."""
    import sqlalchemy
    from sqlalchemy import text

    engine = sqlalchemy.create_engine(_build_connection_url(conn))

    with engine.connect() as connection:
        # Get total count
        count_result = connection.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        total_rows = count_result.scalar() or 0

        # Get preview rows
        result = connection.execute(text(f'SELECT * FROM "{table_name}" LIMIT {limit}'))
        rows = [dict(row._mapping) for row in result]

        return rows, total_rows


def _build_connection_url(conn: Any) -> str:
    """Build database connection URL from config."""
    if hasattr(conn, "url"):
        return conn.url

    # Build from components
    conn_type = conn.type if hasattr(conn, "type") else "unknown"
    host = getattr(conn, "host", "localhost")
    port = getattr(conn, "port", None)
    database = getattr(conn, "database", "")
    username = getattr(conn, "username", "")
    password = getattr(conn, "password", "")

    if conn_type in ("mysql", "mariadb"):
        port = port or 3306
        return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
    elif conn_type in ("postgres", "postgresql"):
        port = port or 5432
        return f"postgresql://{username}:{password}@{host}:{port}/{database}"
    else:
        raise ValueError(f"Unsupported database type: {conn_type}")
