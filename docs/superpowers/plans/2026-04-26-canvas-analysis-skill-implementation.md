# Canvas Analysis Skill 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 canvas-analysis 技能，帮助用户通过 Canvas DAG 构建可复用的数据处理管道。

**Architecture:** 后端新增 4 个 Canvas 工具（inspect, list_tables, table_schema, preview_data），前端技能目录创建 SKILL.md 技能说明文档。

**Tech Stack:** Python (LangChain Tools), Pydantic, SQLAlchemy, Markdown

---

## 文件结构

### 后端新增/修改

| 文件 | 职责 |
|------|------|
| `backend/packages/harness/deerflow/canvas/tools.py` | 修改：添加 4 个新工具 |
| `backend/packages/harness/deerflow/canvas/tools_ext.py` | 新增：扩展工具（列表表、表结构、预览） |

### 前端技能新增

| 文件 | 职责 |
|------|------|
| `skills/public/canvas-analysis/SKILL.md` | 新增：技能说明文档 |

---

## Task 1: 后端 - 创建扩展工具模块

**Files:**
- Create: `backend/packages/harness/deerflow/canvas/tools_ext.py`

- [ ] **Step 1: 创建扩展工具模块**

```python
# backend/packages/harness/deerflow/canvas/tools_ext.py
"""Extended canvas tools for canvas-analysis skill.

These tools provide database introspection capabilities for the canvas-analysis skill.
"""

import logging
from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.canvas.models import Canvas, CanvasStatus, CanvasNode
from deerflow.canvas.storage import CanvasStorage
from deerflow.config import get_app_config
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


def _get_thread_id(runtime: ToolRuntime[ContextT, dict]) -> str | None:
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


# ============================================================
# Tool 1: canvas_inspect
# ============================================================

@tool("canvas_inspect", parse_docstring=True)
def canvas_inspect_tool(
    runtime: ToolRuntime[ContextT, dict],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Inspect the current canvas state.

    Use this tool to get detailed information about the canvas including:
    - Canvas ID and status
    - All nodes with their configurations
    - All edges connecting nodes
    - Available variables from executed nodes

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
                        "Canvas is empty. No canvas exists for this thread.\n"
                        "Use canvas_plan_tool to create a new canvas.",
                        tool_call_id=tool_call_id,
                    )
                ],
            },
        )

    # Build available variables from nodes
    available_variables: list[dict[str, str]] = []

    for node in canvas.nodes:
        if node.type == "data_source":
            if node.data.get("table_name"):
                available_variables.append({
                    "name": f"{{{{{node.id}.table_name}}}}",
                    "value": str(node.data.get("table_name", "")),
                    "node_id": node.id,
                    "node_type": node.type.value,
                })
        elif node.type == "sql_executor":
            if node.data.get("output_table"):
                available_variables.append({
                    "name": f"{{{{{node.id}.output_table}}}}",
                    "value": str(node.data.get("output_table", "")),
                    "node_id": node.id,
                    "node_type": node.type.value,
                })
        elif node.type == "python_script":
            if node.data.get("output_table"):
                available_variables.append({
                    "name": f"{{{{{node.id}.output_table}}}}",
                    "value": str(node.data.get("output_table", "")),
                    "node_id": node.id,
                    "node_type": node.type.value,
                })

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
        "edges": [
            {"source": edge.source, "target": edge.target}
            for edge in canvas.edges
        ],
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

    import json
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

class TablesListResult(BaseModel):
    """Result model for tables list."""
    connections: list[dict[str, Any]]


@tool("canvas_list_tables", parse_docstring=True)
async def canvas_list_tables_tool(
    runtime: ToolRuntime[ContextT, dict],
    connection_id: str = "",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """List available tables from database connections.

    Use this tool to discover what tables are available in the configured database connections.
    This helps you select the right table for a data_source node.

    Args:
        connection_id: Optional specific connection ID. If not provided, lists tables from all connections.
    """
    db_connections = _get_db_connections()

    if not db_connections:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "No database connections configured. "
                        "Please configure db_connections in config.yaml.",
                        tool_call_id=tool_call_id,
                    )
                ],
            },
        )

    results: list[dict[str, Any]] = []

    for conn_id, conn_config in db_connections.items():
        if connection_id and conn_id != connection_id:
            continue

        try:
            tables = await _get_tables_from_connection(conn_config)
            results.append({
                "connection_id": conn_id,
                "connection_name": conn_config.get("name", conn_id),
                "connection_type": conn_config.get("type", "unknown"),
                "tables": tables,
            })
        except Exception as e:
            logger.error(f"Failed to list tables for {conn_id}: {e}")
            results.append({
                "connection_id": conn_id,
                "connection_name": conn_config.get("name", conn_id),
                "error": str(e),
            })

    import json
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

@tool("canvas_table_schema", parse_docstring=True)
async def canvas_table_schema_tool(
    runtime: ToolRuntime[ContextT, dict],
    connection_id: str,
    table_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Get the schema (columns) of a specific table.

    Use this tool to understand the structure of a table before writing SQL queries.
    This shows column names, data types, and nullability.

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
                        f"Connection '{connection_id}' not found. "
                        f"Available connections: {list(db_connections.keys())}",
                        tool_call_id=tool_call_id,
                    )
                ],
            },
        )

    conn_config = db_connections[connection_id]

    try:
        columns = await _get_table_schema(conn_config, table_name)

        import json
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

@tool("canvas_preview_data", parse_docstring=True)
async def canvas_preview_data_tool(
    runtime: ToolRuntime[ContextT, dict],
    source: str,
    limit: int = 100,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Preview data from a table or a node's output.

    Use this tool to see the actual data from:
    - A database table (provide table name as source)
    - A node's output table (provide node ID like "node-1")

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
        if node.type == "data_source":
            output_table = node.data.get("table_name")
        elif node.type in ("sql_executor", "python_script"):
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
        if node.type == "data_source":
            connection_id = node.data.get("connection_id")
        else:
            # For other nodes, find upstream data_source
            for edge in canvas.edges:
                if edge.target == source:
                    for n in canvas.nodes:
                        if n.id == edge.source and n.type == "data_source":
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
            rows, total_rows = await _preview_table_data(
                db_connections[connection_id], output_table, limit
            )

            import json
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
        # Try to get from canvas context
        connection_id = None

        if thread_id:
            storage = _get_storage()
            canvas = storage.load(thread_id)

            if canvas:
                # Find first data_source with a connection
                for node in canvas.nodes:
                    if node.type == "data_source" and node.data.get("connection_id"):
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
                            "No database connection available. "
                            "Please add a data_source node first or specify a node ID.",
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
            rows, total_rows = await _preview_table_data(
                db_connections[connection_id], source, limit
            )

            import json
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

from pydantic import BaseModel


class TableColumnInfo(BaseModel):
    """Column information."""
    name: str
    type: str
    nullable: bool = True


async def _get_tables_from_connection(conn: Any) -> list[str]:
    """Get list of tables from a database connection."""
    import sqlalchemy
    from sqlalchemy import text

    conn_type = conn.get("type", "unknown") if isinstance(conn, dict) else getattr(conn, "type", "unknown")
    engine = sqlalchemy.create_engine(_build_connection_url(conn))

    with engine.connect() as connection:
        if conn_type in ("mysql", "mariadb"):
            result = connection.execute(text("SHOW TABLES"))
            return [row[0] for row in result]
        elif conn_type in ("postgres", "postgresql"):
            result = connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            )
            return [row[0] for row in result]
        else:
            from sqlalchemy import inspect
            inspector = inspect(engine)
            return inspector.get_table_names()


async def _get_table_schema(conn: Any, table_name: str) -> list[TableColumnInfo]:
    """Get column info for a table."""
    import sqlalchemy
    from sqlalchemy import inspect

    engine = sqlalchemy.create_engine(_build_connection_url(conn))
    inspector = inspect(engine)

    # Validate table name to prevent SQL injection
    import re
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


async def _preview_table_data(conn: Any, table_name: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Get preview data from a table."""
    import sqlalchemy
    from sqlalchemy import text

    engine = sqlalchemy.create_engine(_build_connection_url(conn))
    conn_type = conn.get("type", "unknown") if isinstance(conn, dict) else getattr(conn, "type", "unknown")

    # Validate table name
    import re
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        raise ValueError(f"Invalid table name: '{table_name}'")

    # Quote character based on database type
    quote_char = "`" if conn_type in ("mysql", "mariadb") else '"'

    with engine.connect() as connection:
        # Get total count
        count_result = connection.execute(
            text(f"SELECT COUNT(*) FROM {quote_char}{table_name}{quote_char}")
        )
        total_rows = count_result.scalar() or 0

        # Get preview rows with parameterized limit
        result = connection.execute(
            text(f"SELECT * FROM {quote_char}{table_name}{quote_char} LIMIT :limit"),
            {"limit": limit},
        )
        rows = [dict(row._mapping) for row in result]

        return rows, total_rows


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
```

- [ ] **Step 2: 运行 lint 验证**

Run: `cd /Users/frankliu/Code/deerflow/backend && make lint`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add backend/packages/harness/deerflow/canvas/tools_ext.py
git commit -m "feat(canvas): add extended canvas tools for analysis skill

- canvas_inspect: inspect current canvas state and available variables
- canvas_list_tables: list tables from database connections
- canvas_table_schema: get table column information
- canvas_preview_data: preview data from table or node output

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: 后端 - 注册工具到现有 tools.py

**Files:**
- Modify: `backend/packages/harness/deerflow/canvas/tools.py`

- [ ] **Step 1: 添加导入和导出**

在 `backend/packages/harness/deerflow/canvas/tools.py` 文件末尾添加：

```python
# 导入扩展工具
from deerflow.canvas.tools_ext import (
    canvas_inspect_tool,
    canvas_list_tables_tool,
    canvas_table_schema_tool,
    canvas_preview_data_tool,
    CANVAS_EXT_TOOLS,
)

