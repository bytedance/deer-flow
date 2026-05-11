# GenUI / A2UI 技术架构设计

> DeerFlow 项目 — 基于 Agent 的动态 UI 渲染方案

## 1. 背景与目标

### 1.1 问题

当前 DeerFlow 的 Agent 输出仅支持纯文本/Markdown，无法满足以下场景：

- 数据可视化（图表、表格、统计卡片）
- 交互式表单（参数调整、确认操作）
- 富媒体展示（地图、时间线、代码沙箱）
- 多步骤向导（分步引导用户完成复杂任务）

### 1.2 目标

引入 **GenUI（Generative UI）** 和 **A2UI（Agent-to-UI）** 模式：

1. Agent 能够动态生成结构化 UI 指令
2. 前端根据指令渲染对应组件
3. 用户交互结果回流至 Agent 形成闭环
4. 保持现有 SSE 流式架构不变
5. 确保 UIBlock 协议可演进、安全、可观测

---

## 2. 核心概念

| 概念 | 定义 |
| ---- | ---- |
| **UIBlock** | Agent 输出的结构化 UI 描述单元（JSON），带版本号和操作语义 |
| **render_ui Tool** | LangGraph 工具，Agent 调用后通过 InjectedToolArg 注入 StreamWriter 发射 UIBlock |
| **GenUIMiddleware** | 拦截用户 UI 交互回调，转换为 Agent 可读上下文，处理幂等和超时 |
| **Component Registry** | 前端组件注册表，将 UIBlock type 映射到 React 组件 |
| **Props Sanitizer** | 前端安全层，对 UIBlock props 做白名单校验和 XSS 过滤 |
| **BlockStore** | 前端状态管理，维护 UIBlock 生命周期（创建/更新/删除） |
| **InteractionStore** | 后端交互状态存储，管理回调幂等性、超时和 checkpoint 关联 |

---

## 3. 架构总览

```
+------------------+       SSE (stream_mode=custom)       +------------------+
|                  | ─────────────────────────────────────→ |                  |
|   LangGraph      |   UIBlock JSON                       |   React Frontend |
|   Agent Graph    | ─────────────────────────────────────→ |   Component      |
|                  |                                       |   Registry       |
+--------+---------+       HTTP POST (interaction)        +--------+---------+
         |          ←─────────────────────────────────────          |
         |                                                          |
    render_ui Tool                                         GenUI Renderer
    GenUIMiddleware                                        Props Sanitizer
    InteractionStore                                       BlockStore (Zustand)
    Prompt Guidance                                        ErrorBoundary
                                                          Observability
```

---

## 4. UIBlock 协议

### 4.1 基础结构

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "create",
  "block_id": "uuid-v4",
  "component": "chart",
  "props": {
    "chart_type": "bar",
    "title": "Monthly Revenue",
    "data": [{"month": "Jan", "value": 1200}],
    "x_key": "month",
    "y_key": "value"
  },
  "interactive": false,
  "metadata": {
    "created_at": "2026-05-10T10:00:00Z",
    "agent_node": "reporter"
  }
}
```

### 4.2 操作语义（action 字段）

| action | 语义 | 说明 |
| ------ | ---- | ---- |
| `create` | 创建新 block | 默认值，首次渲染 |
| `update` | 更新已有 block | 通过 block_id 匹配，合并 props |
| `delete` | 删除已有 block | 通过 block_id 匹配，移除渲染 |

更新示例（进度条场景）：

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "update",
  "block_id": "progress-task-123",
  "component": "card",
  "props": {
    "progress": 75,
    "status": "Processing step 3/4..."
  }
}
```

### 4.3 交互式 UIBlock

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "create",
  "block_id": "uuid-v4",
  "component": "form",
  "props": {
    "title": "Search Parameters",
    "fields": [
      {"name": "query", "type": "text", "label": "Search Query", "required": true},
      {"name": "top_k", "type": "number", "label": "Results", "default": 5}
    ],
    "submit_label": "Search"
  },
  "interactive": true,
  "callback_id": "form_submit_search_params",
  "callback_timeout_ms": 300000
}
```

### 4.4 布局与分组

当 Agent 需要输出组合式 UI（如 dashboard），使用 `layout` 组件包裹子 block：

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "create",
  "block_id": "dashboard-001",
  "component": "layout",
  "props": {
    "direction": "grid",
    "columns": 2,
    "gap": 16
  },
  "children": ["card-revenue", "card-users", "chart-trend", "table-details"]
}
```

子 block 通过 `parent_id` 关联：

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "create",
  "block_id": "card-revenue",
  "parent_id": "dashboard-001",
  "component": "card",
  "props": {"title": "Revenue", "value": "$12,000", "trend": "+15%"}
}
```

### 4.5 支持的组件类型

| component | 用途 | interactive | 渲染库 |
| --------- | ---- | ----------- | ------ |
| `chart` | 基础图表（bar/line/pie/scatter） | No | Recharts |
| `echart` | 高级图表（map/gauge/funnel/radar/heatmap/sankey/treemap/3D 等） | No | ECharts |
| `table` | 数据表格（排序、分页） | Optional | TanStack Table |
| `card` | 统计卡片/信息卡片 | No | Tailwind |
| `form` | 表单输入 | Yes | React Hook Form |
| `confirm` | 确认对话框 | Yes | Tailwind |
| `code` | 代码块（带沙箱执行按钮） | Optional | Shiki |
| `timeline` | 时间线展示 | No | Tailwind |
| `markdown` | 富文本（降级兼容） | No | 内置 Markdown |
| `layout` | 布局容器（grid/flex） | No | — |

#### `chart` vs `echart` 选型指南

| 场景 | 推荐组件 | 理由 |
| ---- | -------- | ---- |
| 简单 bar/line/pie/scatter | `chart` | Recharts 轻量、React 原生、已有依赖 |
| 地图、仪表盘、漏斗图、雷达图 | `echart` | ECharts 内置丰富图表类型 |
| 热力图、桑基图、树图 | `echart` | Recharts 不支持这些类型 |
| 3D 可视化 | `echart` | ECharts GL 扩展 |
| 大数据量（>10000 点） | `echart` | ECharts 有 dataset + dataZoom 优化 |
| 需要高度自定义交互 | `echart` | ECharts 事件系统更完善 |

#### `echart` 组件 Props 结构

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "create",
  "block_id": "uuid-v4",
  "component": "echart",
  "props": {
    "option": {
      "title": {"text": "Sales Distribution"},
      "tooltip": {},
      "xAxis": {"type": "category", "data": ["Mon", "Tue", "Wed"]},
      "yAxis": {"type": "value"},
      "series": [{"type": "bar", "data": [120, 200, 150]}]
    },
    "height": 400,
    "theme": "default",
    "loading": false
  }
}
```

> **设计决策**：`echart` 组件直接透传 ECharts option 对象，而非像 `chart` 那样抽象为 `chart_type + data + x_key + y_key`。原因：ECharts 配置项极其丰富，抽象层会限制 Agent 的表达能力。安全性通过 Props Sanitizer 白名单 + 禁止函数类型值来保证。

### 4.6 协议版本演进策略

- `schema_version` 遵循语义化版本（MAJOR.MINOR）
- MINOR 升级：新增可选字段，向后兼容
- MAJOR 升级：破坏性变更，前端需同时支持新旧版本（过渡期 2 个迭代）
- 前端遇到未知 `schema_version` 时降级为 markdown 渲染

