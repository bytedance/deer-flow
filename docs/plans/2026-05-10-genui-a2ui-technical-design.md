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

| component | 用途 | interactive |
| --------- | ---- | ----------- |
| `chart` | 图表（bar/line/pie/scatter） | No |
| `table` | 数据表格（排序、分页） | Optional |
| `card` | 统计卡片/信息卡片 | No |
| `form` | 表单输入 | Yes |
| `confirm` | 确认对话框 | Yes |
| `code` | 代码块（带沙箱执行按钮） | Optional |
| `timeline` | 时间线展示 | No |
| `markdown` | 富文本（降级兼容） | No |
| `layout` | 布局容器（grid/flex） | No |

### 4.6 协议版本演进策略

- `schema_version` 遵循语义化版本（MAJOR.MINOR）
- MINOR 升级：新增可选字段，向后兼容
- MAJOR 升级：破坏性变更，前端需同时支持新旧版本（过渡期 2 个迭代）
- 前端遇到未知 `schema_version` 时降级为 markdown 渲染

---
## 5. 后端实现

### 5.1 render_ui Tool（修正 StreamWriter 注入）

```python
# backend/packages/harness/deerflow/tools/render_ui.py

import uuid
from typing import Annotated

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.types import StreamWriter


@tool
def render_ui(
    component: str,
    props: dict,
    interactive: bool = False,
    callback_id: str | None = None,
    parent_id: str | None = None,
    action: str = "create",
) -> str:
    """Render a UI component in the user interface.

    Args:
        component: Component type (chart, table, card, form, confirm, code, timeline, layout)
        props: Component properties
        interactive: Whether the component accepts user interaction
        callback_id: Required if interactive=True, used to route interaction callbacks
        parent_id: Optional parent block_id for layout grouping
        action: One of 'create', 'update', 'delete'
    """
    ALLOWED_COMPONENTS = {"chart", "table", "card", "form", "confirm", "code", "timeline", "markdown", "layout"}
    if component not in ALLOWED_COMPONENTS:
        return f"Error: Unknown component '{component}'. Allowed: {ALLOWED_COMPONENTS}"

    if interactive and not callback_id:
        return "Error: interactive=True requires a callback_id"

    writer = get_stream_writer()

    block = {
        "schema_version": "1.0",
        "type": "ui_block",
        "action": action,
        "block_id": str(uuid.uuid4()),
        "component": component,
        "props": props,
        "interactive": interactive,
    }
    if callback_id:
        block["callback_id"] = callback_id
    if parent_id:
        block["parent_id"] = parent_id

    writer(block)
    return f"UI component '{component}' ({action}) rendered successfully."
```

> **关键修正**：使用 `get_stream_writer()` 从 LangGraph 运行时上下文获取 writer，
> 而非通过函数参数注入。这是 LangGraph >=0.2 的标准做法。

### 5.2 GenUIMiddleware（含状态管理）

```python
# backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py

import time
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage


@dataclass
class InteractionRecord:
    callback_id: str
    thread_id: str
    checkpoint_id: str
    created_at: float
    timeout_ms: int = 300000
    submitted: bool = False
    payload: dict | None = None

    @property
    def is_expired(self) -> bool:
        elapsed_ms = (time.time() - self.created_at) * 1000
        return elapsed_ms > self.timeout_ms


class InteractionStore:
    """Manages interaction state for idempotency and timeout handling."""

    def __init__(self):
        self._records: dict[str, InteractionRecord] = {}

    def register(self, callback_id: str, thread_id: str, checkpoint_id: str, timeout_ms: int = 300000):
        self._records[callback_id] = InteractionRecord(
            callback_id=callback_id,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            created_at=time.time(),
            timeout_ms=timeout_ms,
        )

    def get(self, callback_id: str) -> InteractionRecord | None:
        return self._records.get(callback_id)

    def cleanup_expired(self):
        expired = [k for k, v in self._records.items() if v.is_expired]
        for k in expired:
            del self._records[k]


class GenUIMiddleware:
    """Intercept UI interaction callbacks and convert to Agent context."""

    def __init__(self, store: InteractionStore):
        self.store = store

    def process_interaction(self, callback_id: str, payload: dict) -> HumanMessage | None:
        record = self.store.get(callback_id)

        if record is None:
            return HumanMessage(
                content=f"[UI Interaction] callback_id={callback_id}\nError: Unknown callback (may have expired)",
                metadata={"source": "ui_interaction", "error": "unknown_callback"},
            )

        if record.is_expired:
            return HumanMessage(
                content=f"[UI Interaction] callback_id={callback_id}\nError: Callback has expired",
                metadata={"source": "ui_interaction", "error": "expired"},
            )

        if record.submitted:
            return None  # Idempotent: ignore duplicate submissions

        record.submitted = True
        record.payload = payload

        content = (
            f"[UI Interaction] callback_id={callback_id}\n"
            f"User submitted: {payload}"
        )
        return HumanMessage(
            content=content,
            metadata={
                "source": "ui_interaction",
                "checkpoint_id": record.checkpoint_id,
            },
        )
```

