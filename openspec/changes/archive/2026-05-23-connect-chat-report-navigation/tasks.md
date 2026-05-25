## 1. 报告列表增加来源对话列

- [x] 1.1 在 `report-runs-page.tsx` 的 RunsTab 表格中增加"来源对话"列，使用 `run.thread_id` 渲染可点击链接（`pathOfThread`），无 thread_id 时显示"—"
- [x] 1.2 链接携带 CrossPageContext（`sourceType: "report", sourceId: run.id`），记录 outbound 日志

## 2. Chat → 产物直达链接

- [x] 2.1 在 `chat-report-trigger.tsx` 的下拉菜单项中，已完成且有产物的 run 增加 Markdown/PDF 下载链接
- [x] 2.2 下载链接点击时记录 `logCrossPageNavigation`（`sourceType: "chat"`）
- [x] 2.3 仅展示实际存在的产物（artifact_paths.md/pdf 非 null），状态为 pending/running 的 run 不展示产物链接

## 3. 结构化跳转日志

- [x] 3.1 在 `navigation.ts` 的 `logCrossPageNavigation` 中，增加 `console.info` 的结构化 object 输出（含 traceId、direction、sourceType、sourceId、threadId、runId、timestamp）
- [x] 3.2 保留现有字符串日志不变（兼容性），新增结构化输出为独立 `console.info` 调用

## 4. 回归测试

- [x] 4.1 扩展 `navigation.ts` 单元测试：验证结构化日志字段完整性、CrossPageContext 编解码往返
- [x] 4.2 新增前端组件测试：验证 report-runs 列表表格包含 thread 列、ChatReportTrigger 下拉包含产物链接
- [x] 4.3 检查所有跨页跳转路径不产生死角页面（chat→report list→report detail→chat 闭环）