---

## 5. 后端实现

### 5.1 render_ui Tool

```python
# backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py

import uuid

from langchain.tools import tool
from langgraph.config import get_config, get_stream_writer

from deerflow.tools.render_ui_metrics import get_render_ui_metrics

ALLOWED_COMPONENTS = frozenset(
    {"chart", "echart", "table", "card", "form", "confirm", "code", "timeline", "markdown", "layout"}
)

ALLOWED_ACTIONS = frozenset({"create", "update", "delete"})

SCHEMA_VERSION = "1.0"


@tool("render_ui", parse_docstring=True)
def render_ui_tool(
    component: str,
    props: dict,
    interactive: bool = False,
    callback_id: str | None = None,
    callback_timeout_ms: int | None = None,
    parent_id: str | None = None,
    block_id: str | None = None,
    action: str = "create",
) -> str:
    """Render a UI component in the user interface.

    Use this tool to display rich visual components such as charts, tables,
    cards, forms, and more. The component will be rendered in the chat interface.

    Args:
        component: Component type. One of: chart, echart, table, card, form, confirm, code, timeline, markdown, layout.
        props: Component properties object. Structure depends on the component type.
        interactive: Whether the component accepts user interaction (e.g., form submission).
        callback_id: Required if interactive=True. Used to route interaction callbacks back to the agent.
        callback_timeout_ms: Optional timeout in milliseconds for interactive components.
        parent_id: Optional parent block_id for layout grouping.
        block_id: Optional block_id for update/delete actions. If not provided for create, a new UUID is generated.
        action: One of 'create', 'update', 'delete'. Default is 'create'.

    Returns:
        A success or error message indicating the result of the render operation.
    """
    if component not in ALLOWED_COMPONENTS:
        return f"Error: Unknown component '{component}'. Allowed: {sorted(ALLOWED_COMPONENTS)}"

    if action not in ALLOWED_ACTIONS:
        return f"Error: Unknown action '{action}'. Allowed: {sorted(ALLOWED_ACTIONS)}"

    if interactive and not callback_id:
        return "Error: interactive=True requires a callback_id"

    if action in ("update", "delete") and not block_id:
        return f"Error: action='{action}' requires a block_id"

    metrics = get_render_ui_metrics()

    with metrics.measure(component):
        resolved_block_id = block_id or str(uuid.uuid4())

        block = {
            "schema_version": SCHEMA_VERSION,
            "type": "ui_block",
            "action": action,
            "block_id": resolved_block_id,
            "component": component,
            "props": props,
            "interactive": interactive,
        }

        if callback_id:
            block["callback_id"] = callback_id
        if callback_timeout_ms is not None:
            block["callback_timeout_ms"] = callback_timeout_ms
        if parent_id:
            block["parent_id"] = parent_id

        writer = get_stream_writer()
        writer(block)

        # Persist block for SSE recovery
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id", "")

        from deerflow.agents.genui_persistence import persist_block
        persist_block(thread_id, block)

        # Register interactive callback for idempotency/timeout tracking
        if interactive and callback_id and action == "create":
            from deerflow.agents.middlewares.genui_middleware import get_interaction_store

            checkpoint_id = config.get("configurable", {}).get("checkpoint_id", "")
            timeout_seconds = (callback_timeout_ms / 1000.0) if callback_timeout_ms else 300.0

            store = get_interaction_store()
            store.register(
                callback_id=callback_id,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                timeout=timeout_seconds,
            )

    return f"UI component '{component}' ({action}) rendered successfully. block_id={resolved_block_id}"
```

> **实现要点**：
> - 使用 `@tool("render_ui", parse_docstring=True)` 注册，docstring 自动生成 schema
> - `get_stream_writer()` 从 LangGraph 运行时上下文获取 writer（LangGraph >=0.2 标准做法）
> - `get_config()` 获取 thread_id 和 checkpoint_id 用于持久化和交互注册
> - 集成 `render_ui_metrics` 进行性能监控（`measure()` 上下文管理器）
> - 集成 `genui_persistence` 持久化 block 用于 SSE 断线恢复
> - 交互式组件自动注册到 `InteractionStore` 进行幂等/超时管理

### 5.2 GenUIMiddleware（不可变模式 + 线程安全）

```python
# backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py

import json
import logging
import threading
import time
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InteractionRecord:
    """Immutable record for a registered interactive UI block callback."""

    callback_id: str
    thread_id: str
    checkpoint_id: str
    timeout: float
    created_at: float = field(default_factory=time.time)
    submitted: bool = False
    payload: dict | None = None

    @property
    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.timeout

    def with_submission(self, payload: dict) -> "InteractionRecord":
        """Return a new record marked as submitted (immutable update)."""
        return InteractionRecord(
            callback_id=self.callback_id,
            thread_id=self.thread_id,
            checkpoint_id=self.checkpoint_id,
            timeout=self.timeout,
            created_at=self.created_at,
            submitted=True,
            payload=payload,
        )


class InteractionStore:
    """Thread-safe store for managing interactive UI block callbacks."""

    def __init__(self) -> None:
        self._records: dict[str, InteractionRecord] = {}
        self._lock = threading.Lock()

    def register(self, callback_id: str, thread_id: str, checkpoint_id: str, timeout: float = 300.0) -> InteractionRecord:
        record = InteractionRecord(
            callback_id=callback_id, thread_id=thread_id,
            checkpoint_id=checkpoint_id, timeout=timeout,
        )
        with self._lock:
            self._records[callback_id] = record
        return record

    def get(self, callback_id: str) -> InteractionRecord | None:
        with self._lock:
            return self._records.get(callback_id)

    def submit(self, callback_id: str, payload: dict) -> InteractionRecord | None:
        """Mark as submitted via immutable update. Returns updated record or None."""
        with self._lock:
            record = self._records.get(callback_id)
            if record is None:
                return None
            updated = record.with_submission(payload)
            self._records[callback_id] = updated
            return updated

    def cleanup_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired_keys = [k for k, v in self._records.items() if now > v.created_at + v.timeout]
            for key in expired_keys:
                del self._records[key]
            return len(expired_keys)

    def remove(self, callback_id: str) -> bool:
        with self._lock:
            return self._records.pop(callback_id, None) is not None


# Global singleton (double-checked locking)
_interaction_store: InteractionStore | None = None
_store_lock = threading.Lock()

def get_interaction_store() -> InteractionStore:
    global _interaction_store
    if _interaction_store is None:
        with _store_lock:
            if _interaction_store is None:
                _interaction_store = InteractionStore()
    return _interaction_store


def process_interaction(callback_id: str, payload: dict) -> HumanMessage | None:
    """Process an interaction submission.

    Returns HumanMessage to inject into graph, or None if already submitted (idempotent).
    Raises ValueError (unknown callback) or TimeoutError (expired).
    """
    store = get_interaction_store()
    record = store.get(callback_id)

    if record is None:
        raise ValueError(f"Unknown callback_id: {callback_id}")

    if record.is_expired:
        store.remove(callback_id)
        raise TimeoutError(f"Callback {callback_id} has expired")

    if record.submitted:
        return None  # Idempotent: ignore duplicate submissions

    updated = store.submit(callback_id, payload)
    if updated is None:
        return None

    content = json.dumps(
        {"type": "ui_interaction", "callback_id": callback_id, "payload": payload},
        ensure_ascii=False,
    )
    return HumanMessage(content=content, id=f"ui-interaction:{callback_id}")
```

