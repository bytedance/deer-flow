# 外部数据源选择与 Agent 集成设计

> DeerFlow 项目 — Agent 驱动的外部数据源动态选择方案

## 1. 背景与目标

### 1.1 问题

当前 data-analyst agent 使用硬编码的表单选项（CSV/Excel/数据库/API/已上传文件），无法动态获取外部系统的真实数据源列表。用户需要：

1. 进入 agent 对话时，看到一个**动态加载**的数据选择表单，选项来自外部系统
2. 选择后 agent 自动获取对应数据并开始分析
3. 数据源接入方式需要灵活可扩展（REST API、数据库、MCP Server 等）

### 1.2 目标

设计一个统一的外部数据源选择机制，整合 **Tool**、**Skill**、**MCP** 三个扩展点：

1. Agent 能动态发现并列举可用数据源
2. 通过 GenUI form 组件让用户交互式选择
3. 选择后 Agent 获取实际数据进行分析
4. 支持多种接入方式：平台通用 Tool、Skill 指导、MCP Server 提供

### 1.3 架构原则：业务工具不入 builtins

**关键决策**：`list_datasets` / `fetch_dataset` 是业务工具，不应放在 `builtins/`（平台级工具目录）。

平台层只提供**通用能力**（如 `render_ui`、`http_connector`），业务逻辑通过以下方式承载：

| 层级 | 职责 | 示例 |
| ---- | ---- | ---- |
| 平台 builtins | 通用能力（UI 渲染、HTTP 调用、文件操作） | `render_ui`, `http_connector` |
| 配置层 | 定义具体的 HTTP endpoint 和参数 schema | config.yaml `http_connectors` |
| Skill 层 | 告诉 Agent 调用哪个 connector、如何组合 | SOUL.md |
| MCP 层 | 外部系统自行暴露工具，替代 http_connector | `data_catalog.list` |

好处：
- **builtins 保持纯净**：只有通用能力，不含业务逻辑
- **业务可配置**：新增数据源只需加配置，不需要写代码
- **MCP 优先**：有 MCP Server 时直接用，http_connector 作为轻量 fallback
- **Skill 编排**：业务流程的"智能"在 Skill 里，不在 Tool 里

---

## 2. 架构总览

```
用户触发 data-analyst agent
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent 决策层（由 Skill 指导行为）                              │
│                                                             │
│  1. 调用 http_connector / MCP tool → 获取数据源列表           │
│  2. 调用 render_ui(form) → 渲染动态选择表单                    │
│  3. 等待用户选择 (callback)                                   │
│  4. 调用 http_connector / MCP tool → 获取实际数据             │
│  5. 分析数据 → render_ui(echart/table) 展示结果                │
└─────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
   ┌──────────────┐   ┌────────────┐       ┌──────────┐
   │ Platform Tool │   │   Skill    │       │   MCP    │
   │  (通用能力)    │   │ (指导层)    │       │ (扩展层)  │
   └──────────────┘   └────────────┘       └──────────┘
   http_connector      data-analyst         外部 MCP Server
   render_ui           SOUL.md 指导          提供 data_catalog.*
   (平台 builtins)      Agent 行为            工具
```

### 2.1 三层职责划分

| 层级 | 机制 | 职责 | 扩展方式 |
| ---- | ---- | ---- | -------- |
| **平台层** | Tool (builtins) | 提供通用 HTTP 调用能力，不含业务逻辑 | 平台升级 |
| **配置层** | config.yaml | 定义具体的 endpoint、参数 schema、认证方式 | 修改配置 |
| **指导层** | Skill | 告诉 Agent 何时调用哪个 connector、如何组合表单 | 修改 SOUL.md |
| **扩展层** | MCP | 第三方系统通过 MCP Server 暴露能力，Agent 直接调用 | 注册 MCP Server |

---

## 3. 平台 Tool 层：通用 HTTP Connector

### 3.1 设计理念

不写 `list_datasets` / `fetch_dataset` 这种业务工具。平台提供一个**通用 HTTP Connector Tool**，业务逻辑全部下沉到配置 + Skill。

Agent 调用的是 `http_connector(name="list_datasets", params={...})`，tool 本身不含任何业务逻辑。

**注册方式**：与 `render_ui` 相同，作为硬编码 builtin 加入 `BUILTIN_TOOLS` 列表，始终可用，无需 config.yaml 配置。

### 3.2 `http_connector` Tool 实现

> **设计决策**：使用 `httpx.AsyncClient`（async），因为 LangGraph Agent 运行在 async 事件循环中。同步 httpx 会阻塞事件循环，尤其在外部 API 响应慢（30-60s timeout）时影响严重。LangGraph 原生支持 async tool（`@tool` + `async def`）。