### 5.3 Agent Prompt Guidance

在 Agent 的 system prompt 中注入 GenUI 使用指南：

```python
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
| chart     | Numerical data with trends or comparisons (bar, line, pie, scatter) |
| table     | Structured data with multiple fields, especially >3 rows |
| card      | Single KPI or summary statistic |
| form      | When you need user input to proceed |
| confirm   | Before destructive or irreversible actions |
| code      | Code snippets that user might want to execute |
| timeline  | Sequential events or steps |
| layout    | Grouping multiple blocks into a dashboard |

### Guidelines

1. Prefer plain text/markdown for simple responses (1-2 sentences, short lists)
2. Use `render_ui` when visual structure adds clarity
3. For interactive components, always provide a meaningful `callback_id`
4. Use `layout` to group related blocks (e.g., a dashboard with cards + chart)
5. Never render sensitive data (passwords, tokens) in UI blocks
6. Keep props minimal — only include data the component needs
"""
```

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
# backend/packages/harness/deerflow/api/genui_routes.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class InteractionRequest(BaseModel):
    callback_id: str
    payload: dict


@router.post("/api/threads/{thread_id}/ui-interaction")
async def handle_ui_interaction(thread_id: str, request: InteractionRequest):
    middleware = get_genui_middleware()  # from DI container
    message = middleware.process_interaction(request.callback_id, request.payload)

    if message is None:
        return {"status": "duplicate", "message": "Interaction already processed"}

    if message.metadata.get("error"):
        raise HTTPException(status_code=410, detail=message.content)

    # Resume the graph from the associated checkpoint
    record = middleware.store.get(request.callback_id)
    await resume_graph(thread_id, record.checkpoint_id, message)

    return {"status": "accepted", "callback_id": request.callback_id}
```

---

## 6. 前端实现

### 6.1 Component Registry

```typescript
// frontend/src/core/genui/registry.ts

import { lazy, type ComponentType } from "react";

type UIBlockProps = Record<string, unknown>;

const registry = new Map<string, () => Promise<{ default: ComponentType<UIBlockProps> }>>();

registry.set("chart", () => import("@/components/genui/ChartBlock"));
registry.set("table", () => import("@/components/genui/TableBlock"));
registry.set("form", () => import("@/components/genui/FormBlock"));
registry.set("card", () => import("@/components/genui/CardBlock"));
registry.set("confirm", () => import("@/components/genui/ConfirmBlock"));
registry.set("code", () => import("@/components/genui/CodeBlock"));
registry.set("timeline", () => import("@/components/genui/TimelineBlock"));
registry.set("layout", () => import("@/components/genui/LayoutBlock"));

export function getBlockComponent(type: string) {
  const loader = registry.get(type);
  if (!loader) return null;
  return lazy(loader);
}
```

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

```typescript
// frontend/src/core/genui/store.ts

import { create } from "zustand";

interface UIBlock {
  schema_version: string;
  type: "ui_block";
  action: "create" | "update" | "delete";
  block_id: string;
  component: string;
  props: Record<string, unknown>;
  interactive?: boolean;
  callback_id?: string;
  parent_id?: string;
}

interface InteractionState {
  loading: boolean;
  error: string | null;
  submitted: boolean;
}

interface BlockStoreState {
  blocks: Map<string, UIBlock>;
  interactions: Map<string, InteractionState>;
  applyBlock: (block: UIBlock) => void;
  setInteractionLoading: (callbackId: string) => void;
  setInteractionSuccess: (callbackId: string) => void;
  setInteractionError: (callbackId: string, error: string) => void;
  getChildBlocks: (parentId: string) => UIBlock[];
  reset: () => void;
}

export const useBlockStore = create<BlockStoreState>((set, get) => ({
  blocks: new Map(),
  interactions: new Map(),

  applyBlock: (block) =>
    set((state) => {
      const blocks = new Map(state.blocks);
      switch (block.action) {
        case "create":
        case "update":
          blocks.set(block.block_id, block);
          break;
        case "delete":
          blocks.delete(block.block_id);
          break;
      }
      return { blocks };
    }),

  setInteractionLoading: (callbackId) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { loading: true, error: null, submitted: false });
      return { interactions };
    }),

  setInteractionSuccess: (callbackId) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { loading: false, error: null, submitted: true });
      return { interactions };
    }),

  setInteractionError: (callbackId, error) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { loading: false, error, submitted: false });
      return { interactions };
    }),

  getChildBlocks: (parentId) => {
    const blocks = get().blocks;
    return Array.from(blocks.values()).filter((b) => b.parent_id === parentId);
  },

  reset: () => set({ blocks: new Map(), interactions: new Map() }),
}));
```

### 6.4 GenUI Renderer（含 ErrorBoundary）

```typescript
// frontend/src/components/genui/GenUIRenderer.tsx