> **与原设计的关键差异**：
> - `InteractionRecord` 使用 `frozen=True` 不可变 dataclass，通过 `with_submission()` 返回新实例
> - `InteractionStore` 使用 `threading.Lock()` 保证线程安全
> - `process_interaction()` 是独立函数（非类方法），通过异常（`ValueError`/`TimeoutError`）报告错误
> - 返回的 `HumanMessage` 使用 JSON 格式 content（`type: "ui_interaction"`），而非纯文本
> - 全局单例通过 double-checked locking 模式创建

### 5.3 Agent Prompt Guidance

在 Agent 的 system prompt 中注入 GenUI 使用指南：

````python
# backend/packages/harness/deerflow/agents/prompts/genui_guidance.py

GENUI_SYSTEM_PROMPT = """
## UI Rendering Capabilities

You have access to the `render_ui` tool for displaying rich UI components. Use it when:
- Data is better understood visually (charts, tables, statistics)
- User input is needed (forms, confirmations)
- Information has temporal structure (timelines)

### Available Components

| Component | When to Use |
| --------- | ----------- |
| chart     | Simple bar/line/pie/scatter charts (Recharts) |
| echart    | Complex visualizations: maps, gauge, funnel, radar, heatmap, sankey, treemap, 3D |
| table     | Structured data with multiple fields, especially >3 rows |
| card      | Single KPI or summary statistic |
| form      | When you need user input to proceed |
| confirm   | Before destructive or irreversible actions |
| code      | Code snippets that user might want to execute |
| timeline  | Sequential events or steps |
| layout    | Grouping multiple blocks into a dashboard |

### Chart vs EChart Selection

- Use `chart` for simple data with 1-2 series (bar, line, pie, scatter)
- Use `echart` for:
  - Chart types not supported by `chart` (map, gauge, funnel, radar, heatmap, sankey, treemap)
  - Large datasets (>1000 data points) that benefit from ECharts' dataZoom
  - Complex multi-axis or composite charts
  - 3D visualizations
  - When you need advanced interactions (brush, dataZoom, visual mapping)

### EChart Props Format

The `echart` component accepts a standard ECharts option object:
```json
{
  "option": { ... ECharts option ... },
  "height": 400,
  "theme": "default"
}
```

### Guidelines

1. Prefer plain text/markdown for simple responses (1-2 sentences, short lists)
2. Use `render_ui` when visual structure adds clarity
3. For interactive components, always provide a meaningful `callback_id`
4. Use `layout` to group related blocks (e.g., a dashboard with cards + chart)
5. Never render sensitive data (passwords, tokens) in UI blocks
6. Keep props minimal — only include data the component needs
"""
````

### 5.4 SSE 传输

复用现有 `stream_mode=custom` 通道：

```python
# 在 graph stream 中，render_ui 通过 get_stream_writer() 发射 UIBlock
# 前端通过现有 SSE 连接接收 custom event
async for event in graph.astream(input, stream_mode=["messages", "custom"]):
    if event[0] == "custom":
        # UIBlock JSON 直接推送到前端
        yield f"data: {json.dumps(event[1])}\n\n"
```

### 5.5 交互回调 API

```python
# backend/app/gateway/routers/genui.py

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_run_context, get_run_manager, get_stream_bridge
from app.gateway.services import build_run_config, resolve_agent_factory
from deerflow.agents.middlewares.genui_middleware import (
    get_interaction_store,
    process_interaction,
)
from deerflow.runtime import DisconnectMode, run_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/ui-interaction", tags=["genui"])


class UIInteractionRequest(BaseModel):
    callback_id: str = Field(..., description="The callback ID from the interactive UI block")
    payload: dict = Field(default_factory=dict, description="Interaction payload data")


class UIInteractionResponse(BaseModel):
    success: bool
    message: str
    callback_id: str


@router.post("", response_model=UIInteractionResponse)
async def submit_ui_interaction(
    thread_id: str,
    req: UIInteractionRequest,
    request: Request,
) -> UIInteractionResponse:
    """Submit a user interaction for an interactive UI block."""
    store = get_interaction_store()
    record = store.get(req.callback_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown callback: {req.callback_id}")

    if record.thread_id != thread_id:
        raise HTTPException(status_code=400, detail="Callback does not belong to this thread")

    try:
        human_message = process_interaction(req.callback_id, req.payload)
    except TimeoutError:
        raise HTTPException(status_code=410, detail="Callback has expired")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if human_message is None:
        return UIInteractionResponse(
            success=True, message="Already submitted (idempotent)", callback_id=req.callback_id,
        )

    # Resume the agent graph with the interaction as a HumanMessage
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    agent_factory = resolve_agent_factory(None)
    config = build_run_config(thread_id, None, None)
    graph_input = {"messages": [human_message]}

    try:
        run_record = await run_mgr.create_or_reject(
            thread_id, None,
            on_disconnect=DisconnectMode.continue_,
            metadata={"source": "ui_interaction", "callback_id": req.callback_id},
            kwargs={"input": graph_input, "config": config},
            multitask_strategy="reject",
        )
    except Exception as exc:
        logger.warning("Failed to create run for interaction resumption: %s", exc)
        return UIInteractionResponse(
            success=True, message="Interaction received (graph busy)", callback_id=req.callback_id,
        )

    task = asyncio.create_task(
        run_agent(
            bridge, run_mgr, run_record,
            ctx=run_ctx, agent_factory=agent_factory,
            graph_input=graph_input, config=config,
            stream_modes=["values", "messages", "custom"],
            stream_subgraphs=False,
        )
    )
    run_record.task = task

    return UIInteractionResponse(
        success=True, message="Interaction submitted", callback_id=req.callback_id,
    )
```

> **与原设计的关键差异**：
> - 使用 `RunManager` + `run_agent()` + `StreamBridge` 恢复 graph（非简单 checkpoint resume）
> - 验证 `record.thread_id != thread_id` 防止跨线程回调攻击
> - 使用 `create_or_reject(multitask_strategy="reject")` 处理 graph 繁忙场景
> - 异步 `asyncio.create_task()` 非阻塞执行 agent run
> - 返回结构化 `UIInteractionResponse` 而非简单 dict

---

## 6. 前端实现

### 6.1 Component Registry

实际实现包含 **Schema 版本检查**、**组件缓存** 和 **降级策略**：

