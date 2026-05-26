# AI Report Nav Entries — Page-level Discovery

## Why

模板市场（`/workspace/template-marketplace`）和蓝图目录（`/workspace/report-templates/new`）没有入口，用户无法发现。但它们不应作为独立侧边栏项——它们是"报告模板"页面的操作入口，属于同一功能域。

## What Changes

- 侧边栏保持现有两项：报告历史、报告模板（不变）
- 在报告模板列表页（`/workspace/report-templates`）的 header 区域增加"创建模板"按钮和"模板市场"链接
- `nav_items` 保持在 `ai-report--custom` 上不动

## Capabilities

### New Capabilities

（无新能力）

### Modified Capabilities

（无需修改 spec 级别行为——这是纯 UI 入口调整，不涉及 template-marketplace 或 template-blueprint 的功能需求变更）

## Impact

- **前端**：修改 `report-templates-page.tsx`，在 header 增加两个入口按钮
- **配置文件**：无需改动
- **用户影响**：进入报告模板页后自然发现创建和市场入口，侧边栏保持简洁