```python
# backend/packages/harness/deerflow/tools/builtins/http_connector_tool.py

from __future__ import annotations

import json
import logging

import httpx
from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESPONSE_BYTES = 512 * 1024  # 512KB


def _truncate_response(text: str, max_bytes: int) -> str:
    """Truncate response if it exceeds max_bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + f"\n... [truncated: {len(encoded) - max_bytes} bytes omitted]"


@tool("http_connector", parse_docstring=True)
async def http_connector_tool(
    connector_name: str,
    params: dict | None = None,
    body: dict | None = None,
) -> str:
    """Call a pre-configured HTTP endpoint by name.

    Use this tool to interact with external systems through pre-defined
    HTTP connectors. Each connector has a fixed URL, method, and auth
    configured by the platform administrator.

    Args:
        connector_name: Name of the configured connector (e.g., "list_datasets", "fetch_dataset").
        params: Optional query parameters (for GET requests) or merged into body (for POST).
        body: Optional request body (for POST/PUT requests).

    Returns:
        The HTTP response body as a string (typically JSON).
    """
    tenant_id = get_current_tenant_id()

    app_config = get_app_config()
    connector = app_config.get_http_connector(tenant_id, connector_name)

    if not connector:
        return json.dumps({
            "error": f"Unknown connector '{connector_name}'. "
                     f"Available: {app_config.list_connector_names(tenant_id)}"
        })

    max_bytes = connector.max_response_bytes or DEFAULT_MAX_RESPONSE_BYTES

    try:
        async with httpx.AsyncClient(timeout=connector.timeout_seconds) as client:
            for attempt in range(1 + connector.max_retries):
                try:
                    if connector.method == "GET":
                        response = await client.get(
                            connector.url,
                            params=params or {},
                            headers=connector.resolved_headers(),
                        )
                    else:
                        request_body = {**(body or {}), **(params or {})}
                        response = await client.request(
                            method=connector.method,
                            url=connector.url,
                            json=request_body,
                            headers=connector.resolved_headers(),
                        )

                    if response.status_code in connector.retry_on_status and attempt < connector.max_retries:
                        logger.warning(
                            "http_connector %s attempt %d got %d, retrying",
                            connector_name, attempt + 1, response.status_code,
                        )
                        continue

                    response.raise_for_status()

                    logger.info(
                        "http_connector %s tenant=%s status=%d latency=%.1fms size=%d",
                        connector_name, tenant_id, response.status_code,
                        response.elapsed.total_seconds() * 1000,
                        len(response.content),
                    )

                    return _truncate_response(response.text, max_bytes)

                except httpx.HTTPStatusError:
                    if attempt < connector.max_retries:
                        continue
                    raise

    except httpx.HTTPError as e:
        logger.error("http_connector %s failed: %s", connector_name, e)
        return json.dumps({"error": f"HTTP request failed: {e}"})
```

### 3.3 注册为 Builtin Tool

```python
# backend/packages/harness/deerflow/tools/builtins/__init__.py

from .http_connector_tool import http_connector_tool
from .present_file_tool import present_file_tool
from .ask_clarification_tool import ask_clarification_tool
from .render_ui_tool import render_ui_tool

# backend/packages/harness/deerflow/tools/tools.py

BUILTIN_TOOLS = [
    present_file_tool,
    ask_clarification_tool,
    render_ui_tool,
    http_connector_tool,  # 新增：通用 HTTP 调用能力
]
```

与 `render_ui` 同级，始终注入所有 Agent，无需在 config.yaml 的 `tool_groups` 或 `tools` 中声明。

### 3.4 Connector 配置模型

```python
# backend/packages/harness/deerflow/config/http_connector_config.py

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class HttpConnectorConfig(BaseModel):
    """Configuration for a named HTTP connector endpoint."""

    name: str = Field(..., description="Connector 名称，Agent 通过此名称调用")
    url: str = Field(..., description="目标 URL")
    method: str = Field(default="GET", description="HTTP method: GET | POST | PUT")
    headers: dict[str, str] = Field(default_factory=dict)
    auth_type: str = Field(default="none", description="none | bearer | api_key")
    auth_token_env: str | None = Field(default=None, description="环境变量名，存放 token")
    auth_header: str = Field(default="Authorization", description="token 放在哪个 header")
    timeout_seconds: float = Field(default=30.0)
    description: str = Field(default="", description="给 Agent 看的描述")

    # 响应体积限制（防止外部 API 返回超大 JSON 撑爆 LLM context）
    max_response_bytes: int = Field(default=512 * 1024, description="最大响应体积，超出截断（默认 512KB）")

    # 重试策略
    max_retries: int = Field(default=1, description="最大重试次数（0=不重试）")
    retry_on_status: list[int] = Field(
        default_factory=lambda: [502, 503, 504],
        description="触发重试的 HTTP 状态码",
    )

    # 响应缓存（复用项目现有 Redis cache 基础设施）
    cache_ttl_seconds: int | None = Field(
        default=None,
        description="响应缓存 TTL（秒）。None=不缓存。适用于 list 类接口避免重复调用",
    )
    # NOTE: cache_ttl_seconds 为预留字段，Phase 1 不含缓存实现。
    # Phase 2 接入项目现有 Redis cache 基础设施时启用。
    # 实现时在 http_connector_tool 中增加：
    #   1. 调用前查询 cache（key = f"{tenant_id}:{connector_name}:{hash(params)}"）
    #   2. 命中则直接返回缓存值
    #   3. 未命中则发请求，成功后写入 cache（TTL = cache_ttl_seconds）

    def resolved_headers(self) -> dict[str, str]:
        """Resolve auth token from environment and merge into headers."""
        result = dict(self.headers)
        if self.auth_type == "bearer" and self.auth_token_env:
            token = os.environ.get(self.auth_token_env, "")
            if token:
                result[self.auth_header] = f"Bearer {token}"
        elif self.auth_type == "api_key" and self.auth_token_env:
            token = os.environ.get(self.auth_token_env, "")
            if token:
                result[self.auth_header] = token
        return result
```

在 `AppConfig` 中新增字段：

```python
# backend/packages/harness/deerflow/config/app_config.py (新增)

class AppConfig(BaseModel):
    # ... existing fields ...
    http_connectors: dict[str, list[HttpConnectorConfig]] = Field(
        default_factory=dict,
        description="HTTP connectors keyed by tenant_id"
    )

    def get_http_connector(self, tenant_id: str, name: str) -> HttpConnectorConfig | None:
        connectors = self.http_connectors.get(tenant_id, [])
        return next((c for c in connectors if c.name == name), None)

    def list_connector_names(self, tenant_id: str) -> list[str]:
        return [c.name for c in self.http_connectors.get(tenant_id, [])]
```

### 3.5 config.yaml 配置示例

