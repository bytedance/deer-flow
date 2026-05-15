# 日报页面渲染方式评估与历史会话 Block 顺序修复方案

> 日期：2026-05-15
> 状态：Draft
> 关联 Agent：`ai-report--daily`
> 关联模块：GenUI 渲染管线、Block 持久化与恢复

---

## 1. 评估总览

基于四条业务需求，对当前日报页面渲染方式进行逐项评估。

| 需求 | 评估 | 风险等级 |
|------|------|----------|
| 1. 前端条件选择 | 合理 | 低 |
| 2. 架构与业务解耦 | 优秀 | 低 |
| 3. 图表输出 + 可编辑 + 下载 | 部分缺失（缺编辑能力） | 高 |
| 4. 历史多轮对话查询（含图表） | 存在架构性风险（block 顺序不保证 + 图表恢复脆弱） | 高 |

---

## 2. 架构现状

### 2.1 整体数据流

```
┌─────────────────────────────┐       SSE (custom events)       ┌──────────────────────────────┐
│  前端 (React / Zustand)      │◄──────────────────────────────│  后端 (LangGraph Agent)        │
│                              │                                │                                │
│  useBlockStore (Zustand)    │                                │  render_ui Tool                │
│    ├─ blocks: Map<id, UIBlock>│                               │    → <!--ui_block:{json}-->    │
│    └─ interactions: Map       │                                │    → StreamWriter("ui_block")  │
│                              │                                │                                │
│  Component Registry          │                                │  genui_middleware              │
│    form/card/echart/table/   │                                │    InteractionStore (内存)     │
│    markdown/layout/...       │                                │    → HumanMessage 注入图        │
│                              │  POST /api/threads/{id}/       │                                │
│  用户交互提交流程             │─────────►  ui-interaction ───►│  genui_persistence             │
│  1. ECharts 截图捕获          │                                │    persist_block (内存 + 1h TTL) │
│  2. 上传截图到 uploads       │                                │    get_persisted_blocks         │
│  3. 提交 payload + chart_images│                               │    extract_blocks_from_messages │
│                              │                                │      (checkpoint 恢复兜底)     │
│  GenUISSEManager             │  GET /api/threads/{id}/        │                                │
│    SSE 断线恢复               │─────────►  ui-blocks ────────►│  genui_telemetry               │
│    recoverBlocksFromMessages │                                │    get_thread_blocks           │
│    (消息解析兜底)             │                                │      (内存 → checkpoint 兜底)  │
└─────────────────────────────┘                                └──────────────────────────────┘
```

### 2.2 日报多轮交互流程

```
Round 1:  用户进入 → Agent 渲染 form(daily-report-scope) → 等待提交
Round 1 回调: 校验参数 → 查询设备列表 → 渲染 form(daily-report-equipment) → 等待提交
Round 1.5 回调: 解析设备 → 查询 KPI → 渲染 form(daily-report-confirm) → 等待提交
Round 2 回调: 收集参数 → 调用数据脚本 → 渲染 card/echart/table/markdown → 渲染 form(export)
导出回调:   读取格式 + chart_images → 调用导出脚本 → present_files → 渲染下载链接
```

### 2.3 前端 Block 渲染 3 层区域

在 [message-list.tsx](../../frontend/src/components/workspace/messages/message-list.tsx) 中，历史 Block 通过 `groupedHistoricalStandaloneBlocks` 分为三个 bucket，与消息组交叉渲染：

```
┌──────────────────────────────────────────────────────────┐
│  [beforeMessageBlockIds]                                 │  ← 无锚定消息的历史 Block（render before all messages）
├──────────────────────────────────────────────────────────┤
│  Message Group 1 (human)                                 │
│  Message Group 2 (assistant:processing)                  │
│    └─ claimed BlockIds (inline, 嵌入在 tool msg 内)      │
│  [blockIdsByAnchorGroupKey[group2]] (anchored after)     │  ← 锚定在特定消息组后的历史 Block
├──────────────────────────────────────────────────────────┤
│  Message Group 3 (human) ← 当前轮                        │
│  Message Group 4 (assistant:processing)                  │
│    └─ claimed BlockIds (inline, 实时流式)                 │
├──────────────────────────────────────────────────────────┤
│  [fallbackBlockIds] (孤儿 Block, 兜底区域)                │
│  StreamingIndicator (加载动画)                            │
└──────────────────────────────────────────────────────────┘
```

