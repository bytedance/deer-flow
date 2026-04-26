"""Extended canvas tools for canvas-analysis skill.

These tools provide database introspection capabilities for the canvas-analysis skill.
"""

import asyncio
import json
import logging
import re
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT
from pydantic import BaseModel

from deerflow.agents.thread_state import ThreadState
from deerflow.canvas.storage import CanvasStorage
from deerflow.config import get_app_config
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


def _get_thread_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str | None:
    """Resolve thread ID from runtime context."""
    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if thread_id:
        return thread_id

    runtime_config = getattr(runtime, "config", None) or {}
    return runtime_config.get("configurable", {}).get("thread_id")


def _get_storage() -> CanvasStorage:
    """Get canvas storage instance."""
    return CanvasStorage(base_dir=get_paths().base_dir)


def _get_db_connections() -> dict[str, dict[str, Any]]:
    """Get database connections from config as dict."""
    config = get_app_config()
    db_connections: dict[str, dict[str, Any]] = {}

    if hasattr(config, "db_connections") and config.db_connections:
        for conn in config.db_connections:
            if isinstance(conn, dict):
                conn_name = conn.get("name", "unknown")
                db_connections[conn_name] = conn
            else:
                conn_name = getattr(conn, "name", "unknown")
                db_connections[conn_name] = conn.model_dump()

    return db_connections


class TableColumnInfo(BaseModel):
    """Column information."""

    name: str
    type: str
    nullable: bool = True


# ============================================================
# Tool 1: canvas_inspect
# ============================================================


@tool("canvas_inspect")
def canvas_inspect_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Inspect the current canvas state including nodes, edges and available variables.

    Call this tool BEFORE adding any node to understand the current state.
    """
    thread_id = _get_thread_id(runtime)
    if not thread_id:
        return Command(
            update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]},
        )

    storage = _get_storage()
    canvas = storage.load(thread_id)

    if canvas is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Canvas is empty. No canvas exists for this thread.\nUse canvas_plan to create a new canvas.",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

    # Build available variables from nodes
    available_variables: list[dict[str, str]] = []

    for node in canvas.nodes:
        if node.type.value == "data_source":
            if node.data.get("table_name"):
                available_variables.append(
                    {
                        "name": f"{{{{{node.id}.table_name}}}}",
                        "value": str(node.data.get("table_name", "")),
                        "node_id": node.id,
                        "node_type": node.type.value,
                    }
                )
        elif node.type.value == "sql_executor":
            if node.data.get("output_table"):
                available_variables.append(
                    {
                        "name": f"{{{{{node.id}.output_table}}}}",
                        "value": str(node.data.get("output_table", "")),
                        "node_id": node.id,
                        "node_type": node.type.value,
                    }
                )
        elif node.type.value == "python_script":
            if node.data.get("output_table"):
                available_variables.append(
                    {
                        "name": f"{{{{{node.id}.output_table}}}}",
                        "value": str(node.data.get("output_table", "")),
                        "node_id": node.id,
                        "node_type": node.type.value,
                    }
                )

    # Build response
    result = {
        "canvas_id": canvas.id,
        "status": canvas.status.value,
        "name": canvas.name,
        "description": canvas.description,
        "nodes": [
            {
                "id": node.id,
                "type": node.type.value,
                "config": node.data,
                "position": {"x": node.position.x, "y": node.position.y},
            }
            for node in canvas.nodes
        ],
        "edges": [{"source": edge.source, "target": edge.target} for edge in canvas.edges],
        "available_variables": available_variables,
        "execution_log": [
            {
                "node_id": log.node_id,
                "success": log.success,
                "output_table": log.output_table,
                "rows_affected": log.rows_affected,
            }
            for log in canvas.execution_log
        ],
    }

    result_json = json.dumps(result, ensure_ascii=False, indent=2)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Canvas State:\n```json\n{result_json}\n```",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


# ============================================================
# Tool 2: canvas_list_tables
# ============================================================


@tool("canvas_list_tables")
async def canvas_list_tables_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    connection_id: str = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """List available tables from database connections.

    Args:
        connection_id: Optional specific connection ID to list tables from a specific connection.
    """
    db_connections = _get_db_connections()

    if not db_connections:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "No database connections configured. Please configure db_connections in config.yaml.",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

    results: list[dict[str, Any]] = []

    for conn_id, conn_config in db_connections.items():
        if connection_id and conn_id != connection_id:
            continue

        try:
            tables = await _get_tables_from_connection(conn_config)
            results.append(
                {
                    "connection_id": conn_id,
                    "connection_name": conn_config.get("name", conn_id),
                    "connection_type": conn_config.get("type", "unknown"),
                    "tables": tables,
                }
            )
        except Exception as e:
            logger.error(f"Failed to list tables for {conn_id}: {e}")
            results.append(
                {
                    "connection_id": conn_id,
                    "connection_name": conn_config.get("name", conn_id),
                    "error": str(e),
                }
            )

    result_json = json.dumps({"connections": results}, ensure_ascii=False, indent=2)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    f"Available Tables:\n```json\n{result_json}\n```",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )


# ============================================================
# Tool 3: canvas_table_schema
# ============================================================


@tool("canvas_table_schema")
async def canvas_table_schema_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    connection_id: str,
    table_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Get the schema (columns) of a specific table.

    Args:
        connection_id: The database connection ID.
        table_name: The name of the table to inspect.
    """
    db_connections = _get_db_connections()

    if connection_id not in db_connections:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Connection '{connection_id}' not found. Available connections: {list(db_connections.keys())}",
                        tool_call_id=tool_call_id,
                    )
                ]
            },
        )

    conn_config = db_connections[connection_id]

    try:
        columns = await _get_table_schema(conn_config, table_name)

        result = {
            "connection_id": connection_id,
            "table_name": table_name,
            "columns": [col.model_dump() for col in columns],
        }
        result_json = json.dumps(result, ensure_ascii=False, indent=2)

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Table Schema for '{table_name}':\n```json\n{result_json}\n```",
                        tool_call_id=tool_call_id,
                    )
                ],
            },
        )
    except Exception as e:
        logger.error(f"Failed to get schema for {table_name}: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Error getting schema for '{table_name}': {str(e)}",
                        tool_call_id=tool_call_id,
                    )
                ],
            },
        )