```yaml
# config.yaml — 新增 http_connectors 段

http_connectors:
  default:  # tenant_id
    - name: list_datasets
      description: "列举可用数据集"
      url: "http://data-platform.internal/api/v1/datasets"
      method: GET
      auth_type: bearer
      auth_token_env: DATA_PLATFORM_TOKEN
      timeout_seconds: 30
      max_response_bytes: 524288    # 512KB
      cache_ttl_seconds: 300        # 5 分钟缓存，避免重复调用
      max_retries: 1

    - name: fetch_dataset
      description: "获取指定数据集的数据"
      url: "http://data-platform.internal/api/v1/datasets/query"
      method: POST
      auth_type: bearer
      auth_token_env: DATA_PLATFORM_TOKEN
      timeout_seconds: 60
      max_response_bytes: 1048576   # 1MB（数据量较大）
      cache_ttl_seconds: null       # 不缓存（每次查询参数不同）
      max_retries: 1

    - name: dataset_schema
      description: "获取数据集的字段结构"
      url: "http://data-platform.internal/api/v1/datasets/schema"
      method: GET
      auth_type: bearer
      auth_token_env: DATA_PLATFORM_TOKEN
      timeout_seconds: 15
      cache_ttl_seconds: 600        # 10 分钟缓存（schema 变化不频繁）
```

注意：`http_connector` tool 本身是 builtin（始终可用），但它调用的具体 endpoint 通过此配置定义。无配置时 tool 仍可用，只是会返回 "unknown connector" 错误。

### 3.6 已知限制：GenUI Block 状态不持久化

**问题**：GenUI blocks 存储在前端 Zustand store（内存），页面刷新后丢失。LangGraph checkpointer 只保存消息历史（包含 tool call/result），不保存 UI block 的渲染状态。

**影响**：
- 用户刷新页面后，历史对话中的表单/图表消失（只剩文本消息）
- 当前 inline rendering 方案（从 tool message 中解析 `block_id`）依赖 block store 中有对应数据

**当前缓解**：
- 消息历史中的 tool result 包含 `block_id=<uuid>` 引用，但 block payload 通过 SSE custom event 传递，不在消息中持久化
- 页面刷新后 block store 为空，inline `GenUIBlockList` 渲染为空

**后续方案（Phase 2+）**：
1. **方案 A — 后端持久化**：将 block payload 存入 ThreadState（通过 LangGraph state reducer），页面加载时从 thread state 恢复
2. **方案 B — 消息内嵌**：render_ui tool result 中同时保存完整 block JSON（而非仅 block_id），前端加载历史时从 tool message 重建 store
3. **方案 C — 重新触发**：页面加载历史时，检测到 block_id 引用但 store 为空，向后端请求重新生成 blocks

推荐方案 B（改动最小，不需要后端新增存储），但需要评估 tool message 体积增长对 LLM context 的影响。

---

## 4. Skill 层设计

### 4.1 修改 data-analyst SOUL.md

Skill 作为 prompt 注入，指导 Agent 的行为流程。Skill 中引用的是 connector 名称，不是具体的业务 tool。

> **注**：以下为简化示例（仅展示 MCP + http_connector 两级）。完整 4 级优先级版本见 Section 9.5（MCP → Skill Script → http_connector → 静态表单）。

```markdown
# Data Analyst

## MANDATORY FIRST ACTION

When a user asks for data analysis, you MUST follow this sequence:

### Step 1: Discover Available Data

**If you have MCP tools like `data_catalog.list`**, use them directly:
```
data_catalog.list(limit=50)
```

**Otherwise**, use the platform `http_connector` tool:
```
http_connector(connector_name="list_datasets", params={"limit": 50})
```

Both return a similar structure: a JSON array of dataset objects with id, name, description.

### Step 2: Render Selection Form

Based on the result, call `render_ui` with a dynamic form.
Map each dataset to a select option:

```
render_ui(
  component="form",
  action="create",
  interactive=True,
  callback_id="dataset-selection",
  callback_timeout_ms=600000,
  props={
    "title": "选择数据源",
    "description": "请选择要分析的数据集",
    "submit_label": "开始分析",
    "fields": [
      {
        "name": "dataset_id",
        "label": "数据集",
        "type": "select",
        "required": True,
        "options": [
          // Map from result:
          {"label": "<name> — <description>", "value": "<id>"}
        ]
      },
      {
        "name": "analysis_goal",
        "label": "分析目标",
        "type": "textarea",
        "required": True,
        "placeholder": "描述您想从数据中了解什么..."
      },
      {
        "name": "output_format",
        "label": "输出格式",
        "type": "select",
        "required": True,
        "options": [
          {"label": "图表可视化", "value": "chart"},
          {"label": "数据表格", "value": "table"},
          {"label": "完整分析报告", "value": "report"}
        ]
      }
    ]
  }
)
```

After calling render_ui, respond with: "我已加载可用数据源，请选择后提交。" and STOP.

### Step 3: Fetch Selected Data

When you receive a `ui_interaction` callback with `callback_id="dataset-selection"`:

1. Extract `dataset_id` from the payload
2. Fetch data:
   - MCP: `data_catalog.fetch(dataset_id=<id>, limit=1000)`
   - http_connector: `http_connector(connector_name="fetch_dataset", body={"dataset_id": "<id>", "limit": 1000})`
3. Profile the dataset — distributions, missing values, outliers
4. Apply analysis based on the user's `analysis_goal`
5. Present results using `render_ui` with appropriate components

### Fallback: No Data Source Available

If the connector returns an empty list or error, AND no MCP data tools are available:
- Fall back to the static form (ask user to upload a file or provide data manually)
- Use the original static form fields (CSV/Excel/database/API)

## Role
...
```

### 4.2 Skill 与平台 Tool 的协作关系