```typescript
// frontend/src/core/genui/registry.ts

import { type ComponentType, lazy } from "react";

type LazyComponent = ComponentType<any>;

const COMPONENT_REGISTRY: Record<string, () => Promise<{ default: LazyComponent }>> = {
  chart: () => import("@/components/genui/ChartBlock") as any,
  table: () => import("@/components/genui/TableBlock") as any,
  card: () => import("@/components/genui/CardBlock") as any,
  form: () => import("@/components/genui/FormBlock") as any,
  confirm: () => import("@/components/genui/ConfirmBlock") as any,
  code: () => import("@/components/genui/CodeBlock") as any,
  timeline: () => import("@/components/genui/TimelineBlock") as any,
  layout: () => import("@/components/genui/LayoutBlock") as any,
  markdown: () => import("@/components/genui/MarkdownBlock") as any,
};

const SUPPORTED_MAJOR_VERSION = 1;

// 组件缓存：避免重复创建 React.lazy 包装
const componentCache = new Map<string, React.LazyExoticComponent<LazyComponent>>();

function parseMajorVersion(version: string): number {
  const major = parseInt(version.split(".")[0] ?? "0", 10);
  return isNaN(major) ? 0 : major;
}

export function getBlockComponent(
  componentType: string,
  schemaVersion: string,
): React.LazyExoticComponent<LazyComponent> | null {
  // 版本降级：未知主版本号 → 回退到 markdown 渲染
  const major = parseMajorVersion(schemaVersion);
  if (major > SUPPORTED_MAJOR_VERSION) {
    return getBlockComponent("markdown", "1.0");
  }

  const loader = COMPONENT_REGISTRY[componentType];
  if (!loader) {
    return null;
  }

  // 缓存命中直接返回
  const cached = componentCache.get(componentType);
  if (cached) {
    return cached;
  }

  const LazyComp = lazy(loader);
  componentCache.set(componentType, LazyComp);
  return LazyComp;
}

export function isKnownComponent(componentType: string): boolean {
  return componentType in COMPONENT_REGISTRY;
}
```

> **与原设计的关键差异**：
> - `getBlockComponent` 接受 `schemaVersion` 参数，未知主版本自动降级为 markdown
> - 使用 `componentCache` Map 缓存 `React.lazy` 实例，避免重复创建
> - 导出 `isKnownComponent()` 工具函数供外部判断组件是否支持
> - 注册表使用 `Record` 对象而非 `Map`（更简洁的静态声明）

### 6.2 Props Sanitizer（安全层）

```typescript
// frontend/src/core/genui/sanitizer.ts

import DOMPurify from "dompurify";

const ALLOWED_PROPS_BY_COMPONENT: Record<string, Set<string>> = {
  chart: new Set(["chart_type", "title", "data", "x_key", "y_key", "colors"]),
  table: new Set(["columns", "data", "sortable", "paginated", "page_size"]),
  card: new Set(["title", "value", "trend", "icon", "description", "progress", "status"]),
  form: new Set(["title", "fields", "submit_label", "cancel_label"]),
  confirm: new Set(["title", "message", "confirm_label", "cancel_label", "variant"]),
  code: new Set(["language", "code", "executable", "sandbox_type"]),
  timeline: new Set(["events", "orientation"]),
  markdown: new Set(["content"]),
  layout: new Set(["direction", "columns", "gap", "align"]),
};

export function sanitizeProps(
  component: string,
  props: Record<string, unknown>,
): Record<string, unknown> {
  const allowed = ALLOWED_PROPS_BY_COMPONENT[component];
  if (!allowed) return {};

  const sanitized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (!allowed.has(key)) continue;

    if (typeof value === "string") {
      sanitized[key] = DOMPurify.sanitize(value, { ALLOWED_TAGS: [] });
    } else if (Array.isArray(value)) {
      sanitized[key] = value.map((item) =>
        typeof item === "object" && item !== null ? sanitizeObject(item) : item,
      );
    } else {
      sanitized[key] = value;
    }
  }
  return sanitized;
}

function sanitizeObject(obj: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (typeof value === "string") {
      result[key] = DOMPurify.sanitize(value, { ALLOWED_TAGS: [] });
    } else {
      result[key] = value;
    }
  }
  return result;
}
```

### 6.3 BlockStore（状态管理）

实际实现使用 **状态枚举** 替代布尔字段，并支持 `callback_timeout_ms` 和 `expired` 状态：

```typescript
// frontend/src/core/genui/store.ts

import { create } from "zustand";

export interface UIBlock {
  schema_version: string;
  type: "ui_block";
  action: "create" | "update" | "delete";
  block_id: string;
  component: string;
  props: Record<string, unknown>;
  interactive: boolean;
  callback_id?: string;
  callback_timeout_ms?: number;  // 超时时间（毫秒）
  parent_id?: string;
  metadata?: Record<string, unknown>;
}

// 状态枚举模式（替代原设计的布尔字段）
export interface InteractionState {
  status: "idle" | "loading" | "submitted" | "error" | "expired";
  error?: string;
  submittedAt?: number;  // 提交时间戳，用于 UI 展示
}

interface BlockStoreState {
  blocks: Map<string, UIBlock>;
  interactions: Map<string, InteractionState>;

  applyBlock: (block: UIBlock) => void;
  getChildBlocks: (parentId: string) => UIBlock[];
  setInteractionLoading: (callbackId: string) => void;
  setInteractionSuccess: (callbackId: string) => void;
  setInteractionError: (callbackId: string, error: string) => void;
  setInteractionExpired: (callbackId: string) => void;
  reset: () => void;
}

export const useBlockStore = create<BlockStoreState>((set, get) => ({
  blocks: new Map(),
  interactions: new Map(),

  applyBlock: (block: UIBlock) =>
    set((state) => {
      const blocks = new Map(state.blocks);
      switch (block.action) {
        case "create":
          blocks.set(block.block_id, block);
          break;
        case "update": {
          // update 操作合并 props 而非整体替换
          const existing = blocks.get(block.block_id);
          if (existing) {
            blocks.set(block.block_id, {
              ...existing,
              props: { ...existing.props, ...block.props },
            });
          } else {
            blocks.set(block.block_id, block);
          }
          break;
        }
        case "delete":
          blocks.delete(block.block_id);
          break;
      }
      return { blocks };
    }),

  getChildBlocks: (parentId: string) => {
    const { blocks } = get();
    const children: UIBlock[] = [];
    for (const block of blocks.values()) {
      if (block.parent_id === parentId) {
        children.push(block);
      }
    }
    return children;
  },

  setInteractionLoading: (callbackId: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { status: "loading" });
      return { interactions };
    }),

  setInteractionSuccess: (callbackId: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { status: "submitted", submittedAt: Date.now() });
      return { interactions };
    }),

  setInteractionError: (callbackId: string, error: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { status: "error", error });
      return { interactions };
    }),

  setInteractionExpired: (callbackId: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { status: "expired" });
      return { interactions };
    }),

  reset: () => set({ blocks: new Map(), interactions: new Map() }),
}));
```

> **与原设计的关键差异**：
> - `InteractionState` 使用 `status` 枚举（`"idle"|"loading"|"submitted"|"error"|"expired"`）替代布尔字段组合
> - `UIBlock` 新增 `callback_timeout_ms`、`metadata` 字段；`interactive` 为必填非可选
> - `applyBlock` 的 `update` 操作执行 **props 合并**（`{...existing.props, ...block.props}`）而非整体替换
> - 新增 `setInteractionExpired` 方法，配合前端超时检测
> - `setInteractionSuccess` 记录 `submittedAt` 时间戳

### 6.4 GenUI Renderer（含 ErrorBoundary + Zod 验证 + 超时检测）

实际实现将 ErrorBoundary 独立为单独组件，Renderer 集成 Zod 验证和 `callback_timeout_ms` 超时自动过期：

