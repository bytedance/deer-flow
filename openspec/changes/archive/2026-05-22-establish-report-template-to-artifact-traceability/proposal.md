## Why

报告运行记录当前只存储了 `template_id` 和 `template_version_ref`，但用户无法从一条运行记录回溯到产生它的确切模板 DSL 快照、触发它的对话上下文、以及数据步骤中使用的知识来源。运营人员在排查"这份报告为什么长这样"时，需要在模板管理、对话历史和文件系统之间手工跳转。同时模板被删除/归档后、知识库不可用时的错误语义也不够清晰。此变更在 ISSUE-03（跳转链路）和 ISSUE-04（知识主链）的基础上，补全模板→版本→运行→输入→产物的纵向可追踪性。

## What Changes

- 报告运行详情页展示触发上下文（来源对话/运行链接）和输入来源（原始参数、数据快照路径）
- 报告运行记录关联到具体模板版本快照，用户可从运行记录跳转到产生该运行的确切 DSL 版本
- 报告产物（Markdown/PDF）与报告运行记录之间形成双向导航
- 报告运行列表增加模板版本列和知识来源摘要
- 定义模板不可用、知识库不可用、运行中断、数据步骤失败四类错误码和用户提示
- 新增端到端验证测试：模板→版本→运行→参数→数据快照→payload→产物

## Capabilities

### New Capabilities

- `report-template-version-traceability`: 运行记录关联到具体模板版本快照，用户可从运行记录查看产生该运行的确切 DSL
- `report-run-input-visibility`: 运行详情展示完整输入上下文：触发对话/运行、原始参数、知识来源数据快照
- `report-error-taxonomy`: 模板不可用、知识不可用、运行中断、数据步骤失败四类场景的标准化错误码和用户提示

### Modified Capabilities

- `report-to-source-traceability`: 扩展数据快照可见性（不仅是 thread 链接，还包括知识来源可查看）
- `chat-to-report-navigation`: 扩展触发上下文展示（明确标识哪条对话触发了报告生成）

## Impact

- **后端**: `report_runs.py` 路由（list/get 返回结构扩展）、`records.py`（可能新增 `trigger_context` 字段）、`payload_builder.py`（扩展 payload 中的来源元数据）
- **前端**: `report-run-detail-page.tsx`（新增触发上下文、输入来源、模板版本快照区域）、`report-runs-page.tsx`（列表新增版本列）、`types.ts`（新增字段）、`hooks.ts`（按需扩展）
- **测试**: 新增 `test_report_template_traceability_e2e.py`（端到端验证路径）