```
┌──────────────────────────────────────────────────────────┐
│                    Agent Runtime                           │
│                                                           │
│  System Prompt = base_prompt                              │
│                + SOUL.md (Skill 注入)                      │
│                + GenUI Guidance                            │
│                                                           │
│  Available Tools = [render_ui, http_connector]  ← 平台级   │
│                  + [data_catalog.*]             ← MCP 注入  │
│                                                           │
│  Skill 告诉 Agent:                                        │
│    "优先用 MCP data_catalog.list，                          │
│     没有则用 http_connector(name='list_datasets')"         │
│                                                           │
│  http_connector 本身不知道什么是 dataset，                   │
│  它只是按配置发 HTTP 请求。                                  │
│  业务语义由 Skill + 配置共同赋予。                            │
└──────────────────────────────────────────────────────────┘
```

---

## 5. MCP 层设计

### 5.1 MCP 作为外部数据源扩展点

当外部系统提供 MCP Server 时，Agent 可以直接使用 MCP 暴露的工具，无需内置 `list_datasets` / `fetch_dataset`。

**MCP Server 协议约定**：

外部数据平台实现一个 MCP Server，暴露以下工具：

| MCP Tool Name | 对应功能 | 参数 |
| ------------- | -------- | ---- |
| `data_catalog.list` | 列举数据集 | `source_type?`, `search?`, `limit?` |
| `data_catalog.fetch` | 获取数据 | `dataset_id`, `columns?`, `filters?`, `limit?` |
| `data_catalog.schema` | 获取表结构 | `dataset_id` |
| `data_catalog.preview` | 预览前 N 行 | `dataset_id`, `rows?` |

### 5.2 MCP Server 配置

```json
// extensions_config.json (新增数据平台 MCP Server)
{
  "mcpServers": {
    "data-platform": {
      "type": "http",
      "url": "http://data-platform.internal/mcp",
      "headers": {"Authorization": "$DATA_PLATFORM_TOKEN"},
      "description": "Enterprise data catalog and query service"
    }
  }
}
```

> 注：`$DATA_PLATFORM_TOKEN` 会在运行时从环境变量解析。如需 OAuth2 token 刷新，使用 `oauth` 子配置替代 `headers`。

### 5.3 Agent 配置绑定 MCP Server

```yaml
# AgentConfig 字段（通过租户 Agent API 或 builtin agent 扫描加载）

name: data-analyst
display_name: 数据分析师
description: 数据分析专家，支持从外部数据源选择数据进行分析

tool_groups: null       # null = 所有 tool groups + BUILTIN_TOOLS

mcp_servers:
  - data-platform       # 优先使用 MCP Server 提供的工具

skills:
  - data-analyst        # SOUL.md 指导行为
```

### 5.4 Tool 优先级与 Fallback

```text
Agent 需要列举数据源
        │
        ▼
┌─ MCP Server 可用？──────────────────────────────┐
│  YES: 使用 data_catalog.list                    │
│  (MCP 工具自动合并到 Agent tool set)              │
├─────────────────────────────────────────────────┤
│  NO: 使用 http_connector(name="list_datasets")  │
│  (通过 config.yaml http_connectors 配置)         │
├─────────────────────────────────────────────────┤
│  BOTH EMPTY: 降级为静态表单                       │
└─────────────────────────────────────────────────┘
```

Skill (SOUL.md) 中的指导兼容两种情况（已在第 4 节 Skill 设计中体现）。

---

## 6. 数据流详解

### 6.1 完整交互时序

```text
┌──────┐     ┌──────────┐     ┌──────────┐     ┌──────────────┐
│ User │     │ Frontend │     │  Agent   │     │ External Sys │
└──┬───┘     └────┬─────┘     └────┬─────┘     └──────┬───────┘
   │              │                 │                    │
   │ "分析数据"    │                 │                    │
   │─────────────→│                 │                    │
   │              │  stream start   │                    │
   │              │────────────────→│                    │
   │              │                 │                    │
   │              │                 │ http_connector     │
   │              │                 │ ("list_datasets")  │
   │              │                 │───────────────────→│
   │              │                 │                    │
   │              │                 │ [{id, name, ...}]  │
   │              │                 │←───────────────────│
   │              │                 │                    │
   │              │  render_ui(form)│                    │
   │              │  SSE custom     │                    │
   │              │←────────────────│                    │
   │              │                 │                    │
   │  显示选择表单  │                 │                    │
   │←─────────────│                 │                    │
   │              │                 │                    │
   │ 选择 dataset │                 │                    │
   │─────────────→│                 │                    │
   │              │ POST callback   │                    │
   │              │────────────────→│                    │
   │              │                 │                    │
   │              │                 │ http_connector     │
   │              │                 │ ("fetch_dataset")  │
   │              │                 │───────────────────→│
   │              │                 │                    │
   │              │                 │ {columns, data}    │
   │              │                 │←───────────────────│
   │              │                 │                    │
   │              │  render_ui      │                    │
   │              │  (echart/table) │                    │
   │              │←────────────────│                    │
   │              │                 │                    │
   │  显示分析结果  │                 │                    │
   │←─────────────│                 │                    │
```

### 6.2 数据源列表响应格式

```json
{
  "datasets": [
    {
      "id": "ds-001",
      "name": "销售订单表",
      "description": "2024-2026 年全渠道销售订单明细",
      "source_type": "database",
      "schema": [
        {"name": "order_id", "type": "string"},
        {"name": "amount", "type": "number"},
        {"name": "created_at", "type": "datetime"},
        {"name": "channel", "type": "string"}
      ],
      "row_count": 1250000,
      "updated_at": "2026-05-12T08:00:00Z"
    },
    {
      "id": "ds-002",
      "name": "用户行为日志",
      "description": "App 端用户点击、浏览、购买行为",
      "source_type": "api",
      "schema": [
        {"name": "user_id", "type": "string"},
        {"name": "event_type", "type": "string"},
        {"name": "timestamp", "type": "datetime"}
      ],
      "row_count": 8500000,
      "updated_at": "2026-05-12T10:30:00Z"
    }
  ],
  "total": 2,
  "source": "data-platform-mcp"
}
```