# 扩展工具列表
CANVAS_TOOLS = [
    canvas_plan_tool,
    canvas_add_node_tool,
    canvas_add_edge_tool,
    canvas_execute_tool,
    canvas_status_tool,
    # 扩展工具
    canvas_inspect_tool,
    canvas_list_tables_tool,
    canvas_table_schema_tool,
    canvas_preview_data_tool,
]

__all__ = [
    "canvas_plan_tool",
    "canvas_add_node_tool",
    "canvas_add_edge_tool",
    "canvas_execute_tool",
    "canvas_status_tool",
    # 扩展工具
    "canvas_inspect_tool",
    "canvas_list_tables_tool",
    "canvas_table_schema_tool",
    "canvas_preview_data_tool",
    "CANVAS_TOOLS",
    "CANVAS_EXT_TOOLS",
]
```

- [ ] **Step 2: 运行 lint 验证**

Run: `cd /Users/frankliu/Code/deerflow/backend && make lint`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add backend/packages/harness/deerflow/canvas/tools.py
git commit -m "feat(canvas): register extended tools in CANVAS_TOOLS

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: 技能 - 创建 SKILL.md

**Files:**
- Create: `skills/public/canvas-analysis/SKILL.md`

- [ ] **Step 1: 创建技能目录**

```bash
mkdir -p /Users/frankliu/Code/deerflow/skills/public/canvas-analysis
```

- [ ] **Step 2: 创建 SKILL.md 文件**

```markdown
---
name: canvas-analysis
description: 用于数据分析场景，帮助用户通过 Canvas DAG 构建可复用的数据处理管道。从用户宽泛的分析请求中提炼具体目标，自动设计完整的 DAG 结构，为每个节点生成处理逻辑，执行后输出分析结果。
---

