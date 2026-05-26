# Design: Page-level Discovery for Template Marketplace & Blueprint

## Context

当前报告模板列表页（`/workspace/report-templates`）的 header 只有标题和 scope 切换标签，没有操作入口。用户进入后不知道如何创建模板或访问模板市场。

相关页面路由：
- `/workspace/report-templates` — 模板列表（当前页面）
- `/workspace/report-templates/new` — 蓝图目录（创建模板入口）
- `/workspace/template-marketplace` — 模板市场

## Goals / Non-Goals

**Goals:**

- 在报告模板列表页 header 区域提供"创建模板"按钮和"模板市场"链接
- 保持侧边栏简洁（仅报告历史 + 报告模板）

**Non-Goals:**

- 不修改侧边栏结构
- 不修改 `nav_items` 配置
- 不改变模板市场或蓝图目录的页面逻辑

## Decisions

### 决策 1：header 布局

在报告模板列表页 header 右侧增加操作区：

```
┌─────────────────────────────────────────────┐
│ 报告模板                          [模板市场] [创建模板] │
│ 管理自定义报告模板...                                │
├─────────────────────────────────────────────┤
│ [我的模板] [租户共享] [预置模板]                       │
└─────────────────────────────────────────────┘
```

- "模板市场" — 文字链接样式（`text-sm text-muted-foreground`），跳转 `/workspace/template-marketplace`
- "创建模板" — 主按钮样式（Button + PlusIcon），跳转 `/workspace/report-templates/new`

**理由**：两个入口层级不同——创建模板是主要操作（按钮），浏览市场是次要操作（链接）。

### 决策 2：不修改现有 description 文案

当前页面 description 提到"新建模板请通过自定义模板智能体"。改为直接引导到蓝图目录更符合方案 A 的意图——用户可以直接从页面创建，无需跳转 chat。

## Risks / Trade-offs

- **[文案冲突]** → 现有 description 引导用户去 chat 创建模板，与新按钮冲突。需同步更新文案。
