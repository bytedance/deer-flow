## Why

日报 deep-link 将参数视为"默认值/预填值"而非"跳过表单的执行参数"，周报和月报完全没有 deep-link 支持。外部系统跳转过来的场景下（如定时调度触发报告生成），用户期望传入参数后报告直接生成完毕，不需要任何表单交互。

## What Changes

- 修复日报 deep-link 指令：参数齐全时跳过全部表单步骤，直接执行 DSL 完整链路生成报告
- 周报新增 `Deep-Link 参数直达` 章节：支持 `template_id` + `date_start` + `date_end` 参数，跳过表单直达报告
- 月报新增 `Deep-Link 参数直达` 章节：支持 `template_id` + `month` 参数，跳过表单直达报告
- `deep-link-api.md` 新增周报、月报接口文档

## Capabilities

### New Capabilities

- `report-deep-link-direct`: 日报/周报/月报在 deep-link 参数齐全时，跳过全部 GenUI 表单交互，直达报告生成完成
- `weekly-report-deep-link`: 周报 deep-link API 接口
- `monthly-report-deep-link`: 月报 deep-link API 接口

### Modified Capabilities

<!-- None — existing specs unchanged. -->

## Impact

- **Agent SOUL.md** (3 files): 日报改行为、周报月报新增 deep-link 章节
- **API 文档** (`docs/deep-link-api.md`): 新增周报、月报接口定义
- **前端/后端**: 无改动 — 复用已有 `PassthroughParamsMiddleware` 和 `auto_start` 机制
