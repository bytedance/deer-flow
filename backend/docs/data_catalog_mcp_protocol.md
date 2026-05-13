# data_catalog MCP 工具协议文档

本文档定义了 `data_catalog` MCP Server 提供的工具协议，供外部数据平台团队实现 MCP Server 时参考。

## 概述

`data_catalog` MCP Server 为 DeerFlow Agent 提供数据目录发现和数据获取能力。Agent 通过 MCP 协议调用这些工具，实现动态数据源选择和数据分析。

## 工具定义

### 1. `data_catalog.list_datasets`

列举当前租户可用的数据集。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | integer | 否 | 50 | 返回的最大数据集数量 |
| `offset` | integer | 否 | 0 | 分页偏移量 |
| `keyword` | string | 否 | null | 按名称/描述搜索的关键词 |
| `tags` | string[] | 否 | [] | 按标签过滤 |

**返回值：**

```json
{
  "datasets": [
    {
      "id": "ds_001",
      "name": "销售数据-2024",
      "description": "2024年全渠道销售明细数据",
      "tags": ["sales", "2024"],
      "row_count": 150000,
      "column_count": 25,
      "updated_at": "2024-12-01T08:00:00Z",
      "size_bytes": 45000000
    }
  ],
  "total": 120,
  "has_more": true
}
```

**错误码：**

| 错误 | 说明 |
|------|------|
| `UNAUTHORIZED` | 认证失败或 token 过期 |
| `RATE_LIMITED` | 请求频率超限 |

---

### 2. `data_catalog.get_dataset_schema`

获取指定数据集的字段结构（schema）。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset_id` | string | 是 | 数据集 ID |

**返回值：**

```json
{
  "dataset_id": "ds_001",
  "name": "销售数据-2024",
  "columns": [
    {
      "name": "order_id",
      "type": "string",
      "description": "订单编号",
      "nullable": false
    },
    {
      "name": "amount",
      "type": "float",
      "description": "订单金额（元）",
      "nullable": false
    },
    {
      "name": "created_at",
      "type": "datetime",
      "description": "下单时间",
      "nullable": false
    }
  ],
  "primary_key": ["order_id"],
  "partition_key": "created_at"
}
```

**错误码：**

| 错误 | 说明 |
|------|------|
| `NOT_FOUND` | 数据集不存在 |
| `UNAUTHORIZED` | 认证失败 |

---

### 3. `data_catalog.fetch_dataset`

获取指定数据集的数据内容。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `dataset_id` | string | 是 | - | 数据集 ID |
| `columns` | string[] | 否 | null (全部) | 要获取的列名列表 |
| `filters` | object[] | 否 | [] | 过滤条件 |
| `limit` | integer | 否 | 1000 | 返回行数上限 |
| `offset` | integer | 否 | 0 | 分页偏移 |
| `order_by` | string | 否 | null | 排序字段 |
| `order_dir` | string | 否 | "asc" | 排序方向: asc / desc |
| `format` | string | 否 | "json" | 返回格式: json / csv |

**filters 结构：**

```json
[
  {"column": "created_at", "op": ">=", "value": "2024-01-01"},
  {"column": "amount", "op": ">", "value": 100}
]
```

支持的 `op`: `=`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not_in`, `like`, `is_null`, `is_not_null`

**返回值（format=json）：**

```json
{
  "dataset_id": "ds_001",
  "columns": ["order_id", "amount", "created_at"],
  "rows": [
    {"order_id": "ORD001", "amount": 299.0, "created_at": "2024-01-15T10:30:00Z"},
    {"order_id": "ORD002", "amount": 150.5, "created_at": "2024-01-15T11:00:00Z"}
  ],
  "total_rows": 150000,
  "returned_rows": 1000,
  "has_more": true
}
```

**错误码：**

| 错误 | 说明 |
|------|------|
| `NOT_FOUND` | 数据集不存在 |
| `INVALID_COLUMN` | 请求的列名不存在 |
| `QUERY_TIMEOUT` | 查询超时（建议缩小范围或加过滤条件） |
| `UNAUTHORIZED` | 认证失败 |

---

### 4. `data_catalog.get_dataset_stats`

获取数据集的统计摘要信息。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `dataset_id` | string | 是 | 数据集 ID |
| `columns` | string[] | 否 | null (全部数值列) | 要统计的列 |

**返回值：**

```json
{
  "dataset_id": "ds_001",
  "stats": [
    {
      "column": "amount",
      "type": "float",
      "count": 150000,
      "null_count": 0,
      "min": 0.5,
      "max": 99999.0,
      "mean": 856.3,
      "median": 320.0,
      "std": 2100.5,
      "p25": 120.0,
      "p75": 890.0
    }
  ]
}
```

**错误码：**

| 错误 | 说明 |
|------|------|
| `NOT_FOUND` | 数据集不存在 |
| `UNAUTHORIZED` | 认证失败 |

---

## Python MCP Server 示例实现

以下是一个最小化的 `data_catalog` MCP Server 实现示例，使用 `mcp` Python SDK：

```python
"""data_catalog MCP Server — 示例实现"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("data-catalog")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="data_catalog.list_datasets",
            description="列举可用数据集",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                    "keyword": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        Tool(
            name="data_catalog.get_dataset_schema",
            description="获取数据集字段结构",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="data_catalog.fetch_dataset",
            description="获取数据集数据",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "array"},
                    "limit": {"type": "integer", "default": 1000},
                    "offset": {"type": "integer", "default": 0},
                    "order_by": {"type": "string"},
                    "order_dir": {"type": "string", "enum": ["asc", "desc"]},
                    "format": {"type": "string", "enum": ["json", "csv"]},
                },
                "required": ["dataset_id"],
            },
        ),
        Tool(
            name="data_catalog.get_dataset_stats",
            description="获取数据集统计摘要",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["dataset_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "data_catalog.list_datasets":
        # 实际实现：查询数据平台 API
        return [TextContent(type="text", text='{"datasets": [], "total": 0, "has_more": false}')]
    elif name == "data_catalog.get_dataset_schema":
        dataset_id = arguments["dataset_id"]
        # 实际实现：查询数据平台获取 schema
        return [TextContent(type="text", text=f'{{"dataset_id": "{dataset_id}", "columns": []}}')]
    elif name == "data_catalog.fetch_dataset":
        dataset_id = arguments["dataset_id"]
        limit = arguments.get("limit", 1000)
        # 实际实现：查询数据并返回
        return [TextContent(type="text", text=f'{{"dataset_id": "{dataset_id}", "rows": [], "returned_rows": 0}}')]
    elif name == "data_catalog.get_dataset_stats":
        dataset_id = arguments["dataset_id"]
        # 实际实现：计算统计信息
        return [TextContent(type="text", text=f'{{"dataset_id": "{dataset_id}", "stats": []}}')]
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## 在 DeerFlow 中配置

在 `extensions_config.json` 中添加：

```json
{
  "mcpServers": {
    "data-catalog": {
      "enabled": true,
      "type": "stdio",
      "command": "python",
      "args": ["/path/to/data_catalog_server.py"],
      "description": "数据目录服务 — 提供数据集发现和获取能力"
    }
  }
}
```

配置后，data-analyst Agent 会自动通过 MCP 协议调用 `data_catalog.*` 工具（优先级高于 http_connector）。

## 安全要求

1. MCP Server 必须验证调用方身份（通过环境变量传入的 token）
2. 数据访问必须遵循租户隔离原则
3. 大数据集查询必须支持分页，单次返回不超过 10000 行
4. 敏感字段（如 PII）应在 Server 端脱敏后返回
