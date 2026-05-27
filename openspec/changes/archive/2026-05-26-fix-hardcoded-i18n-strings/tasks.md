## 1. i18n 类型定义

- [x] 1.1 在 `types.ts` 中新增 `reportRuns` 命名空间，包含页面标题、描述、状态标签、表头、空状态、Tab 标签等键
- [x] 1.2 在 `types.ts` 中新增 `genui` 命名空间，包含设备类型标签、选择器提示、加载状态、表单操作、Markdown 编辑器、指标 ARIA、状态标签、报警标签、组织树等键
- [x] 1.3 在 `types.ts` 的 `marketplace` 命名空间中补充报告模板列表页缺失的键（页面标题、描述、可见性过滤、状态标签、空状态等）

## 2. 翻译填充

- [x] 2.1 在 `zh-CN.ts` 中填充 `reportRuns` 命名空间的所有中文翻译
- [x] 2.2 在 `zh-CN.ts` 中填充 `genui` 命名空间的所有中文翻译
- [x] 2.3 在 `zh-CN.ts` 的 `marketplace` 命名空间中补充新增键的中文翻译
- [x] 2.4 在 `en-US.ts` 中填充 `reportRuns` 命名空间的所有英文翻译
- [x] 2.5 在 `en-US.ts` 中填充 `genui` 命名空间的所有英文翻译
- [x] 2.6 在 `en-US.ts` 的 `marketplace` 命名空间中补充新增键的英文翻译

## 3. 报告模板/运行页面组件改造

- [x] 3.1 改造 `report-templates-page.tsx`：导入 `useI18n()`，替换所有硬编码中文为 `t.marketplace.xxx`
- [x] 3.2 改造 `report-runs-page.tsx`：导入 `useI18n()`，替换所有硬编码中文为 `t.reportRuns.xxx`
- [x] 3.3 改造 `report-run-detail-page.tsx`：导入 `useI18n()`，替换所有硬编码中文为 `t.reportRuns.xxx`

## 4. GenUI 组件改造

- [x] 4.1 改造 `DeviceSelectorBlock.tsx`：导入 `useI18n()`，替换设备类型标签和 UI 文本为 `t.genui.xxx`
- [x] 4.2 改造 `DeviceSelectorMultiBlock.tsx`：导入 `useI18n()`，替换所有硬编码中文为 `t.genui.xxx`
- [x] 4.3 改造 `SubDeviceSelectorBlock.tsx`：导入 `useI18n()`，替换所有硬编码中文为 `t.genui.xxx`
- [x] 4.4 改造 `MarkdownBlock.tsx`：导入 `useI18n()`，替换按钮标签和 toast/confirm 文本为 `t.genui.xxx`
- [x] 4.5 改造 `MetricBlock.tsx`：导入 `useI18n()`，替换 ARIA 标签为 `t.genui.xxx`
- [x] 4.6 改造 `FormBlock.tsx`：导入 `useI18n()`，替换搜索、选择、提交等文本为 `t.genui.xxx`
- [x] 4.7 改造 `StatusBlock.tsx`：导入 `useI18n()`，替换状态标签为 `t.genui.xxx`
- [x] 4.8 改造 `AlarmBlock.tsx`：导入 `useI18n()`，替换报警级别标签和空状态文本为 `t.genui.xxx`
- [x] 4.9 改造 `OrgTreePanel.tsx`：导入 `useI18n()`，替换搜索占位符和空状态文本为 `t.genui.xxx`

## 5. 验证

- [x] 5.1 运行 `pnpm typecheck` 确保无类型错误
- [x] 5.2 运行 `pnpm lint` 确保无 lint 错误
- [x] 5.3 全局搜索 `[一-鿿]` 确认 `src/components/genui/` 和 `src/components/workspace/report-templates/` 中无残留硬编码中文（注释除外）
- [x] 5.4 检查 E2E 测试中是否有硬编码中文字符串断言，如有则更新为 i18n 键对应的英文文本