import { Component, Suspense, type ReactNode } from "react";
import { getBlockComponent } from "@/core/genui/registry";
import { sanitizeProps } from "@/core/genui/sanitizer";
import { useBlockStore } from "@/core/genui/store";

interface UIBlock {
  schema_version: string;
  type: "ui_block";
  block_id: string;
  component: string;
  props: Record<string, unknown>;
  interactive?: boolean;
  callback_id?: string;
  parent_id?: string;
}

// Error Boundary
interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class BlockErrorBoundary extends Component<
  { blockId: string; component: string; children: ReactNode },
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <p>Component "{this.props.component}" failed to render.</p>
          <p className="mt-1 text-xs text-red-500">{this.state.error?.message}</p>
        </div>
      );
    }
    return this.props.children;
  }
}

// Main Renderer
interface GenUIRendererProps {
  block: UIBlock;
  onInteraction?: (callbackId: string, payload: unknown) => void;
}

export function GenUIRenderer({ block, onInteraction }: GenUIRendererProps) {
  const Component = getBlockComponent(block.component);
  const interactionState = useBlockStore(
    (s) => block.callback_id ? s.interactions.get(block.callback_id) : undefined,
  );

  if (!Component) {
    return (
      <div className="rounded border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-700">
        Unsupported component: {block.component}
      </div>
    );
  }

  const sanitizedProps = sanitizeProps(block.component, block.props);

  return (
    <BlockErrorBoundary blockId={block.block_id} component={block.component}>
      <Suspense fallback={<div className="animate-pulse h-20 bg-gray-100 rounded" />}>
        <Component
          {...sanitizedProps}
          disabled={interactionState?.loading || interactionState?.submitted}
          onSubmit={
            block.interactive && block.callback_id
              ? (payload: unknown) => onInteraction?.(block.callback_id!, payload)
              : undefined
          }
        />
        {interactionState?.loading && (
          <div className="mt-2 text-sm text-gray-500">Submitting...</div>
        )}
        {interactionState?.error && (
          <div className="mt-2 text-sm text-red-600">{interactionState.error}</div>
        )}
        {interactionState?.submitted && (
          <div className="mt-2 text-sm text-green-600">Submitted successfully</div>
        )}
      </Suspense>
    </BlockErrorBoundary>
  );
}
```

### 6.5 交互回调（含乐观更新和重试）

```typescript
// frontend/src/core/genui/interaction.ts

import { useBlockStore } from "./store";

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

export async function submitInteraction(
  threadId: string,
  callbackId: string,
  payload: unknown,
): Promise<{ status: string }> {
  const store = useBlockStore.getState();
  store.setInteractionLoading(callbackId);

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(`/api/threads/${threadId}/ui-interaction`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callback_id: callbackId, payload }),
      });

      if (response.status === 410) {
        store.setInteractionError(callbackId, "This interaction has expired");
        return { status: "expired" };
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      const result = await response.json();

      if (result.status === "duplicate") {
        store.setInteractionSuccess(callbackId);
        return result;
      }

      store.setInteractionSuccess(callbackId);
      return result;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt < MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * (attempt + 1)));
      }
    }
  }

  store.setInteractionError(callbackId, lastError?.message ?? "Submission failed");
  return { status: "error" };
}
```

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

```typescript
// frontend/src/core/genui/validator.ts

import { z } from "zod";

