# Canvas 数据处理流程实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现完整的 Canvas 数据处理流程，包括数据库连接选择、节点配置编辑、执行结果预览。

**Architecture:** 后端新增数据库连接API和执行控制API，前端扩展状态管理、添加组件面板、增强节点编辑器、实现执行结果面板。

**Tech Stack:** FastAPI (后端), React Flow + TanStack Query + Shadcn UI (前端)

---

## 文件结构

### 后端新增/修改

| 文件 | 职责 |
|------|------|
| `backend/app/gateway/routers/db_connections.py` | 新增：数据库连接 API |
| `backend/app/gateway/routers/canvas.py` | 修改：添加预览、验证、停止端点 |

### 前端新增/修改

| 文件 | 职责 |
|------|------|
| `frontend/src/core/canvas/types.ts` | 修改：添加新类型定义 |
| `frontend/src/core/canvas/api.ts` | 修改：添加新API调用 |
| `frontend/src/core/canvas/hooks.ts` | 修改：添加新hooks |
| `frontend/src/components/workspace/canvas/context.tsx` | 修改：扩展状态管理 |
| `frontend/src/components/workspace/canvas/canvas-panel.tsx` | 修改：集成组件面板 |
| `frontend/src/components/workspace/canvas/canvas-toolbar.tsx` | 修改：模式切换按钮 |
| `frontend/src/components/workspace/canvas/node-editor.tsx` | 修改：各类型节点编辑器 |
| `frontend/src/components/workspace/canvas/execution-status.tsx` | 修改：完整执行历史显示 |
| `frontend/src/components/workspace/canvas/component-panel.tsx` | 新增：左侧组件拖拽面板 |
| `frontend/src/components/workspace/canvas/code-editor-dialog.tsx` | 新增：SQL/Python弹窗编辑器 |
| `frontend/src/components/workspace/canvas/data-preview-dialog.tsx` | 新增：数据预览弹窗 |
| `frontend/src/components/workspace/canvas/editors/` | 新增：各类型节点编辑器 |
| `frontend/src/components/workspace/canvas/index.ts` | 修改：导出新组件 |

---

## Task 1: 后端 - 数据库连接 API

**Files:**
- Create: `backend/app/gateway/routers/db_connections.py`
- Modify: `backend/app/gateway/app.py`

- [ ] **Step 1: 创建数据库连接路由文件**

```python
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
```

- [ ] **Step 2: 在 app.py 中注册路由**

找到 `backend/app/gateway/app.py`，在路由注册部分添加：

```python
# 在其他 router 导入之后添加
from app.gateway.routers import db_connections

# 在 app.include_router 调用之后添加
app.include_router(db_connections.router)
```

- [ ] **Step 3: 运行后端测试验证**

Run: `cd /Users/frankliu/Code/deerflow/backend && make lint`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add backend/app/gateway/routers/db_connections.py backend/app/gateway/app.py
git commit -m "feat(canvas): add database connection API endpoints

- GET /api/db-connections - list available connections
- GET /api/db-connections/{id}/tables - list tables
- GET /api/db-connections/{id}/tables/{name}/schema - get schema
- GET /api/db-connections/{id}/tables/{name}/preview - preview data

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: 后端 - Canvas API 增强

**Files:**
- Modify: `backend/app/gateway/routers/canvas.py`

- [ ] **Step 1: 添加节点预览和SQL验证端点**

在 `backend/app/gateway/routers/canvas.py` 文件末尾添加：

```python
class ValidateSQLRequest(BaseModel):
    """Request model for SQL validation."""

    sql: str = Field(..., description="SQL statement to validate")
    variables: dict[str, str] = Field(default_factory=dict, description="Variable substitutions")


class ValidateSQLResponse(BaseModel):
    """Response model for SQL validation."""

    valid: bool
    resolved_sql: str | None = None
    errors: list[str] = Field(default_factory=list)


class NodePreviewResponse(BaseModel):
    """Response model for node data preview."""

    rows: list[dict[str, Any]]
    columns: list[dict[str, str]]
    rows_count: int


@router.post(
    "/threads/{thread_id}/canvas/validate-sql",
    response_model=ValidateSQLResponse,
)
async def validate_sql(thread_id: str, request: ValidateSQLRequest):
    """Validate SQL statement with variable substitution."""
    import re

    storage = CanvasStorage()
    canvas = storage.load(thread_id)

    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")

    # Resolve variables
    resolved_sql = request.sql
    var_pattern = re.compile(r"\{\{(node-\d+)\.(\w+)\}\}")

    def replace_var(match):
        node_id = match.group(1)
        field = match.group(2)
        if node_id in request.variables:
            return request.variables[node_id]
        # Try to find from canvas nodes
        for node in canvas.nodes:
            if node.id == node_id and field in node.data:
                return str(node.data[field])
        return match.group(0)

    resolved_sql = var_pattern.sub(replace_var, resolved_sql)

    # Basic validation - check for common SQL injection patterns
    errors = []

    # Check for balanced quotes
    single_quotes = resolved_sql.count("'")
    double_quotes = resolved_sql.count('"')
    if single_quotes % 2 != 0:
        errors.append("Unbalanced single quotes")
    if double_quotes % 2 != 0:
        errors.append("Unbalanced double quotes")

    # Check for basic SQL keywords
    sql_keywords = ["SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"]
    has_valid_keyword = any(kw in resolved_sql.upper() for kw in sql_keywords)
    if not has_valid_keyword:
        errors.append("No valid SQL keyword found")

    return ValidateSQLResponse(
        valid=len(errors) == 0,
        resolved_sql=resolved_sql if errors else None,
        errors=errors,
    )


@router.get(
    "/threads/{thread_id}/canvas/nodes/{node_id}/preview",
    response_model=NodePreviewResponse,
)
async def preview_node_output(thread_id: str, node_id: str, limit: int = 100):
    """Preview output data from a specific node."""
    import json
    from pathlib import Path

    storage = CanvasStorage()
    canvas = storage.load(thread_id)

    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")

    # Find the node
    node = None
    for n in canvas.nodes:
        if n.id == node_id:
            node = n
            break

    if node is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    # Find execution log for this node
    exec_log = None
    for log in canvas.execution_log:
        if log.node_id == node_id and log.success:
            exec_log = log
            break

    if exec_log is None:
        raise HTTPException(status_code=404, detail=f"No execution result for node '{node_id}'")

    # Load output file if available
    if exec_log.output_file:
        output_path = Path(exec_log.output_file)
        if not output_path.is_absolute():
            # Resolve relative path
            from deerflow.config.paths import get_paths
            base_dir = get_paths().base_dir
            output_path = base_dir / "threads" / thread_id / "outputs" / output_path.name

        if output_path.exists():
            # Read based on format
            suffix = output_path.suffix.lower()
            if suffix == ".json":
                with open(output_path) as f:
                    data = json.load(f)
                    rows = data if isinstance(data, list) else [data]
            elif suffix == ".csv":
                import csv
                with open(output_path, newline="") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
            else:
                rows = [{"content": output_path.read_text()}]

            columns = [{"name": k, "type": type(v).__name__} for k, v in (rows[0] if rows else {}).items()]

            return NodePreviewResponse(
                rows=rows[:limit],
                columns=columns,
                rows_count=len(rows),
            )

    # Return output table info if available
    if exec_log.output_table:
        return NodePreviewResponse(
            rows=[{"output_table": exec_log.output_table}],
            columns=[{"name": "output_table", "type": "string"}],
            rows_count=exec_log.rows_affected,
        )

    raise HTTPException(status_code=404, detail=f"No preview available for node '{node_id}'")


@router.post("/threads/{thread_id}/canvas/stop")
async def stop_canvas_execution(thread_id: str):
    """Stop canvas execution."""
    storage = CanvasStorage()
    canvas = storage.load(thread_id)

    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")

    # Update status to paused (stopped by user)
    from deerflow.canvas.models import CanvasStatus

    canvas.status = CanvasStatus.PAUSED
    storage.save(canvas)

    return {"success": True}
```