```typescript
// frontend/src/components/genui/GenUIRenderer.tsx

"use client";

import { Suspense, useEffect, useRef } from "react";

import { getBlockComponent } from "@/core/genui/registry";
import { sanitizeProps } from "@/core/genui/sanitizer";
import { type UIBlock, useBlockStore } from "@/core/genui/store";
import { validateProps } from "@/core/genui/validator";

import { BlockErrorBoundary } from "./BlockErrorBoundary";

interface GenUIRendererProps {
  block: UIBlock;
  onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
}

function BlockFallback() {
  return (
    <div className="animate-pulse rounded-lg border bg-muted/50 p-4">
      <div className="h-4 w-1/3 rounded bg-muted" />
      <div className="mt-2 h-20 rounded bg-muted" />
    </div>
  );
}

function UnsupportedBlock({ component }: { component: string }) {
  return (
    <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-800 dark:bg-yellow-950">
      <p className="text-sm text-yellow-800 dark:text-yellow-200">
        Unsupported component: {component}
      </p>
    </div>
  );
}

export function GenUIRenderer({ block, onInteraction }: GenUIRendererProps) {
  const interactionState = useBlockStore(
    (state) => block.callback_id ? state.interactions.get(block.callback_id) : undefined,
  );

  // 超时自动过期：基于 callback_timeout_ms 设置定时器
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (
      !block.interactive ||
      !block.callback_id ||
      !block.callback_timeout_ms ||
      interactionState?.status === "submitted" ||
      interactionState?.status === "expired"
    ) {
      return;
    }

    timeoutRef.current = setTimeout(() => {
      if (block.callback_id) {
        useBlockStore.getState().setInteractionExpired(block.callback_id);
      }
    }, block.callback_timeout_ms);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [block.interactive, block.callback_id, block.callback_timeout_ms, interactionState?.status]);

  // 组件解析（含版本降级）
  const Component = getBlockComponent(block.component, block.schema_version);

  if (!Component) {
    return <UnsupportedBlock component={block.component} />;
  }

  // 安全层：Props 清洗
  const sanitizedProps = sanitizeProps(block.component, block.props);

  // 验证层：Zod schema 校验
  const validation = validateProps(block.component, sanitizedProps);
  if (!validation.success) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950">
        <p className="text-sm font-medium text-red-800 dark:text-red-200">
          Invalid props for {block.component}
        </p>
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">
          {validation.error}
        </p>
      </div>
    );
  }

  // 将清洗后的 props + 交互状态传递给组件
  const blockWithSanitizedProps = {
    ...block,
    props: sanitizedProps,
    interactionState,
    onInteraction,
  };

  return (
    <BlockErrorBoundary componentName={block.component}>
      <Suspense fallback={<BlockFallback />}>
        <Component block={blockWithSanitizedProps} />
      </Suspense>
    </BlockErrorBoundary>
  );
}
```

> **与原设计的关键差异**：
> - ErrorBoundary 独立为 `BlockErrorBoundary` 组件（非内联 class component）
> - 新增 **Zod 验证层**：`validateProps()` 在渲染前校验 props 结构，失败显示错误 UI
> - 新增 **超时检测**：基于 `block.callback_timeout_ms` 自动调用 `setInteractionExpired`
> - 组件接收整个 `block` 对象（含 `interactionState` 和 `onInteraction`），而非展开 props
> - `getBlockComponent` 传入 `schema_version` 参数实现版本降级
> - 支持 dark mode 的错误/警告 UI

### 6.5 交互回调（含乐观更新和重试）

实际实现使用类型化响应、动态 base URL 解析和 `expired` 状态处理：

```typescript
// frontend/src/core/genui/interaction.ts

import { useBlockStore } from "./store";

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

interface InteractionResponse {
  success: boolean;
  message: string;
  callback_id: string;
}

function getBackendBaseUrl(): string {
  if (typeof window !== "undefined") {
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

async function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function submitInteraction(
  threadId: string,
  callbackId: string,
  payload: Record<string, unknown>,
): Promise<InteractionResponse> {
  const store = useBlockStore.getState();
  store.setInteractionLoading(callbackId);

  const baseUrl = getBackendBaseUrl();
  const url = `${baseUrl}/api/threads/${threadId}/ui-interaction`;

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callback_id: callbackId, payload }),
      });

      if (response.status === 410) {
        store.setInteractionExpired(callbackId);
        return { success: false, message: "Interaction expired", callback_id: callbackId };
      }

      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`HTTP ${response.status}: ${detail}`);
      }

      const data: InteractionResponse = await response.json();
      store.setInteractionSuccess(callbackId);
      return data;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt < MAX_RETRIES) {
        await delay(RETRY_DELAY_MS * (attempt + 1));
      }
    }
  }

  const errorMessage = lastError?.message ?? "Unknown error";
  store.setInteractionError(callbackId, errorMessage);
  return { success: false, message: errorMessage, callback_id: callbackId };
}
```

> **与原设计的关键差异**：
> - 使用 `InteractionResponse` 类型化接口（`{success, message, callback_id}`）
> - 动态 `getBackendBaseUrl()` 支持 SSR 和客户端环境
> - HTTP 410 调用 `setInteractionExpired`（非 `setInteractionError`）
> - 返回统一的 `InteractionResponse` 结构（非 `{status: string}`）
> - 使用独立 `delay()` 函数替代内联 Promise

### 6.6 SSE 重连与 Block 恢复

```typescript
// frontend/src/core/genui/sse-recovery.ts

import { useBlockStore } from "./store";

interface SSERecoveryOptions {
  threadId: string;
  onReconnect?: () => void;
}

export class GenUISSEManager {
  private eventSource: EventSource | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private baseDelay = 1000;

  constructor(private options: SSERecoveryOptions) {}

  connect(url: string) {
    this.eventSource = new EventSource(url);

    this.eventSource.onmessage = (event) => {
      this.reconnectAttempts = 0;
      const data = JSON.parse(event.data);

      if (data.type === "ui_block") {
        useBlockStore.getState().applyBlock(data);
      }
    };

    this.eventSource.onerror = () => {
      this.eventSource?.close();
      this.scheduleReconnect(url);
    };
  }

  private scheduleReconnect(url: string) {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;

    const delay = this.baseDelay * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts++;

    setTimeout(() => {
      this.recoverBlocks();
      this.connect(url);
      this.options.onReconnect?.();
    }, delay);
  }

  private async recoverBlocks() {
    try {
      const response = await fetch(
        `/api/threads/${this.options.threadId}/ui-blocks`,
      );
      if (!response.ok) return;

      const blocks = await response.json();
      const store = useBlockStore.getState();
      store.reset();
      for (const block of blocks) {
        store.applyBlock(block);
      }
    } catch {
      // Recovery is best-effort; blocks will re-appear on next Agent output
    }
  }

  disconnect() {
    this.eventSource?.close();
    this.eventSource = null;
  }
}
```

### 6.7 GenUIBlockList（消息集成组件）

原设计中未包含此组件。实际实现中，`GenUIBlockList` 作为消息流中 UIBlock 的入口组件，嵌入在 `message-list-item.tsx` 的 AI 消息内容末尾：

```typescript
// frontend/src/components/genui/GenUIBlockList.tsx

"use client";

import { useBlockStore } from "@/core/genui/store";
import { GenUIRenderer } from "./GenUIRenderer";

interface GenUIBlockListProps {
  threadId: string;
  onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
}

export function GenUIBlockList({ threadId: _threadId, onInteraction }: GenUIBlockListProps) {
  const blocks = useBlockStore((state) => state.blocks);

  // 只渲染顶层 block（无 parent_id），子 block 由 LayoutBlock 递归渲染
  const topLevelBlocks = Array.from(blocks.values()).filter(
    (block) => !block.parent_id,
  );

  if (topLevelBlocks.length === 0) {
    return null;
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {topLevelBlocks.map((block) => (
        <GenUIRenderer
          key={block.block_id}
          block={block}
          onInteraction={onInteraction}
        />
      ))}
    </div>
  );
}
```

