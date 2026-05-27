## Why

前端 i18n 系统已完整（支持 en-US/zh-CN，约 740 个翻译键），但多个组件绕过了 i18n 系统，直接硬编码中文字符串。这导致切换语言时这些组件仍显示中文，破坏了多语言体验的一致性。报告模板/运行页面和 GenUI 组件是主要缺口。

## What Changes

- 在 `src/core/i18n/locales/types.ts` 中新增约 120 个翻译键，覆盖报告模板、报告运行、GenUI 组件
- 在 `src/core/i18n/locales/zh-CN.ts` 和 `en-US.ts` 中添加对应的中英文翻译
- 将以下组件从硬编码字符串改为使用 `useI18n()` hook：
  - 报告模板页面：
    - `report-templates-page.tsx`（报告模板列表页）
    - `report-runs-page.tsx`（报告运行历史页）
    - `report-run-detail-page.tsx`（报告运行详情页）
  - GenUI 组件：
    - `DeviceSelectorMultiBlock.tsx`（设备多选选择器）
    - `DeviceSelectorBlock.tsx`（设备单选选择器）
    - `SubDeviceSelectorBlock.tsx`（子设备选择器）
    - `MarkdownBlock.tsx`（Markdown 编辑器）
    - `MetricBlock.tsx`（指标块）
    - `FormBlock.tsx`（表单块）
    - `StatusBlock.tsx`（状态块）
    - `AlarmBlock.tsx`（报警块）
    - `OrgTreePanel.tsx`（组织树面板）

## Capabilities

### New Capabilities
- `frontend-i18n-completeness`: 补全前端 i18n 翻译键并将所有用户可见字符串接入 i18n 系统，确保中英文切换一致性

### Modified Capabilities
（无现有 spec 需要修改）

## Impact

- **前端代码**：修改 12 个组件文件，新增约 120 个 i18n 键定义和翻译
- **API**：无变更
- **依赖**：无新增依赖
- **测试**：需更新 E2E 测试中的字符串断言（如有硬编码中文断言）
- **用户体验**：切换语言后所有组件正确显示对应语言文本