- [ ] **Step 2: 添加必要的导入**

在文件顶部添加缺失的导入：

```python
from typing import Any

from pydantic import BaseModel, Field
```

- [ ] **Step 3: 运行lint验证**

Run: `cd /Users/frankliu/Code/deerflow/backend && make lint`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add backend/app/gateway/routers/canvas.py
git commit -m "feat(canvas): add node preview and SQL validation endpoints

- POST /threads/{id}/canvas/validate-sql - validate SQL with variables
- GET /threads/{id}/canvas/nodes/{node_id}/preview - preview node output
- POST /threads/{id}/canvas/stop - stop canvas execution

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: 前端 - 扩展类型和API

**Files:**
- Modify: `frontend/src/core/canvas/types.ts`
- Modify: `frontend/src/core/canvas/api.ts`

- [ ] **Step 1: 扩展类型定义**

在 `frontend/src/core/canvas/types.ts` 中添加：

```typescript
// 数据库连接类型
export interface DbConnection {
  id: string;
  name: string;
  type: string;
}

export interface DbConnectionsListResponse {
  connections: DbConnection[];
}

export interface TableColumn {
  name: string;
  type: string;
  nullable: boolean;
}

export interface TableSchemaResponse {
  columns: TableColumn[];
}

export interface TablesListResponse {
  tables: string[];
}

export interface TablePreviewResponse {
  rows: Record<string, unknown>[];
  total_rows: number;
}

// SQL验证
export interface ValidateSQLRequest {
  sql: string;
  variables?: Record<string, string>;
}

export interface ValidateSQLResponse {
  valid: boolean;
  resolved_sql?: string;
  errors: string[];
}

// 节点预览
export interface NodePreviewResponse {
  rows: Record<string, unknown>[];
  columns: { name: string; type: string }[];
  rows_count: number;
}

// Canvas模式
export type CanvasMode = "edit" | "run";

// 节点编辑状态
export interface NodeEditState {
  hasUnsavedChanges: boolean;
  isValid: boolean;
  validationErrors: string[];
}
```

- [ ] **Step 2: 添加API调用函数**

在 `frontend/src/core/canvas/api.ts` 中添加：

```typescript
/**
 * 获取可用的数据库连接。
 */
export async function getDbConnections(): Promise<DbConnectionsListResponse> {
  const response = await fetch(`${getBaseUrl()}/api/db-connections`);

  if (!response.ok) {
    throw new Error(`Failed to get db connections: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 获取连接的表列表。
 */
export async function getTables(connectionId: string): Promise<TablesListResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/db-connections/${connectionId}/tables`
  );

  if (!response.ok) {
    throw new Error(`Failed to get tables: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 获取表结构。
 */
export async function getTableSchema(
  connectionId: string,
  tableName: string
): Promise<TableSchemaResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/db-connections/${connectionId}/tables/${tableName}/schema`
  );

  if (!response.ok) {
    throw new Error(`Failed to get table schema: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 预览表数据。
 */
export async function previewTable(
  connectionId: string,
  tableName: string,
  limit: number = 100
): Promise<TablePreviewResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/db-connections/${connectionId}/tables/${tableName}/preview?limit=${limit}`
  );

  if (!response.ok) {
    throw new Error(`Failed to preview table: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 验证SQL。
 */
export async function validateSQL(
  threadId: string,
  request: ValidateSQLRequest
): Promise<ValidateSQLResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/threads/${threadId}/canvas/validate-sql`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to validate SQL: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 预览节点输出。
 */
export async function previewNodeOutput(
  threadId: string,
  nodeId: string,
  limit: number = 100
): Promise<NodePreviewResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/threads/${threadId}/canvas/nodes/${nodeId}/preview?limit=${limit}`
  );

  if (!response.ok) {
    throw new Error(`Failed to preview node output: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 停止Canvas执行。
 */
export async function stopCanvasExecution(threadId: string): Promise<void> {
  const response = await fetch(
    `${getBaseUrl()}/api/threads/${threadId}/canvas/stop`,
    {
      method: "POST",
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to stop canvas: ${response.statusText}`);
  }
}
```

同时添加导入：

```typescript
import type {
  // ... existing imports
  DbConnectionsListResponse,
  TablesListResponse,
  TableSchemaResponse,
  TablePreviewResponse,
  ValidateSQLRequest,
  ValidateSQLResponse,
  NodePreviewResponse,
} from "./types";
```

- [ ] **Step 3: 运行类型检查**

Run: `cd /Users/frankliu/Code/deerflow/frontend && pnpm typecheck`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add frontend/src/core/canvas/types.ts frontend/src/core/canvas/api.ts
git commit -m "feat(canvas): add database connection types and API functions

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: 前端 - 扩展 Hooks

**Files:**
- Modify: `frontend/src/core/canvas/hooks.ts`

- [ ] **Step 1: 添加数据库连接相关hooks**

在 `frontend/src/core/canvas/hooks.ts` 中添加：

```typescript
import {
  // ... existing imports
  getDbConnections,
  getTables,
  getTableSchema,
  previewTable,
  validateSQL,
  previewNodeOutput,
  stopCanvasExecution,
} from "./api";
import type {
  // ... existing imports
  DbConnection,
  TableColumn,
  ValidateSQLRequest,
} from "./types";

/**
 * 获取数据库连接列表的 hook。
 */
export function useDbConnections(enabled = true) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["db-connections"],
    queryFn: getDbConnections,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 分钟
  });

  return {
    connections: data?.connections ?? [],
    isLoading,
    error,
  };
}

/**
 * 获取表列表的 hook。
 */
export function useTables(connectionId: string | null, enabled = true) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["tables", connectionId],
    queryFn: () => connectionId ? getTables(connectionId) : Promise.resolve({ tables: [] }),
    enabled: enabled && !!connectionId,
    staleTime: 60 * 1000, // 1 分钟
  });

  return {
    tables: data?.tables ?? [],
    isLoading,
    error,
    refetch,
  };
}

/**
 * 获取表结构的 hook。
 */
export function useTableSchema(
  connectionId: string | null,
  tableName: string | null,
  enabled = true
) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["table-schema", connectionId, tableName],
    queryFn: () =>
      connectionId && tableName
        ? getTableSchema(connectionId, tableName)
        : Promise.resolve({ columns: [] }),
    enabled: enabled && !!connectionId && !!tableName,
    staleTime: 60 * 1000,
  });

  return {
    columns: data?.columns ?? [],
    isLoading,
    error,
  };
}