Block 历史解析由 [history.ts](../../frontend/src/core/genui/history.ts) 的 `buildResolvedBlockHistory` 统一处理（含重复 block_id 消歧 `__N` 后缀），分区逻辑见 [visibility.ts](../../frontend/src/core/genui/visibility.ts) 的 `partitionStandaloneBlockIds` 和 `filterSupersededInteractiveBlockIds`。

---

## 3. 逐项评估

### 3.1 需求 1：前端条件选择 ✅ 合理

**当前实现**：多轮渐进式表单（Round 1 日期/类型/对比 → Round 1.5 设备多选 → Round 2 KPI 确认），逐步降低复杂度。

**亮点**：
- `multi-select` 组件支持搜索、分组、全选/全不选、虚拟滚动（>500 条），可处理 1000+ 设备场景
- 前端 Zod schema 校验 + 后端 SOUL.md 双重校验，安全性到位
- `default_values` 支持预填，减少用户操作

**风险点**：无明显风险。

### 3.2 需求 2：架构与业务解耦 ✅ 优秀

**GenUI 协议是通用的**：
- 组件注册表 `COMPONENT_REGISTRY`（[registry.ts](../../frontend/src/core/genui/registry.ts)）包含 11 种通用 Block 类型：`chart`、`echart`、`table`、`card`、`form`、`confirm`、`code`、`timeline`、`layout`、`markdown`、`image`
- 所有 Block 通过统一的 `type: "ui_block"` 协议传输，不绑定任何具体业务

**业务逻辑完全在 SOUL.md + Skill 脚本中**：
- [SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) 定义多轮交互、校验、数据拉取、渲染指令
- Python Skill 脚本负责确定性计算（`list_equipment.py`、`query_daily.py`、`daily_kpi.py`、`export_report.py`）
- 零后端路由耦合、零前端组件耦合

**复用性**：`monitoring-analysis` 等其他 Agent 复用相同的 GenUI 协议和组件。

### 3.3 需求 3：图表 + 编辑 + 下载 ⚠️ 部分缺失

| 子需求 | 状态 | 说明 |
|--------|------|------|
| 图表渲染 | ✅ | ECharts (via `echarts-for-react`) + Recharts 双引擎，`echart` 支持完整 ECharts option |
| 图表截图 | ✅ | [EChartBlock.tsx](../../frontend/src/components/genui/EChartBlock.tsx) `onChartReady` 自动捕获 PNG → [chart-screenshots.ts](../../frontend/src/core/genui/chart-screenshots.ts) 上传到 uploads → 注入导出 payload |
| **内容编辑** | ❌ **缺失** | 所有 GenUI Block（markdown/card/table）均为**纯展示模式**，无可编辑能力 |
| 下载 | ⚠️ | Markdown/PDF 导出可用，但需要额外的"导出表单"提交步骤。PDF 依赖 weasyprint |

**编辑能力的缺失是当前最严重的功能缺口**。需求要求"用户编辑除图表外的其它内容"，但 GenUI 协议中没有任何 `editable` 属性，也没有 update block 的前端交互机制。当前唯一的交互组件是 `FormBlock`，但它只能提交新数据，不能原地编辑已渲染的内容。

**建议**：
1. 在 UIBlock 协议中增加 `editable: boolean` 属性
2. 在 MarkdownBlock / TableBlock 中实现双击进入编辑模式
3. 编辑完成后通过 `POST /api/threads/{id}/ui-interaction` 或新的 update 端点提交
4. 后端 Agent 接收编辑后的内容，重新生成（或直接更新）Block

### 3.4 需求 4：历史多轮对话查询 ⚠️ 架构性风险

**当前持久化链路**：