---

## 7. 配置与注册

### 7.1 Tool 注册

`http_connector` 作为 builtin tool 硬编码注册（见第 3.3 节），无需在 config.yaml 中声明。

如需将其作为可选 tool（非所有 Agent 都可用），可在 config.yaml 的 `tools` 列表中注册：

```yaml
# config.yaml — 可选：作为普通 tool 注册（如果不想放 BUILTIN_TOOLS）

tools:
  - name: http_connector
    group: platform
    use: "deerflow.tools.builtins.http_connector_tool:http_connector_tool"

tool_groups:
  - name: platform
```

推荐方案：直接加入 `BUILTIN_TOOLS`，始终可用。

### 7.2 Agent 配置

data-analyst agent 通过 `AgentConfig` Pydantic 模型定义（可通过租户 Agent CRUD API 创建，或作为 builtin agent 扫描加载）：

```yaml
# Agent 配置（AgentConfig 字段）

name: data-analyst
display_name: 数据分析师
description: 数据分析专家，支持动态数据源选择

tool_groups: null          # null = 使用所有可用 tool groups（含 builtin）

mcp_servers:
  - data-platform          # 可选，有则优先使用 MCP 工具

skills:
  - data-analyst           # 过滤只加载此 skill

# 表单超时设长（用户需要时间选择）
default_callback_timeout_ms: 600000
```

> 注：`tool_groups: null` 表示不限制，Agent 可使用所有已注册的 tool groups + BUILTIN_TOOLS。`http_connector` 作为 builtin 始终可用，无需显式声明。

### 7.3 多租户 Connector 配置管理

**Phase 1（当前方案）**：config.yaml 静态配置，按 tenant_id 分组。适合 self-hosted 单租户或少量租户部署。config.yaml 支持 hot-reload（mtime 检测），修改后无需重启。

**Phase 2（后续演进）**：多租户 SaaS 场景下，不可能让每个租户都去改服务器上的 yaml。需要：

- 通过 Admin API 动态管理 connector 配置（类似现有的 Agent CRUD API）
- 存储在数据库中（per-tenant），运行时按 tenant_id 查询
- 保留 config.yaml 作为 fallback / 默认配置
- API 端点示例：`POST /api/tenants/{tenant_id}/connectors`、`GET /api/tenants/{tenant_id}/connectors`

此演进不影响 `http_connector` tool 的实现（它只调用 `app_config.get_http_connector(tenant_id, name)`），只需替换底层配置源。

---

## 8. 扩展场景

### 8.1 多级选择（先选系统再选表）

Skill 指导 Agent 实现两步表单：

```markdown
### Multi-level Selection

If the data source has hierarchical structure (system → database → table):

1. First call: `http_connector(name="list_datasets", params={"source_type": "system"})` → get systems
2. Render first form: select system
3. On callback: `http_connector(name="list_datasets", params={"source_type": "table", "search": "<selected_system>"})` 
4. Render second form: select specific table
5. On callback: `http_connector(name="fetch_dataset", body={"dataset_id": "<selected_table>"})` 
```

### 8.2 自定义 MCP Server 接入

第三方团队只需实现一个 MCP Server：

```python
# 示例：自定义数据平台 MCP Server (Python)

from mcp import Server, Tool

server = Server("data-platform")

@server.tool("data_catalog.list")
async def list_datasets(source_type: str = None, search: str = None, limit: int = 50):
    """List available datasets from the data platform."""
    datasets = await internal_api.list_datasets(
        source_type=source_type,
        search=search,
        limit=limit,
    )
    return {"datasets": datasets, "total": len(datasets)}

@server.tool("data_catalog.fetch")
async def fetch_dataset(dataset_id: str, columns: list = None, limit: int = 1000):
    """Fetch data from a specific dataset."""
    data = await internal_api.query_dataset(
        dataset_id=dataset_id,
        columns=columns,
        limit=limit,
    )
    return data

@server.tool("data_catalog.schema")
async def get_schema(dataset_id: str):
    """Get the schema of a dataset."""
    return await internal_api.get_schema(dataset_id)
```

### 8.3 无外部系统时的降级

当没有配置 http_connectors 也没有 MCP Server 时，Agent 降级为原有静态表单行为：

```text
http_connector("list_datasets") → 返回 error (unknown connector)
        │
        ▼
Skill 指导 Agent 降级：
  → 渲染静态表单（CSV/Excel/数据库/API/已上传文件）
  → 用户手动提供数据
```

---

## 9. Skill Script 模式（代码驱动数据获取）

### 9.1 概述

除了 `http_connector`（配置驱动）和 MCP（外部扩展），还有第三种数据获取方式：**Skill 引导 Agent 执行脚本**。

Skill 本身不执行代码（纯 prompt 注入），但可以指导 Agent 调用 `bash` tool 执行 skill 目录下的脚本。脚本可以做任意逻辑：多步 API 调用、数据转换、认证刷新、数据库查询等。

> **前提条件**：`bash` 是 sandbox tool（非 builtin），Agent 必须配置包含 sandbox tool group 才能使用。如果 Agent 的 `tool_groups` 不包含 sandbox tools，此模式不可用。SOUL.md 中应包含条件判断："If bash tool is available, use scripts; otherwise fall through to http_connector."

