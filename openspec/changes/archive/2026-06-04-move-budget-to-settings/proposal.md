## Why

费用/配额显示（今日用量/本月用量 $）目前固定在侧边栏底部，占用宝贵的侧边栏空间，对日常操作的感知干扰大于信息价值。移到设置页中查看，既保持了费用可见性，又释放了侧边栏空间。

## What Changes

- 从 sidebar footer 移除 `BudgetIndicator` 组件
- 在设置对话框中新增「费用用量」section，展示今日/本月费用详情（与 BudgetIndicator 相同的 UI 和数据）
- 数据源不变：仍使用 `useBudgetStatus()` hook

## Capabilities

### New Capabilities
- `budget-settings`: 设置页中的费用用量子页，展示每日/每月 LLM 调用费用和配额使用情况

### Modified Capabilities
_None_

## Impact

- **移除**: `workspace-sidebar.tsx` 中 `<SidebarFooter>` 内的 `<BudgetIndicator />`
- **新增**: `budget-settings-page.tsx` 设置子页组件
- **修改**: `settings-dialog.tsx` 新增 section 类型、导航项、渲染条件
- **i18n**: 新增 `settings.sections.budget` 键