| 层级 | 机制 | 问题 |
|------|------|------|
| 后端 | `genui_persistence.py` 内存 `_store` + 1h TTL | TTL 后数据丢失，后端重启后数据全丢 |
| 后端 | `extract_blocks_from_messages` checkpoint 恢复 | 依赖 `<!--ui_block:...-->` 标记未被截断 |
| 后端 | `GET /api/threads/{id}/ui-blocks`（[genui_telemetry.py:111](../../backend/app/gateway/routers/genui_telemetry.py#L111)） | 内存 → checkpoint 两级兜底，端点已实现；但 **返回的 block 无显式顺序** |
| 前端 | `GenUISSEManager.recoverBlocks()` | 调用后端端点，含指数退避重连（1s→30s） |
| 前端 | `recoverBlocksFromMessages()` 消息解析 | 从当前页面消息中提取，仅在当前会话有效 |
| 前端 | `visibility.ts` 分区逻辑 | 能区分历史/live block，但依赖 store 中有数据 |
| 前端 | ECharts `onChartReady` 截图 | 仅首次渲染触发；历史 block 的 `disableExpiration=true` 可能影响触发时机 |

**可靠的恢复路径只有一条**：
```
历史消息加载 → extractBlockIdsFromMessages → recoverBlocksFromMessages
→ partitionStandaloneBlockIds → groupedHistoricalStandaloneBlocks
→ GenUIBlockList 渲染
```
即：前端从历史 ToolMessage 中解析 `<!--ui_block:{"block_id":"...","component":"echart",...}-->` 标记，重建 store，然后 ECharts 从 JSON option 重新渲染。

**但这个路径存在以下风险**：

#### 风险 1：Block 顺序不保证（本文重点）

详见第 4 节。

#### 风险 2：ECharts option 截断

如果 ECharts option 数据量大（例如 24 小时 * 60 个数据点的趋势图），`<!--ui_block:...-->` 中的 JSON 可能因消息长度限制被截断，导致 block 无法解析。

#### 风险 3：交互状态丢失

历史表单的 `interactionState` 全部变为 `readonly`（因为 `disableExpiration=true`），导出表单无法再使用。用户无法在历史会话中执行"导出"操作。

#### 风险 4：图表截图丢失

历史 block 的 ECharts 重新渲染时，`onChartReady` 可能因组件生命周期（`Suspense` + `lazy` 加载时序）不触发，导致无法重新截图。如果截图之前已上传，可通过 `useChartScreenshotStore` 的 `uploaded` Map 找到，但 uploads 目录本身可能已被清理。

---

## 4. Block 顺序问题详细分析

### 4.1 问题根源

整个 GenUI 管线中，Block 的**创建顺序没有被显式保存**：

**A. `UIBlock` 接口无顺序字段**

[store.ts:3-15](../../frontend/src/core/genui/store.ts#L3-L15) — `UIBlock` 类型中没有任何 `sequence`、`order`、`created_at` 等排序字段。

```typescript
export interface UIBlock {
  schema_version: string;
  type: "ui_block";
  action: "create" | "update" | "delete";
  block_id: string;
  component: string;
  props: Record<string, unknown>;
  interactive: boolean;
  callback_id?: string;
  callback_timeout_ms?: number;
  parent_id?: string;
  metadata?: Record<string, unknown>;
  // ❌ 无 sequence / order 字段
}
```

**B. 后端 `_fold_blocks()` 隐式依赖 dict 插入顺序**

[genui_persistence.py:18-48](../../backend/packages/harness/deerflow/agents/genui_persistence.py#L18-L48) — fold 函数使用 `dict` 存储最终 block，顺序 = 首次 `create` 的插入顺序。同一个 block 的多轮 `update` 不会改变其位置。`get_persisted_blocks` 和 `extract_blocks_from_messages` 均通过调用 `_fold_blocks` 获取最终 block 列表。

```python
def _fold_blocks(blocks: list[dict]) -> list[dict]:
    final_blocks: dict[str, dict] = {}  # 顺序 = 首次 create 的插入顺序
    for block in blocks:
        ...
        if action == "delete":
            final_blocks.pop(block_id, None)
        elif action == "update":
            # ❌ update 不改变 key 在 dict 中的位置
            ...
        else:
            final_blocks[block_id] = {...}  # 首次 create 决定位置
    return list(final_blocks.values())  # ❌ 无显式排序
```

**C. `extract_blocks_from_messages` 的排序也不可靠**

[genui_persistence.py:72-100](../../backend/packages/harness/deerflow/agents/genui_persistence.py#L72-L100) — 从消息中提取 block 时，按消息时间顺序扫描 `<!--ui_block:...-->` marker 并收集为列表，然后调用 `_fold_blocks` 合并。由于列表顺序 = 消息中 marker 的物理顺序，而 marker 顺序由 LLM 的 `render_ui` 调用顺序决定，**不保证跨轮的正确性**（例如：Round 1 的 block marker 在 checkpoint 中的位置可能因序列化而改变）。

**D. 前端渲染无显式排序**

[GenUIBlockList.tsx:22-42](../../frontend/src/components/genui/GenUIBlockList.tsx#L22-L42) — 使用 `useMemo` 过滤 `candidateBlocks` 并通过 `filterSupersededInteractiveBlockIds` 去重，但最终返回的 `candidateBlocks` 无排序，完全依赖 `Map` 的插入顺序。

```typescript
// GenUIBlockList.tsx — 当前代码
const filteredBlocks = useMemo(() => {
  const candidateBlocks = Array.from(blocks.values()).filter((block) => {
    if (block.parent_id) return false;
    // ...
  });
  const visibleBlockIds = new Set(
    filterSupersededInteractiveBlockIds(
      candidateBlocks.map((block) => block.block_id),
      blocks,
    ),
  );
  return candidateBlocks.filter((block) => visibleBlockIds.has(block.block_id));
  // ❌ 无排序，完全依赖 Map 插入顺序
}, [blockIds, blocks, excludeBlockIds]);
```

### 4.2 多轮会话的顺序错乱场景

以日报三轮交互为例：

```
Round 1: create form(daily-report-scope)  → sequence 隐含 = 1
         create card(概览)                 → sequence 隐含 = 2
         create echart(趋势)               → sequence 隐含 = 3
         create table(异常)                → sequence 隐含 = 4
         create markdown(总结)             → sequence 隐含 = 5
         create form(export)               → sequence 隐含 = 6

Round 2: update card(概览)                 ← card 保持位置 2
         update echart(趋势)               ← echart 保持位置 3
         update table(异常)                ← table 保持位置 4
         update markdown(总结)             ← markdown 保持位置 5

Round 3: update card(概览)                 ← card 仍保持位置 2
         update echart(趋势)               ← echart 仍保持位置 3
```

当前情况下顺序碰巧是对的（2→3→4→5），但以下场景会打破这个假设：

1. **后端重启后走 checkpoint 恢复**：`extract_blocks_from_messages` 扫描消息时，如果某条消息中 card 的 marker 出现在 echart 之后（例如消息顺序因 LangGraph checkpoint 序列化而变化），返回的 block 顺序就会错乱
2. **同一消息中包含多个 block marker**：marker 在消息文本中的物理顺序决定解析顺序，但这个顺序由 LLM 的 `render_ui` 调用顺序决定，不受我们控制
3. **多轮中某轮增删 block**：如果 Round 2 中 delete 了一个 block 又 create 了一个新的，新 block 会排在 dict 末尾，打破原始的逻辑顺序

### 4.3 修复方案

**核心思路**：在 `UIBlock` 中增加 `sequence` 字段，贯穿整个管线显式排序。

#### 修改清单

| 文件 | 改动 |
|------|------|
| `backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py` | **新增**：在 block 构建时生成 `sequence` 字段（毫秒时间戳），作为整个管线的排序起点 |
| `backend/packages/harness/deerflow/agents/genui_persistence.py` | `_fold_blocks` 保留首次 `create` 的 `sequence`（update 不覆盖），末尾按 `(sequence, block_id)` 排序。`get_persisted_blocks` 和 `extract_blocks_from_messages` 均调用 `_fold_blocks`，排序自动覆盖 |
| `frontend/src/core/genui/store.ts` | (1) `UIBlock` 接口增加 `sequence?: number`；(2) `getChildBlocks` 按 `sequence` 排序子 Block |
| `frontend/src/core/genui/sse-recovery.ts` | `extractBlocksFromMessages` 已委托到 `buildResolvedBlockHistory`，本文件无需直接改动 |
| `frontend/src/core/genui/history.ts` | `buildResolvedBlockHistory` return 语句中按 `(sequence, block_id)` 排序 `blocks` 数组（前端侧 block 解析的集中出口） |
| `frontend/src/core/genui/visibility.ts` | (1) `filterSupersededInteractiveBlockIds` 用 `sequence` 判定同一 callback_id 下的最新版本（替代 Map 插入顺序依赖）；(2) `partitionStandaloneBlockIds` 返回前对 `historicalBlockIds` 和 `tailBlockIds` 按 `sequence` 排序 |
| `frontend/src/components/genui/GenUIBlockList.tsx` | 渲染前按 `sequence` 升序排列 |

以下文件**无需改动**：
- `genui_middleware.py` — `InteractionStore` 不关心 block 顺序
- `genui.py` (router) — interaction 端点不涉及 block 列表
- `genui_telemetry.py` — 透传 `get_persisted_blocks` 的返回值，后端排序后即可
- SOUL.md — LLM 不需要也不应该手动设置 `sequence`

#### 4.3.1 `render_ui_tool.py` — sequence 生成源

[render_ui_tool.py:61-94](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L61-L94) 是 block 的**唯一创建入口**，`sequence` 必须在 `resolved_block_id` 确定之后、`block` dict 构建之前生成：

```python
# render_ui_tool.py（在 resolved_block_id 确定之后，block dict 构建之前）
import time

config = get_config()
thread_id = config.get("configurable", {}).get("thread_id", "")

from deerflow.agents.genui_persistence import persist_block, resolve_create_block_id

if action == "create":
    resolved_block_id = (
        resolve_create_block_id(thread_id, block_id) or str(uuid.uuid4())
    )
else:
    resolved_block_id = block_id or str(uuid.uuid4())

seq = int(time.time() * 1000)  # 毫秒级时间戳 — 新增

block = {
    "schema_version": SCHEMA_VERSION,
    "type": "ui_block",
    "action": action,
    "block_id": resolved_block_id,
    "component": component,
    "props": props,
    "interactive": interactive,
    "sequence": seq,  # 新增
}
```

注意：`resolve_create_block_id` 对重复 `block_id` 追加后缀（如 `-2`），保证每次 create 得到唯一 ID。这与 `sequence` 时间戳协同——每次 re-create 获得新 ID + 新 sequence，排序天然正确。

#### 4.3.2 `store.ts` — 接口定义 + `getChildBlocks` 排序

**接口变更**：

```typescript
// store.ts
export interface UIBlock {
  // ... 现有字段 ...
  /** Monotonically increasing creation order. Set by backend render_ui tool. */
  sequence?: number;
}
```

**`getChildBlocks` 排序**：LayoutBlock 通过此方法获取子 Block，当前直接返回 Map 遍历结果，恢复后顺序不可靠。

```typescript
// store.ts
getChildBlocks: (parentId: string) => {
  const { blocks } = get();
  const children: UIBlock[] = [];
  for (const block of blocks.values()) {
    if (block.parent_id === parentId) {
      children.push(block);
    }
  }
  return children.sort(
    (a, b) => (a.sequence ?? 0) - (b.sequence ?? 0) || (a.block_id ?? "").localeCompare(b.block_id ?? "")
  );
},
```

#### 4.3.3 后端 `_fold_blocks` 保留 sequence

```python
# genui_persistence.py
def _fold_blocks(blocks: list[dict]) -> list[dict]:
    final_blocks: dict[str, dict] = {}

    for block in blocks:
        block_id = block.get("block_id")
        if not block_id:
            continue

        action = block.get("action", "create")
        if action == "delete":
            final_blocks.pop(block_id, None)
        elif action == "update":
            existing = final_blocks.get(block_id)
            if existing:
                # 保留首次 create 的 sequence，不覆盖
                seq = existing.get("sequence")
                final_blocks[block_id] = {
                    **existing,
                    **block,
                    "action": "create",
                    "sequence": seq if seq is not None else block.get("sequence"),
                    "props": {**existing.get("props", {}), **block.get("props", {})},
                }
            else:
                final_blocks[block_id] = {**block, "action": "create"}
        else:
            final_blocks[block_id] = {**block, "action": "create"}

    # 按 (sequence, block_id) 排序，block_id 作为同毫秒下的 tiebreaker
    result = list(final_blocks.values())
    result.sort(key=lambda b: (b.get("sequence", 0), b.get("block_id", "")))
    return result
```

**sequence 保留设计说明**：update 合并时 `**block` 展开可能携带 `sequence` 字段（例如从 checkpoint 恢复的 block marker 中已包含 sequence），但由于显式的 `"sequence": seq` 写在 `**block` 之后，字典字面量中后出现的键覆盖先出现的键，因此 `existing` 的原始 sequence 始终优先。只有当 `existing` 无 sequence（旧数据）时，才回退到 `block.get("sequence")`。这个设计保证了：首次 create 的 sequence 在整个 block 生命周期中不可变，update/delete/recreate 都不会改变排序位置。

#### 4.3.4 后端 `extract_blocks_from_messages` 无需额外排序

`extract_blocks_from_messages` 收集 raw block 列表后调用 `_fold_blocks`，而 `_fold_blocks` 已在 4.3.3 中修复为排序输出。因此 4.3.3 的改动自动覆盖此路径，**无需额外排序代码**。

同样，`get_persisted_blocks` 也调用 `_fold_blocks`，排序同样自动生效。

#### 4.3.5 前端 `GenUIBlockList` 显式排序

```typescript
// GenUIBlockList.tsx — 在 useMemo 内对 candidateBlocks 排序
const filteredBlocks = useMemo(() => {
  const candidateBlocks = Array.from(blocks.values())
    .filter((block) => {
      if (block.parent_id) return false;
      if (blockIds) return blockIds.includes(block.block_id);
      if (excludeBlockIds) return !excludeBlockIds.includes(block.block_id);
      return true;
    })
    .sort((a, b) =>
      (a.sequence ?? 0) - (b.sequence ?? 0)
      || (a.block_id ?? "").localeCompare(b.block_id ?? "")
    );

  const visibleBlockIds = new Set(
    filterSupersededInteractiveBlockIds(
      candidateBlocks.map((block) => block.block_id),
      blocks,
    ),
  );

  return candidateBlocks.filter((block) => visibleBlockIds.has(block.block_id));
}, [blockIds, blocks, excludeBlockIds]);
```

#### 4.3.6 前端 `extractBlocksFromMessages` 已委托到 `buildResolvedBlockHistory`

[sse-recovery.ts:22-24](../../frontend/src/core/genui/sse-recovery.ts#L22-L24) — `extractBlocksFromMessages` 已简化为委托调用，实际解析和 fold 逻辑在 [history.ts](../../frontend/src/core/genui/history.ts) 的 `buildResolvedBlockHistory` 中：

```typescript
// sse-recovery.ts — 当前实现
export function extractBlocksFromMessages(messages: ...): UIBlock[] {
  return buildResolvedBlockHistory(messages as Message[]).blocks;
}
```

排序修复应在 `buildResolvedBlockHistory` 的 return 语句中执行（见 4.3.7）。

#### 4.3.7 前端 `buildResolvedBlockHistory` 按 sequence 排序输出

[history.ts](../../frontend/src/core/genui/history.ts) 的 `buildResolvedBlockHistory` 是前端侧 block 解析的集中出口——被 `sse-recovery.ts`、`message-list.tsx` 共同调用。当前 return 语句直接返回未排序的 `blocks` 数组：

```typescript
// history.ts — buildResolvedBlockHistory return 语句
return {
  blocks: Array.from(blocks.values()),
  blockIdsByMessageKey,
  duplicatedRawBlockIds,
};
```

修复：对 `blocks` 按 `(sequence, block_id)` 排序：

```typescript
// history.ts — buildResolvedBlockHistory return 语句
return {
  blocks: Array.from(blocks.values())
    .sort((a, b) =>
      (a.sequence ?? 0) - (b.sequence ?? 0)
      || (a.block_id ?? "").localeCompare(b.block_id ?? "")
    ),
  blockIdsByMessageKey,
  duplicatedRawBlockIds,
};
```

#### 4.3.8 前端 `filterSupersededInteractiveBlockIds` 用 sequence 判定最新版本

当前实现遍历 `blocks.values()`（全局 store 中所有 block），利用 Map 的插入顺序（后插入的覆盖先插入的）来判定同一 `callback_id` 下的最新 block。这存在两个问题：

1. **范围过大**：遍历 `blocks.values()` 会纳入被 `parent_id` 过滤掉的子 block，如果子 block 与候选 block 共享 `callback_id`，可能错误淘汰候选 block
2. **顺序不可靠**：恢复时 block 的插入顺序取决于消息解析顺序，而非创建顺序

修复：遍历范围限制为传入的 `blockIds`，用 `sequence` 数值比较替代 Map 插入顺序。

```typescript
// visibility.ts — filterSupersededInteractiveBlockIds
export function filterSupersededInteractiveBlockIds(
  blockIds: string[],
  blocks: Map<string, UIBlock>,
): string[] {
  const latestBlockIdByCallback = new Map<string, string>();

  for (const id of blockIds) {
    const block = blocks.get(id);
    if (!block || block.parent_id || !block.interactive || !block.callback_id) continue;
    const current = latestBlockIdByCallback.get(block.callback_id);
    if (!current || (block.sequence ?? 0) > (blocks.get(current)?.sequence ?? 0)) {
      latestBlockIdByCallback.set(block.callback_id, block.block_id);
    }
  }
  // ... 后续去重和过滤逻辑不变 ...
}
```

关键变化：
- 遍历范围从 `blocks.values()` 收窄为 `blockIds`，仅考虑调用方传入的候选 block
- 不再依赖 Map 插入顺序的最后写入者，改用 `sequence` 数值比较显式判定最新版本

#### 4.3.9 前端 `partitionStandaloneBlockIds` 按 sequence 排序输出

`partitionStandaloneBlockIds` 将未归属的 block 分为历史区和尾部区，当前直接返回未排序数组。恢复场景下 block 插入 Map 的顺序不可靠，导致两个区域的 block 渲染顺序随机。

```typescript
// visibility.ts — partitionStandaloneBlockIds
export function partitionStandaloneBlockIds({
  claimedBlockIds,
  storeBlockIds,
  historicalMessageBlockIds,
  liveMessageBlockIds,
  preStreamBlockIds,
  blocks,
  interactions,
}: StandaloneBlockBucketsOptions): StandaloneBlockBuckets {
  // ... 现有分区逻辑保持不变 ...

  const sortByIds = (ids: string[]) =>
    ids.sort((a, b) => {
      const blockA = blocks.get(a);
      const blockB = blocks.get(b);
      return (blockA?.sequence ?? 0) - (blockB?.sequence ?? 0)
        || (a || "").localeCompare(b || "");
    });

  return {
    historicalBlockIds: sortByIds(historicalBlockIds),
    tailBlockIds: sortByIds(tailBlockIds),
  };
}
```

注意：排序依赖 `blocks` Map 中已有 block 数据，调用方需确保排序前 block 已加载到 store。

### 4.4 `sequence` 的生成策略与边界情况

**生成策略**：`render_ui_tool` 在创建 block 时使用 `int(time.time() * 1000)`（毫秒时间戳）。

优点：无需全局计数器，天然递增，后端重启后新 block 的 sequence 自动大于旧 block。
缺点：极端并发下可能重复——此时以 `block_id`（UUID）作为 tiebreaker。

**边界情况**：

1. **同一毫秒内多个 block**：Agent 在一次响应中可能连续创建多个 block（card → echart → table → markdown）。时间戳相同时，以 `block_id` 作为次级排序键。所有排序点均使用 `(sequence, block_id)` 二元组。

2. **后端时钟回拨**：NTP 校时可能导致时钟回拨，使新 block 的 sequence 小于旧 block。短期缓解：`block_id` tiebreaker 保证不崩溃（排序仍稳定）；长期方案：可改用 `time.monotonic()` + 进程启动基准偏移，或使用 Redis INCR。

3. **旧 block 没有 sequence**：平台升级前创建的 block 缺少该字段。`sequence ?? 0` 将所有旧 block 排在新 block 之前（只要 0 < 任何合理的时间戳）。如果同一会话中同时存在新旧 block，旧 block 之间的相对顺序仍依赖 Map 插入顺序（保持不变）。

4. **`render_ui` 工具未设置 sequence**：如果第三方 Agent 或自定义 SOUL.md 使用了 `render_ui` 工具但未传递 `sequence`（实际上 `sequence` 由工具内部生成，不依赖 LLM 传参），上游 LLM 无法覆盖或伪造 sequence 值，保证排序的可靠性。

### 4.5 架构层面补充观察

#### 4.5.1 双路径同步

Block 通过两条路径同时到达前端：

```
路径 A: render_ui_tool → StreamWriter("ui_block") → SSE custom event → useBlockStore.applyBlock()
路径 B: render_ui_tool → persist_block → return value (<!--ui_block:...-->) → ToolMessage → recoverBlocksFromMessages()
```

- **路径 A** 是实时的，但 SSE 断线后会丢失，由 `GenUISSEManager` 重连恢复
- **路径 B** 是持久化的（存入 LangGraph checkpoint 消息历史），在页面加载/历史消息加载时触发
- [sse-recovery.ts:74](../../frontend/src/core/genui/sse-recovery.ts#L74) 中 `if (!existing.has(block.block_id))` 守卫确保 store 中已有的 block 不被路径 B 覆盖——**路径 A 的实时数据优先**

sequence 字段在此场景下不产生新的冲突：两条路径携带相同的 sequence 值（都来自同一次 `render_ui_tool` 调用），store 中的 block 排序结果一致。

#### 4.5.2 `_fold_blocks` 逻辑在前后端各有一份

- 后端：[genui_persistence.py](../../backend/packages/harness/deerflow/agents/genui_persistence.py) 的 `_fold_blocks`
- 前端：[history.ts](../../frontend/src/core/genui/history.ts) 的 `buildResolvedBlockHistory`（内置了 fold 逻辑——使用 Map，create 直接 set，update 合并 props，delete 删除 key，并额外处理重复 block_id 消歧 `__N` 后缀）

两份逻辑需要同步维护。本次修改在两处都添加了 sequence 排序（后端在 `_fold_blocks` 末尾，前端在 `buildResolvedBlockHistory` return 语句），但后续如果 fold 逻辑发生变化，需确保两端同步更新。建议在代码注释中标注两端引用关系。

---

## 5. 其他应修复的问题

### 5.1 TTL 过短

`_BLOCK_TTL_SECONDS = 3600`（1 小时）对于实际使用场景过短。用户可能在下午查看上午生成的日报，届时内存中的 block 已过期。

**建议**：将 TTL 延长到 24 小时，或改为与 thread 生命周期一致（thread 删除时清理）。checkpoint 恢复兜底保证了极端情况下仍可恢复，但 checkpoint 恢复的 block 顺序问题正是本文要解决的。

### 5.2 内容编辑能力

见 3.3 节。需要后续单独设计 GenUI 编辑协议。

### 5.3 历史导出表单不可用

当 `disableExpiration=true` 时，`FormBlock` 的 `interactionState` 变为 `readonly`，所有交互被禁用。这意味着用户在历史会话中无法使用导出表单。

**建议**：对于 `callback_id=daily-report-export` 这类"纯功能型"表单，即使在其他表单已提交的情况下也应保持可用。可在 `visibility.ts` 中为特定 `callback_id` 添加白名单。

---

## 6. 实施优先级

| 优先级 | 任务 | 理由 |
|--------|------|------|
| **P0** | Block `sequence` 字段 + 全链路排序 | 解决历史会话查看时 block 顺序错乱的核心风险 |
| **P1** | TTL 延长到 24h | 减少对 checkpoint 恢复兜底的依赖 |
| **P2** | 历史导出表单可用性 | 用户需要在历史会话中也能下载日报 |
| **P3** | GenUI 编辑协议设计 | 需求 3 的核心缺失，需要独立设计文档 |

---

## 7. 参考文件

| 模块 | 文件 |
|------|------|
| 日报 SOUL | [agents/builtin/ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) |
| 后端 render_ui 工具（sequence 生成源） | [backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py) |
| 后端 Block 持久化 | [backend/packages/harness/deerflow/agents/genui_persistence.py](../../backend/packages/harness/deerflow/agents/genui_persistence.py) |
| 后端 Interaction 中间件 | [backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py](../../backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py) |
| 后端 UI Block 恢复 API | [backend/app/gateway/routers/genui_telemetry.py](../../backend/app/gateway/routers/genui_telemetry.py) |
| 后端 Interaction API | [backend/app/gateway/routers/genui.py](../../backend/app/gateway/routers/genui.py) |
| 前端 Block Store | [frontend/src/core/genui/store.ts](../../frontend/src/core/genui/store.ts) |
| 前端 Block 可见性分区 | [frontend/src/core/genui/visibility.ts](../../frontend/src/core/genui/visibility.ts) |
| 前端 SSE 恢复 | [frontend/src/core/genui/sse-recovery.ts](../../frontend/src/core/genui/sse-recovery.ts) |
| 前端历史消息 Block 提取 | [frontend/src/core/genui/history.ts](../../frontend/src/core/genui/history.ts) |
| 前端 Block 列表渲染 | [frontend/src/components/genui/GenUIBlockList.tsx](../../frontend/src/components/genui/GenUIBlockList.tsx) |
| 前端 ECharts Block | [frontend/src/components/genui/EChartBlock.tsx](../../frontend/src/components/genui/EChartBlock.tsx) |
| 前端图表截图 | [frontend/src/core/genui/chart-screenshots.ts](../../frontend/src/core/genui/chart-screenshots.ts) |
| 前端交互提交 | [frontend/src/core/genui/interaction.ts](../../frontend/src/core/genui/interaction.ts) |
| 前端消息列表 | [frontend/src/components/workspace/messages/message-list.tsx](../../frontend/src/components/workspace/messages/message-list.tsx) |
| 前端 Thread Hooks | [frontend/src/core/threads/hooks.ts](../../frontend/src/core/threads/hooks.ts) |