```text
┌─────────────────────────────────────────────────────────┐
│  Skill (SOUL.md) 指导 Agent:                             │
│  "执行 scripts/list_datasets.py 获取数据源列表"            │
│                                                          │
│  Agent 调用 bash tool:                                   │
│    python /mnt/skills/data-analyst/scripts/list_data.py  │
│                                                          │
│  脚本执行:                                                │
│    → 读取环境变量获取认证信息                               │
│    → 调用外部 API（可能多步）                               │
│    → 数据转换/聚合                                        │
│    → 输出 JSON 到 stdout                                  │
│                                                          │
│  Agent 拿到 JSON → render_ui(form) 渲染选择表单            │
└─────────────────────────────────────────────────────────┘
```

### 9.2 三种数据获取模式对比

| 维度 | http_connector（配置驱动） | Skill Script（代码驱动） | MCP Server（外部扩展） |
| ---- | ---- | ---- | ---- |
| 灵活性 | 单次 HTTP 调用 | 任意逻辑（多步调用、转换、聚合） | 由外部系统定义 |
| 安全性 | 高（预配置 URL，无代码执行） | 中（需沙箱 + 脚本审计） | 高（独立进程隔离） |
| 扩展方式 | 改 config.yaml | 写脚本放到 skill/scripts/ | 注册 MCP Server |
| 适用场景 | 简单 REST API 对接 | 复杂数据获取逻辑 | 第三方系统标准化接入 |
| 部署要求 | 无 | 需要 Python/bash 环境 | 需要 MCP Server 进程 |
| 维护成本 | 低 | 中（脚本需版本管理） | 低（外部团队维护） |

### 9.3 Skill 目录结构

```text
skills/public/data-analyst/
├── SKILL.md                    # Skill 指导文档（prompt 注入）
├── scripts/                    # 可执行脚本
│   ├── list_datasets.py        # 列举数据源
│   ├── fetch_dataset.py        # 获取数据
│   ├── preview_dataset.py      # 预览数据（前 N 行）
│   └── requirements.txt        # 脚本依赖
├── templates/                  # Prompt 模板（可选）
│   └── analysis_report.md
└── references/                 # 参考文档（可选）
    └── data_platform_api.md
```

### 9.4 脚本规范

脚本需遵循以下约定，确保 Agent 能正确调用和解析：

```python
#!/usr/bin/env python3
"""list_datasets.py — 列举可用数据集

Usage:
    python list_datasets.py [--source-type TYPE] [--search KEYWORD] [--limit N]

Output:
    JSON to stdout, format:
    {"datasets": [...], "total": N}

Environment:
    DATA_PLATFORM_TOKEN — Bearer token for authentication
    DATA_PLATFORM_URL — Base URL of the data platform API
"""

import argparse
import json
import os
import sys

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-type", default=None)
    parser.add_argument("--search", default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    base_url = os.environ.get("DATA_PLATFORM_URL", "")
    token = os.environ.get("DATA_PLATFORM_TOKEN", "")

    if not base_url:
        print(json.dumps({"datasets": [], "error": "DATA_PLATFORM_URL not configured"}))
        sys.exit(0)

    params = {"limit": args.limit}
    if args.source_type:
        params["source_type"] = args.source_type
    if args.search:
        params["search"] = args.search

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{base_url}/api/v1/datasets",
                params=params,
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            resp.raise_for_status()
            print(resp.text)
    except Exception as e:
        print(json.dumps({"datasets": [], "error": str(e)}))
        sys.exit(0)


if __name__ == "__main__":
    main()
```

**脚本约定**：

| 约定 | 说明 |
| ---- | ---- |
| 输出格式 | JSON 到 stdout，Agent 直接解析 |
| 错误处理 | 不 crash（exit 0），错误信息放在 JSON 的 `error` 字段 |
| 认证信息 | 通过环境变量获取，不硬编码 |
| 参数传递 | 通过命令行参数（Agent 可灵活构造） |
| 超时控制 | 脚本内部设置 timeout，不依赖外部 kill |
| 无副作用 | 数据获取脚本应为只读操作 |

### 9.5 SOUL.md 中的脚本调用指导

```markdown
## Data Fetching Methods (Priority Order)

### Method 1: MCP Tools (Highest Priority)
If `data_catalog.list` tool is available, use it directly.

### Method 2: Skill Scripts (Medium Priority)
If no MCP tools available, execute the skill scripts:

To list datasets:
```bash
python /mnt/skills/public/data-analyst/scripts/list_datasets.py --limit 50
```

To fetch a specific dataset:
```bash
python /mnt/skills/public/data-analyst/scripts/fetch_dataset.py --dataset-id "<id>" --limit 1000
```

To preview dataset schema:
```bash
python /mnt/skills/public/data-analyst/scripts/preview_dataset.py --dataset-id "<id>" --rows 5
```

Parse the JSON output and use it to construct the selection form.

### Method 3: HTTP Connector (Fallback)
If scripts are not available or fail, use:
```
http_connector(connector_name="list_datasets", params={"limit": 50})
```

### Method 4: Static Form (Last Resort)
If all above methods fail, render the static form asking user to upload data.
```

### 9.6 安全考量

| 风险 | 缓解措施 |
| ---- | ---- |
| 脚本注入（Agent 构造恶意参数） | 脚本使用 argparse 严格解析参数，不使用 shell=True |
| 脚本执行任意命令 | Skill 脚本需经过审计；PUBLIC 类型 skill 为只读 |
| 脚本访问敏感文件 | 容器化部署时限制文件系统访问（只读挂载 /mnt/skills） |
| 脚本长时间运行 | bash tool 有 timeout 限制；脚本内部也设 timeout |
| 脚本输出过大 | Agent 端截断处理；脚本应自行限制输出量 |
| 依赖安全 | requirements.txt 锁定版本；安装时扫描漏洞 |

### 9.7 与沙箱的关系