# Canvas 数据分析技能

## 概述

`canvas-analysis` 是一个数据分析技能，帮助用户通过 Canvas DAG 构建可复用的数据处理管道。技能从用户宽泛的分析请求中提炼具体目标，自动设计完整的 DAG 结构，为每个节点生成处理逻辑，执行后输出分析结果。

## 与现有技能的区别

| 技能 | 数据来源 | 处理方式 | 输出 | 适用场景 |
|-----|---------|---------|------|---------|
| data-analysis | 上传的 Excel/CSV 文件 | DuckDB 即时查询 | 一次性分析结果 | 快速分析本地文件 |
| canvas-analysis | 数据库连接（MySQL/PostgreSQL） | Canvas DAG 多节点管道 | 分析结果 + 可复用 DAG | 生产级数据处理管道 |

## 触发条件

当用户表达数据分析意图时自动触发：
- "帮我分析...数据"
- "做个报表"
- "统计一下..."
- "看看销售情况"
- 任何涉及数据库查询或多步骤数据处理的请求

## 核心流程

```
用户请求 → 需求提炼 → 观察环境 → 设计 DAG 方案 → 用户确认 → 构建 DAG → 执行与呈现
```

## 可用工具

| 工具 | 功能 | 使用时机 |
|-----|------|---------|
| `canvas_inspect_tool` | 检查 Canvas 当前状态 | 每次添加节点前调用 |
| `canvas_list_tables_tool` | 列出数据库连接中的表 | 选择数据源表时 |
| `canvas_table_schema_tool` | 获取表的字段结构 | 设计 SQL 查询前 |
| `canvas_preview_data_tool` | 预览表数据或节点输出 | 验证节点输出、展示结果 |
| `canvas_plan_tool` | 创建或更新 Canvas 描述 | 开始设计 DAG 时 |
| `canvas_add_node_tool` | 添加节点到 Canvas | 构建 DAG 时 |
| `canvas_add_edge_tool` | 添加边连接节点 | 构建 DAG 时 |
| `canvas_execute_tool` | 执行 DAG | 执行分析时 |