**消息流集成位置**（`message-list-item.tsx`）：

```typescript
// 在 AI 消息内容末尾渲染 GenUI blocks
{!isHuman && !isLoading && (
  <GenUIBlockList
    threadId={threadId}
    onInteraction={(callbackId, payload) => {
      void submitInteraction(threadId, callbackId, payload);
    }}
  />
)}
```

> **设计要点**：
> - 仅在 AI 消息完成加载后渲染（`!isLoading`）
> - 顶层 block 过滤：`parent_id` 为空的 block 直接渲染，有 `parent_id` 的由 `LayoutBlock` 通过 `getChildBlocks()` 递归渲染
> - `onInteraction` 回调桥接到 `submitInteraction` 完成交互闭环

---

## 7. 安全设计

### 7.1 Props 安全校验

**威胁模型**：Agent（LLM）生成的 props 可能包含恶意内容，包括 XSS payload、
`dangerouslySetInnerHTML`、事件处理器注入等。

**防御策略**（纵深防御）：

1. **白名单校验**（前端 Sanitizer）：每个组件类型只允许预定义的 prop key
2. **值过滤**：所有字符串值经过 DOMPurify 清洗，移除 HTML/Script 标签
3. **类型校验**：props 在渲染前通过 Zod schema 验证类型正确性
4. **组件白名单**：后端 `render_ui` 拒绝未注册的 component 类型

实际实现覆盖全部 9 个组件类型的完整 Zod schema，返回结构化错误信息：

```typescript
// frontend/src/core/genui/validator.ts

import { z } from "zod";

const trendSchema = z.object({
  direction: z.enum(["up", "down", "flat"]),
  value: z.string(),
});

const chartDataPointSchema = z.record(z.union([z.string(), z.number()]));

const chartSeriesSchema = z.object({
  key: z.string(),
  label: z.string().optional(),
  color: z.string().optional(),
});

export const chartPropsSchema = z.object({
  chart_type: z.enum(["bar", "line", "pie", "scatter"]),
  title: z.string().max(200).optional(),
  subtitle: z.string().max(500).optional(),
  x_key: z.string().max(100).optional(),
  y_key: z.string().max(100).optional(),
  data: z.array(chartDataPointSchema).max(10000),
  series: z.array(chartSeriesSchema).max(50).optional(),
  colors: z.array(z.string().max(50)).max(50).optional(),
  x_label: z.string().max(100).optional(),
  y_label: z.string().max(100).optional(),
  legend: z.boolean().optional(),
  stacked: z.boolean().optional(),
});

const tableColumnSchema = z.object({
  key: z.string(),
  label: z.string(),
  sortable: z.boolean().optional(),
  width: z.number().optional(),
});

export const tablePropsSchema = z.object({
  columns: z.array(tableColumnSchema).max(100),
  data: z.array(z.record(z.unknown())).max(10000),
  title: z.string().max(200).optional(),
  sortable: z.boolean().optional(),
  paginated: z.boolean().optional(),
  page_size: z.number().min(1).max(1000).optional(),
  onRowSelect: z.boolean().optional(),
});

export const cardPropsSchema = z.object({
  title: z.string().max(200),
  value: z.union([z.string().max(100), z.number()]),
  subtitle: z.string().max(500).optional(),
  trend: trendSchema.optional(),
  icon: z.string().max(100).optional(),
  color: z.string().max(50).optional(),
});

const formFieldSchema = z.object({
  name: z.string(),
  type: z.enum(["text", "number", "email", "password", "textarea", "select", "checkbox", "radio", "date"]),
  label: z.string(),
  placeholder: z.string().optional(),
  required: z.boolean().optional(),
  options: z.array(z.object({ label: z.string(), value: z.string() })).optional(),
  validation: z.object({
    min: z.number().optional(),
    max: z.number().optional(),
    pattern: z.string().optional(),
    message: z.string().optional(),
  }).optional(),
});

export const formPropsSchema = z.object({
  title: z.string().max(200).optional(),
  description: z.string().max(1000).optional(),
  fields: z.array(formFieldSchema).max(50),
  submit_label: z.string().max(100).optional(),
  cancel_label: z.string().max(100).optional(),
  default_values: z.record(z.unknown()).optional(),
});

export const confirmPropsSchema = z.object({
  title: z.string().max(200),
  message: z.string().max(2000),
  confirm_label: z.string().max(100).optional(),
  cancel_label: z.string().max(100).optional(),
  variant: z.enum(["default", "destructive"]).optional(),
});

export const codePropsSchema = z.object({
  code: z.string().max(100000),
  language: z.string().max(50).optional(),
  title: z.string().max(200).optional(),
  executable: z.boolean().optional(),
  filename: z.string().max(255).optional(),
});

const timelineEventSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
  timestamp: z.string().optional(),
  status: z.enum(["completed", "active", "pending"]).optional(),
  icon: z.string().optional(),
});

export const timelinePropsSchema = z.object({
  title: z.string().max(200).optional(),
  events: z.array(timelineEventSchema).max(100),
  orientation: z.enum(["vertical", "horizontal"]).optional(),
});

export const layoutPropsSchema = z.object({
  layout_type: z.enum(["grid", "flex"]),
  columns: z.number().min(1).max(12).optional(),
  gap: z.number().min(0).max(100).optional(),
  align: z.enum(["start", "center", "end", "stretch"]).optional(),
});

export const markdownPropsSchema = z.object({
  content: z.string().max(100000),
  title: z.string().max(200).optional(),
});

// 全部 9 个组件类型的 schema 注册
const propsSchemas: Record<string, z.ZodType> = {
  chart: chartPropsSchema,
  table: tablePropsSchema,
  card: cardPropsSchema,
  form: formPropsSchema,
  confirm: confirmPropsSchema,
  code: codePropsSchema,
  timeline: timelinePropsSchema,
  layout: layoutPropsSchema,
  markdown: markdownPropsSchema,
};

// 返回结构化错误信息（非简单 boolean）
export function validateProps(
  component: string,
  props: unknown,
): { success: boolean; error?: string } {
  const schema = propsSchemas[component];
  if (!schema) {
    return { success: false, error: `Unknown component: ${component}` };
  }

  const result = schema.safeParse(props);
  if (result.success) {
    return { success: true };
  }

  return {
    success: false,
    error: result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
  };
}
```

> **与原设计的关键差异**：
> - 覆盖全部 9 个组件类型（原设计仅展示 chart + form 两个示例）
> - `validateProps` 返回 `{success, error?}` 结构（非简单 `boolean`），错误信息包含路径
> - chart schema 支持 `series`、`subtitle`、`x_label`/`y_label`、`legend`、`stacked` 等高级字段
> - form schema 支持 `validation` 嵌套对象（min/max/pattern/message）和 `default_values`
> - 数据量限制更宽松：data 最大 10000 条（原设计 1000），fields 最大 50 个（原设计 20）
> - card 支持 `trend` 子对象（direction + value）

### 7.2 代码沙箱执行

`code` 组件支持可选的代码执行功能，需严格隔离：

**方案选型**：

| 方案 | 安全性 | 延迟 | 复杂度 |
| ---- | ------ | ---- | ------ |
| iframe sandbox + srcdoc | 高 | 低 | 中 |
| Web Worker | 中 | 低 | 低 |
| 后端沙箱（Docker/Firecracker） | 最高 | 高 | 高 |