当项目启用了 sandbox（Docker 隔离执行环境）时，skill 脚本自动在沙箱中执行：

```text
Agent 调用 bash tool
        │
        ▼
┌─ Sandbox 启用？────────────────────────┐
│  YES: 脚本在 Docker 容器中执行           │
│  - 网络受限（只能访问白名单域名）          │
│  - 文件系统只读（除 /tmp）               │
│  - 内存/CPU 限制                        │
├────────────────────────────────────────┤
│  NO: 脚本在宿主机执行                    │
│  - 依赖环境变量隔离                      │
│  - 依赖文件权限控制                      │
└────────────────────────────────────────┘
```

---

## 10. 图片支持设计

数据源中可能包含图片，需要覆盖三种场景：

### 10.1 场景分类

| 场景 | 示例 | 处理方式 |
| ---- | ---- | -------- |
| **数据字段含图片 URL** | 商品表有 `image_url` 列、用户表有头像 | 在 table/card 组件中渲染为 `<img>` |
| **图片本身就是数据** | 图像分类数据集、医学影像、卫星图 | Agent 调用多模态能力分析，或展示缩略图供用户浏览 |
| **图表/报表截图** | 外部 BI 系统返回已生成的图表图片 | 通过 `image` 组件直接展示 |

### 10.2 GenUI 新增 `image` 组件

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "create",
  "block_id": "uuid-v4",
  "component": "image",
  "props": {
    "src": "https://data-platform.internal/images/chart-2026-05.png",
    "alt": "2026年5月销售趋势图",
    "width": 800,
    "height": 400,
    "caption": "来源：数据平台自动生成",
    "fallback": "图片加载失败"
  }
}
```

### 10.3 Table 组件支持图片列

扩展 table 的 column schema，支持 `type: "image"` 列类型：

```json
{
  "component": "table",
  "props": {
    "columns": [
      {"key": "name", "label": "商品名称"},
      {"key": "image_url", "label": "商品图片", "type": "image", "width": 80},
      {"key": "price", "label": "价格"},
      {"key": "stock", "label": "库存"}
    ],
    "data": [
      {"name": "商品A", "image_url": "https://cdn.example.com/a.jpg", "price": 99, "stock": 150}
    ]
  }
}
```

前端 TableBlock 渲染时，`type: "image"` 的列自动渲染为带 fallback 的 `<img>` 标签。

### 10.4 Card 组件支持封面图

```json
{
  "component": "card",
  "props": {
    "title": "患者 CT 扫描",
    "image": "https://medical-system.internal/scans/ct-001.png",
    "image_position": "top",
    "value": "异常检测: 2 处",
    "subtitle": "2026-05-12 上传"
  }
}
```

### 10.5 图片作为分析数据

当数据集本身是图片集合时，Agent 的处理流程：

```text
http_connector("list_datasets") → 返回图像数据集元信息
        │
        ▼
用户选择图像数据集
        │
        ▼
http_connector("fetch_dataset") → 返回图片 URL 列表 + 元数据
        │
        ▼
Agent 决策：
  ├─ 展示：render_ui(table) 带图片缩略图列，供用户浏览
  ├─ 分析：调用多模态 LLM 能力分析图片内容（需要 vision tool）
  └─ 统计：基于元数据（标签、分类、尺寸）做统计分析
```

### 10.6 图片安全

| 风险 | 缓解措施 |
| ---- | -------- |
| 恶意图片 URL（SSRF） | 前端通过 `<img>` 渲染，不在后端代理；配置 CSP `img-src` 白名单 |
| 超大图片导致页面卡顿 | 组件限制最大渲染尺寸 + lazy loading |
| 图片 URL 包含 token | Sanitizer 不对 `src` 做 DOMPurify（会破坏 URL），改用 URL 格式校验 |
| 外部图片不可用 | 组件显示 fallback 占位符 |

### 10.7 实现影响

| 改动点 | 内容 |
| ------ | ---- |
| GenUI 组件注册 | 新增 `image` 组件 |
| table column schema | 新增 `type: "image"` 列类型 |
| card props schema | 新增 `image` + `image_position` 字段 |
| Props Sanitizer | `image` 组件白名单：`src`, `alt`, `width`, `height`, `caption`, `fallback` |
| Sanitizer URL 豁免 | 新增 `URL_PROPS` 机制：URL 类型字段不走 DOMPurify，改用 URL 格式校验 |
| Zod Validator | 新增 `imagePropsSchema`；扩展 `tableColumnSchema` 和 `cardPropsSchema` |
| render_ui ALLOWED_COMPONENTS | 新增 `"image"` |
| Skill (SOUL.md) | 指导 Agent 识别图片字段并选择合适的展示方式 |

### 10.8 Sanitizer URL 豁免机制

当前 sanitizer 对所有字符串值统一执行 `DOMPurify.sanitize(value, { ALLOWED_TAGS: [] })`，这会破坏包含 `&` 等字符的 URL。需要新增 per-component 的 URL 字段豁免：

```typescript
// frontend/src/core/genui/sanitizer.ts (新增)

const URL_PROPS_BY_COMPONENT: Record<string, Set<string>> = {
  image: new Set(["src"]),
  card: new Set(["image"]),
};

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