const chartPropsSchema = z.object({
  chart_type: z.enum(["bar", "line", "pie", "scatter"]),
  title: z.string().max(200),
  data: z.array(z.record(z.unknown())).max(1000),
  x_key: z.string(),
  y_key: z.string(),
  colors: z.array(z.string().regex(/^#[0-9a-fA-F]{6}$/)).optional(),
});

const formFieldSchema = z.object({
  name: z.string().max(50),
  type: z.enum(["text", "number", "select", "checkbox", "date"]),
  label: z.string().max(100),
  required: z.boolean().optional(),
  default: z.unknown().optional(),
  options: z.array(z.object({ label: z.string(), value: z.unknown() })).optional(),
});

const formPropsSchema = z.object({
  title: z.string().max(200),
  fields: z.array(formFieldSchema).max(20),
  submit_label: z.string().max(50).optional(),
  cancel_label: z.string().max(50).optional(),
});

export const propsSchemas: Record<string, z.ZodSchema> = {
  chart: chartPropsSchema,
  form: formPropsSchema,
  // ... other component schemas
};

export function validateProps(component: string, props: unknown): boolean {
  const schema = propsSchemas[component];
  if (!schema) return false;
  return schema.safeParse(props).success;
}
```

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

```python
# backend/packages/harness/deerflow/tools/render_ui_metrics.py

import time
import logging
from functools import wraps
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

RENDER_UI_CALLS = Counter(
    "genui_render_ui_total",
    "Total render_ui tool invocations",
    ["component", "action"],
)

RENDER_UI_ERRORS = Counter(
    "genui_render_ui_errors_total",
    "render_ui validation errors",
    ["component", "error_type"],
)

INTERACTION_LATENCY = Histogram(
    "genui_interaction_latency_seconds",
    "End-to-end interaction callback latency",
    ["callback_id_prefix"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

INTERACTION_OUTCOMES = Counter(
    "genui_interaction_outcomes_total",
    "Interaction processing outcomes",
    ["outcome"],  # accepted, duplicate, expired, unknown
)
```

### 8.3 告警规则

| 指标 | 阈值 | 告警级别 |
| ---- | ---- | -------- |
| `genui_render_ui_errors_total` rate > 5/min | 5 分钟内错误率 > 10% | WARNING |
| `genui_interaction_latency_seconds` p99 > 5s | 交互延迟过高 | WARNING |
| `genui_interaction_outcomes_total{outcome="expired"}` rate > 2/min | 回调频繁超时 | CRITICAL |
| Block render error rate > 20% | 组件渲染大面积失败 | CRITICAL |

---

## 9. 实施计划

### Phase 1: 基础设施（1 周）

- [ ] 定义 UIBlock JSON Schema（含 schema_version、action、parent_id）
- [ ] 实现 `render_ui` Tool（使用 `get_stream_writer()`）并注册到 Agent Graph
- [ ] 实现 Props Sanitizer 和 Zod 校验层
- [ ] 前端 Component Registry + BlockStore 骨架
- [ ] SSE custom event 解析与路由
- [ ] Agent system prompt 注入 GenUI Guidance

### Phase 2: 核心组件（1 周）

- [ ] 实现 `chart` 组件（基于 Recharts）
- [ ] 实现 `table` 组件（基于 TanStack Table）
- [ ] 实现 `card` 组件
- [ ] 实现 `layout` 容器组件
- [ ] 实现 `markdown` 降级组件
- [ ] ErrorBoundary 包裹所有组件

### Phase 3: 交互闭环（1 周）

- [ ] 实现 `form` 组件
- [ ] 实现 `confirm` 组件
- [ ] InteractionStore + GenUIMiddleware（幂等、超时、checkpoint 关联）
- [ ] 前端乐观更新 + loading/error 状态
- [ ] 交互回调 API（含重试逻辑）
- [ ] SSE 断线重连 + Block 恢复机制

### Phase 4: 高级功能（1 周）

- [ ] 实现 `code` 组件（前端 iframe sandbox 执行）
- [ ] 实现 `timeline` 组件
- [ ] UIBlock update/delete 操作（进度条、状态变更场景）
- [ ] 后端代码沙箱（Docker 隔离）
- [ ] 可观测性埋点（前端 telemetry + 后端 Prometheus metrics）
- [ ] 告警规则配置

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
| SSE streaming | 复用 stream_mode=custom 通道 |
| 前端 Message 组件 | 在消息流中识别 ui_block 类型，通过 BlockStore 管理状态 |
| 知识库 RAG | Agent 可将检索结果通过 table/card 组件展示 |
| 监控系统 | Prometheus metrics + 前端 telemetry 上报 |

---

## 12. 技术选型

| 层级 | 技术 | 理由 |
| ---- | ---- | ---- |
| 图表 | Recharts | 已在项目中使用，React 原生 |
| 表格 | TanStack Table | 无头设计，灵活度高 |
| 表单 | React Hook Form + Zod | 类型安全，性能好 |
| 代码高亮 | Shiki | 已在项目中使用 |
| 状态管理 | Zustand (genui store) | 轻量，与现有架构一致 |
| XSS 防护 | DOMPurify | 业界标准，体积小 |
| Schema 校验 | Zod | 已在项目中使用，TypeScript 原生 |
| 前端沙箱 | iframe sandbox | 浏览器原生隔离，零依赖 |
| 后端沙箱 | Docker (read-only, no-network) | 强隔离，支持多语言 |
| 监控 | Prometheus + 自定义 telemetry | 与现有基础设施一致 |