/**
 * 预览表数据的 mutation。
 */
export function usePreviewTable() {
  const { mutateAsync, isPending, error } = useMutation({
    mutationFn: ({
      connectionId,
      tableName,
      limit = 100,
    }: {
      connectionId: string;
      tableName: string;
      limit?: number;
    }) => previewTable(connectionId, tableName, limit),
  });

  return {
    previewTable: mutateAsync,
    isPending,
    error,
  };
}

/**
 * 验证SQL的 mutation。
 */
export function useValidateSQL(threadId: string) {
  const { mutateAsync, isPending, error, data } = useMutation({
    mutationFn: (request: ValidateSQLRequest) => validateSQL(threadId, request),
  });

  return {
    validateSQL: mutateAsync,
    isValidating: isPending,
    error,
    validationResult: data,
  };
}

/**
 * 预览节点输出的 mutation。
 */
export function usePreviewNodeOutput(threadId: string) {
  const { mutateAsync, isPending, error } = useMutation({
    mutationFn: (nodeId: string) => previewNodeOutput(threadId, nodeId, 100),
  });

  return {
    previewNode: mutateAsync,
    isPending,
    error,
  };
}

/**
 * 停止Canvas执行的 mutation。
 */
export function useStopCanvas(threadId: string) {
  const queryClient = useQueryClient();

  const { mutate, mutateAsync, isPending, error } = useMutation({
    mutationFn: () => stopCanvasExecution(threadId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["canvas-status", threadId] });
    },
  });

  return {
    stopCanvas: mutate,
    stopCanvasAsync: mutateAsync,
    isStopping: isPending,
    error,
  };
}
```

- [ ] **Step 2: 运行类型检查**

Run: `cd /Users/frankliu/Code/deerflow/frontend && pnpm typecheck`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/core/canvas/hooks.ts
git commit -m "feat(canvas): add hooks for db connections and validation

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: 前端 - 扩展 CanvasContext

**Files:**
- Modify: `frontend/src/components/workspace/canvas/context.tsx`

- [ ] **Step 1: 扩展 Context 类型和初始状态**

替换整个 `frontend/src/components/workspace/canvas/context.tsx` 文件：

```typescript
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";

import type {
  Canvas,
  CanvasMode,
  DbConnection,
  ExecutionStatusResponse,
  NodeResult,
} from "@/core/canvas/types";

export interface CanvasContextType {
  // Canvas 数据
  canvas: Canvas | null;
  setCanvas: (canvas: Canvas | null) => void;

  // 选中的节点
  selectedNodeId: string | null;
  selectNode: (nodeId: string | null) => void;

  // 面板状态
  open: boolean;
  setOpen: (open: boolean) => void;

  // 编辑状态
  isEditing: boolean;
  setIsEditing: (editing: boolean) => void;

  // React Flow 节点选择
  selectedNodes: string[];
  setSelectedNodes: (nodes: string[]) => void;

  // 边选择
  selectedEdges: string[];
  setSelectedEdges: (edges: string[]) => void;

  // Canvas模式（编辑态/运行态）
  canvasMode: CanvasMode;
  setCanvasMode: (mode: CanvasMode) => void;

  // 执行状态
  executionStatus: ExecutionStatusResponse | null;
  setExecutionStatus: (status: ExecutionStatusResponse | null) => void;

  // 节点执行结果
  nodeResults: Record<string, NodeResult>;
  setNodeResults: (results: Record<string, NodeResult>) => void;

  // 数据库连接列表
  dbConnections: DbConnection[];
  setDbConnections: (connections: DbConnection[]) => void;
}

const CanvasContext = createContext<CanvasContextType | undefined>(undefined);

interface CanvasProviderProps {
  children: ReactNode;
}

export function CanvasProvider({ children }: CanvasProviderProps) {
  const [canvas, setCanvas] = useState<Canvas | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedNodes, setSelectedNodes] = useState<string[]>([]);
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("edit");
  const [executionStatus, setExecutionStatus] = useState<ExecutionStatusResponse | null>(null);
  const [nodeResults, setNodeResults] = useState<Record<string, NodeResult>>({});
  const [dbConnections, setDbConnections] = useState<DbConnection[]>([]);

  const { setOpen: setSidebarOpen } = useSidebar();

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
    if (nodeId) {
      setIsEditing(true);
    }
  }, []);

  const handleSetOpen = useCallback(
    (isOpen: boolean) => {
      setOpen(isOpen);
      if (isOpen) {
        setSidebarOpen(false);
      }
    },
    [setSidebarOpen],
  );

  const handleSetCanvasMode = useCallback((mode: CanvasMode) => {
    setCanvasMode(mode);
    if (mode === "edit") {
      // 编辑模式时清除选择
      setSelectedNodeId(null);
    }
  }, []);

  const value: CanvasContextType = {
    canvas,
    setCanvas,
    selectedNodeId,
    selectNode,
    open,
    setOpen: handleSetOpen,
    isEditing,
    setIsEditing,
    selectedNodes,
    setSelectedNodes,
    selectedEdges,
    setSelectedEdges,
    canvasMode,
    setCanvasMode: handleSetCanvasMode,
    executionStatus,
    setExecutionStatus,
    nodeResults,
    setNodeResults,
    dbConnections,
    setDbConnections,
  };

  return (
    <CanvasContext.Provider value={value}>{children}</CanvasContext.Provider>
  );
}

export function useCanvasContext() {
  const context = useContext(CanvasContext);
  if (context === undefined) {
    throw new Error("useCanvasContext must be used within a CanvasProvider");
  }
  return context;
}
```

- [ ] **Step 2: 运行类型检查**

Run: `cd /Users/frankliu/Code/deerflow/frontend && pnpm typecheck`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/workspace/canvas/context.tsx
git commit -m "feat(canvas): extend CanvasContext with mode and execution state

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: 前端 - 组件面板

**Files:**
- Create: `frontend/src/components/workspace/canvas/component-panel.tsx`
- Modify: `frontend/src/components/workspace/canvas/index.ts`

- [ ] **Step 1: 创建组件面板组件**

```typescript
// frontend/src/components/workspace/canvas/component-panel.tsx
"use client";