// 在 sanitizeProps 中，对 URL 字段使用 URL 校验替代 DOMPurify：
// if (urlProps?.has(key) && typeof value === "string") {
//   sanitized[key] = isValidUrl(value) ? value : "";
// }
```

这样 `src` 字段保持原始 URL 不被 DOMPurify 破坏，同时通过 URL 格式校验防止 XSS（只允许 http/https 协议）。

---

## 11. 安全设计

| 风险 | 缓解措施 |
| ---- | -------- |
| 外部 API Token 泄露 | Token 通过环境变量注入（`auth_token_env`），不存储在配置文件中 |
| 数据量过大导致 OOM | connector 配置 `max_response_bytes`（默认 512KB）截断 + `timeout_seconds` |
| 跨租户数据泄露 | `http_connector` 按 tenant_id 查找 connector 配置，租户间隔离 |
| MCP Server 返回恶意数据 | 数据经过 Agent 处理后通过 render_ui 渲染，受 Props Sanitizer 保护 |
| SQL 注入（如果后端是数据库） | 外部系统负责参数化查询，http_connector 只传 JSON body |
| 超时/慢查询 | httpx timeout（connector 级别配置）+ Agent 端超时检测 |
| 任意 URL 调用 | http_connector 只能调用预配置的 connector，不接受任意 URL |

---

## 11.1 可观测性设计

`http_connector` 作为外部系统调用入口，需要完善的可观测性：

### 请求日志

每次调用记录结构化日志（已在 tool 实现中通过 `logger.info` 输出）：

| 字段 | 说明 |
| ---- | ---- |
| `connector_name` | 调用的 connector 名称 |
| `tenant_id` | 租户标识 |
| `status_code` | HTTP 响应状态码 |
| `latency_ms` | 请求耗时（毫秒） |
| `response_size` | 响应体大小（bytes） |
| `truncated` | 是否被截断 |
| `retry_count` | 实际重试次数 |

### 告警阈值（建议）

| 指标 | 阈值 | 动作 |
| ---- | ---- | ---- |
| 单次请求延迟 | > 10s | WARN 日志 |
| 连续失败 | 同一 connector 5 分钟内 > 3 次 | 告警通知 |
| 响应截断率 | > 20% | 建议调大 `max_response_bytes` 或优化外部 API 分页 |

### 与项目现有基础设施的关系

- 日志：复用项目 `logging` 模块，结构化输出
- 指标：如果项目后续引入 Prometheus/OpenTelemetry，可在 tool 层添加 metrics decorator
- 当前阶段：仅日志，不引入新依赖

---

## 12. 实施计划

### Phase 1: 平台 http_connector Tool + Skill 改造（3 天）

- [ ] 实现 `HttpConnectorConfig` 配置模型（Pydantic BaseModel，与项目其他配置模型一致）
- [ ] 实现 `http_connector` async tool（通用 HTTP 调用，按 connector_name 路由，含响应截断 + 重试）
- [ ] `AppConfig` 新增 `get_http_connector(tenant_id, name)` 和 `list_connector_names(tenant_id)` 方法
- [ ] 注册到 BUILTIN_TOOLS（与 render_ui 同级）
- [ ] 改造 data-analyst SOUL.md（动态表单流程，引用 http_connector）
- [ ] 配置 `callback_timeout_ms: 600000`（10 分钟）
- [ ] 编写 config.yaml `http_connectors` 配置示例

### Phase 2: MCP 扩展支持（2 天）

- [ ] 定义 `data_catalog.*` MCP 工具协议文档
- [ ] data-analyst agent config 添加 `mcp_servers` 绑定
- [ ] Skill 中添加 MCP 工具优先级指导（MCP 优先，http_connector fallback）
- [ ] 编写 MCP Server 接入文档（含 Python 示例）

### Phase 3: 多级选择 + 高级功能（2 天）

- [ ] Skill 支持多级选择流程（两步表单）
- [ ] 新增 `dataset_schema` connector 配置（预览表结构）
- [ ] 搜索/过滤数据源（params 透传）
- [ ] 分页加载大数据集（offset/limit）

### Phase 4: 测试与文档（1 天）

- [ ] 单元测试：http_connector tool（mock httpx）
- [ ] 集成测试：Agent 端到端流程（mock 外部 API）
- [ ] E2E 测试：表单选择 → 数据获取 → 图表渲染
- [ ] 接入文档：如何配置新的外部数据源（http_connectors + MCP 两种方式）

---

## 13. 与现有系统的关系

| 现有模块 | 关系 |
| -------- | ---- |
| GenUI (render_ui) | 复用现有表单渲染和交互回调机制 |
| Tool System | `http_connector` 加入 `BUILTIN_TOOLS`（与 render_ui 同级，始终可用） |
| Skill System | 修改 data-analyst SOUL.md，遵循现有 prompt 注入模式 |
| MCP System | 复用现有 `MultiServerMCPClient` + `extensions_config.json` |
| Agent Config | 复用现有 `tool_groups` + `mcp_servers` + `skills` 配置项 |
| 租户隔离 | `http_connector` 按 tenant_id 查找 connector 配置，复用现有 contextvar |
| config.yaml | 新增 `http_connectors` 配置段，与现有 `tool_groups` 平级 |

---

## 14. 决策记录

| 决策 | 选择 | 理由 |
| ---- | ---- | ---- |
| 业务工具归属 | 不入 builtins，用通用 http_connector + 配置 | builtins 保持纯净，业务逻辑可配置化 |
| 数据源发现方式 | Agent 调用 tool/MCP（非前端直接调用） | Agent 需要理解数据结构才能构造合适的表单 |
| 表单构造方式 | Agent 动态构造（非模板） | 不同数据源的字段不同，需要 Agent 智能适配 |
| MCP vs http_connector | 两者并存，MCP 优先 | http_connector 作为轻量 fallback，MCP 提供无限扩展性 |
| 超时时间 | 10 分钟（600000ms） | 用户选择数据源需要时间浏览和思考 |
| 数据获取方式 | POST（非 GET） | 支持复杂 filter/columns 参数，避免 URL 长度限制 |
| Skill 指导粒度 | 详细步骤 + fallback | Agent 需要明确的行为指导，同时处理异常情况 |
| http_connector 安全 | 只能调用预配置 connector，不接受任意 URL | 防止 SSRF，Agent 无法构造任意 HTTP 请求 |
