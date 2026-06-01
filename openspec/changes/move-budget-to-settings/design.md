## Context

`BudgetIndicator` 渲染在 `workspace-sidebar.tsx` 的 `<SidebarFooter>` 中，通过 `useBudgetStatus()` 获取后台配额数据，以进度条形式展示今日/本月费用消耗百分比和金额。

## Goals / Non-Goals

**Goals:**
- 将费用显示从侧边栏底部移到设置页中
- 保持与 BudgetIndicator 相同的数据展示和样式

**Non-Goals:**
- 不改变费用数据获取逻辑
- 不改变后台配额 API

## Decisions

1. **复用 BudgetIndicator 内部逻辑**：新建 `BudgetSettingsPage` 组件，直接复用 `useBudgetStatus()` hook 和 `BudgetIndicator` 的计算逻辑，以设置页 section 的布局重新渲染。

2. **设置页 section 命名**：类型使用 `"budget"`，i18n 中文 "费用用量"，英文 "Cost & Quota"。

3. **icon 使用** `CoinsIcon`（与 BudgetIndicator 一致）。

## Risks / Trade-offs

- **无实时更新**：设置页关闭时不刷新，与原来侧边栏常驻展示不同。可接受——费用检查不是高频操作。