# ============================================================
# Tool 4: canvas_preview_data
# ============================================================


@tool("canvas_preview_data")
async def canvas_preview_data_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    source: str,
    limit: int = 100,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Preview data from a table or a node's output.

    Args:
        source: Data source - either a table name or node ID (e.g., "node-2").
        limit: Maximum number of rows to return. Default 100, max 1000.
    """
    thread_id = _get_thread_id(runtime)

    # Limit validation
    limit = min(max(1, limit), 1000)

    # Check if source is a node ID
    if source.startswith("node-"):
        if not thread_id:
            return Command(
                update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]},
            )

        storage = _get_storage()
        canvas = storage.load(thread_id)

        if canvas is None:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"No canvas found. Cannot preview node '{source}'.",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

        # Find the node
        node = None
        for n in canvas.nodes:
            if n.id == source:
                node = n
                break

        if node is None:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Node '{source}' not found in canvas.",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

        # Get output table from node
        output_table = None
        if node.type.value == "data_source":
            output_table = node.data.get("table_name")
        elif node.type.value in ("sql_executor", "python_script"):
            output_table = node.data.get("output_table")

        if not output_table:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Node '{source}' does not have an output table defined.",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

        # Find connection_id for data_source nodes
        connection_id = None
        if node.type.value == "data_source":
            connection_id = node.data.get("connection_id")
        else:
            # For other nodes, find upstream data_source
            for edge in canvas.edges:
                if edge.target == source:
                    for n in canvas.nodes:
                        if n.id == edge.source and n.type.value == "data_source":
                            connection_id = n.data.get("connection_id")
                            break
                    if connection_id:
                        break

        if not connection_id:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Cannot determine database connection for node '{source}'.",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

        # Preview the output table
        db_connections = _get_db_connections()
        if connection_id not in db_connections:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Connection '{connection_id}' not found.",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

        try:
            rows, total_rows = await _preview_table_data(db_connections[connection_id], output_table, limit)

            result = {
                "source": source,
                "table_name": output_table,
                "rows": rows,
                "total_rows": total_rows,
                "returned_rows": len(rows),
            }
            result_json = json.dumps(result, ensure_ascii=False, indent=2)

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Data Preview from '{source}' (table: {output_table}):\n```json\n{result_json}\n```",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )
        except Exception as e:
            logger.error(f"Failed to preview data from {source}: {e}")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Error previewing data from '{source}': {str(e)}",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

    else:
        # Source is a table name - need to find connection
        connection_id = None

        if thread_id:
            storage = _get_storage()
            canvas = storage.load(thread_id)

            if canvas:
                # Find first data_source with a connection
                for node in canvas.nodes:
                    if node.type.value == "data_source" and node.data.get("connection_id"):
                        connection_id = node.data.get("connection_id")
                        break

        if not connection_id:
            # Use first available connection
            db_connections = _get_db_connections()
            if db_connections:
                connection_id = list(db_connections.keys())[0]

        if not connection_id:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            "No database connection available. Please add a data_source node first or specify a node ID.",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

        db_connections = _get_db_connections()
        if connection_id not in db_connections:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Connection '{connection_id}' not found.",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )

        try:
            rows, total_rows = await _preview_table_data(db_connections[connection_id], source, limit)

            result = {
                "source": source,
                "connection_id": connection_id,
                "rows": rows,
                "total_rows": total_rows,
                "returned_rows": len(rows),
            }
            result_json = json.dumps(result, ensure_ascii=False, indent=2)

            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Data Preview from table '{source}':\n```json\n{result_json}\n```",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )
        except Exception as e:
            logger.error(f"Failed to preview table {source}: {e}")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Error previewing table '{source}': {str(e)}",
                            tool_call_id=tool_call_id,
                        )
                    ]
                },
            )


# ============================================================
# Helper Functions
# ============================================================


def _get_tables_from_connection_sync(conn: Any) -> list[str]:
    """Synchronous helper to get list of tables from a database connection."""
    import sqlalchemy
    from sqlalchemy import inspect, text

    conn_type = conn.get("type", "unknown") if isinstance(conn, dict) else getattr(conn, "type", "unknown")
    engine = sqlalchemy.create_engine(_build_connection_url(conn))

    with engine.connect() as connection:
        if conn_type in ("mysql", "mariadb"):
            result = connection.execute(text("SHOW TABLES"))
            return [row[0] for row in result]
        elif conn_type in ("postgres", "postgresql"):
            result = connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
            return [row[0] for row in result]
        else:
            inspector = inspect(engine)
            return inspector.get_table_names()


async def _get_tables_from_connection(conn: Any) -> list[str]:
    """Get list of tables from a database connection (async wrapper)."""
    return await asyncio.to_thread(_get_tables_from_connection_sync, conn)


def _get_table_schema_sync(conn: Any, table_name: str) -> list[TableColumnInfo]:
    """Synchronous helper to get column info for a table."""
    import sqlalchemy
    from sqlalchemy import inspect

    engine = sqlalchemy.create_engine(_build_connection_url(conn))
    inspector = inspect(engine)

    # Validate table name to prevent SQL injection
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        raise ValueError(f"Invalid table name: '{table_name}'")

    columns = inspector.get_columns(table_name)

    return [
        TableColumnInfo(
            name=col["name"],
            type=str(col["type"]),
            nullable=col.get("nullable", True),
        )
        for col in columns
    ]


async def _get_table_schema(conn: Any, table_name: str) -> list[TableColumnInfo]:
    """Get column info for a table (async wrapper)."""
    return await asyncio.to_thread(_get_table_schema_sync, conn, table_name)


def _serialize_value(obj: Any) -> Any:
    """Convert non-JSON-serializable types to serializable ones."""
    from datetime import date, datetime
    from decimal import Decimal

    if obj is None:
        return None
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj


def _preview_table_data_sync(conn: Any, table_name: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Synchronous helper to get preview data from a table."""
    import sqlalchemy
    from sqlalchemy import text

    engine = sqlalchemy.create_engine(_build_connection_url(conn))
    conn_type = conn.get("type", "unknown") if isinstance(conn, dict) else getattr(conn, "type", "unknown")

    # Validate table name
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        raise ValueError(f"Invalid table name: '{table_name}'")

    # Quote character based on database type
    quote_char = "`" if conn_type in ("mysql", "mariadb") else '"'

    with engine.connect() as connection:
        # Get total count
        count_result = connection.execute(text(f"SELECT COUNT(*) FROM {quote_char}{table_name}{quote_char}"))
        total_rows = count_result.scalar() or 0

        # Get preview rows with parameterized limit
        result = connection.execute(
            text(f"SELECT * FROM {quote_char}{table_name}{quote_char} LIMIT :limit"),
            {"limit": limit},
        )
        rows = [{k: _serialize_value(v) for k, v in row._mapping.items()} for row in result]

        return rows, total_rows


