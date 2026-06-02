## Why

MarkdownBlock 组件的"编辑→保存"只更新内存中的 Zustand store，不持久化到后端。用户刷新页面或重新进入报告详情页后，所有编辑内容丢失。

## What Changes

- 新增 `BlockPersistContext` — 通用接口，让上层页面注入持久化实现，MarkdownBlock 只依赖接口
- 后端新增 `PUT /api/report-runs/{report_run_id}/payload` 端点，支持更新报告 payload 的 sections
- 前端新增 `updateReportRunPayload` API 函数
- 报告详情页通过 Context Provider 注入后端保存实现
- MarkdownBlock 从 Context 获取 `saveContent`，编辑保存时调用；无 Provider 时回退到仅内存更新（聊天线程场景）

## Capabilities

### New Capabilities

- `block-content-persistence`: MarkdownBlock 编辑内容通过 React Context 持久化，报告上下文中保存到后端，聊天线程中仅内存更新

### Modified Capabilities

<!-- None -->

## Impact

- **前端**: MarkdownBlock, GenUIRenderer, report-run-detail-page, core/report-templates/api.ts, core/genui/block-persist-context.tsx (新增)
- **后端**: app/gateway/routers/report_runs.py (新增 PUT 端点)