**推荐方案**：前端 iframe sandbox（Phase 1）+ 后端沙箱（Phase 4）

```typescript
// frontend/src/components/genui/CodeBlock.tsx (sandbox execution)

interface CodeSandboxProps {
  code: string;
  language: string;
}

function executeSandboxed(code: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const iframe = document.createElement("iframe");
    iframe.sandbox.add("allow-scripts");
    // No allow-same-origin, no allow-top-navigation, no allow-popups
    iframe.style.display = "none";
    document.body.appendChild(iframe);

    const timeout = setTimeout(() => {
      document.body.removeChild(iframe);
      reject(new Error("Execution timed out (5s)"));
    }, 5000);

    window.addEventListener("message", function handler(event) {
      if (event.source === iframe.contentWindow) {
        clearTimeout(timeout);
        window.removeEventListener("message", handler);
        document.body.removeChild(iframe);
        resolve(event.data.result);
      }
    });

    iframe.srcdoc = `
      <script>
        try {
          const result = eval(${JSON.stringify(code)});
          parent.postMessage({ result: String(result) }, "*");
        } catch (e) {
          parent.postMessage({ result: "Error: " + e.message }, "*");
        }
      </script>
    `;
  });
}
```

**后端沙箱**（Phase 4，用于 Python/多语言执行）：

```python
# backend/packages/harness/deerflow/sandbox/executor.py

import asyncio
import docker


class SandboxExecutor:
    """Execute user code in isolated Docker containers."""

    TIMEOUT_SECONDS = 10
    MEMORY_LIMIT = "128m"
    NETWORK_DISABLED = True

    async def execute(self, code: str, language: str) -> dict:
        image = self._get_image(language)
        client = docker.from_env()

        container = client.containers.run(
            image,
            command=self._build_command(code, language),
            mem_limit=self.MEMORY_LIMIT,
            network_disabled=self.NETWORK_DISABLED,
            detach=True,
            read_only=True,
        )

        try:
            result = container.wait(timeout=self.TIMEOUT_SECONDS)
            stdout = container.logs(stdout=True, stderr=False).decode()
            stderr = container.logs(stdout=False, stderr=True).decode()
            return {"stdout": stdout, "stderr": stderr, "exit_code": result["StatusCode"]}
        except Exception:
            container.kill()
            return {"stdout": "", "stderr": "Execution timed out", "exit_code": -1}
        finally:
            container.remove(force=True)

    def _get_image(self, language: str) -> str:
        images = {"python": "python:3.12-slim", "javascript": "node:20-slim"}
        return images.get(language, "python:3.12-slim")

    def _build_command(self, code: str, language: str) -> list[str]:
        if language == "python":
            return ["python", "-c", code]
        return ["node", "-e", code]
```

---

## 8. 可观测性

### 8.1 前端埋点

```typescript
// frontend/src/core/genui/telemetry.ts

interface BlockEvent {
  event: string;
  block_id: string;
  component: string;
  timestamp: number;
  duration_ms?: number;
  error?: string;
}

class GenUITelemetry {
  private events: BlockEvent[] = [];

  trackRender(blockId: string, component: string, durationMs: number) {
    this.emit({ event: "block_render", block_id: blockId, component, duration_ms: durationMs });
  }

  trackRenderError(blockId: string, component: string, error: string) {
    this.emit({ event: "block_render_error", block_id: blockId, component, error });
  }

  trackInteraction(blockId: string, component: string, callbackId: string) {
    this.emit({ event: "block_interaction", block_id: blockId, component });
  }

  trackInteractionLatency(callbackId: string, durationMs: number) {
    this.emit({ event: "interaction_latency", block_id: callbackId, component: "", duration_ms: durationMs });
  }

  private emit(event: Omit<BlockEvent, "timestamp">) {
    const fullEvent = { ...event, timestamp: Date.now() };
    this.events.push(fullEvent);
    // Batch send to analytics endpoint
    if (this.events.length >= 10) this.flush();
  }

  flush() {
    if (this.events.length === 0) return;
    const batch = this.events.splice(0);
    navigator.sendBeacon("/api/telemetry/genui", JSON.stringify(batch));
  }
}

export const genUITelemetry = new GenUITelemetry();
```

### 8.2 后端监控

实际实现使用 **内存计数器 + context manager** 模式（非 Prometheus），线程安全，支持按组件统计：

```python
# backend/packages/harness/deerflow/tools/render_ui_metrics.py

from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class _ComponentMetrics:
    invocations: int = 0
    errors: int = 0
    durations_ms: list[float] = field(default_factory=list)


class RenderUIMetrics:
    """Thread-safe metrics collector for render_ui tool invocations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_component: dict[str, _ComponentMetrics] = defaultdict(_ComponentMetrics)
        self._total_invocations: int = 0
        self._total_errors: int = 0

    def record_invocation(self, component: str, duration_ms: float, error: bool = False) -> None:
        with self._lock:
            self._total_invocations += 1
            m = self._by_component[component]
            m.invocations += 1
            m.durations_ms.append(duration_ms)
            if error:
                self._total_errors += 1
                m.errors += 1

    @contextmanager
    def measure(self, component: str) -> Generator[None, None, None]:
        """Context manager 用于 render_ui_tool 中包裹整个渲染逻辑。"""
        start = time.perf_counter()
        error = False
        try:
            yield
        except Exception:
            error = True
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.record_invocation(component, duration_ms, error=error)

    def summary(self) -> dict:
        """返回汇总数据，包含 avg/p95 延迟和错误率。"""
        with self._lock:
            components = {}
            for name, m in self._by_component.items():
                avg = sum(m.durations_ms) / len(m.durations_ms) if m.durations_ms else 0
                p95 = sorted(m.durations_ms)[int(len(m.durations_ms) * 0.95)] if m.durations_ms else 0
                components[name] = {
                    "invocations": m.invocations,
                    "errors": m.errors,
                    "avg_duration_ms": round(avg, 2),
                    "p95_duration_ms": round(p95, 2),
                }
            return {
                "total_invocations": self._total_invocations,
                "total_errors": self._total_errors,
                "error_rate": round(self._total_errors / self._total_invocations, 4)
                    if self._total_invocations else 0,
                "by_component": components,
            }

    def reset(self) -> None:
        with self._lock:
            self._by_component.clear()
            self._total_invocations = 0
            self._total_errors = 0


# 全局单例
_metrics = RenderUIMetrics()

def get_render_ui_metrics() -> RenderUIMetrics:
    return _metrics
```

**在 render_ui_tool 中的使用方式**：

```python
metrics = get_render_ui_metrics()
with metrics.measure(component):
    # ... 执行渲染逻辑 ...
```

> **与原设计的关键差异**：
> - 使用内存 `defaultdict` + `threading.Lock` 替代 Prometheus Counter/Histogram
> - 通过 `@contextmanager` 的 `measure()` 方法自动计时和错误捕获
> - `summary()` 方法提供 avg/p95 延迟统计，可通过 API 暴露
> - 无外部依赖（不需要 prometheus_client 包）
> - 全局单例模式通过 `get_render_ui_metrics()` 访问

### 8.3 告警规则

由于实际实现使用内存指标（非 Prometheus），告警通过 `summary()` API 返回值进行判断：

