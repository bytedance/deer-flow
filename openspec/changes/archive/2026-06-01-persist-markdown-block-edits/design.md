## Context

MarkdownBlock 是 GenUI 通用组件，通过 GenUIRenderer 动态渲染。目前用于：
- 报告详情页 (`report-run-detail-page.tsx`) — 展示报告 payload sections
- 聊天线程 — 展示 AI 生成的 markdown 内容

组件内置编辑功能：点击编辑按钮 → textarea 修改内容 → 保存。当前 `handleSave` 只调用 `useBlockStore.getState().updateBlockProps()`，写入内存 Zustand store。页面刷新或重新导航后 blocks 从后端重新加载，编辑丢失。

## Goals / Non-Goals

**Goals:**
- MarkdownBlock 编辑保存后，报告详情页中内容持久化到后端 `report_payload.json`
- 聊天线程中（无报告上下文），编辑仍为内存更新（现有行为）
- MarkdownBlock 不直接依赖报告 API，保持通用组件内聚性

**Non-Goals:**
- 聊天线程中的 MarkdownBlock 编辑持久化（涉及消息编辑/artifact 写入，不在本次范围）
- 其他 GenUI block 类型的编辑（仅限于 MarkdownBlock 的 content 属性）

## Decisions

### Decision 1: React Context 注入持久化回调

**选 Context 而非 prop drilling：**
- MarkdownBlock 通过 GenUIRenderer → registry 动态创建，无法直接传 props
- GenUIRenderer 已有 `threadId` 传参模式，但 threadId 本身不足够（上下文信息不完整）
- Context 允许任意上层页面注入自己的持久化实现，不解耦组件注册链

**选 Context 而非 block.metadata 注入：**
- metadata 方案会让 MarkdownBlock 直接 import 报告 API，违反依赖反转
- metadata 只适合存储数据，不适合注入行为

**Context 接口设计：**
```ts
interface BlockPersistContextValue {
  saveContent: (blockId: string, content: string, metadata?: Record<string, unknown>) => Promise<void>;
}
```

- `blockId` — 标识要更新的 block
- `content` — 新的 markdown 内容
- `metadata` — 可选，由调用方自行解析，Context 提供方不关心其结构

### Decision 2: 后端 PUT /api/report-runs/{run_id}/payload

**完整替换而非 PATCH section：**
- 前端 `buildPayloadBlocks` 已将完整 sections 数组转为 blocks
- 保存时传完整的 sections 数组，避免服务端需要 merge 逻辑
- 请求体：`{ sections: PayloadSection[] }`
- 后端直接写回 `report_payload.json`

### Decision 3: 从 block_id 中提取 section index

- `buildPayloadBlocks` 创建的 block_id 格式：`report-detail-{runId}-{sectionId}`
- `sectionId` 对应 `section.id ?? index`
- MarkdownBlock 通过 block_id 后缀识别自己对应的 section
- 报告页 Provider 的 saveContent 解析 block_id → 找到对应 section → 更新 → 调 API

## Risks / Trade-offs

- **block_id 格式依赖**：MarkdownBlock 的行为取决于 Provider 实现，格式约定约束在 Provider 内部，MarkdownBlock 不感知 → 格式变化只需改 Provider
- **并发编辑**：同一报告多个 tab 同时编辑，最后一次保存覆盖之前的 → 现有 etag 机制保证一致性，冲突时前端重试
- **Context 未提供时回退**：MarkdownBlock 检测 Context 为空时退化为内存更新（当前行为），不中断功能