## DAG 设计模式

### 典型结构

```
data_source → sql_executor → [python_script] → data_output
```

### 节点类型与配置

#### data_source 节点

声明数据库表作为数据源。

**配置示例：**
```json
{
  "connection_id": "dataflow",
  "table_name": "dim_experiment",
  "display_name": "实验维度表"
}
```

**可用变量生成：** `{{node-X.table_name}}`

#### sql_executor 节点

执行 SQL 查询，生成新的结果表。

**配置示例：**
```json
{
  "output_table": "result_table_name",
  "sql": "SELECT ... FROM {{node-Y.table_name}} WHERE ...",
  "display_name": "描述性名称"
}
```

**重要：** SQL 中使用变量引用上游节点的表：`{{node-X.table_name}}` 或 `{{node-X.output_table}}`

#### python_script 节点

执行 Python 脚本进行复杂数据处理。

**配置示例：**
```json
{
  "output_table": "processed_table",
  "input_tables": ["{{node-X.output_table}}"],
  "script": "import pandas as pd\n...",
  "display_name": "处理脚本"
}
```

#### data_output 节点

导出数据到文件。

**配置示例：**
```json
{
  "input_table": "{{node-X.output_table}}",
  "output_format": "csv",
  "filename": "分析结果.csv"
}
```

### 按分析类型选择结构

| 分析类型 | DAG 结构 |
|---------|---------|
| 简单查询 | data_source → sql_executor → data_output |
| 多表关联 | 2+ data_source → sql_executor(JOIN) → data_output |
| 聚合统计 | data_source → sql_executor(GROUP BY) → data_output |
| 复杂处理 | data_source → sql_executor → python_script → data_output |
| 对比分析 | data_source → sql_executor(分组统计) → data_output |

## 执行流程

### Step 1: 需求提炼

从用户请求中提取：
- **分析目标**: 用户想得到什么结果？
- **时间范围**: 需要分析哪个时间段的数据？
- **筛选条件**: 需要哪些过滤条件？
- **输出类型**: 报表/统计/对比/趋势？

### Step 2: 观察环境

**关键步骤：每次添加节点前必须调用 `canvas_inspect_tool`**

```
canvas_inspect_tool() → 了解当前 Canvas 状态
canvas_list_tables_tool() → 了解可用数据源
canvas_table_schema_tool() → 了解表结构（按需）
```

**观察内容：**
- 当前 Canvas 是否为空
- 已有节点及其配置
- 已有边连接关系
- 可用变量列表

### Step 3: 设计 DAG 方案

向用户展示：
- 将使用的表及原因
- 节点数量和类型
- 每个 SQL 节点的核心逻辑（SQL 框架）
- 预期输出

**示例：**
```
我设计的分析方案：
1. **data_source**: 从 dim_experiment 获取实验数据
2. **sql_executor**: 按实验类型分组统计数量
3. **data_output**: 导出为 CSV

核心 SQL 逻辑：
SELECT experiment_type, COUNT(*) as count
FROM dim_experiment
GROUP BY experiment_type
ORDER BY count DESC

是否按此方案执行？
```

### Step 4: 用户确认

用户可以：
- 确认执行
- 请求修改某个节点的逻辑
- 指定不同的表

### Step 5: 构建 DAG

**重要模式：每次添加节点前调用 `canvas_inspect_tool()`**

```
canvas_plan_tool(description="...")

canvas_inspect_tool() → 确认状态，获取 canvas_id
canvas_add_node_tool("data_source", {...})

canvas_inspect_tool() → 获取可用变量 {{node-1.table_name}}
canvas_add_node_tool("sql_executor", {
    "sql": "SELECT ... FROM {{node-1.table_name}} ...",
    ...
})

canvas_add_edge_tool("node-1", "node-2")

... 继续添加节点 ...

canvas_add_node_tool("data_output", {...})
canvas_add_edge_tool(..., "node-N")
```

### Step 6: 执行与呈现

```
canvas_execute_tool()
canvas_preview_data_tool(source="node-N")
```

## 结果呈现格式

```markdown
## Canvas 分析完成

**执行状态:** ✅ 完成 (耗时 3.2s)

**DAG 结构:**
- node-1: data_source → dim_experiment (实验维度表)
- node-2: sql_executor → experiment_stats (实验类型统计)
- node-3: data_output → 实验分析报告.csv

**结果预览:**

| experiment_type | count |
|-----------------|-------|
| A/B Test | 45 |
| MVT | 12 |

**输出文件:** `/mnt/user-data/outputs/实验分析报告.csv`

**Canvas 已保存，可通过前端界面查看和编辑。**
```