| 指标（`summary()` 字段） | 阈值 | 告警级别 |
| ---- | ---- | -------- |
| `error_rate` > 0.10 | 错误率超过 10% | WARNING |
| `by_component[*].p95_duration_ms` > 5000 | 组件渲染 P95 延迟 > 5s | WARNING |
| `by_component[*].errors` / `invocations` > 0.20 | 单组件错误率 > 20% | CRITICAL |
| 前端 `InteractionState.status === "expired"` 频率 | 5 分钟内 > 5 次 | CRITICAL |

> **注意**：当前为内存指标，进程重启后重置。如需持久化告警，可通过 telemetry API 定期采集 `summary()` 数据推送到外部监控系统。

---

## 9. 实施计划

> **状态**：Phase 1-3 已完成实现，Phase 4 部分完成。

### Phase 1: 基础设施（1 周）✅ 已完成

- [x] 定义 UIBlock JSON Schema（含 schema_version、action、parent_id、callback_timeout_ms）
- [x] 实现 `render_ui` Tool（使用 `get_stream_writer()` + metrics + persistence）并注册到 Agent Graph
- [x] 实现 Props Sanitizer 和 Zod 校验层（全部 9 个组件 schema）
- [x] 前端 Component Registry（含版本降级 + 组件缓存）+ BlockStore（状态枚举模式）
- [x] SSE custom event 解析与路由（`onCustomEvent` → `applyBlock`）
- [x] Agent system prompt 注入 GenUI Guidance

### Phase 2: 核心组件（1 周）✅ 已完成

- [x] 实现 `chart` 组件（基于 Recharts，支持 bar/line/pie/scatter）
- [x] 实现 `table` 组件（基于 TanStack Table，支持排序/分页）
- [x] 实现 `card` 组件（支持 trend 指标）
- [x] 实现 `layout` 容器组件（grid/flex，递归渲染子 block）
- [x] 实现 `markdown` 降级组件
- [x] BlockErrorBoundary 独立组件 + GenUIRenderer 集成 Zod 验证

### Phase 3: 交互闭环（1 周）✅ 已完成

- [x] 实现 `form` 组件（React Hook Form + 动态字段 + validation）
- [x] 实现 `confirm` 组件（confirm/cancel + destructive variant）
- [x] InteractionStore（immutable frozen dataclass + 线程安全）+ process_interaction（幂等、超时）
- [x] 前端 InteractionState 状态枚举（idle/loading/submitted/error/expired）
- [x] 交互回调 API（RunManager + run_agent 恢复 graph，含重试逻辑）
- [x] GenUIBlockList 消息流集成 + submitInteraction 闭环
- [x] 前端超时检测（callback_timeout_ms → setInteractionExpired）

### Phase 4: 高级功能（1 周）🔄 进行中

- [x] 实现 `code` 组件（代码高亮）
- [x] 实现 `timeline` 组件
- [x] UIBlock update/delete 操作（update 合并 props，delete 移除 block）
- [x] 后端 render_ui_metrics（内存计数器 + context manager）
- [x] 实现 `echart` 组件（基于 ECharts，支持复杂可视化）
- [x] 前端 telemetry 上报（`core/genui/telemetry.ts` + `POST /api/telemetry/genui`）
- [x] Block 恢复 API（`GET /api/threads/{id}/ui-blocks`）
- [ ] 后端代码沙箱执行（Docker 隔离）— 延期至 Phase 5
- [ ] SSE 断线重连前端集成（`GenUISSEManager` 已设计，待接入）

---

## 10. 风险评估

| 风险 | 影响 | 缓解措施 |
| ---- | ---- | -------- |
| Agent 生成无效 UIBlock | 前端渲染失败 | Zod schema 校验 + ErrorBoundary + 降级到 markdown |
| Props 包含 XSS payload | 安全漏洞 | 白名单过滤 + DOMPurify + CSP header |
| 组件包体积膨胀 | 首屏加载变慢 | React.lazy 按需加载 + 代码分割 |
| 交互回调丢失/重复 | 用户操作无响应或重复执行 | InteractionStore 幂等 + 超时检测 + 前端重试 |
| SSE 连接断开 | UIBlock 丢失 | 指数退避重连 + 服务端 block 缓存 + 恢复 API |
| LLM 幻觉生成错误组件 | 展示错误信息 | 后端白名单校验 + 前端 fallback |
| 代码沙箱逃逸 | 安全漏洞 | iframe sandbox 无 same-origin + Docker 隔离 + 超时 |
| 协议版本不兼容 | 前端无法渲染 | schema_version 字段 + 降级策略 + 过渡期双版本支持 |
| 交互回调与 checkpoint 不匹配 | Agent 状态错乱 | InteractionStore 绑定 checkpoint_id |

---

## 11. 与现有架构的集成点

| 模块 | 集成方式 |
| ---- | -------- |
| `deerflow/agents/` | render_ui 作为 Tool 注入 Agent 工具列表 |
| `deerflow/agents/middlewares/` | GenUIMiddleware + InteractionStore 处理交互回调 |
| `deerflow/agents/prompts/` | GenUI Guidance 注入 Agent system prompt |
| `deerflow/agents/genui_persistence.py` | 线程安全的 UIBlock 持久化（内存 + TTL） |
| SSE streaming | 复用 stream_mode=custom 通道 |
| 前端 Message 组件 | GenUIBlockList 嵌入消息流，通过 BlockStore 管理状态 |
| 知识库 RAG | Agent 可将检索结果通过 table/card 组件展示 |
| 监控系统 | 内存 metrics（render_ui_metrics.py）+ 前端 telemetry 上报 |

---

## 12. 技术选型

| 层级 | 技术 | 理由 |
| ---- | ---- | ---- |
| 图表（基础） | Recharts | 已在项目中使用，React 原生，适合 bar/line/pie/scatter |
| 图表（高级） | ECharts | 支持地图、仪表盘、漏斗、雷达、热力图、桑基图、矩形树图、3D 等复杂可视化 |
| 表格 | TanStack Table | 无头设计，灵活度高 |
| 表单 | React Hook Form + Zod | 类型安全，性能好 |
| 代码高亮 | Shiki | 已在项目中使用 |
| 状态管理 | Zustand (genui store) | 轻量，与现有架构一致 |
| XSS 防护 | DOMPurify | 业界标准，体积小 |
| Schema 校验 | Zod | 已在项目中使用，TypeScript 原生 |
| 前端沙箱 | iframe sandbox | 浏览器原生隔离，零依赖 |
| 后端沙箱 | Docker (read-only, no-network) | 强隔离，支持多语言 |
| 监控 | 内存计数器 + 自定义 telemetry | 轻量无外部依赖，通过 API 暴露指标 |

**图表库选择指南**：

| 场景 | 推荐 | 原因 |
| ---- | ---- | ---- |
| 简单 bar/line/pie/scatter | Recharts (`chart` 组件) | 声明式 API，React 原生，bundle 小 |
| 地图、仪表盘、漏斗、雷达 | ECharts (`echart` 组件) | 内置丰富图表类型，无需额外插件 |
| 热力图、桑基图、矩形树图 | ECharts (`echart` 组件) | 专业统计可视化支持 |
| 3D 可视化 | ECharts GL (`echart` 组件) | 原生 WebGL 支持 |
| 需要高度自定义交互 | ECharts (`echart` 组件) | 事件系统完善，支持 brush/zoom/dataZoom |