async def _preview_table_data(conn: Any, table_name: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Get preview data from a table (async wrapper)."""
    return await asyncio.to_thread(_preview_table_data_sync, conn, table_name, limit)


def _build_connection_url(conn: Any) -> str:
    """Build database connection URL from config."""
    if isinstance(conn, dict):
        url = conn.get("url")
        if url:
            return url

        conn_type = conn.get("type", "unknown")
        host = conn.get("host", "localhost")
        port = conn.get("port")
        database = conn.get("database", "")
        username = conn.get("username", "")
        password = conn.get("password", "")

        if conn_type in ("mysql", "mariadb"):
            port = port or 3306
            return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
        elif conn_type in ("postgres", "postgresql"):
            port = port or 5432
            return f"postgresql://{username}:{password}@{host}:{port}/{database}"
        else:
            raise ValueError(f"Unsupported database type: {conn_type}")
    else:
        # Pydantic model
        url = getattr(conn, "url", None)
        if url:
            return url

        conn_type = getattr(conn, "type", "unknown")
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


# ============================================================
# Export
# ============================================================

CANVAS_EXT_TOOLS = [
    canvas_inspect_tool,
    canvas_list_tables_tool,
    canvas_table_schema_tool,
    canvas_preview_data_tool,
]

__all__ = [
    "canvas_inspect_tool",
    "canvas_list_tables_tool",
    "canvas_table_schema_tool",
    "canvas_preview_data_tool",
    "CANVAS_EXT_TOOLS",
]