## 错误处理

### 节点执行失败

- 停止后续执行
- 显示错误详情和失败节点
- 建议修改方案

### 数据源连接失败

- 提示检查连接配置
- 尝试备用连接（如果有）

### SQL 语法错误

- 显示具体错误位置
- 建议修正方案
- 提供重新执行选项

## 示例对话

**用户:** 帮我分析一下我们做的实验的情况，看看哪种类型实验最多

**技能:**
我来帮你分析实验情况。让我先看看可用的数据源。

*[调用 canvas_inspect_tool() - Canvas 为空]*

*[调用 canvas_list_tables_tool()]*

发现 `dataflow` 数据库中有以下实验相关表：
- dim_experiment - 实验维度表
- dim_experiment_metric - 实验指标表
- fact_experiment_assignment - 实验分配事实表

我设计的分析方案：
1. **data_source**: 从 dim_experiment 获取实验数据
2. **sql_executor**: 按实验类型分组统计数量
3. **data_output**: 导出为 CSV

核心 SQL 逻辑：
```sql
SELECT experiment_type, COUNT(*) as count
FROM dim_experiment
GROUP BY experiment_type
ORDER BY count DESC
```

是否按此方案执行？

**用户:** 可以

**技能:**
*[调用 canvas_plan_tool]*
*[调用 canvas_inspect_tool]*
*[调用 canvas_add_node_tool - data_source]*
*[调用 canvas_inspect_tool - 获取可用变量 {{node-1.table_name}}]*
*[调用 canvas_add_node_tool - sql_executor]*
*[调用 canvas_add_edge_tool]*
*[调用 canvas_add_node_tool - data_output]*
*[调用 canvas_add_edge_tool]*
*[调用 canvas_execute_tool]*
*[调用 canvas_preview_data_tool]*

## Canvas 分析完成

**执行状态:** ✅ 完成 (耗时 1.2s)

**结果预览:**

| experiment_type | count |
|-----------------|-------|
| A/B Test | 45 |
| MVT | 12 |
| Multi-armed Bandit | 8 |

**输出文件:** `/mnt/user-data/outputs/实验类型统计.csv`

如需可视化，可以说"生成图表"。
```

- [ ] **Step 3: 提交**

```bash
git add skills/public/canvas-analysis/SKILL.md
git commit -m "feat(skills): add canvas-analysis skill

A data analysis skill that helps users build reusable data processing
pipelines using Canvas DAG. Key features:

- Collects and refines user intent into specific analysis scenarios
- Designs complete DAG structure automatically
- Generates processing logic for each node
- Executes and presents analysis results

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: 配置 - 确保工具可用

**Files:**
- Check: `config.yaml` - 确保 db_connections 已配置
- Check: 工具加载机制

- [ ] **Step 1: 验证配置**

检查 `config.yaml` 中是否有数据库连接配置：

```yaml
db_connections:
- name: dataflow
  type: mysql
  url: mysql+pymysql://user:pass@host:3306/database
```

- [ ] **Step 2: 验证工具加载**

确认 canvas 工具被正确加载到 agent 中。

检查 `deerflow/agents/tools.py` 或类似文件中是否包含 canvas 工具的加载逻辑。

---

## Task 5: 测试验证

- [ ] **Step 1: 运行后端测试**

Run: `cd /Users/frankliu/Code/deerflow/backend && make test`
Expected: 所有测试通过

- [ ] **Step 2: 运行 lint 检查**

Run: `cd /Users/frankliu/Code/deerflow/backend && make lint`
Expected: 无错误

- [ ] **Step 3: 启动服务验证**

Run: `cd /Users/frankliu/Code/deerflow && make dev`

验证：
1. 服务启动无错误
2. Canvas 工具可被调用
3. 技能文件被正确识别

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat(canvas-analysis): complete canvas-analysis skill implementation

- Add 4 new canvas tools: inspect, list_tables, table_schema, preview_data
- Create canvas-analysis skill with comprehensive documentation
- Tools support database introspection and node output preview

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 规格覆盖检查

| 规格要求 | 任务 |
|---------|------|
| canvas_inspect_tool | Task 1 |
| canvas_list_tables_tool | Task 1 |
| canvas_table_schema_tool | Task 1 |
| canvas_preview_data_tool | Task 1 |
| SKILL.md 创建 | Task 3 |
| 工具注册 | Task 2 |
| 配置验证 | Task 4 |
| 测试验证 | Task 5 |

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-26-canvas-analysis-skill-implementation.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