import { Database, Code, FileOutput, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { NodeType } from "@/core/canvas/types";

interface ComponentItem {
  type: NodeType;
  name: string;
  icon: React.ReactNode;
  description: string;
}

const COMPONENT_GROUPS = [
  {
    name: "数据源",
    items: [
      {
        type: "data_source" as NodeType,
        name: "Data Source",
        icon: <Database className="h-4 w-4" />,
        description: "从数据库表读取数据",
      },
    ],
  },
  {
    name: "处理",
    items: [
      {
        type: "sql_executor" as NodeType,
        name: "SQL Executor",
        icon: <Code className="h-4 w-4" />,
        description: "执行SQL查询",
      },
      {
        type: "python_script" as NodeType,
        name: "Python Script",
        icon: <Code className="h-4 w-4" />,
        description: "执行Python代码",
      },
    ],
  },
  {
    name: "输出",
    items: [
      {
        type: "data_output" as NodeType,
        name: "Data Output",
        icon: <FileOutput className="h-4 w-4" />,
        description: "导出数据到文件",
      },
    ],
  },
];

interface ComponentPanelProps {
  onDragStart: (nodeType: NodeType) => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function ComponentPanel({
  onDragStart,
  isCollapsed = false,
  onToggleCollapse,
}: ComponentPanelProps) {
  const [expandedGroups, setExpandedGroups] = useState<string[]>(
    COMPONENT_GROUPS.map((g) => g.name)
  );

  const toggleGroup = (name: string) => {
    setExpandedGroups((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  };

  const handleDragStart = (e: React.DragEvent, type: NodeType) => {
    e.dataTransfer.setData("application/reactflow", type);
    e.dataTransfer.effectAllowed = "move";
    onDragStart(type);
  };

  if (isCollapsed) {
    return (
      <div className="flex flex-col items-center gap-2 border-r bg-background py-2">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onToggleCollapse}
          title="展开组件面板"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-48 flex-col border-r bg-background">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-medium">组件</span>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onToggleCollapse}
          title="折叠组件面板"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-auto p-2">
        {COMPONENT_GROUPS.map((group) => (
          <div key={group.name} className="mb-2">
            <button
              className="flex w-full items-center gap-1 px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
              onClick={() => toggleGroup(group.name)}
            >
              {expandedGroups.includes(group.name) ? "▼" : "▶"}
              {group.name}
            </button>
            {expandedGroups.includes(group.name) && (
              <div className="mt-1 space-y-1">
                {group.items.map((item) => (
                  <div
                    key={item.type}
                    draggable
                    onDragStart={(e) => handleDragStart(e, item.type)}
                    className={cn(
                      "flex cursor-grab items-center gap-2 rounded-md border bg-card p-2 shadow-sm",
                      "hover:border-primary hover:shadow-md active:cursor-grabbing"
                    )}
                    title={item.description}
                  >
                    <div className="flex h-8 w-8 items-center justify-center rounded bg-muted">
                      {item.icon}
                    </div>
                    <div className="flex-1">
                      <div className="text-xs font-medium">{item.name}</div>
                      <div className="text-[10px] text-muted-foreground">
                        拖拽添加
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 更新导出**

在 `frontend/src/components/workspace/canvas/index.ts` 中添加：

```typescript
export { ComponentPanel } from "./component-panel";
```

- [ ] **Step 3: 运行类型检查**

Run: `cd /Users/frankliu/Code/deerflow/frontend && pnpm typecheck`
Expected: 无错误

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/workspace/canvas/component-panel.tsx frontend/src/components/workspace/canvas/index.ts
git commit -m "feat(canvas): add ComponentPanel for drag-and-drop node creation

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: 前端 - 代码编辑器弹窗

**Files:**
- Create: `frontend/src/components/workspace/canvas/code-editor-dialog.tsx`

- [ ] **Step 1: 创建代码编辑器弹窗**

```typescript
// frontend/src/components/workspace/canvas/code-editor-dialog.tsx
"use client";

import { useCallback } from "react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { CanvasNode } from "@/core/canvas/types";

interface AvailableVariable {
  name: string;
  value: string;
  nodeName: string;
}

interface CodeEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  language: "sql" | "python";
  availableVariables?: AvailableVariable[];
  placeholder?: string;
}

export function CodeEditorDialog({
  open,
  onOpenChange,
  title,
  value,
  onChange,
  onSave,
  language,
  availableVariables = [],
  placeholder,
}: CodeEditorDialogProps) {
  const handleInsertVariable = useCallback(
    (variable: AvailableVariable) => {
      const textarea = document.querySelector<HTMLTextAreaElement>(
        ".code-editor-textarea"
      );
      if (textarea) {
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const newValue =
          value.substring(0, start) + variable.value + value.substring(end);
        onChange(newValue);
        // Set cursor position after the inserted variable
        setTimeout(() => {
          textarea.selectionStart = textarea.selectionEnd = start + variable.value.length;
          textarea.focus();
        }, 0);
      } else {
        onChange(value + variable.value);
      }
    },
    [value, onChange]
  );

  const handleSave = () => {
    onSave();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl h-[60vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {availableVariables.length > 0 && (
          <div className="border-b pb-3">
            <div className="text-xs font-medium text-muted-foreground mb-2">
              可用变量（点击插入）:
            </div>
            <div className="flex flex-wrap gap-2">
              {availableVariables.map((v) => (
                <button
                  key={v.value}
                  onClick={() => handleInsertVariable(v)}
                  className={cn(
                    "px-2 py-1 text-xs rounded border bg-muted hover:bg-primary hover:text-primary-foreground",
                    "transition-colors"
                  )}
                  title={`${v.nodeName} -> ${v.value}`}
                >
                  {v.value}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex-1 flex flex-col min-h-0">
          <Textarea
            className="code-editor-textarea flex-1 font-mono text-sm resize-none"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            spellCheck={false}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave}>保存并关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/workspace/canvas/code-editor-dialog.tsx
git commit -m "feat(canvas): add CodeEditorDialog for SQL/Python editing

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: 前端 - 数据预览弹窗

**Files:**
- Create: `frontend/src/components/workspace/canvas/data-preview-dialog.tsx`

- [ ] **Step 1: 创建数据预览弹窗**

```typescript
// frontend/src/components/workspace/canvas/data-preview-dialog.tsx
"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Download } from "lucide-react";

interface DataPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  columns: { name: string; type: string }[];
  rows: Record<string, unknown>[];
  totalRows: number;
  onExport?: () => void;
}

export function DataPreviewDialog({
  open,
  onOpenChange,
  title,
  columns,
  rows,
  totalRows,
  onExport,
}: DataPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] flex flex-col">
        <DialogHeader className="flex-shrink-0">
          <DialogTitle className="flex items-center justify-between">
            <span>数据预览 - {title}</span>
            {onExport && (
              <Button variant="outline" size="sm" onClick={onExport}>
                <Download className="mr-1 h-4 w-4" />
                导出CSV
              </Button>
            )}
          </DialogTitle>
        </DialogHeader>

        <ScrollArea className="flex-1 -mx-4 px-4">
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map((col) => (
                  <TableHead key={col.name}>
                    <div className="flex flex-col">
                      <span>{col.name}</span>
                      <span className="text-xs font-normal text-muted-foreground">
                        {col.type}
                      </span>
                    </div>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow key={index}>
                  {columns.map((col) => (
                    <TableCell key={col.name}>
                      {formatValue(row[col.name])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </ScrollArea>

        <div className="flex-shrink-0 pt-2 text-xs text-muted-foreground">
          显示前 {rows.length} 行，共 {totalRows} 行
        </div>
      </DialogContent>
    </Dialog>
  );
}

function formatValue(value: unknown): string {
  if (value === null) return "NULL";
  if (value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/workspace/canvas/data-preview-dialog.tsx
git commit -m "feat(canvas): add DataPreviewDialog for viewing node output

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: 前端 - Data Source 节点编辑器

**Files:**
- Create: `frontend/src/components/workspace/canvas/editors/data-source-editor.tsx`

- [ ] **Step 1: 创建 Data Source 编辑器**

```typescript
// frontend/src/components/workspace/canvas/editors/data-source-editor.tsx
"use client";

import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Eye, Loader2 } from "lucide-react";

import { useCanvasContext } from "../context";
import { DataPreviewDialog } from "../data-preview-dialog";

import {
  useTables,
  useTableSchema,
  usePreviewTable,
  useDbConnections,
} from "@/core/canvas/hooks";
import type { DataSourceNodeData } from "@/core/canvas/types";

interface DataSourceEditorProps {
  nodeId: string;
  data: DataSourceNodeData;
  onChange: (data: DataSourceNodeData) => void;
}

export function DataSourceEditor({ nodeId, data, onChange }: DataSourceEditorProps) {
  const { threadId } = useCanvasContext();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewData, setPreviewData] = useState<{
    rows: Record<string, unknown>[];
    total_rows: number;
  } | null>(null);

  // Hooks for data loading
  const { connections, isLoading: loadingConnections } = useDbConnections(!!threadId);
  const { tables, isLoading: loadingTables } = useTables(
    data.connection_id ?? null,
    !!data.connection_id
  );
  const { columns, isLoading: loadingSchema } = useTableSchema(
    data.connection_id ?? null,
    data.table_name ?? null,
    !!(data.connection_id && data.table_name)
  );
  const { previewTable, isPending: isPreviewing } = usePreviewTable();

  const handleChange = useCallback(
    (field: keyof DataSourceNodeData, value: string) => {
      if (field === "connection_id") {
        // Reset table when connection changes
        onChange({
          ...data,
          connection_id: value,
          table_name: undefined,
        });
      } else {
        onChange({
          ...data,
          [field]: value,
        });
      }
    },
    [data, onChange]
  );

  const handlePreview = useCallback(async () => {
    if (!data.connection_id || !data.table_name) return;

    try {
      const result = await previewTable({
        connectionId: data.connection_id,
        tableName: data.table_name,
        limit: 100,
      });
      setPreviewData(result);
      setPreviewOpen(true);
    } catch (error) {
      console.error("Failed to preview table:", error);
    }
  }, [data.connection_id, data.table_name, previewTable]);

  const isConfigValid = !!(data.connection_id && data.table_name);

  return (
    <div className="space-y-4">
      <div>
        <Label>显示名称</Label>
        <Input
          value={data.display_name ?? ""}
          onChange={(e) => handleChange("display_name", e.target.value)}
          placeholder="可选"
        />
      </div>

      <div>
        <Label>数据库连接</Label>
        <Select
          value={data.connection_id ?? ""}
          onValueChange={(v) => handleChange("connection_id", v)}
          disabled={loadingConnections}
        >
          <SelectTrigger>
            <SelectValue placeholder={loadingConnections ? "加载中..." : "选择连接"} />
          </SelectTrigger>
          <SelectContent>
            {connections.map((conn) => (
              <SelectItem key={conn.id} value={conn.id}>
                {conn.name} ({conn.type})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {data.connection_id && (
        <div>
          <Label>数据表</Label>
          <Select
            value={data.table_name ?? ""}
            onValueChange={(v) => handleChange("table_name", v)}
            disabled={loadingTables}
          >
            <SelectTrigger>
              <SelectValue placeholder={loadingTables ? "加载中..." : "选择表"} />
            </SelectTrigger>
            <SelectContent>
              {tables.map((table) => (
                <SelectItem key={table} value={table}>
                  {table}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {data.table_name && columns.length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <Label>表结构预览</Label>
            <Button
              variant="outline"
              size="sm"
              onClick={handlePreview}
              disabled={isPreviewing || !isConfigValid}
            >
              {isPreviewing ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Eye className="mr-1 h-4 w-4" />
              )}
              预览数据
            </Button>
          </div>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>字段名</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>可空</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loadingSchema ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center">
                      加载中...
                    </TableCell>
                  </TableRow>
                ) : (
                  columns.map((col) => (
                    <TableRow key={col.name}>
                      <TableCell>{col.name}</TableCell>
                      <TableCell>{col.type}</TableCell>
                      <TableCell>{col.nullable ? "是" : "否"}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      <DataPreviewDialog
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        title={data.table_name ?? ""}
        columns={columns.map((c) => ({ name: c.name, type: c.type }))}
        rows={previewData?.rows ?? []}
        totalRows={previewData?.total_rows ?? 0}
      />
    </div>
  );
}
```

- [ ] **Step 2: 创建 editors 目录索引**

```typescript
// frontend/src/components/workspace/canvas/editors/index.ts
export { DataSourceEditor } from "./data-source-editor";
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/workspace/canvas/editors/
git commit -m "feat(canvas): add DataSourceEditor with preview function

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: 前端 - SQL Executor 节点编辑器

**Files:**
- Create: `frontend/src/components/workspace/canvas/editors/sql-executor-editor.tsx`

- [ ] **Step 1: 创建 SQL Executor 编辑器**

```typescript
// frontend/src/components/workspace/canvas/editors/sql-executor-editor.tsx
"use client";

import { useCallback, useState, useMemo } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Check, Edit, Loader2 } from "lucide-react";

import { useCanvasContext } from "../context";
import { CodeEditorDialog } from "../code-editor-dialog";

import { useValidateSQL } from "@/core/canvas/hooks";
import type { SQLExecutorNodeData, CanvasNode } from "@/core/canvas/types";

interface SQLExecutorEditorProps {
  nodeId: string;
  data: SQLExecutorNodeData;
  onChange: (data: SQLExecutorNodeData) => void;
}

export function SQLExecutorEditor({
  nodeId,
  data,
  onChange,
}: SQLExecutorEditorProps) {
  const { canvas, threadId } = useCanvasContext();
  const [codeDialogOpen, setCodeDialogOpen] = useState(false);
  const [tempSQL, setTempSQL] = useState(data.sql ?? "");

  const { validateSQL, isValidating, validationResult } = useValidateSQL(threadId ?? "");

  // 计算可用变量（来自上游节点的输出表）
  const availableVariables = useMemo(() => {
    if (!canvas) return [];

    const vars: { name: string; value: string; nodeName: string }[] = [];

    // 找到当前节点的上游节点
    const incomingEdges = canvas.edges.filter((e) => e.target === nodeId);
    for (const edge of incomingEdges) {
      const sourceNode = canvas.nodes.find((n) => n.id === edge.source);
      if (sourceNode && sourceNode.data.output_table) {
        vars.push({
          name: `${sourceNode.id}.output_table`,
          value: `{{${sourceNode.id}.output_table}}`,
          nodeName: sourceNode.data.display_name || sourceNode.id,
        });
      }
    }

    return vars;
  }, [canvas, nodeId]);

  const handleChange = useCallback(
    (field: keyof SQLExecutorNodeData, value: string) => {
      onChange({
        ...data,
        [field]: value,
      });
    },
    [data, onChange]
  );

  const handleOpenCodeDialog = () => {
    setTempSQL(data.sql ?? "");
    setCodeDialogOpen(true);
  };

  const handleSaveSQL = () => {
    onChange({
      ...data,
      sql: tempSQL,
    });
  };

  const handleValidate = useCallback(async () => {
    if (!data.sql) return;

    const variables: Record<string, string> = {};
    for (const v of availableVariables) {
      variables[v.name.split(".")[0]] = `table_${v.name.split(".")[0]}`;
    }

    await validateSQL({
      sql: data.sql,
      variables,
    });
  }, [data.sql, availableVariables, validateSQL]);

  const hasSQL = !!(data.sql && data.sql.trim().length > 0);

  return (
    <div className="space-y-4">
      <div>
        <Label>显示名称</Label>
        <Input
          value={data.display_name ?? ""}
          onChange={(e) => handleChange("display_name", e.target.value)}
          placeholder="可选"
        />
      </div>

      <div>
        <Label>输出表名</Label>
        <Input
          value={data.output_table ?? ""}
          onChange={(e) => handleChange("output_table", e.target.value)}
          placeholder="例如: result_table"
        />
      </div>

      <div>
        <Label>SQL语句</Label>
        <div className="mt-2 flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleOpenCodeDialog}
          >
            <Edit className="mr-1 h-4 w-4" />
            编辑SQL语句
          </Button>
          {hasSQL ? (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <Check className="h-3 w-3" />
              已编辑
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">未编辑</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={handleValidate}
          disabled={!hasSQL || isValidating}
        >
          {isValidating ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : null}
          验证SQL
        </Button>
        {validationResult && (
          <span
            className={
              validationResult.valid
                ? "text-xs text-green-600"
                : "text-xs text-red-600"
            }
          >
            {validationResult.valid ? "验证通过" : validationResult.errors.join(", ")}
          </span>
        )}
      </div>

      <CodeEditorDialog
        open={codeDialogOpen}
        onOpenChange={setCodeDialogOpen}
        title="编辑 SQL 语句"
        value={tempSQL}
        onChange={setTempSQL}
        onSave={handleSaveSQL}
        language="sql"
        availableVariables={availableVariables}
        placeholder="输入SQL语句，可使用 {{node-X.output_table}} 引用上游输出"
      />
    </div>
  );
}
```

- [ ] **Step 2: 更新编辑器索引**

```typescript
// frontend/src/components/workspace/canvas/editors/index.ts
export { DataSourceEditor } from "./data-source-editor";
export { SQLExecutorEditor } from "./sql-executor-editor";
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/workspace/canvas/editors/
git commit -m "feat(canvas): add SQLExecutorEditor with code dialog

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: 前端 - 更新 NodeEditor 组件

**Files:**
- Modify: `frontend/src/components/workspace/canvas/node-editor.tsx`

- [ ] **Step 1: 重构 NodeEditor 组件**

```typescript
// frontend/src/components/workspace/canvas/node-editor.tsx
"use client";

import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";

import { useCanvasContext } from "./context";
import { DataSourceEditor, SQLExecutorEditor } from "./editors";

import type { NodeType, CanvasNode } from "@/core/canvas/types";

export function NodeEditor() {
  const {
    selectedNodeId,
    canvas,
    setIsEditing,
    canvasMode,
    updateNodeData,
  } = useCanvasContext();

  const selectedNode = canvas?.nodes.find((n) => n.id === selectedNodeId);

  if (!selectedNode) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        选择节点以编辑
      </div>
    );
  }

  const handleDataChange = (newData: Record<string, unknown>) => {
    // Update node data in canvas
    if (canvas) {
      const updatedNodes = canvas.nodes.map((n) =>
        n.id === selectedNodeId ? { ...n, data: newData } : n
      );
      // TODO: Trigger canvas update
    }
  };

  const isEditMode = canvasMode === "edit";

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <h3 className="font-medium">
          编辑 {getNodeTypeLabel(selectedNode.type)}
        </h3>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsEditing(false)}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <ScrollArea className="flex-1 p-4">
        {isEditMode ? (
          renderEditor(selectedNode, handleDataChange)
        ) : (
          <div className="text-muted-foreground text-sm">
            运行模式下不可编辑
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

function renderEditor(
  node: CanvasNode,
  onChange: (data: Record<string, unknown>) => void
) {
  switch (node.type) {
    case "data_source":
      return (
        <DataSourceEditor
          nodeId={node.id}
          data={node.data as Record<string, unknown>}
          onChange={onChange}
        />
      );
    case "sql_executor":
      return (
        <SQLExecutorEditor
          nodeId={node.id}
          data={node.data as Record<string, unknown>}
          onChange={onChange}
        />
      );
    case "python_script":
      return (
        <div className="text-muted-foreground">
          Python Script 编辑器待实现
        </div>
      );
    case "data_output":
      return (
        <div className="text-muted-foreground">
          Data Output 编辑器待实现
        </div>
      );
    default:
      return (
        <div className="text-muted-foreground">未知节点类型</div>
      );
  }
}

function getNodeTypeLabel(type: NodeType | undefined): string {
  switch (type) {
    case "data_source":
      return "Data Source";
    case "sql_executor":
      return "SQL Executor";
    case "python_script":
      return "Python Script";
    case "data_output":
      return "Data Output";
    default:
      return "节点";
  }
}
```

- [ ] **Step 2: 运行类型检查**

Run: `cd /Users/frankliu/Code/deerflow/frontend && pnpm typecheck`
Expected: 无错误（可能有类型问题需要修复）

- [ ] **Step 3: 修复类型问题并提交**

```bash
git add frontend/src/components/workspace/canvas/node-editor.tsx
git commit -m "feat(canvas): refactor NodeEditor to use type-specific editors

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: 前端 - 更新 CanvasPanel 集成组件面板

**Files:**
- Modify: `frontend/src/components/workspace/canvas/canvas-panel.tsx`

- [ ] **Step 1: 集成组件面板和拖拽功能**

更新 `frontend/src/components/workspace/canvas/canvas-panel.tsx`：

```typescript
"use client";

import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type OnSelectionChangeParams,
  type NodeChange,
  type EdgeChange,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { nanoid } from "nanoid";

import { useCanvasContext } from "./context";
import { CanvasToolbar } from "./canvas-toolbar";
import { NodeEditor } from "./node-editor";
import { ExecutionStatus } from "./execution-status";
import { ComponentPanel } from "./component-panel";
import { DataSourceNode } from "./nodes/data-source-node";
import { SQLExecutorNode } from "./nodes/sql-executor-node";
import { PythonScriptNode } from "./nodes/python-script-node";
import { DataOutputNode } from "./nodes/data-output-node";

import type { CanvasNode, CanvasEdge, NodeType } from "@/core/canvas/types";

const nodeTypes = {
  data_source: DataSourceNode,
  sql_executor: SQLExecutorNode,
  python_script: PythonScriptNode,
  data_output: DataOutputNode,
};

function CanvasPanelInner() {
  const {
    canvas,
    setSelectedNodes,
    setSelectedEdges,
    selectedNodeId,
    selectNode,
    canvasMode,
    setCanvas,
  } = useCanvasContext();

  const { screenToFlowPosition } = useReactFlow();
  const [componentPanelCollapsed, setComponentPanelCollapsed] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>(
    canvas?.nodes ?? []
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState<CanvasEdge>(
    canvas?.edges ?? []
  );

  // Sync canvas data with React Flow state
  useEffect(() => {
    if (canvas) {
      setNodes(canvas.nodes);
      setEdges(canvas.edges);
    }
  }, [canvas, setNodes, setEdges]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge(connection, eds));
    },
    [setEdges]
  );

  const onSelectionChange = useCallback(
    ({
      nodes: selectedNodes,
      edges: selectedEdges,
    }: OnSelectionChangeParams<CanvasNode, CanvasEdge>) => {
      setSelectedNodes(selectedNodes.map((n) => n.id));
      setSelectedEdges(selectedEdges.map((e) => e.id));
      if (selectedNodes.length === 1) {
        selectNode(selectedNodes[0]!.id);
      } else {
        selectNode(null);
      }
    },
    [setSelectedNodes, setSelectedEdges, selectNode]
  );

  // Handle drag and drop
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const nodeType = event.dataTransfer.getData(
        "application/reactflow"
      ) as NodeType;

      if (!nodeType || !canvas) return;

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newNode: CanvasNode = {
        id: `node-${nanoid(8)}`,
        type: nodeType,
        position,
        data: {},
      };

      setNodes((nds) => [...nds, newNode]);
      setCanvas({
        ...canvas,
        nodes: [...canvas.nodes, newNode],
      });
    },
    [screenToFlowPosition, canvas, setNodes, setCanvas]
  );

  // Handle nodes/edges change with mode check
  const handleNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      if (canvasMode === "run") return;
      onNodesChange(changes);
    },
    [canvasMode, onNodesChange]
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange<CanvasEdge>[]) => {
      if (canvasMode === "run") return;
      onEdgesChange(changes);
    },
    [canvasMode, onEdgesChange]
  );

  const handleDragStart = useCallback(() => {
    // Optional: track drag state
  }, []);

  return (
    <div className="flex h-full w-full">
      <ComponentPanel
        isCollapsed={componentPanelCollapsed}
        onToggleCollapse={() => setComponentPanelCollapsed(!componentPanelCollapsed)}
        onDragStart={handleDragStart}
      />

      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onConnect={onConnect}
          onSelectionChange={onSelectionChange}
          onDragOver={onDragOver}
          onDrop={onDrop}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
          nodesDraggable={canvasMode === "edit"}
          nodesConnectable={canvasMode === "edit"}
          elementsSelectable={true}
        >
          <Controls />
          <MiniMap />
          <Background variant={BackgroundVariant.Dots} gap={12} size={1} />
        </ReactFlow>

        {/* 工具栏 */}
        <div className="absolute top-2 left-2 z-10">
          <CanvasToolbar />
        </div>

        {/* 执行状态 */}
        <div className="absolute bottom-2 left-2 z-10">
          <ExecutionStatus />
        </div>
      </div>

      {/* Node Editor侧边栏 */}
      {selectedNodeId && (
        <div className="w-64 border-l bg-background">
          <NodeEditor />
        </div>
      )}
    </div>
  );
}

export function CanvasPanel() {
  return (
    <ReactFlowProvider>
      <CanvasPanelInner />
    </ReactFlowProvider>
  );
}
```

- [ ] **Step 2: 运行类型检查**

Run: `cd /Users/frankliu/Code/deerflow/frontend && pnpm typecheck`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/workspace/canvas/canvas-panel.tsx
git commit -m "feat(canvas): integrate ComponentPanel with drag-and-drop

- Add ComponentPanel to canvas layout
- Support drag-and-drop node creation
- Disable editing in run mode

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: 前端 - 更新 CanvasToolbar 添加模式切换

**Files:**
- Modify: `frontend/src/components/workspace/canvas/canvas-toolbar.tsx`

- [ ] **Step 1: 更新工具栏组件**

```typescript
// frontend/src/components/workspace/canvas/canvas-toolbar.tsx
"use client";

import {
  Play,
  Save,
  Square,
  Edit3,
  Eye,
  Loader2,
  AlertCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { useCanvasContext } from "./context";

interface CanvasToolbarProps {
  onExecute?: () => void;
  onSave?: () => void;
  onStop?: () => void;
}

export function CanvasToolbar({
  onExecute,
  onSave,
  onStop,
}: CanvasToolbarProps) {
  const {
    canvas,
    canvasMode,
    setCanvasMode,
    executionStatus,
  } = useCanvasContext();

  const isRunning = executionStatus?.status === "running";
  const hasNodes = canvas && canvas.nodes.length > 0;
  const canExecute = hasNodes && !isRunning;

  const handleModeToggle = () => {
    if (canvasMode === "edit") {
      // Switch to run mode
      setCanvasMode("run");
    } else {
      // Confirm before switching to edit mode
      if (isRunning) {
        const confirmStop = window.confirm(
          "正在执行，切换到编辑模式将停止执行。是否继续？"
        );
        if (!confirmStop) return;
        onStop?.();
      }
      setCanvasMode("edit");
    }
  };

  return (
    <TooltipProvider>
      <div className="flex items-center gap-2 rounded-md border bg-background px-3 py-1.5 shadow-sm">
        <span className="text-sm font-medium">
          {canvas?.name ?? "Canvas"}
        </span>

        <Separator orientation="vertical" className="h-5" />

        {/* 模式切换按钮 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={canvasMode === "edit" ? "default" : "outline"}
              size="sm"
              onClick={handleModeToggle}
            >
              {canvasMode === "edit" ? (
                <>
                  <Edit3 className="mr-1 h-4 w-4" />
                  编辑
                </>
              ) : (
                <>
                  <Eye className="mr-1 h-4 w-4" />
                  运行
                </>
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {canvasMode === "edit"
              ? "切换到运行模式查看执行"
              : "切换到编辑模式修改节点"}
          </TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="h-5" />

        {/* 执行/停止按钮 */}
        {isRunning ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="destructive"
                size="sm"
                onClick={onStop}
              >
                <Square className="mr-1 h-4 w-4" />
                停止
              </Button>
            </TooltipTrigger>
            <TooltipContent>停止执行</TooltipContent>
          </Tooltip>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                onClick={onExecute}
                disabled={!canExecute}
              >
                <Play className="mr-1 h-4 w-4" />
                执行
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {!hasNodes ? "请先添加节点" : "执行Canvas"}
            </TooltipContent>
          </Tooltip>
        )}

        {/* 保存按钮 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              onClick={onSave}
              disabled={canvasMode === "run"}
            >
              <Save className="mr-1 h-4 w-4" />
              保存
            </Button>
          </TooltipTrigger>
          <TooltipContent>保存Canvas配置</TooltipContent>
        </Tooltip>

        {/* 执行状态指示 */}
        {executionStatus && (
          <>
            <Separator orientation="vertical" className="h-5" />
            <div className="flex items-center gap-1.5 text-xs">
              {isRunning ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
                  <span className="text-muted-foreground">
                    {executionStatus.completed_nodes.length}/
                    {executionStatus.completed_nodes.length +
                      executionStatus.pending_nodes.length}
                  </span>
                </>
              ) : executionStatus.status === "completed" ? (
                <>
                  <span className="h-2 w-2 rounded-full bg-green-500" />
                  <span className="text-muted-foreground">完成</span>
                </>
              ) : executionStatus.status === "failed" ? (
                <>
                  <AlertCircle className="h-3 w-3 text-red-500" />
                  <span className="text-muted-foreground">失败</span>
                </>
              ) : null}
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/workspace/canvas/canvas-toolbar.tsx
git commit -m "feat(canvas): add mode toggle to CanvasToolbar

- Edit/Run mode switch button
- Execute/Stop button based on mode
- Status indicator display

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: 前端 - 更新执行状态组件

**Files:**
- Modify: `frontend/src/components/workspace/canvas/execution-status.tsx`

- [ ] **Step 1: 增强执行状态组件**

```typescript
// frontend/src/components/workspace/canvas/execution-status.tsx
"use client";

import {
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  ChevronRight,
  Eye,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import { useCanvasContext } from "./context";
import { DataPreviewDialog } from "./data-preview-dialog";

import type {
  ExecutionStatusResponse,
  CanvasStatus,
  NodeResult,
} from "@/core/canvas/types";

interface ExecutionStatusProps {
  className?: string;
}

const statusIcons: Record<CanvasStatus, React.ReactNode> = {
  idle: <Clock className="h-4 w-4" />,
  running: <Loader2 className="h-4 w-4 animate-spin text-blue-500" />,
  paused: <Clock className="h-4 w-4 text-yellow-500" />,
  completed: <CheckCircle className="h-4 w-4 text-green-500" />,
  failed: <XCircle className="h-4 w-4 text-red-500" />,
};

const statusLabels: Record<CanvasStatus, string> = {
  idle: "空闲",
  running: "执行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
};

export function ExecutionStatus({ className }: ExecutionStatusProps) {
  const {
    canvas,
    executionStatus,
    canvasMode,
    selectedNodeId,
    selectNode,
  } = useCanvasContext();

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewNodeId, setPreviewNodeId] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<{
    rows: Record<string, unknown>[];
    columns: { name: string; type: string }[];
    rows_count: number;
  } | null>(null);

  if (!executionStatus && !canvas) return null;

  const status = executionStatus?.status ?? "idle";
  const completedNodes = executionStatus?.completed_nodes ?? [];
  const pendingNodes = executionStatus?.pending_nodes ?? [];
  const results = executionStatus?.results ?? {};

  // Get execution log from canvas
  const executionLog = canvas?.execution_log ?? [];

  const handlePreviewNode = (nodeId: string) => {
    setPreviewNodeId(nodeId);
    // TODO: Load actual preview data from API
    setPreviewData({
      rows: [],
      columns: [],
      rows_count: 0,
    });
    setPreviewOpen(true);
  };

  return (
    <div className={cn("border rounded-md bg-background", className)}>
      <div className="border-b px-3 py-2">
        <div className="flex items-center gap-2">
          {statusIcons[status]}
          <span className="text-sm font-medium">
            {statusLabels[status]}
          </span>
          {status === "running" && (
            <span className="text-xs text-muted-foreground">
              {completedNodes.length}/
              {completedNodes.length + pendingNodes.length}
            </span>
          )}
        </div>
      </div>

      <ScrollArea className="h-[200px]">
        <div className="p-2">
          <div className="text-xs font-medium text-muted-foreground mb-2">
            节点执行历史
          </div>
          {executionLog.length === 0 ? (
            <div className="text-xs text-muted-foreground text-center py-4">
              暂无执行记录
            </div>
          ) : (
            <div className="space-y-1">
              {executionLog.map((log) => {
                const isSelected = selectedNodeId === log.node_id;
                const nodeResult = results[log.node_id];

                return (
                  <div
                    key={log.node_id}
                    className={cn(
                      "flex items-center justify-between rounded p-1.5",
                      "hover:bg-muted cursor-pointer",
                      isSelected && "bg-muted"
                    )}
                    onClick={() => selectNode(log.node_id)}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-xs",
                          log.success ? "text-green-600" : "text-red-600"
                        )}
                      >
                        {log.success ? "✓" : "✗"}
                      </span>
                      <span className="text-xs">{log.node_id}</span>
                      {log.output_table && (
                        <span className="text-xs text-muted-foreground">
                          → {log.output_table}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {log.success && log.rows_affected > 0 && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5"
                          onClick={(e) => {
                            e.stopPropagation();
                            handlePreviewNode(log.node_id);
                          }}
                        >
                          <Eye className="h-3 w-3" />
                        </Button>
                      )}
                      <ChevronRight className="h-3 w-3 text-muted-foreground" />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Selected node result */}
      {selectedNodeId && results[selectedNodeId] && (
        <div className="border-t p-2">
          <div className="text-xs font-medium mb-1">
            {selectedNodeId} 结果:
          </div>
          <div className="text-xs space-y-0.5">
            {results[selectedNodeId].output_table && (
              <div>
                输出表: {results[selectedNodeId].output_table}
              </div>
            )}
            <div>
              影响行数: {results[selectedNodeId].rows_affected}
            </div>
            {!results[selectedNodeId].success && (
              <div className="text-red-600">
                错误: {results[selectedNodeId].error}
              </div>
            )}
          </div>
        </div>
      )}

      <DataPreviewDialog
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        title={previewNodeId ?? ""}
        columns={previewData?.columns ?? []}
        rows={previewData?.rows ?? []}
        totalRows={previewData?.rows_count ?? 0}
      />
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/workspace/canvas/execution-status.tsx
git commit -m "feat(canvas): enhance ExecutionStatus with history and preview

- Show execution log history
- Click to select node
- Preview data button for successful nodes
- Selected node detail panel

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 15: 集成测试与修复

- [ ] **Step 1: 运行前端类型检查和lint**

Run: `cd /Users/frankliu/Code/deerflow/frontend && pnpm check`
Expected: 无错误

如有错误，修复后继续。

- [ ] **Step 2: 运行后端lint**

Run: `cd /Users/frankliu/Code/deerflow/backend && make lint`
Expected: 无错误

- [ ] **Step 3: 启动开发服务器验证**

Run: `cd /Users/frankliu/Code/deerflow && make dev`

在浏览器中验证：
1. Canvas面板可以打开
2. 组件面板显示并可拖拽
3. 节点编辑器根据节点类型显示
4. 模式切换按钮工作
5. 执行状态显示工作

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat(canvas): complete Canvas data processing implementation

- Add database connection API for table browsing
- Add SQL validation and node preview endpoints
- Implement component panel with drag-and-drop
- Add type-specific node editors (Data Source, SQL Executor)
- Add code editor dialog for SQL/Python editing
- Add data preview dialog
- Implement edit/run mode toggle
- Enhance execution status display

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## 规格覆盖检查

| 规格要求 | 任务 |
|---------|------|
| 数据库连接 API | Task 1 |
| 表列表/结构/预览 API | Task 1 |
| SQL 验证 API | Task 2 |
| 节点预览 API | Task 2 |
| 停止执行 API | Task 2 |
| CanvasContext 扩展 | Task 5 |
| 组件面板（拖拽） | Task 6 |
| 代码编辑弹窗 | Task 7 |
| 数据预览弹窗 | Task 8 |
| Data Source 编辑器 | Task 9 |
| SQL Executor 编辑器 | Task 10 |
| 节点编辑器重构 | Task 11 |
| 组件面板集成 | Task 12 |
| 模式切换按钮 | Task 13 |
| 执行结果面板 | Task 14 |

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-26-canvas-data-processing-implementation.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
